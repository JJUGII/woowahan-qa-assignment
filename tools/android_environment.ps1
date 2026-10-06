# Project-local Android build tools; no global PATH or Java configuration changes.
function Get-ArchiveHash([string]$File, [string]$Algorithm) {
    $stream=[IO.File]::OpenRead($File)
    $digest=[Security.Cryptography.HashAlgorithm]::Create($Algorithm)
    try { return [BitConverter]::ToString($digest.ComputeHash($stream)).Replace('-','') }
    finally { $stream.Dispose(); $digest.Dispose() }
}
function Get-VerifiedArchive([string]$Url, [string]$File, [string]$Hash, [string]$Algorithm = 'SHA256') {
    if ((Test-Path -LiteralPath $File) -and (Get-ArchiveHash $File $Algorithm) -eq $Hash) { return }
    Write-Host "도구 다운로드: $Url"
    $partial = "$File.partial"
    & curl.exe --fail --location --silent --show-error --retry 2 --output $partial $Url
    if ($LASTEXITCODE -ne 0) { throw "다운로드 실패: $Url" }
    if ((Get-ArchiveHash $partial $Algorithm) -ne $Hash) { throw "다운로드 무결성 검사 실패: $File" }
    Move-Item -LiteralPath $partial -Destination $File -Force
}

function Ensure-AndroidEnvironment([string]$ToolsRoot) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    New-Item -ItemType Directory -Path $ToolsRoot -Force | Out-Null
    $javaHome = $env:JAVA_HOME
    $valid = $false
    if ($javaHome -and (Test-Path -LiteralPath "$javaHome\bin\javac.exe")) {
        $version = & "$javaHome\bin\javac.exe" -version
        $valid = $LASTEXITCODE -eq 0 -and "$version" -match '^javac 17\.'
    }
    if (-not $valid) {
        $jdkRoot = Join-Path $ToolsRoot 'jdk17'
        $found = Get-ChildItem -Path "$jdkRoot\*\bin\javac.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $found) {
            $assets = Invoke-RestMethod -Uri 'https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=windows'
            $package = $assets[0].binary.package
            $zip = Join-Path $ToolsRoot 'jdk17.zip'
            Get-VerifiedArchive $package.link $zip $package.checksum
            Expand-Archive -LiteralPath $zip -DestinationPath $jdkRoot -Force
            $found = Get-ChildItem -Path "$jdkRoot\*\bin\javac.exe" | Select-Object -First 1
        }
        if (-not $found) { throw 'JDK 17 구성 실패' }
        $javaHome = Split-Path (Split-Path $found.FullName)
    }
    $env:JAVA_HOME = $javaHome
    $env:PATH = "$javaHome\bin;" + $env:PATH
    $gradle = Join-Path $ToolsRoot 'gradle-8.9\bin\gradle.bat'
    if (-not (Test-Path -LiteralPath $gradle)) {
        $hash = ([string](Invoke-RestMethod -Uri 'https://services.gradle.org/distributions/gradle-8.9-bin.zip.sha256')).Trim()
        $zip = Join-Path $ToolsRoot 'gradle-8.9.zip'
        Get-VerifiedArchive 'https://services.gradle.org/distributions/gradle-8.9-bin.zip' $zip $hash
        Expand-Archive -LiteralPath $zip -DestinationPath $ToolsRoot -Force
    }
    # Use a dedicated SDK: ANDROID_HOME may point to platform-tools only.
    $sdk = Join-Path $ToolsRoot 'android-sdk'
    $manager = Join-Path $sdk 'cmdline-tools\19.0\bin\sdkmanager.bat'
    if (-not (Test-Path -LiteralPath $manager)) {
        [xml]$repository = (Invoke-WebRequest -UseBasicParsing -Uri 'https://dl.google.com/android/repository/repository2-1.xml').Content
        $package = $repository.SelectSingleNode("//*[local-name()='remotePackage' and @path='cmdline-tools;19.0']")
        if (-not $package) { throw '공식 Android 저장소에서 command-line tools 19.0을 찾지 못했습니다.' }
        $archive = $package.SelectSingleNode(".//*[local-name()='archive'][*[local-name()='host-os']='windows']/*[local-name()='complete']")
        $url = $archive.SelectSingleNode("*[local-name()='url']").InnerText
        $checksum = $archive.SelectSingleNode("*[local-name()='checksum']")
        $zip = Join-Path $ToolsRoot 'android-commandline19.zip'
        Get-VerifiedArchive ("https://dl.google.com/android/repository/" + $url) $zip $checksum.InnerText 'SHA1'
        $unpack = Join-Path $ToolsRoot 'android-commandline19'
        Expand-Archive -LiteralPath $zip -DestinationPath $unpack -Force
        $destination = Join-Path $sdk 'cmdline-tools\19.0'
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        Get-ChildItem -LiteralPath (Join-Path $unpack 'cmdline-tools') | Copy-Item -Destination $destination -Recurse -Force
    }
    $env:ANDROID_HOME = $sdk; $env:ANDROID_SDK_ROOT = $sdk
    $env:PATH = "$sdk\platform-tools;" + $env:PATH
    if (-not (Test-Path -LiteralPath "$sdk\platforms\android-35\android.jar") -or
        -not (Test-Path -LiteralPath "$sdk\build-tools\34.0.0\aapt2.exe") -or
        -not (Test-Path -LiteralPath "$sdk\platform-tools\adb.exe")) {
        Write-Host 'Android SDK 약관에 동의하고 API 35 / Build Tools 34 / ADB를 설치합니다.'
        & $venvPython (Join-Path $PSScriptRoot 'install_android_sdk.py') $manager $sdk | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'Android SDK 설치 실패' }
    }
    return @{ Gradle=$gradle; Sdk=$sdk; Java=$javaHome }
}

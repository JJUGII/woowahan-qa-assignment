function Ensure-AppiumEnvironment([string]$Project, [string]$ToolsRoot) {
    . (Join-Path $PSScriptRoot 'android_environment.ps1')
    $android=Ensure-AndroidEnvironment $ToolsRoot
    $nodeCommand=Get-Command node.exe -ErrorAction SilentlyContinue
    $node=$null
    if($nodeCommand) {
        $versionText=& $nodeCommand.Source --version
        if($LASTEXITCODE -eq 0 -and "$versionText" -match '^v(\d+)\.' -and [int]$Matches[1] -ge 24){$node=$nodeCommand.Source}
    }
    if(-not $node) {
        $version='v24.18.0'; $name="node-$version-win-x64.zip"
        $node=Join-Path $ToolsRoot "node-$version-win-x64\node.exe"
        if(-not (Test-Path -LiteralPath $node)) {
            $sums=[string](Invoke-RestMethod -Uri "https://nodejs.org/dist/$version/SHASUMS256.txt")
            $line=($sums -split "`n" | Where-Object { $_ -match ([regex]::Escape($name)+'\s*$') } | Select-Object -First 1)
            if(-not $line){throw 'Node.js 공식 체크섬 조회 실패'}
            $hash=($line.Trim() -split '\s+')[0]
            $zip=Join-Path $ToolsRoot $name
            Get-VerifiedArchive "https://nodejs.org/dist/$version/$name" $zip $hash
            Expand-Archive -LiteralPath $zip -DestinationPath $ToolsRoot -Force
        }
    }
    $nodeDir=Split-Path $node; $env:PATH="$nodeDir;"+$env:PATH
    $npm=Join-Path $nodeDir 'npm.cmd'
    $prefix=Join-Path $Project '.tools\appium'
    $package=Join-Path $prefix 'node_modules\appium\package.json'
    if(-not (Test-Path -LiteralPath $package) -or (Get-Content -LiteralPath $package -Raw | ConvertFrom-Json).version -ne '3.8.0') {
        & $npm install --prefix $prefix --no-audit --no-fund appium@3.8.0 | Out-Host
        if($LASTEXITCODE -ne 0){throw 'Appium 설치 실패'}
    }
    $env:APPIUM_HOME=Join-Path $Project '.tools\appium-home'
    $entry=Join-Path $prefix 'node_modules\appium\index.js'
    $driver=Join-Path $env:APPIUM_HOME 'node_modules\appium-uiautomator2-driver\package.json'
    if(-not (Test-Path -LiteralPath $driver)) {
        & $node $entry driver install uiautomator2@8.7.0 | Out-Host
        if($LASTEXITCODE -ne 0){throw 'UiAutomator2 드라이버 설치 실패'}
    }
    & $node $entry --version | Out-Host
    if($LASTEXITCODE -ne 0){throw 'Appium 실행 확인 실패'}
    & $node $entry driver list --installed | Out-Host
    if($LASTEXITCODE -ne 0){throw 'Appium 드라이버 확인 실패'}
    Write-Host 'ADB / JDK / Node.js / Appium 준비 완료. 기기 연결과 AI 계정 설정은 프로그램에서 진행하세요.'
}

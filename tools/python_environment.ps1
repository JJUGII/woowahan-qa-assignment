function Test-Python([string]$Candidate) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return $false }
    try {
        # Store aliases must not open the Store during discovery.
        if ($Candidate -like '*\Microsoft\WindowsApps\*') { return $false }
        $check = if ($script:MinimumPython -eq '3.14') { 'import sys, venv, ensurepip, tkinter; sys.exit(0 if sys.version_info[:2] == (3, 14) else 1)' } else { 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 11) else 1)' }
        & $Candidate -c $check 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Find-Python {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $found = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { $candidates.Add([string]($found | Select-Object -Last 1)) }
        } catch { }
    }
    foreach ($name in @('python.exe', 'python3.exe')) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.Source) { $candidates.Add($command.Source) }
        }
    }
    # A new installation may not yet be visible in this process's PATH.
    foreach ($registryRoot in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        foreach ($version in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
            $installKey = Get-Item -LiteralPath (Join-Path $version.PSPath 'InstallPath') -ErrorAction SilentlyContinue
            if ($installKey) {
                $executable = $installKey.GetValue('ExecutablePath')
                $directory = $installKey.GetValue('')
                if ($executable) { $candidates.Add([string]$executable) }
                elseif ($directory) { $candidates.Add((Join-Path $directory 'python.exe')) }
            }
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Python $candidate) { return $candidate }
    }
    return $null
}

function Ensure-PythonEnvironment([string]$Project, [string]$ExplicitPython) {
    $venv=Join-Path $Project '.venv'
    $python=Join-Path $venv 'Scripts\python.exe'
    if (Test-Path -LiteralPath $venv) {
        if (-not (Test-Python $python)) { throw "기존 .venv가 실행되지 않거나 필요한 Python $script:MinimumPython 버전과 다릅니다. 폴더 이름을 변경한 뒤 다시 실행하세요. 자동 삭제하지 않습니다." }
        Write-Host '기존 가상환경 사용'
    } else {
        $base=$ExplicitPython
        if ($base -and -not (Test-Python $base)) { throw '지정한 PythonPath의 버전/실행 상태를 확인하세요.' }
        if (-not $base) { $base=Find-Python }
        if (-not $base) {
            $winget=Get-Command winget.exe -ErrorAction SilentlyContinue
            if (-not $winget) { throw 'Python과 winget을 찾지 못했습니다. python.org에서 Python 3.14를 설치한 후 다시 실행하세요.' }
            Write-Host 'Python 3.14를 현재 사용자용으로 설치합니다(패키지/소스 약관 동의).'
            & $winget.Source install --id Python.Python.3.14 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Host
            if ($LASTEXITCODE -ne 0) { throw 'Python 설치 실패' }
            $base=Find-Python
            if (-not $base) { throw '설치 후 Python 탐색 실패. 창을 닫고 다시 실행하세요.' }
        }
        Write-Host "가상환경 생성: $base"
        & $base -m venv $venv | Out-Host
        if ($LASTEXITCODE -ne 0) { throw '가상환경 생성 실패' }
    }
    & $python --version | Out-Host
}

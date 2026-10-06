param(
    [Parameter(Mandatory=$true)][ValidateSet(2,4)][int]$Problem,
    [ValidateSet('tests','app','prepare','concurrency')][string]$Mode='tests',
    [switch]$NoPause,
    [switch]$NoOpen,
    [string]$PythonPath,
    [int]$Runs=50,
    [int]$MinGapMs=10,
    [int]$MaxGapMs=50,
    [string]$Seed=''
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
$root=Split-Path $PSScriptRoot
$folders=@{2='problem2_inventory_api';4='problem4_ai_qa_tool'}
$project=Join-Path $root $folders[$Problem]
$runDir=Join-Path $project ('reports\runs\'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$venvPython=Join-Path $project '.venv\Scripts\python.exe'
$script:MinimumPython=if($Problem -eq 4){'3.14'}else{'3.11'}
$result=1; $started=$false; $rows=New-Object System.Collections.Generic.List[object]
$scope=if($Problem -eq 4){'가상 입력 / mock 기반 자체 테스트. 단말과 AI API는 별도 연결이 필요합니다.'}else{'로컬 HTTP 스텁의 재고 API 검증. 실제 B마트 서버가 아닙니다.'}
try {
    Set-Location -LiteralPath $project
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null
    Start-Transcript -LiteralPath (Join-Path $runDir 'setup-and-test.log') | Out-Null; $started=$true
    . (Join-Path $PSScriptRoot 'python_environment.ps1')
    Write-Host "[1/4] Python $script:MinimumPython 환경 확인"
    Ensure-PythonEnvironment $project $PythonPath
    Write-Host '[2/4] 실행에 필요한 라이브러리와 도구 확인'
    if ($Problem -in @(2,4)) {
        $pipLog=Join-Path $runDir 'pip-install.log'
        & $venvPython -m pip install --disable-pip-version-check -r requirements.txt *> $pipLog
        if ($LASTEXITCODE -ne 0) { Get-Content -LiteralPath $pipLog -Tail 30; throw '라이브러리 설치 실패. pip-install.log 확인' }
        if ($Problem -eq 4) {
            & $venvPython -m pip install --disable-pip-version-check --no-deps -r requirements-airtest.txt *>> $pipLog
            if ($LASTEXITCODE -ne 0) { throw 'Airtest 설치 실패. pip-install.log 확인' }
            & $venvPython -c 'import tkinter, customtkinter, cv2, airtest, recorder.writer_agent'
            if ($LASTEXITCODE -ne 0) { throw 'GUI/이미지/AI 모듈 불러오기 실패' }
        } else {
            & $venvPython -m pip check
            if ($LASTEXITCODE -ne 0) { throw '라이브러리 의존성 검사 실패' }
        }
        Write-Host "라이브러리 준비 완료. 설치 상세: $pipLog"
        Write-Host '[3/4] 실행'
        if ($Problem -eq 4 -and $Mode -in @('app','prepare')) {
            . (Join-Path $PSScriptRoot 'appium_environment.ps1')
            Ensure-AppiumEnvironment $project (Join-Path $root '.tools')
        }
        if ($Mode -eq 'app' -and $Problem -eq 4) {
            Write-Host '도구 창을 엽니다. 도구를 종료하면 실행 결과를 저장합니다.'
            & $venvPython main.py
            $result=$LASTEXITCODE
            $rows.Add(@{id='APP-START';title='GUI 프로그램 실행';status=$(if($result -eq 0){'PASS'}else{'ERROR'});duration=0;actual="프로세스 종료 코드: $result. 개별 기능 시험 결과는 아닙니다."})
        } elseif ($Mode -eq 'prepare' -and $Problem -eq 4) {
            $result=0
            $rows.Add(@{id='ENV-4';title='단말 도구 실행 환경 구성';status='PASS';duration=0;actual='Python/라이브러리/JDK/SDK/Node.js/Appium/UiAutomator2 설치 및 명령 실행 확인';expected='필수 도구 설치 및 실행 가능'})
            $rows.Add(@{id='DEVICE-4';title='실제 단말과 AI 연동';status='NOT_RUN';duration=0;actual='기기/QA 앱/AI 계정 준비 후 run_app.bat에서 별도 확인'})
        } elseif ($Mode -eq 'concurrency' -and $Problem -eq 2) {
            $randomArgs=@('--problem',2,'--project',$project,'--output',$runDir,'--concurrency-only','--runs',$Runs,'--gap-min-ms',$MinGapMs,'--gap-max-ms',$MaxGapMs)
            if($Seed -ne ''){ $randomArgs+=@('--seed',$Seed) }
            & $venvPython (Join-Path $PSScriptRoot 'run_python_tests.py') @randomArgs
            $result=$LASTEXITCODE
        } elseif ($Mode -eq 'tests') {
            & $venvPython (Join-Path $PSScriptRoot 'run_python_tests.py') --problem $Problem --project $project --output $runDir
            $result=$LASTEXITCODE
        } else { throw '이 문제에서 지원하지 않는 실행 모드입니다.' }
    }
} catch {
    $result=1
    Write-Host ('실행 중단: '+$_.Exception.Message) -ForegroundColor Red
    $rows.Add(@{id='SETUP-RUN';title='환경 구성 또는 실행';status='ERROR';duration=0;actual=$_.Exception.Message})
} finally {
    Write-Host '[4/4] 시험성적서 저장'
    if ($rows.Count -gt 0) {
        @{title="문제 $Problem";scope=$scope;rows=@($rows.ToArray());exit_code=$result} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDir 'status.json') -Encoding UTF8
        if (Test-Path -LiteralPath $venvPython) {
            & $venvPython (Join-Path $PSScriptRoot 'render_status.py') $runDir
            if ($LASTEXITCODE -ne 0) { $result=1 }
        }
    }
    $report=Join-Path $runDir '시험성적서.html'
    if (-not (Test-Path -LiteralPath $report)) {
        # Even Python installation failures leave a human-readable failure artifact.
        $message=[System.Net.WebUtility]::HtmlEncode(($rows | ConvertTo-Json -Depth 8))
        "<!doctype html><meta charset='utf-8'><title>환경 구성 실패</title><h1>문제 $Problem 시험성적서: 실행 오류</h1><p>테스트 미실행. setup-and-test.log를 확인하세요.</p><pre>$message</pre>" | Set-Content -LiteralPath $report -Encoding UTF8
        $result=1
    }
    Write-Host "시험성적서: $report"
    if ($started) { Stop-Transcript | Out-Null }
    if (-not $NoOpen) { Start-Process -FilePath $report }
}
exit $result

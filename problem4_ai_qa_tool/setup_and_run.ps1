param([switch]$NoPause,[switch]$NoOpen,[string]$PythonPath,[ValidateSet('tests','app','device','prepare')][string]$Mode='tests')
& (Join-Path $PSScriptRoot '..\tools\run_problem.ps1') -Problem 4 -Mode $Mode -NoPause:$NoPause -NoOpen:$NoOpen -PythonPath $PythonPath
exit $LASTEXITCODE

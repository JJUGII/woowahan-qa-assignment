param([switch]$NoPause,[switch]$NoOpen)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot
$result=0
$links=New-Object System.Collections.Generic.List[string]
foreach($mode in @('tests','concurrency')) {
    $started=Get-Date
    & (Join-Path $PSScriptRoot 'run_problem.ps1') -Problem 2 -Mode $mode -NoPause -NoOpen
    $code=$LASTEXITCODE
    if($code -ne 0){$result=1}
    $runs=Join-Path $root 'problem2_inventory_api\reports\runs'
    $current=Get-ChildItem -LiteralPath $runs -Directory | Where-Object { $_.CreationTime -ge $started.AddSeconds(-2) } | Sort-Object Name -Descending | Select-Object -First 1
    $label=if($mode -eq 'tests'){'기본 API 시험'}else{'동시 주문 50회 반복'}
    if($current -and (Test-Path -LiteralPath (Join-Path $current.FullName '시험성적서.html'))) {
        $href='problem2_inventory_api/reports/runs/'+$current.Name+'/시험성적서.html'
        $links.Add("<li><a href='$href'>$label</a> (종료 코드: $code)</li>")
    } else { $links.Add("<li>${label}: 이번 실행 성적서가 생성되지 않았습니다.</li>");$result=1 }
}
$file=Join-Path $root '시험성적서_모음.html'
$items=$links -join "`n"
"<!doctype html><html lang='ko'><meta charset='utf-8'><title>문제2 시험성적서</title><style>body{font:18px/1.8 'Malgun Gothic';max-width:1000px;margin:50px auto}a{color:#087c47}</style><h1>문제2 시험성적서</h1><p>실행: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')</p><ul>$items</ul><p>로컬 HTTP 스텁의 API 시험 결과입니다.</p></html>" | Set-Content -LiteralPath $file -Encoding UTF8
if(-not $NoOpen){Start-Process -FilePath $file}
exit $result

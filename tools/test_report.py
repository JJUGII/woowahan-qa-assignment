"""Dependency-free, local HTML/CSV/JSON test report. Never infer a pass from a log."""
import csv
import html
import json
import platform
from collections import Counter
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET


def write_report(folder, title, scope, rows, exit_code=0, environment=None, timing=None, random_events=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    counts = Counter(r['status'] for r in rows)
    overall = ('FAIL' if exit_code or any(counts[x] for x in ('FAIL', 'ERROR')) else
               'INCOMPLETE' if any(counts[x] for x in ('NOT_RUN', 'SKIP')) else 'PASS')
    data = dict(title=title, created=datetime.now().astimezone().isoformat(timespec='seconds'),
                scope=scope, environment=environment or {'Python': platform.python_version(), 'OS': platform.platform()},
                exit_code=exit_code, overall=overall, counts=dict(counts), cases=rows)
    if timing is not None: data['timing_summary']=timing
    if random_events: data['random_events']=random_events
    (folder / 'result.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    fields = ['id', 'title', 'status', 'duration', 'precondition', 'procedure', 'expected', 'actual', 'source']
    with (folder / '시험성적서.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fields, extrasaction='ignore'); writer.writeheader()
        for row in rows:
            # Protect spreadsheet viewers from formula interpretation in test evidence.
            writer.writerow({k: ("'" + str(row.get(k, '')) if str(row.get(k, '')).startswith(('=', '+', '-', '@'))
                                  else row.get(k, '')) for k in fields})
    e = lambda value: html.escape(str(value))
    labels = {'PASS':'통과', 'FAIL':'실패', 'ERROR':'실행 오류', 'SKIP':'건너뜀', 'NOT_RUN':'미실행', 'INCOMPLETE':'미완료'}
    body = []
    for row in rows:
        details = ''.join(f'<dt>{label}</dt><dd>{e(row.get(key, ""))}</dd>' for key, label in
                          [('precondition','사전조건'),('procedure','시험 절차'),('expected','기대 결과'),('actual','실행 결과와 근거'),('source','코드 위치')])
        body.append(f'<tr data-status="{e(row["status"])}"><td>{e(row["id"])}</td><td><strong>{e(row["title"])}</strong>'
                    f'<details><summary>TC 상세와 결과 보기</summary><dl>{details}</dl></details></td>'
                    f'<td class="{e(row["status"])}">{labels[row["status"]]}</td><td>{float(row.get("duration",0)):.3f}초</td></tr>')
    summary = ' / '.join(f'{labels.get(k,k)} {v}' for k,v in counts.items())
    env = ' / '.join(f'{e(k)}: {e(v)}' for k,v in data['environment'].items())
    document = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>시험성적서</title><style>
body{font:16px/1.65 "Malgun Gothic",sans-serif;color:#21302d;max-width:1250px;margin:36px auto;padding:0 24px}h1{border-bottom:3px solid #22b57b;padding-bottom:12px} .meta{background:#f0faf5;padding:18px;border-left:4px solid #22b57b}.controls{margin:24px 0;display:flex;gap:12px;flex-wrap:wrap}input,select,button{font:inherit;padding:8px;border:1px solid #b5c9bf;border-radius:5px}input{flex:1;min-width:180px}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{text-align:left;vertical-align:top;border:1px solid #ccd9d2;padding:12px;overflow-wrap:anywhere}th{background:#baedd9}th:first-child{width:16%}th:nth-child(3){width:9%}th:last-child{width:9%}summary{color:#067e52;cursor:pointer;margin-top:8px}dt{font-weight:bold;margin-top:8px}dd{margin:0;white-space:pre-wrap;font-size:14px}.PASS{color:#087c47;font-weight:bold}.FAIL,.ERROR{color:#bd2635;font-weight:bold}.NOT_RUN,.SKIP{color:#8b6010}footer{margin:24px 0;color:#52625b}@media print{@page{size:A4 landscape;margin:14mm}body{font-size:10pt;margin:0;padding:0}.controls{display:none}tr{break-inside:avoid}dd{font-size:9pt}thead{display:table-header-group}}
</style>'''
    document += f'<h1>{e(title)} — 시험성적서</h1><div class="meta"><b>판정: {labels[overall]}</b> | {e(summary)}<br>실행 시각: {e(data["created"])}<br>{env}<br>검증 범위: {e(scope)}</div>'
    if timing:
        document += '<h2>동시 주문 간격별 비교 (단위: ms)</h2><p>설정 간격과 실제 서버 접수 간격은 다를 수 있습니다. 주문 성공 1건, 품절 1건, 재고 0, 저장 주문 1건과 요청 중첩 및 실제 간격 조건이 모두 충족되어야 통과입니다. 아래 값은 로컬 스텁의 측정 결과이며 서비스의 응답 시간 기준이나 최대 처리량이 아닙니다.</p><table><thead><tr><th>설정 간격</th><th>통과 / 실행</th><th>실측 최소</th><th>실측 중앙값</th><th>실측 최대</th></tr></thead><tbody>'
        for t in timing:
            values=[f'{t["gap_ms"]}ms',f'{t["passed"]} / {t["runs"]}',t['min_ms'],t['median_ms'],t['max_ms']]
            document+='<tr>'+''.join(f'<td>{e(v)}</td>' for v in values)+'</tr>'
        document+='</tbody></table>'
    if random_events:
        headers=['회차','시험 시작 시각','계획 선전송','실제 전송 순서','설정 ms','전송 실측 ms','서버 접수 순서','접수 실측 ms','A 주문 결과','B 주문 결과','시험 결과','시드','A 전송 시각','B 전송 시각']
        event_rows=[]
        outcomes={'SUCCESS':'성공','SOLD_OUT':'품절','REQUEST_ERROR':'요청 오류','UNEXPECTED':'예상 밖 응답'}
        for ev in random_events:
            events=ev.get('events',{})
            event_rows.append([ev['repeat_index'],ev['started_at'],ev['first_sender'],'→'.join(ev['actual_send_order']),
                              ev['gap_ms'],ev.get('send_gap_ms','미측정'),'→'.join(ev['server_order']),ev.get('server_arrival_gap_ms','미측정'),
                              outcomes.get(events.get('A',{}).get('outcome'),'미확인'),outcomes.get(events.get('B',{}).get('outcome'),'미확인'),
                              labels[ev['test_status']],ev['seed'],events.get('A',{}).get('call_started_at',''),events.get('B',{}).get('call_started_at','')])
        with (folder/'이벤트기록.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow(headers);writer.writerows(event_rows)
        document += '<h2>무작위 동시 주문 반복 기록</h2><p>매회 선전송 고객과 간격을 무작위 선택합니다. 첫 요청의 서버 접수부터 설정 간격을 기다린 후 두 번째 요청을 전송합니다. 두 요청은 재고 처리 직전 대기시켜 중첩을 확인합니다. 실측 서버 접수 간격은 설정값 이상 100ms 미만이어야 합니다. 전송 시각은 클라이언트 HTTP 호출 시작 시각이며 서버 접수와 별도로 측정합니다. 성공 고객은 서버 접수 순서로 검증합니다. 같은 시드를 지정하면 선택된 고객과 간격 순서를 재현할 수 있습니다.</p>'
        document += f'<p><strong>시드: {e(random_events[0]["seed"])}</strong> / 전체 날짜와 A/B별 전송 시각은 이벤트기록.csv와 TC 상세에서 확인할 수 있습니다.</p>'
        document += '<style>#random-events{font-size:13px;table-layout:auto}#random-events th{width:auto}#random-events td{padding:8px}#random-events td:first-child{white-space:nowrap}</style><table id="random-events"><thead><tr>'
        short_headers=['회차','시작 시각','계획 선전송','전송 순서','설정 ms','전송 ms','접수 순서','접수 ms','A 결과','B 결과','시험']
        document+=''.join(f'<th>{e(h)}</th>' for h in short_headers)+'</tr></thead><tbody>'
        for ev,row in zip(random_events,event_rows):
            display=row[:11];display[1]=str(display[1]).split('T')[-1][:12]
            document+=f'<tr data-status="{e(ev["test_status"])}">'+''.join(f'<td>{e(v)}</td>' for v in display)+'</tr>'
        document+='</tbody></table>'
    document += '<div class="controls"><input id="search" aria-label="TC 검색" placeholder="TC ID, 시험명, 기대 결과 검색"><select id="status" aria-label="결과 필터"><option value="">전체 결과</option>'
    document += ''.join(f'<option value="{k}">{v}</option>' for k,v in labels.items() if k != 'INCOMPLETE')
    document += '</select><button onclick="document.querySelectorAll(\'details\').forEach(x=>x.open=true)">TC 모두 펼치기</button><button onclick="document.querySelectorAll(\'details\').forEach(x=>x.open=true);window.print()">인쇄 / PDF 저장</button></div><table id="cases"><thead><tr><th>TC ID</th><th>시험 내용</th><th>결과</th><th>소요 시간</th></tr></thead><tbody>'
    document += ''.join(body) + '</tbody></table><footer>이번 실행 결과만 기록했습니다. 미실행과 건너뜀은 통과에 포함하지 않습니다. 원본: result.json, junit.xml(테스트 실행 시), setup-and-test.log.</footer>'
    document += '''<script>function filter(){const q=document.getElementById('search').value.toLowerCase(),s=document.getElementById('status').value;document.querySelectorAll('#cases tbody tr').forEach(r=>r.hidden=!(r.textContent.toLowerCase().includes(q)&&(!s||r.dataset.status===s)))}document.getElementById('search').oninput=filter;document.getElementById('status').onchange=filter;</script></html>'''
    (folder / '시험성적서.html').write_text(document, encoding='utf-8')
    print(f'\n시험성적서: {folder / "시험성적서.html"}\n{summary}', flush=True)
    return data


def write_junit(folder, rows):
    root = ET.Element('testsuite', name='submission', tests=str(len(rows)),
                      failures=str(sum(r['status']=='FAIL' for r in rows)),
                      errors=str(sum(r['status']=='ERROR' for r in rows)),
                      skipped=str(sum(r['status'] in ('SKIP','NOT_RUN') for r in rows)))
    for row in rows:
        case = ET.SubElement(root, 'testcase', name=row['id']+' '+row['title'], classname=row.get('source',''), time=str(row.get('duration',0)))
        tag = {'FAIL':'failure','ERROR':'error','SKIP':'skipped','NOT_RUN':'skipped'}.get(row['status'])
        if tag: ET.SubElement(case, tag).text = row.get('actual','')
        ET.SubElement(case, 'system-out').text = row.get('actual','')
    ET.ElementTree(root).write(Path(folder)/'junit.xml', encoding='utf-8', xml_declaration=True)

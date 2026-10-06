"""TC-aware pytest / unittest runners. HTML is generated even on test failures."""
import argparse
import contextlib
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import time
import statistics
import traceback
import unittest
from test_report import write_report, write_junit


class InventoryReport:
    def __init__(self, project):
        self.catalog = json.loads((project/'docs/test_cases.json').read_text(encoding='utf-8'))
        self.by_function = {x['Automation']:x for x in self.catalog}
        self.items = {}; self.phases = {}; self.errors = []

    def pytest_collection_finish(self, session):
        for item in session.items:
            function = item.originalname or item.name
            tc = self.by_function.get(function)
            if not tc: raise RuntimeError(f'TC 명세 누락: {function}')
            marker = item.get_closest_marker('tc')
            if not marker or marker.args[0] != tc['TC ID']: raise RuntimeError(f'TC ID 불일치: {function}')
            self.items[item.nodeid] = tc
        selected = {tc['TC ID'] for tc in self.items.values()}
        print(f'\n[TC 목록] {len(selected)}개 명세 / {len(self.items)}개 실행 조건')
        for tc in self.catalog:
            if tc['TC ID'] not in selected: continue
            print(f"{tc['TC ID']} | {tc['Title']} | 기대: {tc['Result']}")

    def pytest_collectreport(self, report):
        if report.failed: self.errors.append(str(report.longrepr))

    def pytest_runtest_logreport(self, report):
        phases = self.phases.setdefault(report.nodeid, [])
        phases.append(report)
        if report.when == 'teardown':
            row = self.row(report.nodeid)
            print(f"\n[{row['status']}] {row['id']} | {row['title']} ({row['duration']:.3f}초)", flush=True)
            event=row.get('random_event')
            if event:
                print(f"시작 {event['started_at']} | 계획 {event['first_sender']} 먼저 | 실제 전송 {'→'.join(event['actual_send_order'])} | "
                      f"설정 {event['gap_ms']}ms / 전송 {event.get('send_gap_ms','미측정')}ms / 접수 {event.get('server_arrival_gap_ms','미측정')}ms | "
                      f"서버 접수 {'→'.join(event['server_order'])} | 주문 성공 {','.join(event['successful_customers']) or '없음'} / "
                      f"품절 {','.join(event['sold_out_customers']) or '없음'} | seed={event['seed']}",flush=True)

    def row(self, nodeid):
        tc = self.items[nodeid]; phases = self.phases.get(nodeid, [])
        status = 'NOT_RUN'; evidence = []; random_event=None
        for phase in phases:
            if phase.failed:
                status = 'FAIL' if phase.when == 'call' and status != 'ERROR' else 'ERROR'
                evidence.append(f'{phase.when}: {phase.longrepr}')
            elif phase.skipped and status not in ('FAIL','ERROR'):
                status='SKIP'; evidence.append(str(phase.longrepr))
            elif phase.when=='call' and phase.passed and status=='NOT_RUN': status='PASS'
            for name, value in phase.user_properties:
                if name=='random_order_evidence': random_event=json.loads(value)
                entry = f'{name}: {value}'
                if entry not in evidence: evidence.append(entry)
            for name, text in phase.sections:
                if text and text not in evidence: evidence.append(text)
        if status=='PASS': evidence.insert(0, '테스트 코드의 모든 검증문과 준비/정리가 성공했습니다.')
        if status=='NOT_RUN': evidence.append('실행 결과가 없습니다.')
        parameter = '['+nodeid.split('[',1)[1] if '[' in nodeid else ''
        procedure=tc['Procedure']
        if random_event:
            procedure=f"{random_event['repeat_index']}회차: 무작위로 {random_event['first_sender']} 먼저, {random_event['gap_ms']}ms 간격 선택. 두 요청 중첩 후 서버 접수 순서대로 결과 검증. seed={random_event['seed']}"
        row=dict(id=tc['TC ID']+parameter, title=tc['Title'], status=status,
                    duration=sum(p.duration for p in phases), precondition=tc['Precondition'],
                    procedure=procedure, expected=tc['Result'], actual='\n'.join(evidence), source=nodeid)
        if random_event:
            random_event['test_status']=status
            row['random_event']=random_event
        return row


class DetailedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.rows=[]; self.current={}

    def startTest(self, test):
        super().startTest(test)
        self.started=time.perf_counter()
        name=test.id()
        self.current=dict(id='QA4-'+hashlib.sha256(name.encode()).hexdigest()[:8].upper(),
            title=test.shortDescription() or name.rsplit('.',1)[-1], status='PASS', duration=0,
            precondition='테스트 코드의 setUp / mock / fixture', procedure=name,
            expected='해당 테스트에 정의된 검증문(assert)이 모두 성립', actual='', source=name)

    def addFailure(self, test, err):
        super().addFailure(test,err); self.current.update(status='FAIL',actual=self._exc_info_to_string(err,test))
    def addError(self, test, err):
        super().addError(test,err)
        if not self.current:
            self.startTest(test)
            self.current.update(status='ERROR',actual=self._exc_info_to_string(err,test)); self.stopTest(test)
        else: self.current.update(status='ERROR',actual=self._exc_info_to_string(err,test))
    def addSkip(self, test, reason):
        super().addSkip(test,reason)
        outside=not self.current
        if outside: self.startTest(test)
        self.current.update(status='SKIP',actual=reason)
        if outside: self.stopTest(test)
    def addExpectedFailure(self,test,err):
        super().addExpectedFailure(test,err); self.current.update(status='SKIP',actual='예상된 실패: '+self._exc_info_to_string(err,test))
    def addUnexpectedSuccess(self,test):
        super().addUnexpectedSuccess(test); self.current.update(status='FAIL',actual='예상 실패 테스트가 성공함: 기대 조건 재검토 필요')
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err:
            self.current['status']='FAIL' if issubclass(err[0],test.failureException) else 'ERROR'
            self.current['actual']+='\n'+str(subtest)+'\n'+self._exc_info_to_string(err,test)
    def stopTest(self,test):
        self.current['duration']=time.perf_counter()-self.started
        if self.current['status']=='PASS': self.current['actual']='테스트 코드의 검증문과 준비/정리가 성공했습니다.'
        row=self.current; self.rows.append(row)
        print(f"[{row['status']}] {row['id']} | {row['title']} ({row['duration']:.3f}초)",flush=True)
        self.current={}; super().stopTest(test)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--problem',type=int,choices=[2,4],required=True)
    parser.add_argument('--project',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--concurrency-only',action='store_true')
    parser.add_argument('--runs',type=int,default=50)
    parser.add_argument('--gap-min-ms',type=int,default=10);parser.add_argument('--gap-max-ms',type=int,default=50)
    parser.add_argument('--seed',type=int,default=None)
    args=parser.parse_args(); project=args.project.resolve(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    os.chdir(project); sys.path.insert(0,str(project))
    rows=[]; code=1; random_events=[]
    try:
        if args.problem==2:
            import pytest
            plugin=InventoryReport(project)
            pytest_args=['-q','-s',f'--junitxml={out / "junit.xml"}']
            if args.concurrency_only:
                pytest_args += ['-k','test_concurrent_last_stock',f'--concurrency-runs={args.runs}',f'--gap-min-ms={args.gap_min_ms}',f'--gap-max-ms={args.gap_max_ms}']
            if args.seed is not None: pytest_args += [f'--random-seed={args.seed}']
            code=int(pytest.main(pytest_args,plugins=[plugin]))
            rows=[plugin.row(n) for n in plugin.items]
            for error in plugin.errors:
                rows.append(dict(id='COLLECTION',title='테스트 수집',status='ERROR',actual=error))
            random_events=[r['random_event'] for r in rows if 'random_event' in r]
            if random_events:
                (out/'random-events.json').write_text(json.dumps(random_events,ensure_ascii=False,indent=2),encoding='utf-8')
        else:
            suite=unittest.defaultTestLoader.discover(str(project/'tests'))
            result=unittest.TextTestRunner(verbosity=0,resultclass=DetailedResult).run(suite)
            rows=result.rows; code=0 if result.wasSuccessful() and result.testsRun else 1
            write_junit(out,rows)
        if not rows: raise RuntimeError('실행할 테스트가 없습니다.')
    except BaseException:
        rows.append(dict(id='RUNNER',title='시험 실행기',status='ERROR',actual=traceback.format_exc())); code=1
    write_report(out,f'문제 {args.problem}',
                 '로컬 HTTP 스텁 검증. 실제 B마트 서버가 아닙니다.' if args.problem==2 else
                 '가상 데이터와 mock 기반 자동 테스트. 실제 단말/AI API/주문 E2E 결과가 아닙니다.', rows,code,random_events=random_events)
    return code

if __name__=='__main__': sys.exit(main())

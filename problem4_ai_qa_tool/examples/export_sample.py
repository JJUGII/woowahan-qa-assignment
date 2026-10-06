"""가상 화면으로 Python/Kotlin 표시 검증 코드를 생성. 단말/API 호출 없음."""
from pathlib import Path
import argparse,sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from recorder.writer_agent import Screen
from recorder.writer_session import WriterSession

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',default='examples/output_sample')
    args=parser.parse_args()
    source=Path(__file__).with_name('input_sample.xml')
    screen=Screen.parse(source.read_text(encoding='utf-8'))
    session=WriterSession()
    session.goal='설정 화면의 제목을 확인한다.'
    session.arrival='설정'
    session.initial='가상 XML 기반 예시. 실제 앱 실행/AI 응답 결과가 아님.'
    target=screen.arrival('설정')
    assert target is not None
    session.records=[{'kind':'selector','step':screen.step(target,'ASSERT','가상 입력 예시'),
                      'description':'설정 제목 표시 검증'}]
    directory=Path(args.output_dir)
    for language in ['Python','Kotlin']:
        print(session.export(directory,'settings_sample',language))
    (directory/'input_summary.json').write_text(json.dumps(screen.summary(),ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__': main()

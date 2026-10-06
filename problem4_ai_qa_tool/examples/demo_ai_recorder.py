"""No device/API needed: validated demo recommendations -> explicit confirmation -> files."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder.ai_recommender import DemoProvider, recommend, confirm_step
from recorder.ui_inspector import get_element_by_click
from recorder.code_builder import CodeBuilder


def main():
    parser = argparse.ArgumentParser(description='규칙 기반 데모 — 실제 LLM 호출 없음')
    parser.add_argument('--output', type=Path, default=Path('generated_scripts/demo/test_ai_demo.py'))
    parser.add_argument('--expected-text', required=True, help='사용자가 요구사항에서 확인한 로그인 버튼 문구')
    args = parser.parse_args()
    xml = (Path(__file__).resolve().parents[1] / 'tests/fixtures/login.xml').read_text(encoding='utf-8')
    provider = DemoProvider()
    element = get_element_by_click(xml, 200, 250)
    builder = CodeBuilder('ai_demo')
    for mode, assertion, expected, description in [
        ('ASSERT', 'text_equals', args.expected_text, '로그인 버튼 문구가 요구사항과 일치하는지 확인한다'),
        ('CLICK', None, None, '로그인 버튼을 눌러 인증을 시작한다'),
    ]:
        candidates, response = recommend(provider, xml, element, mode, description)
        step = confirm_step(candidates, response, element, xml, 's1', mode, assertion, expected,
                            True, response['step_description'], provider.name)
        builder.add_confirmed_step(step)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    builder.generate_script(args.output)
    print(json.dumps({'provider': provider.name, 'script': str(args.output.resolve()),
                      'confirmed_steps': len(builder.confirmed_steps),
                      'note': '코드 생성 데모입니다. 실제 단말 실행/LLM 품질 검증 결과가 아닙니다.'}, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Generate a Kotlin order-flow example; does not connect, click, or call an API."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recorder.ai_recommender import ConfirmedStep, xpath_literal
from recorder.kotlin_builder import KotlinCodeBuilder


def build_example():
    builder = KotlinCodeBuilder('order_flow')
    for text in ('치킨', '후라이드', '주문하기', '결제'):
        builder.add_click_action({'text': text})
    builder.add_sleep_action(5)
    builder.add_confirmed_step(ConfirmedStep(
        'ASSERT', 'XPATH', '//*[@text=' + xpath_literal('접수 대기') + ']',
        '접수 대기 요소가 표시되는지 확인한다.', 'visible', True, '사용자 제공 예시'))
    return builder


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='generated_scripts/kotlin_demo')
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    builder = build_example()
    path = output / builder.filename
    builder.generate_script(path)
    print(path.resolve())

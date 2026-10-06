"""Observed-action journal shared by the manual recorder and bounded AI loop."""
from dataclasses import asdict
import json
from pathlib import Path
import threading
import uuid

from recorder.code_builder import CodeBuilder
from recorder.kotlin_builder import KotlinCodeBuilder
from recorder.writer_agent import needs_confirmation


class WriterSession:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.records = []
        self.cancel = threading.Event()
        self.goal = self.arrival = self.initial = ''

    def export(self, directory, name, language):
        builder = KotlinCodeBuilder(name) if language == 'Kotlin' else CodeBuilder(name)
        path = Path(directory) / (builder.filename if language == 'Kotlin' else f'test_{name}.py')
        metadata = path.with_suffix('.scenario.json')
        if any(p.exists() for p in (path, metadata, path.with_suffix('.steps.json'))):
            raise ValueError('같은 이름의 파일이 있습니다. 다른 시나리오 이름을 입력하세요.')
        if not self.records:
            raise ValueError('먼저 동작을 기록하세요.')
        for row in self.records:
            if row['kind'] == 'selector':
                builder.add_confirmed_step(row['step'])
            elif row['kind'] == 'input':
                builder.add_input_action(row['text'])
            elif row['kind'] == 'back':
                builder.add_back_action()
            elif row['kind'] == 'swipe':
                builder.add_swipe_action(*row['coords'])
            elif row['kind'] == 'wait':
                builder.add_sleep_action(row['seconds'])
        Path(directory).mkdir(parents=True, exist_ok=True)
        builder.generate_script(str(path))
        rows = [dict(row, step=asdict(row['step'])) if row['kind'] == 'selector' else row for row in self.records]
        metadata.write_text(json.dumps({'version': 1, 'goal': self.goal, 'arrival_exact_text': self.arrival,
                            'initial_state': self.initial, 'steps': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
        return path


def run_agent(device, session, planner, instruction, emit, max_steps=25, recommend_only=False):
    """Only completed actions enter the journal. Pause invalidates in-flight responses."""
    unchanged, previous = 0, None

    def record(row):
        session.records.append(row)
        emit('step', row)

    for _ in range(max_steps):
        if session.cancel.is_set():
            return
        emit('status', '현재 화면을 확인하고 있습니다…')
        screen = device.screen()
        if session.cancel.is_set():
            return
        target = screen.arrival(session.arrival)
        if target:
            if recommend_only:
                emit('message', '도착 문구가 보입니다. 해당 요소를 선택해 표시 검증을 기록할 수 있습니다.')
                return
            if device.perform({'action': 'assert', 'target': target}, screen, session.cancel, record, 'AI 진행 ,  사용자 도착 조건'):
                emit('message', '도착 문구가 표시된 것을 확인했고, 마지막 단계에 표시 검증을 기록했습니다.')
                emit('complete', '')
            return
        unchanged = unchanged + 1 if screen.signature == previous else 0
        if unchanged >= 3:
            raise ValueError('같은 화면이 반복되어 멈췄습니다. 추가 지시를 입력하거나 직접 조작하세요.')
        previous = screen.signature
        emit('status', 'AI가 다음 동작을 판단하고 있습니다…')
        history = [r['description'] for r in session.records][-20:]
        action = planner.next(session.goal, session.arrival, instruction, history, screen)
        emit('usage', '')
        if session.cancel.is_set():
            return
        emit('message', action['reason'])
        if recommend_only:
            label = screen.elements.get(action['target'], {}).get('attrs', {})
            emit('message', '추천 동작: ' + action['action'] + ' / ' +
                 (label.get('text') or label.get('content-desc') or action['direction'] or action['text']))
            return
        if action['action'] in {'ask', 'done'}:
            if action['action'] == 'done':
                emit('message', '지정한 도착 문구가 확인되지 않아 완료 처리하지 않았습니다.')
            return
        if needs_confirmation(action, screen):
            emit('message', '주문, 결제, 권한, 동의 관련 요소입니다. 화면에서 직접 선택해 기록한 뒤 AI를 이어서 진행하세요.')
            return
        if action['action'] == 'input' and action['text'] not in session.goal + '\n' + instruction:
            emit('message', '사용자가 제공하지 않은 입력값이라 멈췄습니다. 입력할 값을 추가 지시에 적어주세요.')
            return
        emit('status', action['reason'])
        if not device.perform(action, screen, session.cancel, record, planner.provider.name):
            return
        session.cancel.wait(.7)
    emit('message', f'한 번에 진행하는 {max_steps}단계에 도달해 멈췄습니다. 확인 후 이어서 진행할 수 있습니다.')

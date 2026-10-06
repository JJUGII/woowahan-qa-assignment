"""Local usage estimates. No prompts, screenshots or credentials in this ledger."""
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import threading

PRICING_SOURCE = 'https://developers.openai.com/api/docs/pricing'
PRICING_DATE = '2026-10-06'
# Standard processing, short context, USD / 1M tokens. Custom models need explicit rates.
PRESETS = {'gpt-6-luna': ('0.10', '0.01', '0.125', '0.50'),
           'gpt-6.1-sol': ('2', '0.10', '2.50', '10'),
           'gpt-6-astra': ('10', '1', '12.50', '50')}


def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError()
        return result
    except (InvalidOperation, ValueError):
        raise ValueError('금액은 0 이상의 유한한 숫자로 입력하세요.') from None


@dataclass(frozen=True)
class Rates:
    input: str
    cached: str
    write: str
    output: str

    def __post_init__(self):
        for value in asdict(self).values():
            money(value)

    def cost(self, counts):
        return sum((Decimal(counts[key]) * money(value) for key, value in asdict(self).items()), Decimal(0)) / 1_000_000


def usage_counts(usage):
    """Cached read/write are subsets of input; reasoning is already part of output."""
    if not isinstance(usage, dict):
        return None
    incoming = usage.get('prompt_tokens', usage.get('input_tokens'))
    outgoing = usage.get('completion_tokens', usage.get('output_tokens'))
    detail = usage.get('prompt_tokens_details', usage.get('input_tokens_details')) or {}
    if not isinstance(detail, dict):
        return None
    cached, write = detail.get('cached_tokens', 0), detail.get('cache_write_tokens', 0)
    if any(type(v) is not int or v < 0 for v in (incoming, outgoing, cached, write)):
        return None
    if cached + write > incoming:
        return None
    return dict(input=incoming - cached - write, cached=cached, write=write, output=outgoing)


class UsageLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.rows = []
        self.notice = ''
        if self.path.exists():
            try:
                lines = self.path.read_text(encoding='utf-8').splitlines()
            except (OSError, UnicodeError):
                self.notice = '과거 비용 기록을 읽지 못했습니다. 오늘 합계가 불완전합니다.'
                lines = []
            for line in lines:
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict) or not {'scenario', 'date', 'cost', 'counts'} <= row.keys():
                        raise ValueError()
                    if not isinstance(row['scenario'], str) or not isinstance(row['date'], str):
                        raise ValueError()
                    datetime.fromisoformat(row['date'])
                    if row['cost'] is not None:
                        money(row['cost'])
                    self.rows.append(row)
                except (ValueError, TypeError):
                    self.notice = '일부 과거 비용 기록을 읽지 못했습니다. 오늘 합계가 불완전할 수 있습니다.'

    def record(self, scenario, model, rates, usage, status):
        counts = usage_counts(usage)
        row = {'scenario': scenario, 'date': datetime.now().astimezone().isoformat(),
               'model': model, 'rates': asdict(rates), 'counts': counts, 'status': status,
               'cost': str(rates.cost(counts)) if counts is not None else None}
        with self.lock:
            self.rows.append(row)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            except OSError:
                self.notice = '비용 기록을 파일에 저장하지 못했습니다. 이번 실행에서만 집계합니다.'
        return row

    def totals(self, scenario=None, today=False):
        with self.lock:
            rows = [r for r in self.rows if (scenario is None or r['scenario'] == scenario)
                    and (not today or r['date'][:10] == datetime.now().astimezone().date().isoformat())]
        return (sum((money(r['cost']) for r in rows if r['cost'] is not None), Decimal(0)),
                len(rows), sum(r['cost'] is None for r in rows))

    def check_budget(self, scenario, budget, rates, payload, output_limit):
        cost, _, unknown = self.totals(scenario)
        if unknown:
            raise ValueError('사용량을 받지 못한 요청이 있어 자동 진행을 멈췄습니다. 비용 상세를 확인하세요.')
        # Conservative bound for our capped text-only requests, with protocol overhead.
        incoming = len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) * 2 + 2048
        if incoming > 60000:
            raise ValueError('요청이 너무 깁니다. 목표와 추가 지시를 줄여주세요.')
        estimate = (Decimal(incoming) * max(money(rates.input), money(rates.cached), money(rates.write))
                    + Decimal(output_limit) * money(rates.output)) / 1_000_000
        if cost + estimate > money(budget):
            raise ValueError(f'다음 요청의 보수적 예상 비용 ${estimate:.5f}이 남은 예산을 넘습니다.')
        return estimate

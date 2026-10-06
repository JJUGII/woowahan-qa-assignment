"""각 시험의 서버와 재고를 새로 준비하고, 시험이 끝나면 정리합니다."""
import threading
import random
import secrets
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace

import pytest

from app import Inventory, StockServer
from helpers import Client


# 실행할 때 반복 횟수, 요청 간격 범위와 재현용 번호를 지정할 수 있게 합니다.
def pytest_addoption(parser):
    parser.addoption('--concurrency-runs', type=int, default=3)
    parser.addoption('--gap-min-ms', type=int, default=10)
    parser.addoption('--gap-max-ms', type=int, default=50)
    parser.addoption('--random-seed', type=int, default=None,
                     help='Replay the same planned sender/gap sequence; timings may vary.')


# 동시 주문의 회차별 고객 순서와 간격을 무작위로 미리 정합니다.
def pytest_generate_tests(metafunc):
    if 'order_case' not in metafunc.fixturenames:
        return
    config=metafunc.config
    runs=config.getoption('--concurrency-runs')
    low=config.getoption('--gap-min-ms'); high=config.getoption('--gap-max-ms')
    if not (1 <= runs <= 1000 and 10 <= low <= high <= 80):
        raise pytest.UsageError('Use 1..1000 runs and 10 <= gap-min-ms <= gap-max-ms <= 80.')
    seed=config.getoption('--random-seed')
    if seed is None: seed=secrets.randbits(32)
    # 같은 번호를 넣으면 같은 순서와 간격이 선택됩니다.
    rng=random.Random(seed)
    cases=[dict(seed=seed,repeat_index=i,first_sender=rng.choice(['A','B']),gap_ms=rng.randint(low,high))
           for i in range(1,runs+1)]
    metafunc.parametrize('order_case',cases,
        ids=[f"run{x['repeat_index']:03d}-{x['first_sender']}-first-{x['gap_ms']}ms" for x in cases])


# 서버를 켜서 시험에 제공하고, 성공/실패와 관계없이 사용 후 종료합니다.
@contextmanager
def running_server(stocks, observer=None):
    store = Inventory(stocks, on_admission=observer)
    # 내 PC에서만 접속하며, 비어 있는 통신 포트를 자동으로 골라 충돌을 피합니다.
    server = StockServer(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        client = Client(f"http://127.0.0.1:{server.server_port}")
        # 정해진 시간만 기다리는 대신, 실제 재고 조회에 응답하는지 확인합니다.
        assert client.stock(next(iter(stocks))).status == 200
        yield SimpleNamespace(client=client, store=store, url=client.base_url)
    finally:
        # 시험이 끝나거나 실패하면 서버와 작업을 정리합니다.
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "Stub server did not stop"


@pytest.fixture
# fixture는 시험 준비 도우미입니다. 시험마다 새 서버와 독립된 재고를 만듭니다.
def server_factory():
    with ExitStack() as stack:
        def create(stocks=None, observer=None):
            # 일반 시험은 재고 5개/8개를 사용하고, 품절/동시 주문 시험은 원하는 수량을 따로 지정합니다.
            initial = {"P001": 5, "P002": 8} if stocks is None else stocks
            return stack.enter_context(running_server(initial, observer))
        yield create


@pytest.fixture
# 일반 시험에서 바로 요청을 보낼 수 있도록 기본 서버 연결을 준비합니다.
def api(server_factory):
    return server_factory().client

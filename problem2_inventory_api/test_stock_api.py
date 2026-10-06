"""18개 시험 항목입니다. 일부 항목을 여러 조건으로 반복해 기본 실행은 총 25회입니다."""
from concurrent.futures import ThreadPoolExecutor
import json
from datetime import datetime
import threading
import time

import pytest

from helpers import Client, assert_cancel, assert_error, assert_order, assert_stock

# assert는 기대한 결과와 다르면 시험을 실패로 표시합니다.
# @pytest.mark.tc의 번호는 Excel TC 명세서에서 같은 시험을 찾는 데 사용합니다.


@pytest.mark.tc("TC-STK-001")
def test_get_stock(api):
    # 기본 재고 5개를 올바르게 조회하는지 확인합니다.
    assert_stock(api, 5)


@pytest.mark.tc("TC-STK-002")
def test_repeated_reads_do_not_change_stock(api):
    # 여러 번 조회해도 재고 수량은 바뀌지 않아야 합니다.
    for _ in range(3):
        assert_stock(api, 5)


@pytest.mark.tc("TC-ORD-001")
def test_order_decreases_stock(api):
    # 1개 주문하면 재고가 5개에서 4개로 줄고, 다른 상품은 그대로여야 합니다.
    response = api.order()
    assert_order(response, 1)
    assert response.body["stock"]["stock"] == 4
    assert_stock(api, 4)
    assert_stock(api, 8, "P002")


@pytest.mark.tc("TC-ORD-002")
def test_order_multiple_units(api):
    # 3개를 주문하면 주문 수량만큼 줄어 재고가 2개 남아야 합니다.
    assert_order(api.order(3), 3)
    assert_stock(api, 2)


@pytest.mark.tc("TC-ORD-003")
def test_order_all_stock_marks_sold_out(api):
    # 남은 5개를 모두 주문하면 재고 0, 품절, 주문 불가 상태가 되어야 합니다.
    response = api.order(5)
    assert_order(response, 5)
    assert response.body["stock"] == {
        "productId": "P001", "stock": 0, "soldOut": True, "orderable": False}
    # 다른 고객이 바로 조회해도 재고가 0으로 나오는지 확인합니다.
    assert_stock(Client(api.base_url), 0)


@pytest.mark.tc("TC-ORD-004")
def test_sold_out_order_fails_without_mutation(server_factory):
    # 품절 상품의 주문은 거절하고 재고와 주문 기록을 바꾸지 않아야 합니다.
    server = server_factory({"P001": 0, "P002": 8})
    assert_error(server.client.order(), 409, "OUT_OF_STOCK")
    assert_stock(server.client, 0)
    assert_stock(server.client, 8, "P002")
    assert server.store.order_snapshot() == []


@pytest.mark.tc("TC-ORD-005")
def test_excess_quantity_has_no_partial_deduction(server_factory):
    # 재고보다 많이 주문하면 일부만 차감하지 않고 주문 전체를 거절해야 합니다.
    server = server_factory()
    assert_error(server.client.order(6), 409, "OUT_OF_STOCK")
    assert_stock(server.client, 5)
    assert server.store.order_snapshot() == []
    # 잘못된 주문이 실패한 뒤에도 정상 주문은 처리할 수 있어야 합니다.
    assert_order(server.client.order(5), 5)
    assert_stock(server.client, 0)


@pytest.mark.tc("TC-CAN-001")
def test_cancel_restores_exact_quantity(api):
    # 3개 주문을 취소하면 차감했던 3개만 복구되어야 합니다.
    order_id = assert_order(api.order(3), 3)
    assert_stock(api, 2)
    assert_cancel(api.cancel(order_id), order_id, 3)
    assert_stock(api, 5)


@pytest.mark.tc("TC-CAN-002")
def test_cancel_sold_out_product_clears_sold_out(api):
    # 품절된 상품도 주문 취소로 재고가 돌아오면 다시 구매할 수 있어야 합니다.
    order_id = assert_order(api.order(5), 5)
    assert_stock(api, 0)
    response = api.cancel(order_id)
    assert_cancel(response, order_id, 5)
    assert response.body["stock"]["soldOut"] is False
    assert_stock(Client(api.base_url), 5)


@pytest.mark.tc("TC-CAN-003")
def test_other_customer_can_buy_immediately_after_cancel(server_factory):
    # A가 취소한 직후 B가 복구된 마지막 1개를 구매할 수 있어야 합니다.
    server = server_factory({"P001": 1})
    order_a = assert_order(server.client.order(), 1)
    assert_cancel(server.client.cancel(order_a), order_a, 1)
    buyer_b = Client(server.url)
    order_b = assert_order(buyer_b.order(customer_id="B"), 1, "B")
    assert order_b != order_a
    assert_stock(buyer_b, 0)


@pytest.mark.tc("TC-CAN-004")
def test_repeated_cancel_does_not_restore_twice(api):
    # 같은 주문을 두 번 취소해도 재고는 한 번만 복구되어야 합니다.
    order_id = assert_order(api.order(2), 2)
    assert_cancel(api.cancel(order_id), order_id, 2)
    assert_cancel(api.cancel(order_id), order_id, 0)
    assert_stock(api, 5)


@pytest.mark.tc("TC-ERR-001")
def test_unknown_product_query(api):
    # 없는 상품을 조회하면 오류가 나고 기존 상품의 재고는 그대로여야 합니다.
    assert_error(api.stock("MISSING"), 404, "PRODUCT_NOT_FOUND")
    assert_stock(api, 5)
    assert_stock(api, 8, "P002")


@pytest.mark.tc("TC-ERR-002")
def test_unknown_product_order(server_factory):
    # 없는 상품의 주문은 거절하고 주문 기록도 만들지 않아야 합니다.
    server = server_factory()
    assert_error(server.client.order(product_id="MISSING"), 404, "PRODUCT_NOT_FOUND")
    assert_stock(server.client, 5)
    assert_stock(server.client, 8, "P002")
    assert server.store.order_snapshot() == []


@pytest.mark.tc("TC-ERR-003")
@pytest.mark.parametrize("quantity", [0, -1, 1.5, "1", True, None],
                         ids=["zero", "negative", "fraction", "string", "boolean", "null"])
def test_invalid_quantity_does_not_change_stock(server_factory, quantity):
    # 0, 음수, 소수, 글자, 참/거짓, 빈 값의 6가지 수량을 각각 거절하는지 확인합니다.
    server = server_factory()
    assert_error(server.client.order(quantity), 400, "INVALID_QUANTITY")
    assert_stock(server.client, 5)
    assert server.store.order_snapshot() == []


@pytest.mark.tc("TC-ERR-004")
def test_unknown_order_cancel_does_not_change_stock(api):
    # 없는 주문 번호를 취소해도 재고가 늘어나서는 안 됩니다.
    assert_error(api.cancel("MISSING"), 404, "ORDER_NOT_FOUND")
    assert_stock(api, 5)
    assert_stock(api, 8, "P002")


@pytest.mark.tc("TC-INT-001")
def test_stock_matches_order_and_cancel_ledger(server_factory):
    # 여러 주문과 취소 뒤에도 계산한 재고와 저장된 주문 기록이 맞아야 합니다.
    server = server_factory({"P001": 10, "P002": 8})
    api = server.client
    orders = [assert_order(api.order(q), q) for q in (2, 3, 1)]
    assert_stock(api, 4)
    assert_cancel(api.cancel(orders[1]), orders[1], 3)
    assert_error(api.order(8), 409, "OUT_OF_STOCK")
    assert_order(api.order(2, product_id="P002"), 2, product_id="P002")
    # 기대 재고는 서버 값을 가져다 쓰지 않고, 처음 수량과 주문/취소 수량으로 계산합니다.
    assert_stock(api, 10 - (2 + 3 + 1) + 3)
    assert_stock(api, 8 - 2, "P002")
    ledger = server.store.order_snapshot()
    assert len(ledger) == 4
    assert sum(o["quantity"] for o in ledger
               if o["productId"] == "P001" and o["status"] == "PAID") == 3


class AdmissionProbe:
    """두 주문이 재고 처리 직전에 함께 대기하게 합니다. 성공/품절 결과를 미리 정하지 않습니다."""
    def __init__(self):
        # 첫 요청 도착, 두 요청 도착, 처리 재개를 알리는 신호를 각각 준비합니다.
        self.first = threading.Event()
        self.both = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.arrivals = []

    def __call__(self, ticket, customer, timestamp_ns):
        with self.lock:
            self.arrivals.append((ticket, customer, timestamp_ns))
            self.first.set()
            if len(self.arrivals) == 2:
                self.both.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("Test did not release the admission gate")


@pytest.mark.tc("TC-CON-001")
@pytest.mark.concurrency
def test_concurrent_last_stock(server_factory, order_case, record_property):
    # 마지막 1개에 두 주문을 겹쳐 보내 성공 1건과 품절 1건인지 확인합니다.
    # 시드는 무작위 선택을 재현하는 번호입니다. 실제 실행 시간까지 같아지지는 않습니다.
    evidence = dict(order_case, started_at=datetime.now().astimezone().isoformat(timespec="microseconds"),
                    events={}, overlap=False, gap_reference="first_server_admission")
    gap_ms = order_case["gap_ms"]
    first = order_case["first_sender"]
    second = "B" if first == "A" else "A"
    probe = AdmissionProbe()
    server = server_factory({"P001": 1}, observer=probe)
    responses = {}

    def send(customer):
        if customer == second:
            # 첫 요청이 서버에 도착한 시각부터 선택한 간격만큼 기다립니다.
            # 첫 요청은 대기 장치에서 기다리므로 두 번째 요청과 처리 시간이 겹칩니다.
            assert probe.first.wait(timeout=3), "First request did not reach the server"
            with probe.lock:
                admitted_customer, admitted_ns = probe.arrivals[0][1:]
            assert admitted_customer == first
            deadline = admitted_ns + gap_ms * 1_000_000
            while (remaining := (deadline - time.monotonic_ns()) / 1_000_000_000) > 0:
                time.sleep(remaining)
        # 요청을 보내기 시작한 시각입니다. 서버가 접수한 시각은 따로 기록합니다.
        event = dict(call_started_at=datetime.now().astimezone().isoformat(timespec="microseconds"),
                     call_started_ns=time.perf_counter_ns())
        evidence["events"][customer] = event
        try:
            response = Client(server.url).order(customer_id=customer)
            responses[customer] = response
            event.update(response_at=datetime.now().astimezone().isoformat(timespec="microseconds"),
                         http_status=response.status, error_code=response.body.get("error", {}).get("code"))
            event["outcome"] = ("SUCCESS" if response.status == 201 else
                                "SOLD_OUT" if response.status == 409 and event["error_code"] == "OUT_OF_STOCK" else "UNEXPECTED")
            return response
        except Exception as error:
            event.update(outcome="REQUEST_ERROR",error=repr(error))
            raise

    try:
        # 두 고객의 요청을 별도 작업으로 실행해 첫 주문이 끝나기 전에 다음 요청을 보냅니다.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {customer: pool.submit(send, customer) for customer in (first, second)}
            try:
                # 두 요청이 모두 도착했고 아직 처리 완료되지 않았는지 확인합니다.
                evidence["overlap"] = probe.both.wait(timeout=3)
                assert evidence["overlap"], "Both requests must reach the admission gate"
                assert all(not future.done() for future in futures.values()), "Requests did not overlap"
            finally:
                # 대기 중인 주문을 풀어 실제 재고 처리와 응답이 진행되게 합니다.
                probe.release.set()
            for future in futures.values():
                future.result(timeout=5)

        arrivals = sorted(probe.arrivals)  # 서버가 부여한 접수 번호순으로 먼저 도착한 고객을 찾습니다.
        winner, loser = arrivals[0][1], arrivals[1][1]
        order_id = assert_order(responses[winner], 1, winner)
        assert_error(responses[loser], 409, "OUT_OF_STOCK")
        assert_stock(server.client, 0)
        ledger = server.store.order_snapshot()
        # 성공한 주문 한 건만 저장됐는지 확인해 중복 판매를 잡습니다.
        assert len(ledger) == 1 and ledger[0]["orderId"] == order_id
        evidence["inventory_checks_passed"] = True

        arrival_gap = (arrivals[1][2] - arrivals[0][2]) / 1_000_000
        # 실제 서버 접수 간격이 범위를 벗어나면 재시도 없이 실패로 기록합니다.
        assert winner == first, "Server admission order differed from the controlled input"
        assert gap_ms <= arrival_gap < 100, f"Server admission gap {arrival_gap:.3f} ms; expected [{gap_ms}, 100)"
        evidence["timing_checks_passed"] = True
    finally:
        probe.release.set()
        arrivals = sorted(probe.arrivals)
        evidence["server_order"] = [entry[1] for entry in arrivals]
        evidence["server_admissions"] = [dict(ticket=t,customer=c,monotonic_ns=ns) for t,c,ns in arrivals]
        events = evidence["events"]
        evidence["actual_send_order"] = sorted(events, key=lambda customer: events[customer]["call_started_ns"])
        if len(events) == 2:
            evidence["send_gap_ms"] = round(abs(events["A"]["call_started_ns"]-events["B"]["call_started_ns"])/1_000_000,3)
        if len(arrivals) == 2:
            evidence["server_arrival_gap_ms"] = round((arrivals[1][2]-arrivals[0][2])/1_000_000,3)
        evidence["successful_customers"] = [c for c,e in events.items() if e.get("outcome")=="SUCCESS"]
        evidence["sold_out_customers"] = [c for c,e in events.items() if e.get("outcome")=="SOLD_OUT"]
        # 중간에 실패하더라도 그때까지의 시각과 결과를 시험성적서에 남깁니다.
        record_property("random_order_evidence", json.dumps(evidence, ensure_ascii=False))
        record_property("random_seed", order_case["seed"])


@pytest.mark.tc("TC-CON-002")
@pytest.mark.concurrency
def test_parallel_cancel_restores_stock_only_once(server_factory):
    # 같은 주문의 취소 요청이 겹쳐도 재고가 한 번만 복구되어야 합니다.
    server = server_factory({"P001": 1})
    order_id = assert_order(server.client.order(), 1)
    # 취소 요청 두 개가 준비될 때까지 기다렸다가 함께 출발시킵니다.
    start = threading.Barrier(2)

    def cancel():
        start.wait(timeout=3)
        return Client(server.url).cancel(order_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(cancel) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    # 두 번 취소해도 한 번만 1개를 복구하고, 나머지 요청은 0개를 복구해야 합니다.
    assert sorted(r.body["restoredQuantity"] for r in results) == [0, 1]
    for response in results:
        assert_cancel(response, order_id, response.body["restoredQuantity"])
    assert_stock(server.client, 1)
    assert server.store.order_snapshot()[0]["status"] == "CANCELLED"

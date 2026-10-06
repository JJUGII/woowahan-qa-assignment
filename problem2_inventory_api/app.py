"""실제 서버 대신 내 PC에서 주문과 재고를 처리하는 시험용 서버입니다. 실행: python app.py --port 8000"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlsplit


# 실패한 이유와 응답 번호를 함께 전달합니다.
class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


@dataclass
# 주문 한 건의 번호, 상품, 고객, 수량과 상태를 보관합니다.
class Order:
    orderId: str
    productId: str
    customerId: str
    quantity: int
    status: str = "PAID"


# 현재 재고와 주문 내역을 관리합니다. 서버를 끄면 이 데이터는 사라집니다.
class Inventory:
    def __init__(self, stocks: dict[str, int], on_admission: Callable | None = None):
        if any(type(q) is not int or q < 0 for q in stocks.values()):
            raise ValueError("Initial stock must be a nonnegative integer")
        self._stocks = dict(stocks)
        self._orders: dict[str, Order] = {}
        self._condition = threading.Condition()
        self._next_ticket = 0
        self._turn = 0
        # 시험할 때만 요청 도착을 알리고 잠시 대기합니다. 외부에서 호출하는 기능은 아닙니다.
        self._on_admission = on_admission

    # 재고가 0이면 품절로, 1개 이상이면 주문 가능으로 표시합니다.
    def _stock(self, product_id: str) -> dict:
        if product_id not in self._stocks:
            raise APIError(404, "PRODUCT_NOT_FOUND", "Unknown product")
        quantity = self._stocks[product_id]
        return {"productId": product_id, "stock": quantity,
                "soldOut": quantity == 0, "orderable": quantity > 0}

    # 재고를 바꾸는 중간 값이 조회되지 않도록 보호합니다.
    def stock(self, product_id: str) -> dict:
        with self._condition:
            return self._stock(product_id)

    # 상품, 고객, 수량을 확인한 뒤 주문을 접수합니다.
    def create_order(self, payload: dict) -> dict:
        product_id, customer_id = payload.get("productId"), payload.get("customerId")
        quantity = payload.get("quantity")
        if not isinstance(product_id, str) or not product_id.strip():
            raise APIError(400, "INVALID_REQUEST", "productId is required")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise APIError(400, "INVALID_REQUEST", "customerId is required")
        # 참/거짓 값이 숫자 1/0으로 잘못 받아들여지지 않도록 수량의 종류도 확인합니다.
        if type(quantity) is not int or quantity <= 0:
            raise APIError(400, "INVALID_QUANTITY", "quantity must be a positive integer")
        with self._condition:
            # 접수 번호와 도착 시각을 남겨 주문 처리 순서를 정합니다.
            ticket = self._next_ticket
            self._next_ticket += 1
            admitted_ns = time.monotonic_ns()
        observer_error = None
        try:
            if self._on_admission:
                self._on_admission(ticket, customer_id, admitted_ns)
        except Exception as exc:
            observer_error = exc
        # 재고 확인부터 차감, 주문 저장까지 다른 요청이 끼어들지 못하도록 잠급니다.
        with self._condition:
            self._condition.wait_for(lambda: ticket == self._turn)
            try:
                if observer_error is not None:
                    raise observer_error
                stock = self._stock(product_id)["stock"]
                if stock < quantity:
                    raise APIError(409, "OUT_OF_STOCK", "Insufficient stock")
                order = Order(str(uuid.uuid4()), product_id, customer_id, quantity)
                self._stocks[product_id] -= quantity
                self._orders[order.orderId] = order
                return {"order": asdict(order), "stock": self._stock(product_id)}
            finally:
                # 이번 주문이 실패해도 다음 주문이 계속 처리되도록 차례를 넘깁니다.
                self._turn += 1
                self._condition.notify_all()

    # 아직 취소하지 않은 주문만 재고를 되돌립니다. 반복 취소로 재고가 더 늘지 않습니다.
    def cancel(self, order_id: str) -> dict:
        with self._condition:
            order = self._orders.get(order_id)
            if order is None:
                raise APIError(404, "ORDER_NOT_FOUND", "Unknown order")
            restored = 0
            if order.status == "PAID":
                restored = order.quantity
                self._stocks[order.productId] += restored
                order.status = "CANCELLED"
            return {"order": asdict(order), "restoredQuantity": restored,
                    "stock": self._stock(order.productId)}

    def order_snapshot(self) -> list[dict]:
        """저장된 주문을 복사해 시험에서 건수를 확인합니다. 원본 주문은 변경하지 않습니다."""
        with self._condition:
            return [asdict(order) for order in self._orders.values()]


# 여러 고객의 요청을 동시에 받을 수 있는 시험용 서버입니다.
class StockServer(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, address: tuple[str, int], inventory: Inventory):
        self.inventory = inventory
        super().__init__(address, Handler)


# 들어온 요청을 읽고 조회, 주문, 취소 기능으로 연결합니다.
class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass  # 시험 결과를 보기 쉽도록 일반 접속 로그는 생략합니다.

    # 처리 결과와 성공/실패 번호를 요청한 고객에게 돌려줍니다.
    def _reply(self, status: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # 요청 내용을 읽습니다. 비어 있거나 형식이 잘못된 요청은 거절합니다.
    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError()
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError()
            return payload
        except (ValueError, UnicodeError):
            raise APIError(400, "INVALID_REQUEST", "A JSON object body is required") from None

    # 요청 주소에 맞는 기능을 실행합니다. 없는 주소는 찾을 수 없다고 응답합니다.
    def _dispatch(self):
        path = urlsplit(self.path).path
        inventory = self.server.inventory
        if self.command == "GET":
            match = re.fullmatch(r"/v1/products/([^/]+)/stock", path)
            if match:
                return 200, inventory.stock(match[1])
        if self.command == "POST":
            if path == "/v1/orders":
                return 201, inventory.create_order(self._body())
            match = re.fullmatch(r"/v1/orders/([^/]+)/cancel", path)
            if match:
                return 200, inventory.cancel(match[1])
        raise APIError(404, "NOT_FOUND", "Unknown endpoint")

    # 처리 중 발생한 예상된 오류도 시험에서 확인할 수 있는 응답으로 바꿉니다.
    def _handle(self):
        try:
            status, body = self._dispatch()
        except APIError as exc:
            status, body = exc.status, {"error": {"code": exc.code, "message": str(exc)}}
        self._reply(status, body)

    do_GET = _handle
    do_POST = _handle


# 이 파일을 직접 실행할 때만 서버를 켭니다. 자동 시험에서는 준비 코드가 서버를 켭니다.
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    with StockServer(("127.0.0.1", args.port), Inventory({"P001": 5, "P002": 8})) as server:
        print(f"Stock stub: http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

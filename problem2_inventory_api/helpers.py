"""여러 시험에서 공통으로 쓰는 요청 보내기와 결과 확인 기능입니다."""
import json
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener


@dataclass(frozen=True)
# 서버가 돌려준 응답 번호와 내용을 한곳에 담습니다.
class Response:
    status: int
    body: dict
    headers: dict


# 고객 역할로 시험용 서버에 조회, 주문, 취소 요청을 보냅니다.
class Client:
    def __init__(self, base_url):
        self.base_url = base_url

    # 요청을 보내고 결과를 읽는 공통 기능입니다. 응답은 최대 5초까지 기다립니다.
    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base_url + path, data=data, method=method,
                          headers={"Content-Type": "application/json"})
        # 고객별 요청이 서로 영향을 주지 않도록 각 요청은 별도 연결로 보냅니다.
        opener = build_opener(ProxyHandler({}))
        try:
            response = opener.open(request, timeout=5)
        # 품절 같은 실패 응답도 시험 대상이므로 내용을 읽어 확인할 수 있게 합니다.
        except HTTPError as error:
            response = error
        with response:
            return Response(response.status, json.load(response), dict(response.headers))

    # 상품의 현재 재고를 조회합니다.
    def stock(self, product_id="P001"):
        return self.request("GET", f"/v1/products/{quote(product_id, safe='')}/stock")

    # 누가 어떤 상품을 몇 개 주문할지 서버에 전달합니다.
    def order(self, quantity=1, product_id="P001", customer_id="A"):
        return self.request("POST", "/v1/orders", {
            "productId": product_id, "customerId": customer_id, "quantity": quantity})

    # 주문 번호로 취소를 요청합니다.
    def cancel(self, order_id):
        return self.request("POST", f"/v1/orders/{quote(order_id, safe='')}/cancel")


# 예상 재고와 실제 재고를 비교하고, 품절/주문 가능 표시도 함께 확인합니다.
def assert_stock(client, expected, product_id="P001"):
    response = client.stock(product_id)
    assert response.status == 200, response
    assert response.body == {"productId": product_id, "stock": expected,
                             "soldOut": expected == 0, "orderable": expected > 0}
    assert response.headers["Cache-Control"] == "no-store"
    return response.body


# 실패했다는 사실뿐 아니라 품절, 잘못된 수량 등 실패 이유도 확인합니다.
def assert_error(response, status, code):
    assert response.status == status, response
    assert set(response.body) == {"error"}
    assert response.body["error"]["code"] == code
    assert response.body["error"]["message"]


# 주문 성공 여부와 주문에 저장된 고객, 상품, 수량을 확인합니다.
def assert_order(response, quantity, customer_id="A", product_id="P001"):
    assert response.status == 201, response
    order = response.body["order"]
    assert order["orderId"]
    assert order == {"orderId": order["orderId"], "productId": product_id,
                     "customerId": customer_id, "quantity": quantity, "status": "PAID"}
    return order["orderId"]


# 해당 주문이 취소됐는지, 복구한 재고 수량이 맞는지 확인합니다.
def assert_cancel(response, order_id, restored):
    assert response.status == 200, response
    assert response.body["order"]["orderId"] == order_id
    assert response.body["order"]["status"] == "CANCELLED"
    assert response.body["restoredQuantity"] == restored

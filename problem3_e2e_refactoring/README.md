# 문제 3. E2E 자동화 코드 리뷰 및 리팩토링

## Q1. 기존 코드에는 어떤 문제가 있는가?

화면 문구에 의존하고, 상태와 무관한 고정 대기와 분산된 Timeout 설정으로 정상 기능도 CI에서 간헐적으로 실패할 수 있습니다. 마지막에는 ‘접수 대기’ 문구의 존재만 확인하므로 실제 주문 성공 여부도 충분히 검증하지 못합니다.

### 1. 안정성

- 고정 대기: Thread.sleep(5000)은 화면 준비 여부와 관계없이 항상 5초를 기다립니다. 화면이 빨리 준비되면 불필요한 대기 시간이 발생하고, 5초 이후에도 준비되지 않아 다음 단계의 최대 대기 시간까지 넘으면 실패할 수 있습니다. 특정 화면이나 상태가 나타나는 즉시 진행하는 조건 기반 대기로 변경하겠습니다.
- Timeout 관리: device.wait()는 최대 대기 시간 안에 요소가 나타나면 즉시 반환합니다. 3000ms, 5000ms는 고정 수면 시간이 아니라 최대 대기 시간입니다. 단계별 Timeout이 코드에 직접 지정되어 있어 실행 환경 변화에 대응하기 어렵습니다. 공통 Timeout 정책을 두고 실제 지연 수준과 서비스 허용 시간에 맞게 관리하겠습니다.
- 화면 전환 확인 부족: 클릭 후 다음 요소를 기다리지만, 의도한 화면으로 이동했는지는 따로 확인하지 않습니다. 전환이 끝나지 않았거나 다른 화면으로 이동했을 때도 다음 요소를 찾으려 할 수 있습니다.
- 조회 실패와 버튼 상태 처리 부족: device.wait(Until.findObject(...), timeout)이 제한 시간 안에 요소를 찾지 못하면 null을 반환할 수 있습니다. 이를 확인하지 않고 바로 click()하면 null 관련 예외로 끝나 어느 대상을 기다리다 실패했는지 알기 어렵습니다. 대상과 최대 대기 시간을 포함한 실패 메시지가 필요합니다. 비활성 버튼, 팝업에 가려진 요소나 교체된 뷰도 확인해야 합니다.
- 테스트 데이터 의존: 가게가 영업을 종료했거나 메뉴가 품절이면 테스트가 실패합니다. 사용할 수 있는 전용 매장, 메뉴와 계정을 준비하고 로그인, 배송지, 장바구니 상태를 고정해야 합니다.

### 2. 유지보수성

- 화면 문구에 직접 의존: By.textContains("주문하기")는 버튼 문구가 ‘주문’으로 바뀌면 실패합니다. 개발팀과 합의한 resource-id를 우선 사용하고, contentDescription을 쓴다면 문구나 언어 변경의 영향도 확인해야 합니다.
- 부분 문구의 중복: ‘치킨’이 가게 이름, 메뉴 설명과 추천 영역에 함께 있으면 의도하지 않은 요소를 선택할 수 있습니다. 식별자와 정확한 테스트 이름을 함께 사용해야 합니다.
- 한 함수에 몰린 화면 로직: 매장 선택, 메뉴 선택, 주문, 결제와 검증이 섞여 있어 UI 변경 시 여러 테스트를 수정해야 합니다. ShopPage, MenuPage, PaymentPage처럼 화면별 Page Object로 분리하는 것이 적합합니다.
- 분산된 Timeout: 여러 곳의 값을 따로 바꾸면 변경이 누락되기 쉽습니다. 공통 설정으로 관리해야 합니다.
- 재사용할 함수 부족: 버튼 대기와 클릭, 화면 전환 확인을 다른 E2E에서도 다시 작성해야 합니다. 공통 동작을 함수로 분리해야 합니다.

### 3. 신뢰성

Assert.assertNotNull(statusText)는 화면에 ‘접수 대기’가 있으면 통과합니다. 다음 경우를 구분하지 못합니다.

- 이전 주문이나 다른 주문의 상태가 표시된 경우
- 잘못된 메뉴, 수량이나 금액으로 주문한 경우
- 결제는 실패했지만 다른 영역에 같은 문구가 있는 경우
- 화면에는 결과가 표시됐지만 서버에는 주문이 저장되지 않은 경우

주문번호, 주문한 메뉴, 결제 결과와 현재 상태가 이번 주문에 해당하는지 확인해야 합니다. API나 서버 로그를 사용할 수 있다면 주문 ID로 서버 결과와 화면을 대조해야 합니다. 정상 주문이 빠르게 다음 상태로 넘어가 ‘접수 대기’를 놓칠 수 있으므로, 해당 상태를 유지할 테스트 조건이나 허용 상태 전이도 정해야 합니다.
결제 후 응답만 유실된 상황에서 전체 흐름을 재실행하면 중복 주문이 생길 수 있습니다. 실패 당시 화면, 로그와 주문 ID를 남기고 서버 처리 여부부터 확인해야 합니다.

## Q2. 어떤 부분을 리팩토링했는가?

[OrderFlowTest.kt](OrderFlowTest.kt)에 화면별 Page Object, 공통 대기와 실패 자료 저장 코드를 한 파일로 작성했습니다.

```kotlin
class OrderFlowRefactoredTest(
    private val device: UiDevice,
    private val packageName: String,
    private val artifactDir: File
) {
    fun testOrderFlow() {
        runWithFailureArtifacts {
            ShopPage().selectShop("치킨")
                .selectMenu("후라이드")
                .proceedToPayment()
                .pay()
                .verifyOrder(expectedStatus = "접수 대기", expectedMenu = "후라이드")
        }
    }

    // 최대 timeout까지 찾되 발견 즉시 반환. 못 찾으면 대상과 제한 시간을 명시해 실패.
    private inner class UiWait {
        private val defaultTimeout = 10_000L
        fun visible(selector: BySelector, description: String, timeout: Long = defaultTimeout): UiObject2 {
            return device.wait(Until.findObject(selector), timeout)
                ?: throw AssertionError("$description 을(를) ${timeout}ms 안에 찾지 못했습니다.")
        }
        fun click(selector: BySelector, description: String) {
            // 표시된 버튼이 활성화되고 클릭 가능한 상태가 될 때까지 기다림.
            val ready = By.copy(selector).enabled(true).clickable(true)
            val element = visible(ready, "$description 클릭 가능 상태")
            element.click() // 결제 중복을 막기 위해 클릭 자체는 재시도하지 않음.
        }
    }

    // 화면별 조작을 분리하고, ID와 정확한 이름으로 대상을 선택.
    private inner class ShopPage {
        private val wait = UiWait()
        fun selectShop(shopName: String): MenuPage {
            wait.click(By.res(packageName, "shop_name").text(shopName), "매장 '$shopName'")
            return MenuPage().waitUntilDisplayed()
        }
    }

    private inner class MenuPage {
        private val wait = UiWait()
        fun waitUntilDisplayed(): MenuPage {
            wait.visible(By.res(packageName, "menu_list"), "메뉴 목록")
            return this
        }
        fun selectMenu(menuName: String): OrderPage {
            wait.click(By.res(packageName, "menu_name").text(menuName), "메뉴 '$menuName'")
            return OrderPage().waitUntilDisplayed()
        }
    }

    private inner class OrderPage {
        private val wait = UiWait()
        fun waitUntilDisplayed(): OrderPage {
            wait.visible(By.res(packageName, "order_button"), "주문하기 버튼")
            return this
        }
        fun proceedToPayment(): PaymentPage {
            wait.click(By.res(packageName, "order_button"), "주문하기 버튼")
            return PaymentPage().waitUntilDisplayed()
        }
    }

    private inner class PaymentPage {
        private val wait = UiWait()
        fun waitUntilDisplayed(): PaymentPage {
            wait.visible(By.res(packageName, "payment_button"), "결제 버튼")
            return this
        }
        fun pay(): OrderStatusPage {
            wait.click(By.res(packageName, "payment_button"), "결제 버튼")
            return OrderStatusPage().waitUntilDisplayed()
        }
    }

    // 상태 문구만 확인하지 않고 주문 메뉴와 주문번호도 검증.
    private inner class OrderStatusPage {
        private val wait = UiWait()
        fun waitUntilDisplayed(): OrderStatusPage {
            wait.visible(By.res(packageName, "order_status"), "주문 상태")
            return this
        }
        fun verifyOrder(expectedStatus: String, expectedMenu: String) {
            // 요소만 먼저 표시되는 경우를 고려해 기대 문구와 주문번호가 준비될 때까지 대기.
            val status = wait.visible(By.res(packageName, "order_status").text(expectedStatus), "주문 상태: $expectedStatus").text
            val menu = wait.visible(By.res(packageName, "ordered_menu").text(expectedMenu), "주문 메뉴: $expectedMenu").text
            val orderNumber = wait.visible(By.res(packageName, "order_number").text(java.util.regex.Pattern.compile(".*\\S.*", java.util.regex.Pattern.DOTALL)), "값이 있는 주문 번호").text
            assertEquals("주문 상태가 예상과 다릅니다.", expectedStatus, status)
            assertEquals("주문 메뉴가 예상과 다릅니다.", expectedMenu, menu)
            assertTrue("주문 번호가 생성되지 않았습니다.", !orderNumber.isNullOrBlank())
        }
    }

    // 실패 당시 화면과 UI 구조를 저장해 CI 원인 분석에 사용.
    private fun runWithFailureArtifacts(block: () -> Unit) {
        try {
            block()
        } catch (e: Throwable) {
            saveFailureArtifacts()
            throw e
        }
    }
    private fun saveFailureArtifacts() {
        val directory = artifactDir
        runCatching { directory.mkdirs() }
        val timestamp = System.currentTimeMillis()
        runCatching { device.takeScreenshot(File(directory, "order_flow_$timestamp.png")) }
        runCatching { device.dumpWindowHierarchy(File(directory, "order_flow_$timestamp.xml")) }
    }
}
```

**설계 의도**

화면 탐색과 조작 방법은 Page Object에 두고 테스트에서는 사용자 흐름만 표현했습니다. 버튼 ID나 화면 구조가 변경되어도 해당 Page를 수정하면 다른 테스트에 미치는 영향을 줄일 수 있습니다. 각 Page는 다음 화면의 요소를 확인한 뒤 반환합니다.
공통 UiWait는 device.wait(Until.findObject(...), timeout)으로 조건을 만족하는 요소를 찾으면 즉시 반환합니다. 클릭할 때는 enabled(true)와 clickable(true)를 함께 지정해 버튼이 활성화될 때까지 기다립니다. 제한 시간 안에 찾지 못하면 ?: throw AssertionError(...)로 대상과 최대 대기 시간을 명시합니다. 결과 화면에서는 기대 상태와 메뉴, 비어 있지 않은 주문번호까지 기다립니다. 클릭 자체는 재시도하지 않습니다. 부분 문구 검색은 resource-id와 정확한 이름의 조합으로 바꿨고, 실패하면 화면 캡처와 UI hierarchy 저장을 시도합니다.

**적용 전제와 검증 범위**

- CI에서는 실행 전 로그인, 배송지, 장바구니, 시작 화면과 테스트 데이터를 초기화합니다.
- 이번 코드는 UI의 주문번호, 메뉴와 상태를 검증합니다. 신규 주문 생성, 금액과 결제 성공 여부는 실제 연동 환경에서 주문 ID로 서버 결과와 대조합니다.
- 실제 앱 정보가 없어 resource-id는 예시입니다. 코드의 ‘치킨’과 ‘후라이드’는 정확히 일치하는 테스트 매장명과 메뉴명입니다. 실제 적용 시 개발팀과 합의한 식별자와 테스트 데이터로 교체합니다.
- 버튼의 활성화와 클릭 가능 상태까지 기다리지만 팝업에 가리지 않았는지, 터치가 처리됐는지까지 보장하지는 않습니다. 다음 화면을 확인하며, 중복 요소 검사와 stale 복구는 별도 보완 사항입니다.
- 실패 시 PNG와 XML 저장을 시도합니다. CI에서는 앱이 제거되기 전에 파일을 가져오고, logcat, 빌드, 기기와 테스트 데이터 정보를 함께 보관해야 합니다.

## Q3. CI에서 간헐적으로 실패하면 어떤 순서로 원인을 추적할 것인가?

최초 실패 정보를 보존한 뒤 제품, 테스트 코드, 데이터와 환경 중 어디서 문제가 발생했는지 구분하겠습니다.

1. 실패 정보 확보: 실패 시점의 화면 캡처, UI hierarchy, 로그, 빌드, 기기, 테스트 데이터와 실패 단계를 저장합니다.
2. 실패 지점 확인: 매장 선택, 메뉴 선택, 주문, 결제, 주문 상태 확인 중 처음 문제가 발생한 단계를 찾습니다. 결제 후 실패했다면 서버 주문과 결제 내역부터 확인하고, 처리 여부가 불명확하면 재결제하지 않습니다.
3. 원인 분리: 기존 주문을 확인하고 데이터를 정리한 뒤 동일 조건으로 진단 목적의 재실행을 한 번 수행합니다. 성공한 실행과 비교해 UI 로딩 지연, 선택자, 네트워크, 데이터와 서버 처리 문제를 구분합니다.
4. 재현 조건 축소: 특정 기기, 빌드, 네트워크나 데이터에서만 발생하는지 조건을 하나씩 바꿉니다. 단독 실행만 통과한다면 실행 순서와 병렬 실행의 데이터 공유도 확인합니다.
5. 수정 후 회귀: 원인을 수정한 뒤 최초 실패 조건과 관련 주문 흐름을 다시 실행해 재발 여부를 확인합니다.

재실행에 성공해도 최초 실패 기록은 삭제하지 않습니다. 테스트 코드나 환경 문제로 확인된 항목은 담당자, 수정 기한과 대체 검증을 정해 격리하겠습니다. 실제 사용자에게도 발생할 수 있는 주문 상태 불일치나 허용 시간을 넘는 지연은 제품 결함으로 조사하겠습니다.

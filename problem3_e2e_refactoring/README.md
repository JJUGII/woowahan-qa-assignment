# 문제 3. E2E 자동화 코드 리뷰 및 리팩토링

## Q1. 기존 코드에는 어떤 문제가 있는가?

기존 코드의 문제를 안정성, 유지보수성, 신뢰성으로 나누어 정리했습니다. 화면 문구만으로 대상을 찾으면 다른 요소를 선택할 수 있습니다. 고정 대기와 단계별 Timeout 설정 때문에 정상 흐름도 실패할 수 있고, ‘접수 대기’ 문구만으로는 이번 주문이 정상 처리되었는지 확인하기 어렵습니다.

### 1. 안정성

- 고정 대기: Thread.sleep(5000)은 화면이 준비되어도 5초를 기다립니다. 반대로 화면이 늦게 준비되어 이후 device.wait()의 제한 시간까지 넘으면 실패합니다. 필요한 화면이나 상태가 나타나면 바로 진행하도록 변경했습니다.
- Timeout 관리: device.wait()의 3000ms, 5000ms는 최대 대기 시간이며, 요소를 찾으면 바로 반환합니다. 이 값이 단계마다 직접 지정되어 있어 일괄 수정하기 어렵습니다. 공통 설정으로 분리했고, 실제 적용 시 실행 환경의 지연과 서비스 허용 시간에 맞춰 조정하겠습니다.
- 화면 전환 확인 부족: 클릭 후 다음 요소를 기다리지만, 의도한 화면에 도착했는지는 따로 확인하지 않습니다. 다른 화면의 같은 문구를 찾을 수도 있어 다음 화면을 구분하는 요소를 확인해야 합니다.
- 조회 실패와 버튼 상태 처리 부족: 제한 시간 안에 요소를 찾지 못하면 device.wait()가 null을 반환할 수 있습니다. 바로 click()하면 어떤 요소를 기다렸는지 알기 어려우므로 대상과 제한 시간을 실패 메시지에 남겨야 합니다. 버튼이 비활성이거나 팝업에 가려진 경우, 화면 갱신으로 기존 요소가 교체된 경우도 고려해야 합니다.
- 테스트 데이터 의존: 가게가 영업을 종료했거나 메뉴가 품절이면 실패합니다. 전용 매장, 메뉴와 계정을 준비하고 로그인, 배송지와 장바구니를 같은 조건으로 초기화해야 합니다.

### 2. 유지보수성

- 화면 문구에 직접 의존: By.textContains("주문하기")는 버튼 문구가 ‘주문’으로 바뀌면 실패합니다. 개발팀과 합의한 resource-id를 우선 사용하고, contentDescription을 쓴다면 문구나 언어 변경의 영향도 확인해야 합니다.
- 부분 문구의 중복: ‘치킨’이 가게 이름, 메뉴 설명과 추천 영역에 함께 있으면 의도하지 않은 요소를 선택할 수 있습니다. 식별자와 정확한 테스트 이름을 함께 사용해야 합니다.
- 한 함수에 몰린 화면 로직: 매장 선택부터 결제와 검증까지 한 함수에 있어 같은 동작을 재사용하기 어렵습니다. 화면이 바뀌면 해당 동작을 사용하는 테스트마다 수정해야 하므로 화면별 Page Object로 분리했습니다.
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

화면별 조회와 클릭 코드는 Page Object로 분리했습니다. 테스트에는 매장 선택부터 주문 확인까지의 순서를 작성했습니다. 버튼 ID나 화면 구조가 바뀌면 해당 Page에서 수정하도록 구성했습니다. 다음 화면의 요소를 확인한 뒤 다음 단계로 진행합니다.

공통 UiWait는 device.wait(Until.findObject(...), timeout)을 사용했습니다. 클릭 대상은 enabled(true)와 clickable(true)를 함께 지정해 활성화될 때까지 기다립니다. 제한 시간 안에 찾지 못하면 대상과 최대 대기 시간을 포함한 AssertionError를 발생시킵니다. 결과 화면에서는 예상 상태와 메뉴가 표시되고 주문번호가 채워질 때까지 기다립니다.

대상은 resource-id와 정확한 이름으로 찾습니다. 중복 결제를 막기 위해 클릭은 재시도하지 않습니다. 실패하면 화면 캡처와 UI hierarchy 저장을 시도합니다.

**적용 전제와 검증 범위**

- 실제 CI 적용 시 테스트 시작 전에 로그인, 배송지, 장바구니, 시작 화면과 테스트 데이터를 초기화해야 합니다.
- 이번 코드는 UI의 주문번호, 메뉴와 상태를 검증합니다. 신규 주문 생성, 금액과 결제 성공 여부는 실제 연동 환경에서 주문 ID로 서버 결과와 대조해야 합니다.
- 실제 앱 정보가 없어 resource-id는 예시입니다. 코드의 ‘치킨’과 ‘후라이드’는 정확히 일치하는 테스트 매장명과 메뉴명입니다. 실제 적용 시 개발팀과 합의한 식별자와 테스트 데이터로 교체합니다.
- 버튼의 활성화와 클릭 가능 상태까지 기다리지만 팝업에 가리지 않았는지, 터치가 처리됐는지까지 보장하지는 않습니다. 다음 화면을 확인하며, 중복 요소 검사와 stale 복구는 별도 보완 사항입니다.
- 실패 시 PNG와 XML 저장을 시도합니다. CI에서는 앱이 제거되기 전에 파일을 가져오고, logcat, 빌드, 기기와 테스트 데이터 정보를 함께 보관해야 합니다.

## Q3. CI에서 간헐적으로 실패하면 어떤 순서로 원인을 추적할 것인가?

처음 실패한 화면과 로그부터 확보하겠습니다. 실패한 단계를 확인한 후 테스트 코드, 데이터, 실행 환경과 서버 처리 결과를 비교하겠습니다.

1. 실패 정보 확보: 실패 시점의 화면 캡처, UI hierarchy, 로그, 빌드, 기기, 테스트 데이터와 실패 단계를 저장합니다.
2. 실패 지점 확인: 매장 선택, 메뉴 선택, 주문, 결제, 주문 상태 확인 중 처음 문제가 발생한 단계를 찾습니다. 결제 후 실패했다면 서버 주문과 결제 내역부터 확인하고, 처리 여부가 불명확하면 재결제하지 않습니다.
3. 원인 분리: 기존 주문의 처리 여부를 확인하고 데이터를 정리한 뒤 같은 조건으로 한 번 재실행합니다. 성공한 실행과 비교해 UI 로딩, 선택자, 네트워크, 데이터와 서버 처리 중 차이가 있는 부분을 찾습니다.
4. 재현 조건 축소: 특정 기기, 빌드, 네트워크나 데이터에서만 발생하는지 조건을 하나씩 바꿉니다. 단독 실행만 통과한다면 실행 순서와 병렬 실행의 데이터 공유도 확인합니다.
5. 수정 후 회귀: 원인을 수정한 뒤 최초 실패 조건과 관련 주문 흐름을 다시 실행해 재발 여부를 확인합니다.

재실행에 성공해도 처음 실패한 기록은 유지하겠습니다. 테스트 코드나 환경 문제라면 담당자와 수정 기한을 정해 격리하고, 그동안 필요한 대체 검증을 진행하겠습니다. 주문 상태가 맞지 않거나 허용 시간을 넘는 지연이 실제 사용자에게도 발생한다면 제품 결함으로 확인하겠습니다.

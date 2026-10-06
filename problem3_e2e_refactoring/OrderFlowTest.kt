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

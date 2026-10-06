package generated.recorder

import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import org.junit.Assert
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class Recorded_settings_sampleTest {
    private lateinit var device: UiDevice

    @Before
    fun setUp() {
        device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        // Prepare the app and starting screen before running. No app launch or data reset.
    }

    @Test
    fun test_settings_sample() {
        // 설정 표시 확인
        val element1 = requireUnique(By.res("com.example.qa:id/settings_title"))
        Assert.assertNotNull(element1)

    }

    private fun requireUnique(
        selector: BySelector,
        timeoutMs: Long = 15000L,
        predicate: (UiObject2) -> Boolean = { true }
    ): UiObject2 {
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        do {
            device.wait(Until.findObject(selector), (deadline - SystemClock.uptimeMillis()).coerceAtLeast(1L))
            val matches = device.findObjects(selector)
            Assert.assertTrue("Selector matched multiple elements: $selector", matches.size <= 1)
            val element = matches.singleOrNull()
            if (element != null && !element.visibleBounds.isEmpty && predicate(element)) return element
            SystemClock.sleep(50L)
        } while (SystemClock.uptimeMillis() < deadline)
        throw AssertionError("Element missing or expected state not reached: $selector")
    }
}

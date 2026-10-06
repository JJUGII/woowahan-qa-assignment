"""AndroidX UIAutomator export. No Python/Airtest source translation or model code."""
import json
import math
import os
import re
from dataclasses import asdict

from recorder.ai_recommender import ConfirmedStep


def kotlin_string(value):
    """Quoted Kotlin string: escape interpolation as well as control characters."""
    return json.dumps(str(value), ensure_ascii=False).replace('$', '\\$')


_QUOTED = r"(?:'[^']*'|\"[^\"]*\")"
_LITERAL = rf'(?:{_QUOTED}|concat\({_QUOTED}(?:,\s*{_QUOTED})*\))'
_TERM = re.compile(rf'@(?P<key>class|text|content-desc|resource-id|package)=(?P<value>{_LITERAL})')


def xpath_attributes(value):
    """Accept only Recorder's equality predicates, never approximate arbitrary XPath."""
    if not value.startswith('//*[') or not value.endswith(']'):
        raise ValueError('Kotlin에서는 Recorder가 만든 속성 일치 XPath만 변환할 수 있습니다.')
    body, attrs = value[4:-1], {}
    while body:
        match = _TERM.match(body)
        if not match or match['key'] in attrs:
            raise ValueError('Kotlin으로 변환할 수 없는 XPath입니다. ID, 설명, 텍스트를 선택하세요.')
        literal = match['value']
        attrs[match['key']] = (''.join(x[1:-1] for x in re.findall(_QUOTED, literal[7:-1]))
                               if literal.startswith('concat(') else literal[1:-1])
        body = body[match.end():]
        if body:
            if not body.startswith(' and '):
                raise ValueError('지원하지 않는 XPath 연산입니다.')
            body = body[5:]
            if not body:
                raise ValueError('불완전한 XPath입니다.')
    if not attrs:
        raise ValueError('빈 XPath는 지원하지 않습니다.')
    return attrs


def by_attributes(attrs):
    methods = {'resource-id': 'res', 'content-desc': 'desc', 'class': 'clazz', 'text': 'text', 'package': 'pkg'}
    return 'By.' + '.'.join(f'{methods[k]}({kotlin_string(v)})' for k, v in attrs.items())


class KotlinCodeBuilder:
    extension = '.kt'
    supports_images = False

    def __init__(self, scenario_name, preparation=None, test_address=None, app_package=None):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', scenario_name):
            raise ValueError('생성 파일명은 영문/숫자/밑줄로 작성하고 숫자로 시작하지 마세요.')
        self.scenario_name = scenario_name
        self.class_name = 'Recorded_' + scenario_name + 'Test'
        self.filename = self.class_name + self.extension
        self.lines, self.confirmed_steps = [], []
        self.preparation, self.app_package = preparation, app_package
        self.count = 0

    def _selector(self, strategy, value):
        methods = {'ID': 'res', 'ACCESSIBILITY_ID': 'desc', 'CLASS_NAME': 'clazz',
                   'TEXT': 'text', 'TEXT_CONTAINS': 'textContains'}
        if strategy in methods:
            return f'By.{methods[strategy]}({kotlin_string(value)})'
        if strategy == 'XPATH':
            return by_attributes(xpath_attributes(value))
        raise ValueError('Kotlin에서 지원하지 않는 Selector입니다.')

    def validate_confirmed_step(self, step):
        if not isinstance(step, ConfirmedStep) or step.strategy not in {'ID', 'ACCESSIBILITY_ID', 'XPATH'}:
            raise ValueError('검증된 Step이 필요합니다.')
        self._selector(step.strategy, step.value)
        if step.mode not in {'CLICK', 'ASSERT'}:
            raise ValueError('지원되지 않는 동작입니다.')
        if step.mode == 'ASSERT':
            if step.assertion == 'visible' and step.expected_value is True:
                return
            if step.assertion == 'text_equals' and isinstance(step.expected_value, str):
                return
            if step.assertion == 'enabled' and type(step.expected_value) is bool:
                return
            raise ValueError('요구사항에 따른 검증 기대값이 필요합니다.')

    def validate_click_action(self, el):
        self._element_selector(el)

    def _element_selector(self, el):
        if el:
            for key, strategy in [('resource-id', 'ID'), ('content-desc', 'ACCESSIBILITY_ID')]:
                if el.get(key):
                    return strategy, self._selector(strategy, el[key])
            if el.get('text'):
                attrs = {k: el[k] for k in ('class', 'text', 'package') if el.get(k)}
                return 'TEXT', by_attributes(attrs)
        raise ValueError('Kotlin은 이미지 기반 동작을 지원하지 않습니다. 속성이 있는 요소 또는 Python을 선택하세요.')

    def _action(self, selector, *, click=False, predicate=None, description=''):
        self.count += 1
        if description:
            comment = ''.join(c if c.isprintable() else ' ' for c in description)
            self.lines.append('        // ' + comment)
        suffix = (' { it.isEnabled }' if click else '') if predicate is None else ' { ' + predicate + ' }'
        self.lines.append(f'        val element{self.count} = requireUnique({selector}){suffix}')
        self.lines.append(f'        element{self.count}.click()' if click else f'        Assert.assertNotNull(element{self.count})')
        self.lines.append('')

    def add_click_action(self, el=None, x=None, y=None, img_name=None):
        strategy, selector = self._element_selector(el)
        self._action(selector, click=True)
        return strategy

    def add_assertion_action(self, el=None, img_name=None):
        _, selector = self._element_selector(el)
        self._action(selector)

    def add_custom_assertion(self, loc_type, loc_val):
        self._action(self._selector(loc_type, loc_val))

    def add_confirmed_step(self, step):
        self.validate_confirmed_step(step)
        predicate = None
        if step.mode == 'ASSERT' and step.assertion == 'text_equals':
            predicate = 'it.text == ' + kotlin_string(step.expected_value)
        elif step.mode == 'ASSERT' and step.assertion == 'enabled':
            predicate = 'it.isEnabled == ' + str(step.expected_value).lower()
        self._action(self._selector(step.strategy, step.value), click=step.mode == 'CLICK',
                     predicate=predicate, description=step.description)
        self.confirmed_steps.append(asdict(step))

    def add_input_action(self, text):
        self.count += 1
        self.lines.extend([f'        val input{self.count} = requireUnique(By.focused(true)) {{ it.isEnabled }}',
                           '        // Append to the focused field, matching Recorder input behavior.',
                           f'        input{self.count}.text = (input{self.count}.text ?: "") + {kotlin_string(text)}', ''])

    def add_sleep_action(self, seconds):
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0 or seconds > 2147483:
            raise ValueError('대기 시간은 0~2147483초의 유한한 숫자여야 합니다.')
        self.lines.extend([f'        Thread.sleep({round(seconds * 1000)}L)', ''])

    def add_back_action(self):
        self.lines.extend(['        Assert.assertTrue("Back key failed", device.pressBack())',
                           '        Thread.sleep(1500L)', ''])

    def add_swipe_action(self, sx, sy, ex, ey, duration=400):
        if any(type(v) is not int or v < 0 or v > 2147483647 for v in (sx, sy, ex, ey, duration)):
            raise ValueError('스와이프 좌표와 시간은 음수가 아닌 정수여야 합니다.')
        steps = max(1, round(duration / 5))
        self.lines.extend(['        // UiDevice uses steps (~5ms each); coordinates assume the recorded screen size.',
                           f'        Assert.assertTrue("Swipe failed", device.swipe({sx}, {sy}, {ex}, {ey}, {steps}))',
                           '        Thread.sleep(1000L)', ''])

    def source(self):
        before = ['        device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())',
                  '        // Prepare the app and starting screen before running. No app launch or data reset.']
        if self.preparation:
            before.append('        // Complete permissions, required terms and test address beforehand; Python preparation is not embedded.')
        if self.app_package:
            before.append('        Assert.assertTrue("Open the target app before running", device.wait(')
            before.append(f'            Until.hasObject(By.pkg({kotlin_string(self.app_package)})), 5000L))')
        return '\n'.join([
            'package generated.recorder', '',
            'import android.os.SystemClock',
            'import androidx.test.ext.junit.runners.AndroidJUnit4',
            'import androidx.test.platform.app.InstrumentationRegistry',
            'import androidx.test.uiautomator.By', 'import androidx.test.uiautomator.BySelector',
            'import androidx.test.uiautomator.UiDevice', 'import androidx.test.uiautomator.UiObject2',
            'import androidx.test.uiautomator.Until',
            'import org.junit.Assert', 'import org.junit.Before', 'import org.junit.Test',
            'import org.junit.runner.RunWith', '',
            '@RunWith(AndroidJUnit4::class)', f'class {self.class_name} {{',
            '    private lateinit var device: UiDevice', '',
            '    @Before', '    fun setUp() {', *before, '    }', '',
            '    @Test', f'    fun test_{self.scenario_name}() {{', *self.lines, '    }', '',
            '    private fun requireUnique(',
            '        selector: BySelector,', '        timeoutMs: Long = 15000L,',
            '        predicate: (UiObject2) -> Boolean = { true }',
            '    ): UiObject2 {',
            '        val deadline = SystemClock.uptimeMillis() + timeoutMs',
            '        do {',
            '            device.wait(Until.findObject(selector), (deadline - SystemClock.uptimeMillis()).coerceAtLeast(1L))',
            '            val matches = device.findObjects(selector)',
            '            Assert.assertTrue("Selector matched multiple elements: $selector", matches.size <= 1)',
            '            val element = matches.singleOrNull()',
            '            if (element != null && !element.visibleBounds.isEmpty && predicate(element)) return element',
            '            SystemClock.sleep(50L)',
            '        } while (SystemClock.uptimeMillis() < deadline)',
            '        throw AssertionError("Element missing or expected state not reached: $selector")',
            '    }', '}', '',
        ])

    def generate_script(self, save_path):
        if os.path.splitext(save_path)[1].lower() != '.kt':
            raise ValueError('Kotlin 스크립트 확장자는 .kt여야 합니다.')
        source = self.source()
        # Compile in Android Studio; Python ast.parse cannot validate Kotlin.
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(source)
        metadata_path = os.path.splitext(save_path)[0] + '.steps.json'
        if self.confirmed_steps or os.path.exists(metadata_path):
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump({'schema_version': 1, 'language': 'kotlin',
                           'scope': 'confirmed recommendation steps only', 'steps': self.confirmed_steps},
                          f, ensure_ascii=False, indent=2)

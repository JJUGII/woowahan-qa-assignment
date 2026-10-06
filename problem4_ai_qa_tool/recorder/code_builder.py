import os
import time
import ast
import json
import re
from dataclasses import asdict
from recorder.ai_recommender import xpath_literal, ConfirmedStep

class CodeBuilder:
    def __init__(self, scenario_name, preparation=None, test_address=None):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', scenario_name):
            raise ValueError('생성 파일명은 영문/숫자/밑줄로 작성하고 숫자로 시작하지 마세요.')
        self.scenario_name = scenario_name
        self.lines = []
        self.confirmed_steps = []
        self.preparation = preparation
        self.test_address = test_address
        self._set_header()

    def _set_header(self):
        """하이브리드 스크립트 상단 기본 라이브러리 세팅"""
        self.lines.extend([
            "import os, time",
            "from appium.webdriver.common.appiumby import AppiumBy",
            "from selenium.webdriver.support.ui import WebDriverWait",
            "from selenium.webdriver.support import expected_conditions as EC",
            "from airtest.core.api import *",
            "import core.control_airtest as control_airtest",
            "",
            f"def test_{self.scenario_name}(info):",
            "    driver = info['appium_driver']",
            "    udid = info['device_udid']",
            "    ",
            "    # [초기화] Airtest 이미지 인식 세션 준비",
            "    dev = control_airtest.init_airtest(udid)",
            f"    print('>> [START] 시나리오 실행: {self.scenario_name}')",
            ""
        ])
        if self.preparation:
            self.lines.extend([
                '    # [사전 작업] 권한, 필수 약관, 설정된 테스트 주소 처리 후 기존 앱 상태 유지',
                '    from recorder.onboarding import prepare_onboarding',
                f'    preparation_info = dict(info, onboarding_address={self.test_address!r})',
                '    prepare_onboarding(preparation_info)',
                ''
            ])

    def _get_locator_string(self, el: dict):
        if not el: return None, None

        # 1순위: ID
        res_id = el.get('resource-id', '').strip()
        if res_id: return "ID", f"AppiumBy.ID, {res_id!r}"

        # 2순위: Accessibility ID (content-desc)
        content_desc = el.get('content-desc', '').strip()
        if content_desc: return "ACCESSIBILITY_ID", f"AppiumBy.ACCESSIBILITY_ID, {content_desc!r}"

        # 3순위: XPath (Class, Package, Index, Text 조합)
        cls_val = el.get('class', '').strip()
        if cls_val:
            xpath_parts = [f"@{k}={xpath_literal(el[k])}" for k in ['package', 'index'] if el.get(k)]
            text_val = el.get('text', '').strip()
            if text_val:
                xpath_parts.append(f"@text={xpath_literal(text_val)}")
            xpath_parts.insert(0, f"@class={xpath_literal(cls_val)}")
            full_xpath = f"//*[{' and '.join(xpath_parts)}]"
            return "XPATH", f"AppiumBy.XPATH, {full_xpath!r}"

        return None, None

    def add_click_action(self, el: dict = None, x=None, y=None, img_name: str = None):
        """[CLICK] 로직 수정 (경로 및 안정화 대기 추가)"""
        loc_type, locator = self._get_locator_string(el) if el else (None, None)

        if locator:
            self.lines.append(f"    # [XML] 엘리먼트 클릭 (Appium - {loc_type})")
            self.lines.append(f"    WebDriverWait(driver, 15).until(EC.element_to_be_clickable(({locator}))).click()")
            self.lines.append(f"    print(' -> [ACTION] XML 요소 클릭 완료 ({loc_type})')")
        elif img_name:
            self.lines.append(f"    # [IMAGE] 이미지 인식 클릭 (Airtest)")
            # [핵심 수정] 루트 폴더의 resources에 접근하기 위해 .. 을 두 번 사용
            self.lines.append(f"    img_path = os.path.join(os.path.dirname(__file__), '..', '..', 'resources', 'images', '{img_name}')")
            self.lines.append(f"    img_path = os.path.normpath(img_path)")
            self.lines.append(f"    time.sleep(1.0)  # 화면 안정화 대기")
            self.lines.append(f"    touch(Template(img_path, threshold=0.8))")
            self.lines.append(f"    print(' -> [ACTION] 이미지 인식 클릭 완료')")
        self.lines.append("")

        return loc_type

    def add_assertion_action(self, el: dict = None, img_name: str = None):
        """[ASSERT] 하이브리드 검증 코드 생성"""
        if img_name:
            self.lines.append(f"    # [ASSERT-IMAGE] 이미지가 화면에 존재하는지 확인 (Airtest)")
            self.lines.append(f"    img_path = os.path.join(os.path.dirname(__file__), '..', '..', 'resources', 'images', '{img_name}')")
            self.lines.append(f"    img_path = os.path.normpath(img_path)")
            self.lines.append(f"    assert_exists(Template(img_path, threshold=0.8), '화면에 이미지 {img_name}가 존재해야 함')")
            self.lines.append(f"    print(' -> [PASS] 이미지 검증 완료: {img_name}')")
        self.lines.append("")

    def add_custom_assertion(self, loc_type: str, loc_val: str):
        """[ASSERT] 사용자가 수동으로 선택한 속성으로 검증 코드를 생성합니다."""
        locator = ""
        if loc_type == "ID":
            locator = f"AppiumBy.ID, {loc_val!r}"
        elif loc_type == "ACCESSIBILITY_ID":
            locator = f"AppiumBy.ACCESSIBILITY_ID, {loc_val!r}"
        elif loc_type == "XPATH":
            locator = f"AppiumBy.XPATH, {loc_val!r}"
        elif loc_type == "CLASS_NAME":
            locator = f"AppiumBy.CLASS_NAME, {loc_val!r}"

        if locator:
            self.lines.append(f"    # [ASSERT] 수동 지정 검증")
            self.lines.append(f"    WebDriverWait(driver, 15).until(EC.visibility_of_element_located(({locator})))")
            self.lines.append(f"    print(' -> [PASS] 검증 완료: ', {locator})")
            self.lines.append("")

    def add_input_action(self, text: str):
        self.lines.append(f"    # [INPUT] 텍스트 입력")
        self.lines.append(f"    driver.switch_to.active_element.send_keys({text!r})")
        self.lines.append(f"    print({' -> [INPUT] 텍스트 입력 완료: ' + text!r})\n")

    def add_sleep_action(self, seconds: float):
        self.lines.append(f"    # [SLEEP] 대기")
        self.lines.append(f"    time.sleep({seconds})")
        self.lines.append(f"    print(' -> [SLEEP] {seconds}초 대기 완료')\n")

    def add_back_action(self):
        """[ACTION] 뒤로가기 후 안정화 대기 추가"""
        self.lines.append(f"    # [ACTION] 시스템 뒤로가기 및 안정화 대기")
        self.lines.append(f"    driver.back()")
        self.lines.append(f"    time.sleep(1.5)  # 화면 전환 대기 시간 확보")
        self.lines.append(f"    print(' -> [ACTION] 뒤로가기 완료')\n")

    def add_swipe_action(self, sx, sy, ex, ey, duration=400):
        """[ACTION] 스와이프 동작 기록 추가"""
        self.lines.append(f"    # [ACTION] 스와이프 수행")
        self.lines.append(f"    driver.swipe({sx}, {sy}, {ex}, {ey}, {duration})")
        self.lines.append(f"    time.sleep(1)  # 스와이프 후 안정화")
        self.lines.append(f"    print(' -> [ACTION] 스와이프 완료: ({sx},{sy}) -> ({ex},{ey})')\n")

    def add_confirmed_step(self, step: ConfirmedStep):
        """Only fixed templates, never source code supplied by a model."""
        if not isinstance(step, ConfirmedStep) or step.strategy not in {'ID', 'ACCESSIBILITY_ID', 'XPATH'}:
            raise ValueError('검증된 Step이 필요합니다.')
        if step.mode not in {'CLICK', 'ASSERT'} or (step.mode == 'ASSERT' and
                step.assertion not in {'visible', 'text_equals', 'enabled'}):
            raise ValueError('지원되지 않는 Step입니다.')
        if not self.confirmed_steps:
            self.lines.extend([
                "    # 재실행 시에도 Selector가 유일한지 확인",
                "    def _unique(by, value):",
                "        matches = driver.find_elements(by, value)",
                "        return matches[0] if len(matches) == 1 else False",
                "    def _checked(predicate):",
                "        element = _unique(_by, _value)",
                "        return element if element and predicate(element) else False",
                "",
            ])
        # Model/user descriptions are comments only; strip line/control characters.
        description = ' '.join(step.description.splitlines())
        description = ''.join(c if c.isprintable() else ' ' for c in description)
        self.lines.append(f"    # [STEP {len(self.confirmed_steps) + 1}] {description}")
        self.lines.append(f"    _by, _value = AppiumBy.{step.strategy}, {step.value!r}")
        if step.mode == 'CLICK':
            self.lines.append("    WebDriverWait(driver, 15).until(lambda d: _checked(lambda e: e.is_displayed() and e.is_enabled())).click()")
        elif step.assertion == 'visible':
            self.lines.append("    WebDriverWait(driver, 15).until(lambda d: _checked(lambda e: e.is_displayed()))")
        elif step.assertion == 'text_equals':
            self.lines.append(f"    _expected = {step.expected_value!r}  # 사용자가 요구사항에 따라 확인한 기대값")
            self.lines.append("    WebDriverWait(driver, 15).until(lambda d: _checked(lambda e: e.text == _expected))")
        elif step.assertion == 'enabled':
            self.lines.append(f"    _expected = {step.expected_value!r}")
            self.lines.append("    WebDriverWait(driver, 15).until(lambda d: _checked(lambda e: e.is_enabled() == _expected))")
        self.lines.extend([f"    print({('[STEP] ' + description)!r})", ""])
        self.confirmed_steps.append(asdict(step))

    def generate_script(self, save_path):
        source = "\n".join(self.lines)
        ast.parse(source)  # Reject invalid Python before replacing an existing script.
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(source)
        metadata_path = os.path.splitext(save_path)[0] + '.steps.json'
        if self.confirmed_steps or os.path.exists(metadata_path):
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump({'schema_version': 1, 'scope': 'confirmed recommendation steps only',
                           'steps': self.confirmed_steps}, f, ensure_ascii=False, indent=2)

import os, time
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from airtest.core.api import *
import core.control_airtest as control_airtest

def test_settings_sample(info):
    driver = info['appium_driver']
    udid = info['device_udid']
    
    # [초기화] Airtest 이미지 인식 세션 준비
    dev = control_airtest.init_airtest(udid)
    print('>> [START] 시나리오 실행: settings_sample')

    # 재실행 시에도 Selector가 유일한지 확인
    def _unique(by, value):
        matches = driver.find_elements(by, value)
        return matches[0] if len(matches) == 1 else False
    def _checked(predicate):
        element = _unique(_by, _value)
        return element if element and predicate(element) else False

    # [STEP 1] 설정 표시 확인
    _by, _value = AppiumBy.ID, 'com.example.qa:id/settings_title'
    WebDriverWait(driver, 15).until(lambda d: _checked(lambda e: e.is_displayed()))
    print('[STEP] 설정 표시 확인')

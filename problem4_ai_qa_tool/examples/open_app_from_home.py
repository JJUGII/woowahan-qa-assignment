"""홈 화면에 놓인 앱 아이콘을 눌러 실행하는 사전 스크립트.

다른 앱을 사용하면 TARGET_PACKAGE와 APP_ICON_TEXT를 수정하세요.
Recorder가 만든 Appium 세션을 재사용하고 앱 데이터를 초기화하지 않습니다.
"""
import logging
import time
import xml.etree.ElementTree as ET

from core.control_adb import adb_shell, get_foreground_activity
from recorder.ui_inspector import parse_bounds

TARGET_PACKAGE = 'com.sampleapp'
APP_ICON_TEXT = '배달의민족'
logger = logging.getLogger(__name__)


def open_app_from_home(device_info):
    pkg = device_info['app_package']
    udid = device_info['device_udid']
    if pkg != TARGET_PACKAGE:
        raise ValueError(f'이 예제는 {TARGET_PACKAGE}용입니다. 스크립트의 앱 설정을 수정하세요.')
    adb_shell(udid, 'input', 'keyevent', '3')  # HOME
    driver = device_info['appium_driver']
    deadline = time.monotonic() + 8
    matches = []
    while time.monotonic() < deadline:
        root = ET.fromstring(driver.page_source)
        matches = [node for node in root.iter()
                   if node.get('text') == APP_ICON_TEXT and node.get('clickable') == 'true'
                   and node.get('enabled') == 'true' and node.get('bounds')]
        if matches:
            break
        time.sleep(.4)
    if len(matches) != 1:
        raise RuntimeError(f'홈 화면의 "{APP_ICON_TEXT}" 아이콘 일치 수: {len(matches)}. '
                           '아이콘을 현재 홈 화면에 하나만 놓아주세요.')
    bounds = parse_bounds(matches[0].get('bounds'))
    if not bounds:
        raise RuntimeError('앱 아이콘의 좌표를 확인하지 못했습니다.')
    x1, y1, x2, y2 = bounds
    if x1 >= x2 or y1 >= y2:
        raise RuntimeError('앱 아이콘의 좌표 범위가 잘못됐습니다.')
    foreground, _ = get_foreground_activity(udid)
    if matches[0].get('package') != foreground:
        raise RuntimeError('아이콘을 확인한 뒤 화면이 바뀌었습니다. 다시 시작하세요.')
    logger.info('[아이콘 실행] %s / (%s, %s)', APP_ICON_TEXT, (x1 + x2) // 2, (y1 + y2) // 2)
    adb_shell(udid, 'input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))

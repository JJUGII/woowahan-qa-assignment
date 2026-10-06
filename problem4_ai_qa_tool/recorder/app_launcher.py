"""Open a unique home icon with a short ADB touch and bounded startup retries."""
import logging
import time
import xml.etree.ElementTree as ET

from core.control_adb import adb_shell, get_foreground_activity, get_app_permission_activity, wait_for_app_foreground
from recorder.ui_inspector import parse_bounds

logger = logging.getLogger(__name__)


def launch_from_home_icon(device_info, icon_text, attempts=3):
    if not icon_text or not isinstance(icon_text, str):
        raise ValueError('홈 화면에 표시된 앱 아이콘 이름을 입력하세요.')
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise ValueError('아이콘 실행 재시도 횟수는 1~3회입니다.')
    udid, pkg = device_info['device_udid'], device_info['app_package']
    foreground, _ = get_foreground_activity(udid)
    if foreground == pkg or (foreground in ('com.android.permissioncontroller', 'com.google.android.permissioncontroller')
                             and get_app_permission_activity(udid, pkg)):
        return wait_for_app_foreground(udid, pkg)
    driver = device_info['appium_driver']
    for attempt in range(1, attempts + 1):
        logger.info('[홈 아이콘 실행] %s / %s회 중 %s회 / 짧은 터치 80ms', icon_text, attempts, attempt)
        if get_foreground_activity(udid)[0] in ('com.android.permissioncontroller', 'com.google.android.permissioncontroller'):
            adb_shell(udid, 'input', 'keyevent', '4')  # Dismiss an orphaned prompt; do not select a permission.
        adb_shell(udid, 'input', 'keyevent', '3')
        deadline = time.monotonic() + 8
        nodes = []
        while time.monotonic() < deadline:
            root = ET.fromstring(driver.page_source)
            nodes = [node for node in root.iter() if node.get('text') == icon_text
                     and node.get('clickable') == 'true' and node.get('enabled') == 'true'
                     and node.get('displayed') != 'false' and node.get('bounds')]
            if nodes:
                break
            time.sleep(.4)
        if len(nodes) != 1:
            raise RuntimeError(f'홈 아이콘 "{icon_text}" 일치 수: {len(nodes)}. 현재 홈 화면에 아이콘을 하나만 놓아주세요.')
        x1, y1, x2, y2 = parse_bounds(nodes[0].get('bounds'))
        if x1 < 0 or y1 < 0 or x1 >= x2 or y1 >= y2:
            raise RuntimeError('홈 아이콘의 좌표 범위가 잘못됐습니다.')
        if get_foreground_activity(udid)[0] != nodes[0].get('package'):
            raise RuntimeError('아이콘을 확인한 후 화면이 변경됐습니다. 다시 시작하세요.')
        x, y = str((x1 + x2) // 2), str((y1 + y2) // 2)
        adb_shell(udid, 'input', 'touchscreen', 'swipe', x, y, x, y, '80')
        try:
            return wait_for_app_foreground(udid, pkg)
        except RuntimeError as exc:
            logger.warning('[홈 아이콘 실행] %s회 실패: %s', attempt, exc)
            if attempt == attempts:
                raise RuntimeError(f'{attempts}회 아이콘 실행 후에도 {pkg}이 유지되지 않습니다. '
                                   '앱을 직접 열고 현재 열린 앱에 연결을 선택하세요.') from exc
            adb_shell(udid, 'am', 'force-stop', pkg)
            time.sleep(2)

"""Deterministic preparation before recording/replay; never part of recorded Steps.

Runtime permission dialogs are supported for any verified target app. Terms and
guest entry are app-specific rules, based on observed com.sampleapp screens.
"""
from dataclasses import dataclass
import logging
import time
import xml.etree.ElementTree as ET

from core.control_adb import adb_shell, get_foreground_activity, get_app_permission_activity
from recorder.ui_inspector import parse_bounds
from recorder.ai_recommender import xpath_literal

logger = logging.getLogger(__name__)
CONTROLLERS = ('com.android.permissioncontroller', 'com.google.android.permissioncontroller')
REQUIRED_TERM = '위치 기반 서비스 약관 동의 (필수)'
OPTIONAL_TERM = '마케팅 정보 앱 푸시 알림 수신 동의 (선택)'


@dataclass(frozen=True)
class Action:
    key: str
    value: str
    package: str
    bounds: str
    checked: str
    description: str
    mode: str = 'touch'
    payload: str = ''


def _nodes(root, key, value, package):
    return [n for n in root.iter() if n.get(key) == value and n.get('package') == package
            and n.get('displayed') != 'false']


def _target(root, key, value, package):
    matches = _nodes(root, key, value, package)
    if not matches:
        return None
    if len(matches) != 1:
        raise RuntimeError(f'사전 작업 요소가 중복됩니다: {value} ({len(matches)}개)')
    parents = {child: parent for parent in root.iter() for child in parent}
    node = matches[0]
    while node.get('clickable') != 'true' and node in parents:
        node = parents[node]
    if node.get('package') != package or node.get('clickable') != 'true' or not node.get('bounds'):
        raise RuntimeError(f'사전 작업의 클릭 대상이 확인되지 않습니다: {value}')
    return node


def _action(root, key, value, package, description, checkbox=False):
    node = _target(root, key, value, package)
    if node is None or node.get('enabled') != 'true':
        return None
    if checkbox and node.get('checkable') != 'true':
        raise RuntimeError(f'약관 체크 상태를 확인할 수 없습니다: {value}')
    return Action(key, value, package, node.get('bounds'), node.get('checked', ''), description)


def _address_action(root, package, address):
    """Known address screens; exact configured result only, no first-result guess."""
    if not isinstance(address, dict) or any(not isinstance(address.get(k), str) or not address[k].strip()
                                           for k in ('query', 'result_text', 'detail')):
        raise ValueError('테스트 주소의 query/result_text/detail을 모두 입력하세요.')
    parents = {c:p for p in root.iter() for c in p}
    def action(node, description, mode='touch', payload=''):
        if node.get('enabled') != 'true':
            return None
        return Action('bounds', node.get('bounds'), package, node.get('bounds'),
                      node.get('checked', ''), description, mode, payload)
    if _nodes(root, 'text', '주소 상세', package):
        if not _nodes(root, 'text', address['result_text'], package):
            raise RuntimeError('상세 화면의 주소가 지정한 테스트 주소와 다릅니다.')
        edits = _nodes(root, 'class', 'android.widget.EditText', package)
        fields = [n for n in edits if n.get('text') == address['detail']
                  or any(c.get('text') == '건물명, 동/호수 등 상세주소' for c in n.iter())]
        if len(fields) != 1:
            raise RuntimeError('상세주소 입력칸을 유일하게 확인할 수 없습니다.')
        if fields[0].get('text') != address['detail']:
            return action(fields[0], '테스트 상세주소 입력', 'input', address['detail'])
        return _action(root, 'text', '주소 등록', package, '테스트 주소 등록')
    if not _nodes(root, 'text', '주소 검색', package):
        return None
    rows = set()
    for node in _nodes(root, 'text', address['result_text'], package):
        ancestor = node
        in_input = False
        while ancestor in parents:
            if ancestor.get('class') == 'android.widget.EditText':
                in_input = True
                break
            ancestor = parents[ancestor]
        if in_input:
            continue
        while node.get('clickable') != 'true' and node in parents:
            node = parents[node]
        if node.get('clickable') == 'true' and node.get('package') == package:
            rows.add(node)
    if rows:
        if len(rows) != 1:
            raise RuntimeError('테스트 주소 검색 결과가 여러 개입니다. 결과 문구를 확인하세요.')
        return action(rows.pop(), '지정한 테스트 주소 선택')
    edits = _nodes(root, 'class', 'android.widget.EditText', package)
    if edits:
        if len(edits) != 1:
            raise RuntimeError('주소 검색 입력칸이 중복됩니다.')
        return action(edits[0], '테스트 주소 검색', 'input_search', address['query'])
    nodes = _nodes(root, 'content-desc', '도로명, 건물명, 지번으로 검색', package)
    if len(nodes) == 1 and nodes[0].get('class') == 'android.widget.Button':
        return action(nodes[0], '주소 검색 화면 열기')
    raise RuntimeError('지원하지 않는 주소 검색 화면입니다. 단말에서 주소를 설정하세요.')


def next_action(root, foreground, package, address=None):
    """Return one allowlisted action, or None when no preparation action exists."""
    current, activity = foreground
    if current in CONTROLLERS:
        # Persistent while-in-use grant first; never choose always/one-time by default.
        for suffix in ('permission_allow_foreground_only_button', 'permission_allow_button'):
            action = _action(root, 'resource-id', f'{current}:id/{suffix}', current, '시스템 권한 허용')
            if action:
                return action
        raise RuntimeError('지원하지 않는 권한 화면입니다. 단말에서 권한을 설정한 뒤 다시 시작하세요.')
    if current != package:
        raise RuntimeError(f'사전 작업 중 대상 앱을 벗어났습니다: {current or "확인 불가"}. '
                           '별도 시스템 설정 화면이라면 단말에서 설정한 뒤 다시 시작하세요.')
    if package != 'com.sampleapp':
        # Unknown app terms must be configured explicitly rather than guessed.
        if any('(필수)' in n.get('text', '') for n in root.iter() if n.get('package') == package):
            raise RuntimeError('이 앱의 필수 약관 처리 규칙이 없습니다. 먼저 단말에서 동의해주세요.')
        return None
    if activity.endswith('TutorialActivity') and _nodes(root, 'text', REQUIRED_TERM, package):
        required = _action(root, 'text', REQUIRED_TERM, package, '필수 위치 서비스 약관 동의', checkbox=True)
        if required is None:
            return None
        if required.checked != 'true':
            return required
        optional = _action(root, 'text', OPTIONAL_TERM, package, '선택 마케팅 동의 해제', checkbox=True)
        if optional and optional.checked == 'true':
            return optional
        return _action(root, 'text', '시작하기', package, '필수 약관 동의 완료')
    if activity.endswith('TutorialActivity') and _nodes(root, 'text', '마케팅정보 앱 푸시 알림 거부 안내', package):
        return _action(root, 'text', '확인', package, '선택 마케팅 수신 거부 안내 닫기')
    if activity.endswith('LoginActivity'):
        return _action(root, 'text', '둘러보기', package, '로그인 없이 둘러보기')
    if activity.endswith('AddressActivity') and address:
        return _address_action(root, package, address)
    return None


def prepare_onboarding(info, timeout=60):
    """Apply known initial setup once, preserving data and existing warm screen.

    Uses only a configured test address. Never logs in or navigates a ready app
    back to its home screen. Address entry without a profile can be recorded too.
    """
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 120:
        raise ValueError('사전 작업 대기 시간은 0초 초과 120초 이하입니다.')
    driver, udid, package = info['appium_driver'], info['device_udid'], info['app_package']
    address = info.get('onboarding_address')
    deadline = time.monotonic() + timeout
    completed, repetitions = [], {}
    idle_signature, idle_count = None, 0
    while time.monotonic() < deadline:
        foreground = get_foreground_activity(udid)
        if foreground[0] in CONTROLLERS and not get_app_permission_activity(udid, package):
            raise RuntimeError('선택한 앱이 요청한 권한창이 아니거나 앱 프로세스가 종료됐습니다.')
        root = ET.fromstring(driver.page_source)
        action = next_action(root, foreground, package, address)
        if action:
            idle_count = 0
            # Re-read and re-plan immediately before touching, including checkbox state.
            fresh = ET.fromstring(driver.page_source)
            if next_action(fresh, foreground, package, address) != action or get_foreground_activity(udid) != foreground:
                time.sleep(.4)
                continue
            if foreground[0] in CONTROLLERS and not get_app_permission_activity(udid, package):
                raise RuntimeError('권한 요청 대상이 변경됐습니다.')
            repetitions[action] = repetitions.get(action, 0) + 1
            if repetitions[action] > 3 or len(completed) >= 24:
                raise RuntimeError('사전 작업을 눌렀지만 화면이 진행되지 않습니다. 단말 화면을 확인하세요.')
            x1, y1, x2, y2 = parse_bounds(action.bounds)
            width, height = int(root.get('width', 0)), int(root.get('height', 0))
            if not (0 <= x1 < x2 and 0 <= y1 < y2) or (width and x2 > width) or (height and y2 > height):
                raise RuntimeError('사전 작업 요소의 좌표가 화면 범위를 벗어났습니다.')
            x, y = str((x1 + x2) // 2), str((y1 + y2) // 2)
            logger.info('[사전 작업] %s: %s', action.description, action.value)
            if action.mode in ('input', 'input_search'):
                xpath = (f"//*[@package={xpath_literal(package)} and @class='android.widget.EditText' "
                         f"and @bounds={xpath_literal(action.bounds)}]")
                elements = driver.find_elements('xpath', xpath)
                if len(elements) != 1 or not elements[0].is_displayed() or not elements[0].is_enabled():
                    raise RuntimeError('주소 입력 대상을 유일하게 확인할 수 없습니다.')
                elements[0].clear()
                elements[0].send_keys(action.payload)
                if action.mode == 'input_search':
                    driver.execute_script('mobile: performEditorAction', {'action': 'search'})
            else:
                adb_shell(udid, 'input', 'touchscreen', 'swipe', x, y, x, y, '80')
            completed.append(action.description)
            time.sleep(1.2)
            continue
        # Router/tutorial/loading must not be mistaken for completed setup.
        waiting = foreground[1].endswith(('RouterActivity', 'TutorialActivity', 'LoginActivity')) or (
            address and foreground[1].endswith('AddressActivity'))
        if package == 'com.sampleapp' and foreground[1].endswith('RootContainerActivity'):
            waiting = waiting or not any(n.get('package') == package and (
                n.get('content-desc') == '하단탭바 홈탭' or n.get('content-desc', '').startswith('검색 버튼'))
                for n in root.iter())
        signature = (foreground, tuple((n.get('text'), n.get('content-desc'), n.get('enabled'))
                                       for n in root.iter() if n.get('package') == package))
        visible = any(n.get('package') == package and n.get('displayed') != 'false'
                      and (n.get('text') or n.get('content-desc')) for n in root.iter())
        idle_count = idle_count + 1 if signature == idle_signature else 1
        idle_signature = signature
        if not waiting and visible and idle_count >= 3:
            # Final foreground must still match the screen that was inspected.
            if get_foreground_activity(udid) != foreground:
                idle_count = 0
                continue
            info['onboarding_preparation'] = {'status': 'ready', 'actions': completed,
                                               'start_activity': foreground[1], 'preserve_data': True}
            logger.info('[사전 작업 완료] %s / 처리 %s회 / 앱 상태 유지', foreground[1], len(completed))
            if _nodes(root, 'content-desc', '도로명, 건물명, 지번으로 검색', package):
                logger.info('[시작 화면] 주소 검색. 홈에서 시작하려면 테스트 주소를 단말에서 설정하세요.')
            return info['onboarding_preparation']
        time.sleep(.5)
    raise RuntimeError('권한, 필수 약관 사전 작업 시간이 초과됐습니다. 지원되지 않는 화면을 단말에서 처리하세요.')

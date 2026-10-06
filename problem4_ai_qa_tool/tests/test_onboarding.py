import ast
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
import xml.etree.ElementTree as ET

from recorder import onboarding as prep
from recorder.code_builder import CodeBuilder

PKG = 'com.sampleapp'
ADDRESS = {'query': '서울특별시 송파구 위례성대로 2', 'result_text': '서울 송파구 위례성대로 2', 'detail': '1층'}

def node(text='', body='', **attrs):
    values = {'package': PKG, 'text': text, 'enabled': 'true', 'displayed': 'true',
              'clickable': 'false', 'bounds': '[10,20][200,100]', 'checked': 'false', **attrs}
    element = ET.Element('node', values)
    if body:
        element.append(ET.fromstring(body))
    return ET.tostring(element, encoding='unicode')

def screen(*nodes):
    return '<hierarchy width="1080" height="2400">' + ''.join(nodes) + '</hierarchy>'

def button(text, **attrs):
    return node(body=node(text), clickable='true', **attrs)

def terms(checked='false', optional='false'):
    return screen(button(prep.REQUIRED_TERM, checked=checked, checkable='true'),
                  button(prep.OPTIONAL_TERM, checked=optional, checkable='true'), button('시작하기'), button('전체동의'))

HOME = screen(node(**{'content-desc': '하단탭바 홈탭'}))
PERMISSION = screen(node(package=prep.CONTROLLERS[0], clickable='true',
                         **{'resource-id': prep.CONTROLLERS[0]+':id/permission_allow_button'}))

def plan(xml, activity='TutorialActivity', address=None, package=PKG):
    return prep.next_action(ET.fromstring(xml), (package, activity), package, address)


class OnboardingTests(unittest.TestCase):
    def test_terms_accept_only_required_then_continue_without_toggling_checked_term(self):
        self.assertEqual(plan(terms()).value, prep.REQUIRED_TERM)
        self.assertEqual(plan(terms('true')).value, '시작하기')
        self.assertEqual(plan(terms('true', 'true')).value, prep.OPTIONAL_TERM)

    def test_duplicate_required_labels_block_action(self):
        with self.assertRaisesRegex(RuntimeError, '중복'):
            plan(screen(button(prep.REQUIRED_TERM, checkable='true'), button(prep.REQUIRED_TERM, checkable='true')))

    def test_unreadable_checkbox_blocks_acceptance(self):
        with self.assertRaisesRegex(RuntimeError, '체크'):
            plan(screen(button(prep.REQUIRED_TERM)))

    def test_disabled_start_does_not_click(self):
        xml = screen(button(prep.REQUIRED_TERM, checkable='true', checked='true'), button('시작하기', enabled='false'))
        self.assertIsNone(plan(xml))

    def test_other_app_terms_are_not_guessed(self):
        xml = screen(node('서비스 약관 (필수)', package='com.other'))
        with self.assertRaisesRegex(RuntimeError, '규칙'):
            plan(xml, package='com.other')

    def test_permission_prefers_persistent_foreground_over_one_time(self):
        controller = prep.CONTROLLERS[0]
        xml = screen(*(node(package=controller, clickable='true', **{'resource-id': controller+':id/'+suffix})
                       for suffix in ('permission_allow_button', 'permission_allow_foreground_only_button',
                                      'permission_allow_one_time_button')))
        action = prep.next_action(ET.fromstring(xml), (controller, '.Grant'), PKG)
        self.assertTrue(action.value.endswith('permission_allow_foreground_only_button'))

    def test_special_system_settings_screen_is_not_blindly_changed(self):
        with self.assertRaisesRegex(RuntimeError, '시스템 설정'):
            prep.next_action(ET.fromstring(screen(button('허용', package='com.android.settings'))),
                             ('com.android.settings', '.Settings'), PKG)

    def test_normal_screen_with_agree_text_is_not_clicked(self):
        self.assertIsNone(plan(screen(button('동의'), button('주문하기')), 'RootContainerActivity'))

    def test_address_result_deduplicates_labels_in_one_row_not_distinct_rows(self):
        row = node(body=node(ADDRESS['result_text']), clickable='true')
        root = ET.fromstring(screen(row))
        root[0].append(ET.fromstring(node(ADDRESS['result_text'])))
        root.append(ET.fromstring(node('주소 검색')))
        self.assertEqual(prep.next_action(root, (PKG, 'AddressActivity'), PKG, ADDRESS).description, '지정한 테스트 주소 선택')
        with self.assertRaisesRegex(RuntimeError, '여러 개'):
            plan(screen(node('주소 검색'), row, row), 'AddressActivity', ADDRESS)

    def test_address_input_text_is_not_confused_with_search_result(self):
        query = dict(ADDRESS, query=ADDRESS['result_text'])
        xml = screen(node('주소 검색'), node(query['result_text'], clickable='true', **{'class': 'android.widget.EditText'}))
        self.assertEqual(plan(xml, 'AddressActivity', query).mode, 'input_search')

    def test_address_detail_requires_matching_address_and_exact_field(self):
        field = node(body=node('건물명, 동/호수 등 상세주소'), clickable='true', **{'class':'android.widget.EditText'})
        xml = screen(node('주소 상세'), node(ADDRESS['result_text']), field, button('주소 등록'))
        action = plan(xml, 'AddressActivity', ADDRESS)
        self.assertEqual((action.mode, action.payload), ('input', '1층'))
        with self.assertRaisesRegex(RuntimeError, '다릅니다'):
            plan(xml.replace(ADDRESS['result_text'], '다른 주소'), 'AddressActivity', ADDRESS)

    def run_flow(self, states, owner=True, timeout=60):
        state = {'index': 0}
        class Driver:
            @property
            def page_source(self):
                return states[state['index']][1]
        def advance(*args):
            state['index'] = min(state['index']+1, len(states)-1)
        info = {'appium_driver': Driver(), 'device_udid': 'serial', 'app_package': PKG}
        with ExitStack() as stack:
            stack.enter_context(patch.object(prep, 'get_foreground_activity', side_effect=lambda _: states[state['index']][0]))
            stack.enter_context(patch.object(prep, 'get_app_permission_activity', return_value='.Tutorial' if owner else None))
            shell = stack.enter_context(patch.object(prep, 'adb_shell', side_effect=advance))
            stack.enter_context(patch.object(prep.time, 'sleep'))
            result = prep.prepare_onboarding(info, timeout=timeout)
        return result, shell

    def test_full_setup_permissions_terms_guest_then_warm_screen(self):
        states = [((prep.CONTROLLERS[0], '.Grant'), PERMISSION), ((PKG, 'TutorialActivity'), terms()),
                  ((PKG, 'TutorialActivity'), terms('true')),
                  ((PKG, 'TutorialActivity'), screen(node('마케팅정보 앱 푸시 알림 거부 안내'), button('확인'))),
                  ((PKG, 'LoginActivity'), screen(button('둘러보기'))), ((PKG, 'RootContainerActivity'), HOME)]
        result, shell = self.run_flow(states)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(len(result['actions']), 5)
        self.assertEqual(shell.call_count, 5)
        self.assertTrue(all(c.args[1:4] == ('input', 'touchscreen', 'swipe') for c in shell.call_args_list))

    def test_warm_screen_is_idempotent_without_navigation_or_reset(self):
        result, shell = self.run_flow([((PKG, 'RootContainerActivity'), HOME)])
        self.assertEqual(result['actions'], [])
        shell.assert_not_called()

    def test_permission_other_owner_blocks_before_touch(self):
        with self.assertRaisesRegex(RuntimeError, '요청한 권한창'):
            self.run_flow([((prep.CONTROLLERS[0], '.Grant'), PERMISSION)], owner=False)

    def test_stuck_action_is_bounded(self):
        with self.assertRaisesRegex(RuntimeError, '진행되지'):
            self.run_flow([((PKG, 'TutorialActivity'), terms())])

    def test_root_activity_loading_screen_does_not_count_as_warm_ready(self):
        xml = screen(node(**{'content-desc':'배달의민족 앱을 시작합니다.'}))
        with patch.object(prep.time, 'monotonic', side_effect=[0, 0, 61]), \
             patch.object(prep.time, 'sleep'), \
             patch.object(prep, 'get_foreground_activity', return_value=(PKG, 'RootContainerActivity')), \
             patch.object(prep, 'adb_shell') as shell:
            with self.assertRaisesRegex(RuntimeError, '시간이 초과'):
                prep.prepare_onboarding({'appium_driver':SimpleNamespace(page_source=xml),
                                         'device_udid':'serial', 'app_package':PKG})
        shell.assert_not_called()

    def test_stale_checkbox_state_is_replanned_without_touch(self):
        driver = Mock()
        driver.configure_mock(**{'page_source': terms()})
        from unittest.mock import PropertyMock
        with patch.object(type(driver), 'page_source', new_callable=PropertyMock, create=True,
                          side_effect=[terms(), terms('true'), HOME, HOME, HOME]), \
             patch.object(prep, 'get_foreground_activity', side_effect=[(PKG, 'TutorialActivity'),
                        (PKG, 'RootContainerActivity'), (PKG, 'RootContainerActivity'),
                        (PKG, 'RootContainerActivity'), (PKG, 'RootContainerActivity')]), \
             patch.object(prep.time, 'sleep'), patch.object(prep, 'adb_shell') as shell:
            prep.prepare_onboarding({'appium_driver': driver, 'device_udid':'serial', 'app_package':PKG})
        shell.assert_not_called()

    def test_preparation_reset_conflict_rejected_before_device_actions(self):
        from recorder.gui_manager import AtlanRecorderGUI
        from core import control_appium, control_adb
        fake = SimpleNamespace(apk_path_var=SimpleNamespace(get=lambda:PKG), target_udid='serial',
                               onboarding_var=SimpleNamespace(get=lambda:True))
        with patch.object(control_appium, 'get_appium_launch_command'), \
             patch.object(control_adb, 'ensure_package_installed') as ensure:
            with self.assertRaisesRegex(ValueError, '웜 스타트'):
                AtlanRecorderGUI.prepare_appium_session(fake, True)
        ensure.assert_not_called()

    def test_generated_script_preserves_preparation_as_precondition(self):
        builder = CodeBuilder('warm', preparation={'status':'ready'}, test_address=ADDRESS)
        builder.add_click_action({'resource-id':'com.sampleapp:id/sample'})
        code = '\n'.join(builder.lines)
        ast.parse(code)
        self.assertLess(code.index('prepare_onboarding(preparation_info)'), code.index('# [XML]'))
        self.assertIn(repr(ADDRESS), code)
        self.assertEqual(builder.confirmed_steps, [])
        self.assertNotIn('prepare_onboarding', '\n'.join(CodeBuilder('original').lines))

    def test_address_flow_enters_explicit_text_via_appium_and_registers_before_ready(self):
        search_start = screen(node('주소 검색'), node(**{'class':'android.widget.Button',
                              'content-desc':'도로명, 건물명, 지번으로 검색'}))
        search_input = screen(node('주소 검색'), node(clickable='true', **{'class':'android.widget.EditText'}))
        results = screen(node('주소 검색'), button(ADDRESS['result_text']))
        detail_empty = screen(node('주소 상세'), node(ADDRESS['result_text']),
                              node(body=node('건물명, 동/호수 등 상세주소'), clickable='true',
                                   **{'class':'android.widget.EditText'}), button('주소 등록'))
        detail_done = screen(node('주소 상세'), node(ADDRESS['result_text']),
                             node('1층', clickable='true', **{'class':'android.widget.EditText'}), button('주소 등록'))
        pages = [search_start, search_input, results, detail_empty, detail_done, HOME]
        state, entered, editor = {'index':0}, [], Mock()
        def advance(*args):
            state['index'] += 1
        element = Mock()
        element.is_displayed.return_value = element.is_enabled.return_value = True
        element.send_keys.side_effect = lambda text: (entered.append(text), advance())
        class Driver:
            execute_script = editor
            find_elements = Mock(return_value=[element])
            @property
            def page_source(self):
                return pages[state['index']]
        info = {'appium_driver':Driver(), 'device_udid':'serial', 'app_package':PKG, 'onboarding_address':ADDRESS}
        with patch.object(prep, 'get_foreground_activity', side_effect=lambda _: (PKG,
                          'AddressActivity' if state['index'] < 5 else 'RootContainerActivity')), \
             patch.object(prep, 'adb_shell', side_effect=advance) as shell, patch.object(prep.time, 'sleep'):
            result = prep.prepare_onboarding(info)
        self.assertEqual(entered, [ADDRESS['query'], ADDRESS['detail']])
        editor.assert_called_once_with('mobile: performEditorAction', {'action':'search'})
        self.assertEqual(shell.call_count, 3)
        self.assertEqual(result['start_activity'], 'RootContainerActivity')
        self.assertEqual(len(result['actions']), 5)


if __name__ == '__main__':
    unittest.main()

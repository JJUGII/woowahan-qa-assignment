from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from recorder.pre_script import run_pre_script, validate_pre_script
from examples import open_app_from_home as home
from examples import open_app_with_monkey as monkey


class PreScriptTests(unittest.TestCase):
    def test_monkey_is_package_scoped_and_uses_one_event(self):
        info = {'device_udid': 'serial', 'app_package': 'com.example.qa'}
        with patch.object(monkey, 'ensure_package_installed'), \
                patch.object(monkey, 'adb_shell', return_value='Events injected: 1\n') as shell:
            monkey.open_app_with_monkey(info)
        self.assertEqual(shell.call_args.args,
                         ('serial', 'monkey', '-p', 'com.example.qa', '-c', 'android.intent.category.LAUNCHER', '1'))

    def test_monkey_no_activity_or_aborted_is_a_failure(self):
        info = {'device_udid': 'serial', 'app_package': 'com.example.qa'}
        for output in ['** No activities found to run, monkey aborted.', 'Events injected: 0']:
            with patch.object(monkey, 'ensure_package_installed'), \
                    patch.object(monkey, 'adb_shell', return_value=output):
                with self.assertRaises(RuntimeError):
                    monkey.open_app_with_monkey(info)

    def test_fresh_module_uses_device_info_and_reloads_edited_file(self):
        with TemporaryDirectory(prefix='startup space ') as directory:
            path = Path(directory) / 'startup.py'
            path.write_text('def startup(info):\n    info["result"] = "first"\n', encoding='utf-8')
            info = {}
            run_pre_script(path, info)
            self.assertEqual(info['result'], 'first')
            path.write_text('def startup(info):\n    info["result"] = "other"\n', encoding='utf-8')
            run_pre_script(path, info)
            self.assertEqual(info['result'], 'other')

    def test_run_entry_and_false_return(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'startup.py'
            path.write_text('def run(info):\n    return False\n', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'False'):
                run_pre_script(path, {})

    def test_syntax_and_entry_validation_do_not_execute_top_level_code(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'startup.py'
            path.write_text('raise RuntimeError("must not run")\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_pre_script(path)
            path.write_text('def startup(info)\n', encoding='utf-8')
            with self.assertRaises(SyntaxError):
                validate_pre_script(path)
            with self.assertRaises(ValueError):
                validate_pre_script(Path(directory) / 'missing.py')

    def test_bad_signature_is_reported_and_does_not_execute_function(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'startup.py'
            path.write_text('def startup():\n    raise RuntimeError("must not run")\n', encoding='utf-8')
            with self.assertRaises(RuntimeError) as error:
                run_pre_script(path, {})
            self.assertNotIn('must not run', str(error.exception))

    def test_duplicate_icons_do_not_tap(self):
        xml = '<hierarchy>' + ('<node text="배달의민족" clickable="true" enabled="true" '
                              'bounds="[0,0][80,80]" package="launcher"/>' * 2) + '</hierarchy>'
        info = {'app_package': home.TARGET_PACKAGE, 'device_udid': 'serial',
                'appium_driver': SimpleNamespace(page_source=xml)}
        with patch.object(home, 'adb_shell') as shell:
            with self.assertRaisesRegex(RuntimeError, '2'):
                home.open_app_from_home(info)
        self.assertEqual(shell.call_args_list[0].args, ('serial', 'input', 'keyevent', '3'))
        self.assertEqual(shell.call_count, 1)

    def test_changed_screen_does_not_tap(self):
        xml = ('<hierarchy><node text="배달의민족" clickable="true" enabled="true" '
               'bounds="[0,0][80,80]" package="launcher"/></hierarchy>')
        info = {'app_package': home.TARGET_PACKAGE, 'device_udid': 'serial',
                'appium_driver': SimpleNamespace(page_source=xml)}
        with patch.object(home, 'adb_shell') as shell, \
                patch.object(home, 'get_foreground_activity', return_value=('different.app', '.Home')):
            with self.assertRaisesRegex(RuntimeError, '바뀌었습니다'):
                home.open_app_from_home(info)
        self.assertEqual(shell.call_count, 1)

    def test_hook_replaces_am_start_and_foreground_is_checked_afterwards(self):
        from recorder import gui_manager as gui
        driver, process = Mock(), Mock()
        fake = SimpleNamespace(apk_path_var=SimpleNamespace(get=lambda: 'com.example.qa'), target_udid='serial',
                               device_info={'platform_name': 'Android', 'device_udid': 'serial',
                                            'device_name': 'device', 'platform_version': '15', 'device_number': 0},
                               close_appium_session=Mock(), appium_driver=None, appium_process=None)
        order = []
        with patch.object(gui, 'validate_pre_script', return_value=Path('startup.py')), \
                patch.object(gui, 'run_pre_script', side_effect=lambda p, i: order.append('hook')) as hook, \
                patch.object(gui.control_appium, 'get_appium_launch_command'), \
                patch.object(gui.control_adb, 'ensure_package_installed'), \
                patch.object(gui.control_adb, 'get_main_activity', return_value='.Alias'), \
                patch.object(gui.control_adb, 'launch_app') as launch, \
                patch.object(gui.control_adb, 'clear_app_data', side_effect=lambda *a: order.append('reset')), \
                patch.object(gui.control_adb, 'wait_for_app_foreground',
                             side_effect=lambda *a: order.append('check') or '.Home'), \
                patch.object(gui.control_appium, 'start_appium_server', return_value=process), \
                patch.object(gui.control_appium, 'check_selenium_ready', return_value=True), \
                patch.object(gui.control_appium, 'fetch_appium_driver',
                             return_value={'serial': {'appium_driver': driver}}):
            info = gui.AtlanRecorderGUI.prepare_appium_session(fake, True, pre_script_path='startup.py')
        self.assertEqual(order, ['reset', 'hook', 'check'])
        self.assertIs(hook.call_args.args[1]['appium_driver'], driver)
        self.assertFalse(info['appium_capabilities']['appium:autoLaunch'])
        launch.assert_not_called()

    def test_invalid_hook_stops_before_reset_or_session(self):
        from recorder import gui_manager as gui
        fake = SimpleNamespace()
        with patch.object(gui.control_appium, 'get_appium_launch_command'), \
                patch.object(gui.control_adb, 'clear_app_data') as clear, \
                patch.object(gui.control_appium, 'start_appium_server') as start:
            with self.assertRaises(ValueError):
                gui.AtlanRecorderGUI.prepare_appium_session(fake, True, pre_script_path='missing.py')
        clear.assert_not_called()
        start.assert_not_called()


if __name__ == '__main__':
    unittest.main()

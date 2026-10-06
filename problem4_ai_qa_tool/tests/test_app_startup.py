import subprocess
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import requests
import core.control_adb as adb
import core.control_appium as appium


class AppStartupTests(unittest.TestCase):
    def test_home_icon_mode_is_passed_to_recording_preparation(self):
        from recorder.gui_manager import AtlanRecorderGUI
        fake = SimpleNamespace(rec_start_mode_var=SimpleNamespace(get=lambda: '홈 아이콘 터치로 실행'),
                               rec_clear_data_var=SimpleNamespace(get=lambda: False),
                               home_icon_text_var=SimpleNamespace(get=lambda: '배달의민족'),
                               prepare_appium_session=Mock(return_value={'ready': True}),
                               show_opencv_window=Mock())
        with patch.object(appium, 'get_appium_launch_command'):
            AtlanRecorderGUI.run_recorder(fake)
        fake.prepare_appium_session.assert_called_once_with(False, attach=False, launch_method='home_icon', icon_text='배달의민족')

    def test_app_profile_selects_home_icon_mode_and_preserves_data(self):
        from recorder.gui_manager import AtlanRecorderGUI
        fake = SimpleNamespace(home_icon_text_var=Mock(), rec_start_mode_var=Mock(), rec_clear_data_var=Mock(), onboarding_var=Mock(),
                               on_record_start_mode_change=Mock())
        fake.rec_start_mode_var.get.return_value = '홈 아이콘 터치로 실행'
        with TemporaryDirectory() as directory:
            (Path(directory) / 'app_launch_profiles.json').write_text(json.dumps({'com.example.qa':
                {'mode': 'home_icon', 'icon_text': 'QA 앱'}}), encoding='utf-8')
            with patch.object(appium, 'project_root', return_value=Path(directory)):
                AtlanRecorderGUI.apply_app_launch_profile(fake, 'com.example.qa')
        fake.home_icon_text_var.set.assert_called_with('QA 앱')
        fake.rec_start_mode_var.set.assert_called_with('홈 아이콘 터치로 실행')
        fake.rec_clear_data_var.set.assert_called_with(False)

    def test_home_icon_preparation_reuses_driver_and_never_calls_other_launchers(self):
        from recorder import gui_manager as gui
        driver, process = Mock(), Mock()
        fake = SimpleNamespace(apk_path_var=SimpleNamespace(get=lambda: 'com.example.qa'), target_udid='serial',
                               device_info={'platform_name': 'Android', 'device_udid': 'serial',
                                            'device_name': 'device', 'platform_version': '15', 'device_number': 0},
                               close_appium_session=Mock(), appium_driver=None, appium_process=None)
        with patch.object(appium, 'get_appium_launch_command'), \
                patch.object(adb, 'ensure_package_installed'), patch.object(adb, 'get_main_activity', return_value='.Alias'), \
                patch.object(adb, 'launch_app_with_monkey') as monkey, patch.object(adb, 'launch_app') as activity, \
                patch.object(appium, 'start_appium_server', return_value=process), \
                patch.object(appium, 'check_selenium_ready', return_value=True), \
                patch.object(appium, 'fetch_appium_driver', return_value={'serial': {'appium_driver': driver}}), \
                patch.object(gui, 'launch_from_home_icon', return_value='.Tutorial') as icon:
            info = gui.AtlanRecorderGUI.prepare_appium_session(fake, False, launch_method='home_icon', icon_text='QA 앱')
        self.assertIs(icon.call_args.args[0]['appium_driver'], driver)
        self.assertEqual(icon.call_args.args[1], 'QA 앱')
        self.assertTrue(info['appium_capabilities']['appium:skipDeviceInitialization'])
        monkey.assert_not_called()
        activity.assert_not_called()

    def test_monkey_command_success_is_followed_by_foreground_check(self):
        with patch.object(adb, 'ensure_package_installed'), \
                patch.object(adb, 'get_foreground_activity', return_value=('launcher', '.Home')), \
                patch.object(adb, 'adb_shell', return_value='Events injected: 1') as shell, \
                patch.object(adb, 'wait_for_app_foreground', return_value='.Tutorial') as wait:
            self.assertEqual(adb.launch_app_with_monkey('serial', 'com.example.qa'), '.Tutorial')
        self.assertEqual(shell.call_args.args,
                         ('serial', 'monkey', '-p', 'com.example.qa', '-c', 'android.intent.category.LAUNCHER', '1'))
        wait.assert_called_once_with('serial', 'com.example.qa')

    def test_monkey_failure_does_not_fall_back_to_activity_start(self):
        with patch.object(adb, 'ensure_package_installed'), \
                patch.object(adb, 'get_foreground_activity', return_value=('launcher', '.Home')), \
                patch.object(adb, 'adb_shell', return_value='No activities found') as shell, \
                patch.object(adb, 'wait_for_app_foreground') as wait:
            with self.assertRaises(RuntimeError):
                adb.launch_app_with_monkey('serial', 'com.example.qa')
        self.assertEqual(shell.call_count, 1)
        wait.assert_not_called()

    def test_explicit_monkey_mode_does_not_require_a_pre_script(self):
        from recorder.gui_manager import AtlanRecorderGUI
        fake = SimpleNamespace(rec_start_mode_var=SimpleNamespace(get=lambda: 'ADB Monkey로 실행'),
                               rec_clear_data_var=SimpleNamespace(get=lambda: False),
                               prepare_appium_session=Mock(return_value={'ready': True}),
                               show_opencv_window=Mock())
        with patch.object(appium, 'get_appium_launch_command'):
            AtlanRecorderGUI.run_recorder(fake)
        fake.prepare_appium_session.assert_called_once_with(False, attach=False)
        fake.show_opencv_window.assert_called_once_with({'ready': True})

    def test_explicit_activity_mode_is_preserved(self):
        from recorder.gui_manager import AtlanRecorderGUI
        fake = SimpleNamespace(rec_start_mode_var=SimpleNamespace(get=lambda: 'Activity 직접 실행'),
                               rec_clear_data_var=SimpleNamespace(get=lambda: False),
                               prepare_appium_session=Mock(return_value={'ready': True}),
                               show_opencv_window=Mock())
        with patch.object(appium, 'get_appium_launch_command'):
            AtlanRecorderGUI.run_recorder(fake)
        fake.prepare_appium_session.assert_called_once_with(False, attach=False, launch_method='activity')

    def test_default_preparation_uses_checked_monkey_and_skips_device_initialization(self):
        from recorder.gui_manager import AtlanRecorderGUI
        fake = SimpleNamespace(apk_path_var=SimpleNamespace(get=lambda: 'com.example.qa'), target_udid='serial',
                               device_info={'platform_name': 'Android', 'device_udid': 'serial',
                                            'device_name': 'device', 'platform_version': '15', 'device_number': 0},
                               close_appium_session=Mock(), appium_driver=None, appium_process=None)
        driver, process = Mock(), Mock()
        with patch.object(appium, 'get_appium_launch_command'), \
                patch.object(adb, 'ensure_package_installed'), \
                patch.object(adb, 'get_main_activity', return_value='.Alias'), \
                patch.object(adb, 'launch_app_with_monkey', return_value='.Tutorial') as monkey, \
                patch.object(adb, 'launch_app') as activity, \
                patch.object(adb, 'clear_app_data') as clear, \
                patch.object(appium, 'start_appium_server', return_value=process), \
                patch.object(appium, 'check_selenium_ready', return_value=True), \
                patch.object(appium, 'fetch_appium_driver', return_value={'serial': {'appium_driver': driver}}):
            info = AtlanRecorderGUI.prepare_appium_session(fake, False)
        monkey.assert_called_once_with('serial', 'com.example.qa')
        activity.assert_not_called()
        clear.assert_not_called()
        self.assertTrue(info['appium_capabilities']['appium:skipDeviceInitialization'])
        self.assertFalse(info['appium_capabilities']['appium:autoLaunch'])

    def test_launcher_resolution_uses_main_and_launcher_and_checks_output(self):
        with patch.object(adb, 'adb_shell', side_effect=['package:/data/base.apk',
                                                       'priority=0\ncom.example.qa/.LauncherAlias']) as shell:
            self.assertEqual(adb.get_main_activity('serial', 'com.example.qa'), '.LauncherAlias')
            self.assertIn('android.intent.action.MAIN', shell.call_args.args)
            self.assertIn('android.intent.category.LAUNCHER', shell.call_args.args)
        with patch.object(adb, 'adb_shell', return_value='No activity found'):
            with self.assertRaises(RuntimeError):
                adb.get_main_activity('serial', 'com.example.qa')

    def test_parses_both_android_resumed_activity_formats(self):
        for output in ['topResumedActivity=ActivityRecord{abcd u0 com.example.qa/.Tutorial t25}',
                       'mResumedActivity: ActivityRecord{abcd u0 com.example.qa/com.example.qa.Home t25}']:
            with patch.object(adb, 'adb_shell', return_value=output):
                self.assertEqual(adb.get_foreground_activity('serial')[0], 'com.example.qa')

    def test_adb_success_exit_code_does_not_hide_activity_error(self):
        with patch.object(adb, 'get_foreground_activity', return_value=('launcher', '.Home')), \
                patch.object(adb, 'adb_shell', return_value='Error type 3\nActivity does not exist'), \
                patch.object(adb, 'wait_for_app_foreground') as wait:
            with self.assertRaises(RuntimeError):
                adb.launch_app('serial', 'com.example.qa', '.Missing')
            wait.assert_not_called()

    def test_already_open_app_is_not_relaunched(self):
        with patch.object(adb, 'get_foreground_activity', return_value=('com.example.qa', '.Tutorial')), \
                patch.object(adb, 'adb_shell') as shell, \
                patch.object(adb, 'wait_for_app_foreground', return_value='.Tutorial'):
            self.assertEqual(adb.launch_app('serial', 'com.example.qa', '.Alias'), '.Tutorial')
            shell.assert_not_called()

    def test_short_lived_foreground_does_not_count_as_ready(self):
        with patch.object(adb, 'get_foreground_activity', side_effect=[('com.example.qa', '.Splash'),
                                                                    ('launcher', '.Home'), ('launcher', '.Home')]), \
                patch.object(adb.time, 'monotonic', side_effect=[0, 0, 1, 2, 11]), \
                patch.object(adb.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                adb.wait_for_app_foreground('serial', 'com.example.qa')

    def test_cleanup_quits_driver_before_terminating_own_server(self):
        order = []
        driver = Mock()
        driver.quit.side_effect = lambda: order.append('quit')
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = lambda: order.append('terminate')
        with patch.object(appium.requests, 'get', return_value=SimpleNamespace(status_code=200)):
            appium.close_appium_session(driver, process)
        self.assertEqual(order, ['quit', 'terminate'])

    def test_dead_server_skips_http_session_delete_and_retries(self):
        driver, process = Mock(), Mock()
        process.poll.return_value = 1
        with patch.object(appium.requests, 'get') as probe:
            appium.close_appium_session(driver, process)
        driver.quit.assert_not_called()
        driver.command_executor.close.assert_called_once()
        probe.assert_not_called()
        process.terminate.assert_not_called()

    def test_unreachable_server_skips_driver_quit(self):
        driver, process = Mock(), Mock()
        process.poll.return_value = None
        with patch.object(appium.requests, 'get', side_effect=requests.ConnectionError):
            appium.close_appium_session(driver, process)
        driver.quit.assert_not_called()
        process.terminate.assert_called_once()

    def test_attach_preserves_app_even_if_reset_flag_was_set(self):
        from recorder.gui_manager import AtlanRecorderGUI
        fake = SimpleNamespace(apk_path_var=SimpleNamespace(get=lambda: 'com.example.qa'), target_udid='serial',
                               device_info={'platform_name': 'Android', 'device_udid': 'serial',
                                            'device_name': 'device', 'platform_version': '15', 'device_number': 0},
                               close_appium_session=Mock(), appium_driver=None, appium_process=None)
        driver, process = Mock(), Mock()
        with patch.object(appium, 'get_appium_launch_command'), \
                patch.object(adb, 'ensure_package_installed'), \
                patch.object(adb, 'get_foreground_activity', return_value=('com.example.qa', '.Tutorial')), \
                patch.object(adb, 'wait_for_app_foreground', return_value='.Tutorial'), \
                patch.object(adb, 'launch_app') as launch, patch.object(adb, 'clear_app_data') as clear, \
                patch.object(appium, 'start_appium_server', return_value=process), \
                patch.object(appium, 'check_selenium_ready', return_value=True), \
                patch.object(appium, 'fetch_appium_driver', return_value={'serial': {'appium_driver': driver}}):
            info = AtlanRecorderGUI.prepare_appium_session(fake, clear_data=True, attach=True)
        clear.assert_not_called()
        launch.assert_not_called()
        self.assertTrue(info['appium_capabilities']['appium:noReset'])
        self.assertFalse(info['appium_capabilities']['appium:autoLaunch'])
        self.assertTrue(info['appium_capabilities']['appium:skipDeviceInitialization'])

    def test_recorder_does_not_open_or_save_when_app_preparation_fails(self):
        from recorder.gui_manager import AtlanRecorderGUI
        fake = SimpleNamespace(rec_start_mode_var=SimpleNamespace(get=lambda: '자동 실행'),
                               rec_clear_data_var=SimpleNamespace(get=lambda: False),
                               prepare_appium_session=Mock(side_effect=RuntimeError('app failed')),
                               show_opencv_window=Mock())
        with patch.object(appium, 'get_appium_launch_command'):
            with self.assertRaises(RuntimeError):
                AtlanRecorderGUI.run_recorder(fake)
        fake.show_opencv_window.assert_not_called()


    def test_replay_attach_mode_ignores_pre_script_and_requests_attachment(self):
        from recorder.gui_manager import AtlanRecorderGUI
        fake = SimpleNamespace(target_udid='serial', apk_path_var=SimpleNamespace(get=lambda: 'com.example.qa'),
                               test_clear_data_var=SimpleNamespace(get=lambda: False),
                               rec_start_mode_var=SimpleNamespace(get=lambda: '현재 열린 앱에 연결'),
                               pre_script_var=SimpleNamespace(get=Mock(side_effect=AssertionError('unused hook'))),
                               prepare_appium_session=Mock(side_effect=RuntimeError('stop before replay')),
                               close_appium_session=Mock(), after=Mock())
        with patch.object(appium, 'get_appium_launch_command'):
            AtlanRecorderGUI.run_test(fake, 'test_demo.py')
        fake.prepare_appium_session.assert_called_once_with(False, attach=True)
        fake.pre_script_var.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()

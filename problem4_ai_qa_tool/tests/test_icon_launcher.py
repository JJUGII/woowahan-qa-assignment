from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import control_adb as adb
from recorder import app_launcher as launcher

ICON = ('<hierarchy><node text="배달의민족" clickable="true" enabled="true" '
        'package="launcher" bounds="[100,200][200,400]"/></hierarchy>')


def info(xml=ICON):
    return {'device_udid': 'serial', 'app_package': 'com.example.qa',
            'appium_driver': SimpleNamespace(page_source=xml)}


class IconLauncherTests(unittest.TestCase):
    def test_home_icon_preparation_rejects_reset_before_device_mutation(self):
        from recorder.gui_manager import AtlanRecorderGUI
        from core import control_appium as appium
        with patch.object(appium, 'get_appium_launch_command'), \
                patch.object(adb, 'clear_app_data') as clear:
            with self.assertRaisesRegex(ValueError, '데이터'):
                AtlanRecorderGUI.prepare_appium_session(SimpleNamespace(), True,
                                                       launch_method='home_icon', icon_text='QA 앱')
        clear.assert_not_called()
    def test_unique_icon_uses_short_stationary_touch_and_checks_app(self):
        with patch.object(launcher, 'get_foreground_activity', return_value=('launcher', '.Home')), \
                patch.object(launcher, 'adb_shell') as shell, \
                patch.object(launcher, 'wait_for_app_foreground', return_value='.Tutorial') as wait:
            self.assertEqual(launcher.launch_from_home_icon(info(), '배달의민족'), '.Tutorial')
        self.assertEqual(shell.call_args.args, ('serial', 'input', 'touchscreen', 'swipe', '150', '300', '150', '300', '80'))
        wait.assert_called_once_with('serial', 'com.example.qa')
        self.assertFalse(any('clear' in c.args for c in shell.call_args_list))

    def test_failed_start_retries_only_target_and_stops_on_success(self):
        with patch.object(launcher, 'get_foreground_activity', return_value=('launcher', '.Home')), \
                patch.object(launcher, 'adb_shell') as shell, \
                patch.object(launcher.time, 'sleep'), \
                patch.object(launcher, 'wait_for_app_foreground', side_effect=[RuntimeError('dead'), '.Tutorial']):
            launcher.launch_from_home_icon(info(), '배달의민족')
        touches = [c for c in shell.call_args_list if 'swipe' in c.args]
        self.assertEqual(len(touches), 2)
        stops = [c for c in shell.call_args_list if 'force-stop' in c.args]
        self.assertEqual([c.args for c in stops], [('serial', 'am', 'force-stop', 'com.example.qa')])

    def test_all_failed_starts_are_bounded_to_three_attempts(self):
        with patch.object(launcher, 'get_foreground_activity', return_value=('launcher', '.Home')), \
                patch.object(launcher, 'adb_shell') as shell, \
                patch.object(launcher.time, 'sleep'), \
                patch.object(launcher, 'wait_for_app_foreground', side_effect=RuntimeError('dead')):
            with self.assertRaisesRegex(RuntimeError, '3회'):
                launcher.launch_from_home_icon(info(), '배달의민족')
        self.assertEqual(sum('swipe' in c.args for c in shell.call_args_list), 3)

    def test_duplicate_icon_blocks_touch(self):
        xml = ICON.replace('</hierarchy>', ICON.split('<hierarchy>')[1])
        with patch.object(launcher, 'get_foreground_activity', return_value=('launcher', '.Home')), \
                patch.object(launcher, 'adb_shell') as shell:
            with self.assertRaisesRegex(RuntimeError, '2'):
                launcher.launch_from_home_icon(info(xml), '배달의민족')
        self.assertFalse(any('swipe' in c.args for c in shell.call_args_list))

    def test_screen_change_blocks_touch(self):
        with patch.object(launcher, 'get_foreground_activity', side_effect=[('launcher', '.Home'), ('launcher', '.Home'), ('other', '.Screen')]), \
                patch.object(launcher, 'adb_shell') as shell:
            with self.assertRaisesRegex(RuntimeError, '변경'):
                launcher.launch_from_home_icon(info(), '배달의민족')
        self.assertFalse(any('swipe' in c.args for c in shell.call_args_list))

    def test_live_owned_permission_dialog_is_preserved_without_taps(self):
        with patch.object(launcher, 'get_foreground_activity', return_value=('com.android.permissioncontroller', '.Grant')), \
                patch.object(launcher, 'get_app_permission_activity', return_value='.Tutorial'), \
                patch.object(launcher, 'wait_for_app_foreground', return_value='.Tutorial'), \
                patch.object(launcher, 'adb_shell') as shell:
            self.assertEqual(launcher.launch_from_home_icon(info(), '배달의민족'), '.Tutorial')
        shell.assert_not_called()

    def test_invalid_retry_count_is_rejected_before_device_access(self):
        with patch.object(launcher, 'get_foreground_activity') as device:
            for count in [0, 4, True]:
                with self.assertRaises(ValueError):
                    launcher.launch_from_home_icon(info(), '배달의민족', attempts=count)
        device.assert_not_called()


PERMISSION = '''topResumedActivity=ActivityRecord{abc u0 com.android.permissioncontroller/.Grant t10}
    * Hist #1: ActivityRecord{abc u0 com.android.permissioncontroller/.Grant t10}
      launchedFromPackage=com.example.qa userId=0
      resultTo=ActivityRecord{def u0 com.example.qa/.Tutorial t10} resultWho=permission
    * Hist #0: ActivityRecord{def u0 com.example.qa/.Tutorial t10}
'''


class PermissionStartupTests(unittest.TestCase):
    def test_live_permission_owner_returns_target_activity(self):
        with patch.object(adb, 'adb_shell', side_effect=[PERMISSION, '12345']):
            self.assertEqual(adb.get_app_permission_activity('serial', 'com.example.qa'), '.Tutorial')

    def test_other_app_permission_is_not_accepted(self):
        with patch.object(adb, 'adb_shell', return_value=PERMISSION.replace('launchedFromPackage=com.example.qa', 'launchedFromPackage=other.app')) as shell:
            self.assertIsNone(adb.get_app_permission_activity('serial', 'com.example.qa'))
        self.assertEqual(shell.call_count, 1)

    def test_orphan_permission_dialog_without_target_process_is_not_accepted(self):
        for result in ['', RuntimeError('pidof exit 1')]:
            with patch.object(adb, 'adb_shell', side_effect=[PERMISSION, result]):
                self.assertIsNone(adb.get_app_permission_activity('serial', 'com.example.qa'))

    def test_ready_wait_accepts_owned_permission_without_granting_it(self):
        with patch.object(adb, 'get_foreground_activity', return_value=('com.android.permissioncontroller', '.Grant')), \
                patch.object(adb, 'get_app_permission_activity', return_value='.Tutorial'), \
                patch.object(adb.time, 'sleep'), patch.object(adb, 'adb_shell') as shell:
            self.assertEqual(adb.wait_for_app_foreground('serial', 'com.example.qa'), '.Tutorial')
        shell.assert_not_called()


if __name__ == '__main__':
    unittest.main()

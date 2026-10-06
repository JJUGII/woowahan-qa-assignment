import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import core.control_appium as runtime


class AppiumRuntimeTests(unittest.TestCase):
    def test_project_runtime_works_without_path_or_user_npm_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'project'
            entry = root / '.tools/appium/node_modules/appium/index.js'
            entry.parent.mkdir(parents=True)
            entry.write_text('// fixture', encoding='utf-8')
            programs = Path(temp) / 'program files'
            node = programs / 'nodejs/node.exe'
            node.parent.mkdir(parents=True)
            node.touch()
            env = {'PATH': '', 'APPDATA': str(Path(temp) / 'missing'), 'ProgramFiles': str(programs)}
            with patch.object(runtime, 'project_root', return_value=root), patch.dict(os.environ, env), \
                    patch.object(runtime.shutil, 'which', return_value=None):
                self.assertEqual(runtime.get_appium_launch_command(), [str(node), str(entry)])
                self.assertEqual(runtime.build_appium_env(str(entry))['APPIUM_HOME'], str(root / '.tools/appium-home'))

    def test_missing_runtime_stops_before_device_reset(self):
        from recorder.gui_manager import AtlanRecorderGUI
        with patch.object(runtime, 'get_appium_launch_command', side_effect=FileNotFoundError('missing')), \
                patch('recorder.gui_manager.execute_adb_command_direct') as adb, \
                patch('recorder.gui_manager.kill_zombie_appium') as kill:
            with self.assertRaises(FileNotFoundError):
                AtlanRecorderGUI.run_recorder(SimpleNamespace())
            adb.assert_not_called()
            kill.assert_not_called()

    def test_node_launch_keeps_json_as_one_argument_and_captures_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            info = {'device_number': 0, 'device_name': 'fixture', 'appium_capabilities': {
                'appium:automationName': 'uiautomator2', 'appium:deviceName': '공백 "따옴표"'}}
            command = [r'C:\Program Files\nodejs\node.exe', r'E:\project with spaces\index.js']
            with patch.object(runtime, 'get_appium_launch_command', return_value=command), \
                    patch.object(runtime.subprocess, 'Popen', return_value=SimpleNamespace(pid=123)) as popen:
                runtime.start_appium_server(info, temp)
            args = popen.call_args.args[0]
            kwargs = popen.call_args.kwargs
            self.assertFalse(kwargs['shell'])
            self.assertEqual(args[:2], command)
            self.assertEqual(json.loads(args[args.index('--default-capabilities') + 1]), info['appium_capabilities'])
            self.assertEqual(kwargs['stderr'], runtime.subprocess.STDOUT)

    def test_standard_global_shim_resolves_direct_node_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            shim = Path(temp) / 'appium.cmd'
            entry = Path(temp) / 'node_modules/appium/index.js'
            entry.parent.mkdir(parents=True)
            entry.touch()
            with patch.object(runtime, 'find_appium_command', return_value=str(shim)), \
                    patch.object(runtime, 'find_node_command', return_value='node.exe'):
                self.assertEqual(runtime.get_appium_launch_command(), ['node.exe', str(entry)])


if __name__ == '__main__':
    unittest.main()

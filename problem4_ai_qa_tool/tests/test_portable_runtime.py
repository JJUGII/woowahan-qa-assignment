import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from recorder.portable_runtime import configure_portable_runtime
from core import control_appium


class PortableRuntimeTests(unittest.TestCase):
    def fixture(self, root):
        for name in ['portable_manifest.json', '.tools/node/node.exe', '.tools/java/bin/java.exe',
                     '.tools/java/bin/javac.exe', '.tools/android-sdk/platform-tools/adb.exe',
                     '.tools/android-sdk/platform-tools/AdbWinApi.dll', '.tools/android-sdk/platform-tools/AdbWinUsbApi.dll',
                     '.tools/android-sdk/build-tools/36.0.0/lib/apksigner.jar',
                     '.tools/android-sdk/build-tools/36.0.0/aapt2.exe',
                     '.tools/appium/node_modules/appium/index.js',
                     '.tools/appium-home/node_modules/appium-uiautomator2-driver/package.json']:
            path = root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (root/'.tools/extensions-template.json').write_text(json.dumps({'drivers':{'uiautomator2':{'installPath':'old-machine'}},'plugins':{},'schemaRev':4}))

    def test_no_portable_marker_leaves_development_environment_unchanged(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'JAVA_HOME':'existing'}):
            before = dict(os.environ)
            self.assertFalse(configure_portable_runtime(folder))
            self.assertEqual(dict(os.environ), before)

    def test_relocation_rewrites_paths_and_overrides_wrong_machine_tools(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PATH':'wrong','JAVA_HOME':'wrong'}, clear=True):
            root = Path(folder)/'새 PC portable'
            self.fixture(root)
            self.assertTrue(configure_portable_runtime(root))
            self.assertEqual(os.environ['JAVA_HOME'],str(root/'.tools/java'))
            self.assertEqual(os.environ['ANDROID_HOME'],str(root/'.tools/android-sdk'))
            self.assertTrue(os.environ['PATH'].startswith(str(root/'.tools/node')))
            cache = root/'.tools/appium-home/node_modules/.cache/appium/extensions.yaml'
            self.assertIn(str(root), json.loads(cache.read_text(encoding='utf-8'))['drivers']['uiautomator2']['installPath'])
            moved = Path(folder)/'다른 위치'
            root.rename(moved)
            configure_portable_runtime(moved)
            data = json.loads((moved/cache.relative_to(root)).read_text(encoding='utf-8'))
            self.assertEqual(data['drivers']['uiautomator2']['installPath'],str(moved/'.tools/appium-home/node_modules/appium-uiautomator2-driver'))

    def test_missing_bundle_file_fails_before_changing_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'portable_manifest.json').touch()
            before = dict(os.environ)
            with self.assertRaisesRegex(RuntimeError,'누락'):
                configure_portable_runtime(root)
            self.assertEqual(dict(os.environ),before)

    def test_bundled_node_preferred_over_installed_node(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            with patch.object(control_appium,'project_root',return_value=root), patch.object(control_appium.shutil,'which',return_value='wrong-node.exe'):
                self.assertEqual(control_appium.find_node_command(),str(root/'.tools/node/node.exe'))


if __name__ == '__main__':
    unittest.main()

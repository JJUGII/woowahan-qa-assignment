"""Relocatable desktop runtime. Changes only this process's environment."""
import json
import os
from pathlib import Path
import sys


def app_root():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def configure_portable_runtime(root=None):
    root = Path(root) if root else app_root()
    manifest = root / 'portable_manifest.json'
    if not manifest.is_file():
        return False
    required = ['.tools/node/node.exe', '.tools/java/bin/java.exe', '.tools/java/bin/javac.exe',
                '.tools/android-sdk/platform-tools/adb.exe', '.tools/android-sdk/platform-tools/AdbWinApi.dll',
                '.tools/android-sdk/platform-tools/AdbWinUsbApi.dll', '.tools/appium/node_modules/appium/index.js',
                '.tools/appium-home/node_modules/appium-uiautomator2-driver/package.json',
                '.tools/android-sdk/build-tools/36.0.0/lib/apksigner.jar',
                '.tools/android-sdk/build-tools/36.0.0/aapt2.exe',
                '.tools/extensions-template.json']
    missing = [name for name in required if not (root/name).is_file()]
    if missing:
        raise RuntimeError('배포 파일이 누락되었습니다. ZIP 전체를 다시 압축 해제하세요.\n' + '\n'.join(missing))
    paths = [root/'.tools/node', root/'.tools/java/bin', root/'.tools/android-sdk/platform-tools']
    os.environ['PATH'] = os.pathsep.join(map(str, paths)) + os.pathsep + os.environ.get('PATH', '')
    os.environ['JAVA_HOME'] = str(root/'.tools/java')
    os.environ['ANDROID_HOME'] = str(root/'.tools/android-sdk')
    os.environ['ANDROID_SDK_ROOT'] = str(root/'.tools/android-sdk')
    os.environ['APPIUM_HOME'] = str(root/'.tools/appium-home')
    # Appium stores an absolute installPath. Regenerate it when the folder moves.
    template = json.loads((root/'.tools/extensions-template.json').read_text(encoding='utf-8'))
    template['drivers']['uiautomator2']['installPath'] = str(root/'.tools/appium-home/node_modules/appium-uiautomator2-driver')
    cache = root/'.tools/appium-home/node_modules/.cache/appium/extensions.yaml'
    serialized = json.dumps(template, ensure_ascii=False, indent=2)
    if not cache.is_file() or cache.read_text(encoding='utf-8') != serialized:
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.with_name('extensions-' + str(os.getpid()) + '.tmp')
        temporary.write_text(serialized, encoding='utf-8')
        temporary.replace(cache)  # JSON is valid YAML.
    return True


def self_test(destination=None):
    """No API calls or device actions. Validate the frozen GUI and bundled server."""
    import socket
    import subprocess
    import time
    import urllib.request
    root = app_root()
    report = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': {}}
    output = Path(destination) if destination else root/'LOG/portable-self-test.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        configure_portable_runtime(root)
        commands = {'node': [str(root/'.tools/node/node.exe'), '--version'],
                    'java': [str(root/'.tools/java/bin/java.exe'), '-version'],
                    'adb': [str(root/'.tools/android-sdk/platform-tools/adb.exe'), 'version'],
                    'appium': [str(root/'.tools/node/node.exe'), str(root/'.tools/appium/node_modules/appium/index.js'), '--version'],
                    'drivers': [str(root/'.tools/node/node.exe'), str(root/'.tools/appium/node_modules/appium/index.js'), 'driver', 'list', '--installed', '--json']}
        for name, command in commands.items():
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    timeout=90, creationflags=creationflags)
            if result.returncode:
                raise RuntimeError(f'{name} failed: {(result.stdout + result.stderr)[-1800:]}')
            report['checks'][name] = (result.stdout + result.stderr).strip()
        apk = root/'.tools/appium-home/node_modules/appium-uiautomator2-driver/node_modules/appium-uiautomator2-server/apks/appium-uiautomator2-server-v10.3.3.apk'
        apks = apk.parent
        candidates = [p for p in apks.glob('*.apk') if 'androidTest' not in p.name]
        if len(candidates) != 1:
            raise RuntimeError('Expected one bundled UiAutomator2 server APK')
        apk = candidates[0]
        for name, command in {
            'apk_signature': [str(root/'.tools/java/bin/java.exe'), '-jar',
                              str(root/'.tools/android-sdk/build-tools/36.0.0/lib/apksigner.jar'), 'verify', '--verbose', str(apk)],
            'android_build_tools': [str(root/'.tools/android-sdk/build-tools/36.0.0/aapt2.exe'), 'dump', 'badging', str(apk)],
        }.items():
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    timeout=90, creationflags=creationflags)
            if result.returncode:
                raise RuntimeError(f'{name} failed: {(result.stdout + result.stderr)[-1800:]}')
            report['checks'][name] = result.stdout[:1800].strip()
        from recorder.writer_gui import ScriptWriterGUI
        app = ScriptWriterGUI()
        app.withdraw()
        app.update()
        report['checks']['gui'] = app.title()
        from recorder.model_picker import ModelPicker
        settings = app._settings_dialog()
        settings.withdraw()
        app.update()
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        picker = next(widget for widget in descendants(settings) if isinstance(widget, ModelPicker))
        if picker.fetch_button.cget('text') != '모델 목록 조회':
            raise RuntimeError('Model discovery control is missing')
        report['checks']['model_picker'] = 'Model discovery button and dropdown created; no API call'
        for timer in app.tk.call('after', 'info'):
            app.tk.call('after', 'cancel', timer)
        app.destroy()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        command = commands['appium'][:-1] + ['--address', '127.0.0.1', '--port', str(port), '--use-drivers', 'uiautomator2']
        log_path = output.with_suffix('.appium.log')
        with log_path.open('w', encoding='utf-8') as log:
            server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, creationflags=creationflags)
            try:
                for _ in range(60):
                    if server.poll() is not None:
                        raise RuntimeError('Bundled Appium exited before becoming ready')
                    try:
                        # Bypass inherited proxy settings for localhost diagnostics.
                        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/status', timeout=1) as response:
                            status = json.load(response)
                        if status['value']['ready']:
                            report['checks']['server'] = status['value']['build']['version']
                            break
                    except (OSError, ValueError, KeyError):
                        pass
                    time.sleep(.5)
                else:
                    raise RuntimeError('Bundled Appium readiness timed out')
            finally:
                server.terminate()
                server.wait(timeout=15)
        report['ok'] = True
    except Exception as exc:
        report['error'] = str(exc)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['ok'] else 1

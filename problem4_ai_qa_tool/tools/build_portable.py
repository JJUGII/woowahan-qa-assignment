"""Build a clean, relocatable Windows x64 writer distribution from pinned local tools."""
import argparse
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kw):
    return subprocess.run(list(map(str, args)), check=True, **kw)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'dist')
    parser.add_argument('--java', type=Path, default=Path(os.environ.get('JAVA_HOME', '')))
    parser.add_argument('--node', type=Path, default=Path(shutil.which('node') or 'node.exe'))
    parser.add_argument('--platform-tools', type=Path, default=Path(shutil.which('adb') or 'adb.exe').parent)
    parser.add_argument('--build-tools', type=Path, default=ROOT/'.tools/android-build-tools/android-16')
    args = parser.parse_args()
    for file in [args.java/'bin/java.exe', args.java/'bin/javac.exe', args.node, args.platform_tools/'adb.exe',
                 ROOT/'.tools/appium/node_modules/appium/index.js',
                 ROOT/'.tools/appium-home/node_modules/appium-uiautomator2-driver/package.json']:
        if not file.is_file():
            raise SystemExit(f'Missing build input: {file}')
    for name in ['lib/apksigner.jar', 'aapt2.exe', 'source.properties']:
        if not (args.build_tools/name).is_file():
            raise SystemExit(f'Missing Android Build Tools 36.0.0 input: {args.build_tools/name}')
    if 'Pkg.Revision=36.0.0' not in (args.build_tools/'source.properties').read_text().replace(' ', ''):
        raise SystemExit('This bundle requires Android Build Tools 36.0.0')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    # Keep extracted node_modules below MAX_PATH even when the delivery folder is deep.
    output = ROOT/'dist'/('p-' + stamp)
    output.mkdir(parents=True, exist_ok=False)
    print('OUTPUT:', output, flush=True)
    work = ROOT/'build'/('portable-' + stamp)
    run([sys.executable, '-m', 'PyInstaller', '--clean', '--distpath', output, '--workpath', work,
         ROOT/'AndroidScriptStudio.spec'], cwd=ROOT)
    bundle = output/'AndroidScriptStudio'
    bundled_tools = bundle/'.tools'
    bundled_tools.mkdir()
    ignore = shutil.ignore_patterns('.cache', '.npmrc', '.env', '*.log', '.DS_Store', '.nyc_output', 'coverage')
    for name in ['appium', 'appium-home']:
        print('Bundling', name, flush=True)
        shutil.copytree(ROOT/'.tools'/name, bundled_tools/name, ignore=ignore)
    print('Bundling Java / Node / Android platform tools', flush=True)
    shutil.copytree(args.java, bundled_tools/'java')
    shutil.copytree(args.platform_tools, bundled_tools/'android-sdk/platform-tools')
    shutil.copytree(args.build_tools, bundled_tools/'android-sdk/build-tools/36.0.0')
    (bundled_tools/'node').mkdir()
    shutil.copy2(args.node, bundled_tools/'node/node.exe')
    node_version = run([args.node, '--version'], capture_output=True, text=True).stdout.strip()
    # Preserve the upstream Node notices that are not installed by the Windows MSI.
    with urllib.request.urlopen(f'https://raw.githubusercontent.com/nodejs/node/{node_version}/LICENSE', timeout=30) as response:
        (bundled_tools/'node/LICENSE').write_bytes(response.read())
    package = json.loads((bundled_tools/'appium-home/node_modules/appium-uiautomator2-driver/package.json').read_text(encoding='utf-8'))
    driver = dict(pkgName=package['name'], version=package['version'], installType='npm',
                  installSpec='uiautomator2@' + package['version'], installPath='',
                  appiumVersion=package['peerDependencies']['appium'], automationName='UiAutomator2',
                  platformNames=['Android'], mainClass='AndroidUiautomator2Driver')
    (bundled_tools/'extensions-template.json').write_text(json.dumps({'drivers':{'uiautomator2':driver},'plugins':{},'schemaRev':4}, indent=2), encoding='utf-8')
    licenses = bundle/'THIRD_PARTY_LICENSES'
    licenses.mkdir()
    python_license = Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, licenses/'Python-LICENSE.txt')
    versions = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata['Name']
        versions[name] = dist.version
        for rel in dist.files or []:
            if any(part.lower().startswith(('license', 'copying', 'notice')) for part in rel.parts) and '.dist-info' in str(rel):
                source = Path(dist.locate_file(rel))
                if source.is_file():
                    target = licenses/name/Path(*rel.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    manifest = {'product':'Android Script Studio', 'build':stamp, 'platform':'Windows x64',
                'python':sys.version.split()[0], 'node':node_version, 'java':(args.java/'release').read_text(encoding='utf-8'),
                'appium':json.loads((bundled_tools/'appium/node_modules/appium/package.json').read_text())['version'],
                'uiautomator2':package['version'], 'python_build_packages':versions,
                'android_build_tools': '36.0.0',
                'scope':'Script authoring and export; no Android Studio or Kotlin test runner included'}
    (bundle/'portable_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copy2(ROOT/'tools/PORTABLE_README.txt', bundle/'처음 실행 안내.txt')
    (bundle/'환경진단.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nstart /wait "" "%~dp0AndroidScriptStudio.exe" --self-test\r\nnotepad "%~dp0LOG\\portable-self-test.json"\r\n', encoding='utf-8')
    print('Checking frozen executable with isolated development-tool environment', flush=True)
    env = os.environ.copy()
    for name in list(env):
        if name.upper() in {'JAVA_HOME','ANDROID_HOME','ANDROID_SDK_ROOT','APPIUM_HOME','NODE_PATH','NODE_OPTIONS','PYTHONPATH','PYTHONHOME'} or name.startswith('AI_RECORDER_'):
            env.pop(name, None)
    env['PATH'] = str(Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32')
    report = work/'self-test.json'
    run([bundle/'AndroidScriptStudio.exe', '--self-test', report], env=env, cwd=output, timeout=180)
    result = json.loads(report.read_text(encoding='utf-8'))
    if not result.get('ok'):
        raise RuntimeError('Frozen self test failed: ' + str(report))
    cache = bundled_tools/'appium-home/node_modules/.cache/appium/extensions.yaml'
    cache.write_text((bundled_tools/'extensions-template.json').read_text(encoding='utf-8'), encoding='utf-8')
    # No machine credentials, device history, or runtime logs are copied into the distribution.
    forbidden = {'recorder_settings.json','writer_preferences.json','device_config.json','app_name_cache.json','adbkey','adbkey.pub'}
    for file in bundle.rglob('*'):
        if file.is_file() and file.name in forbidden:
            raise RuntimeError('Private settings unexpectedly included: ' + str(file))
    hashes = []
    for file in sorted(bundle.rglob('*')):
        if file.is_file():
            hashes.append(hashlib.sha256(file.read_bytes()).hexdigest() + '  ' + file.relative_to(bundle).as_posix())
    (bundle/'SHA256SUMS.txt').write_text('\n'.join(hashes) + '\n', encoding='utf-8')
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output.resolve() / f'AndroidScriptStudio-Windows-x64-{stamp}.zip'
    print('Compressing:', archive, flush=True)
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package_zip:
        for file in sorted(bundle.rglob('*')):
            if file.is_file():
                package_zip.write(file, file.relative_to(output))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest + '  ' + archive.name + '\n', encoding='utf-8')
    print('BUILD_OK', json.dumps({'zip':str(archive),'bytes':archive.stat().st_size,'sha256':digest,'self_test':str(report)}), flush=True)


if __name__ == '__main__':
    main()

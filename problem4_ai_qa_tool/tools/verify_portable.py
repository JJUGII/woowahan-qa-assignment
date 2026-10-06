"""Extract and verify the delivered ZIP under a different path, without development PATH."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive',type=Path)
    parser.add_argument('destination',type=Path)
    parser.add_argument('report',type=Path)
    args = parser.parse_args()
    destination = args.destination.resolve()
    destination.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(args.archive) as archive:
        for member in archive.infolist():
            if not (destination/member.filename).resolve().is_relative_to(destination):
                raise RuntimeError('Invalid archive path')
        archive.extractall(destination)  # zipfile checks each member CRC during extraction.
    root = destination/'AndroidScriptStudio'
    count = 0
    for line in (root/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        expected, name = line.split('  ',1)
        file = (root/name).resolve()
        if not file.is_relative_to(root):
            raise RuntimeError('Invalid manifest path')
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Content hash mismatch: ' + name)
        count += 1
    print('ZIP CRC and file hashes verified:',count,flush=True)
    env = os.environ.copy()
    for key in list(env):
        if key.upper() in {'JAVA_HOME','ANDROID_HOME','ANDROID_SDK_ROOT','APPIUM_HOME','NODE_PATH','NODE_OPTIONS','PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'} or key.startswith('AI_RECORDER_'):
            env.pop(key,None)
    env['PATH'] = str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32')
    profile = destination/'empty-user-profile'
    profile.mkdir()
    for key, suffix in [('USERPROFILE',''),('APPDATA','AppData/Roaming'),('LOCALAPPDATA','AppData/Local')]:
        directory = profile/suffix
        directory.mkdir(parents=True,exist_ok=True)
        env[key] = str(directory)
    subprocess.run([str(root/'AndroidScriptStudio.exe'),'--self-test',str(args.report.resolve())],cwd=destination,
                   env=env,check=True,timeout=180)
    report = json.loads(args.report.read_text(encoding='utf-8'))
    drivers = json.loads(report['checks']['drivers'])
    expected_driver = root/'.tools/appium-home/node_modules/appium-uiautomator2-driver'
    assert Path(drivers['uiautomator2']['installPath']) == expected_driver
    assert report['ok'] and report['frozen']
    report['verified_archive_sha256'] = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    report['verified_file_count'] = count
    report['relocation'] = 'New path with Korean and spaces; isolated development PATH and empty profile'
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RELOCATION_OK',flush=True)


if __name__ == '__main__':
    main()

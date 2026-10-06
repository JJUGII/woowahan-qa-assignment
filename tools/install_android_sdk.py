"""Provide SDK license responses through one stdin stream on Windows."""
import subprocess
import sys
from pathlib import Path

manager, sdk = sys.argv[1:]
for args in [ ['--licenses'], ['platforms;android-35','build-tools;34.0.0','platform-tools'] ]:
    result=subprocess.run([manager, '--sdk_root='+sdk, *args], input='y\n'*100, text=True)
    if result.returncode: sys.exit(result.returncode)
for item in ['platforms/android-35/android.jar','build-tools/34.0.0/aapt2.exe','platform-tools/adb.exe']:
    if not (Path(sdk)/item).is_file():
        sys.exit('Android SDK 설치 결과가 없습니다: '+item)

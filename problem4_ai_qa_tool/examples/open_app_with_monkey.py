"""Activity를 직접 지정하지 않고 ADB Monkey로 앱을 여는 사전 스크립트."""
import logging
import re

from core.control_adb import adb_shell, ensure_package_installed

logger = logging.getLogger(__name__)


def open_app_with_monkey(device_info):
    udid = device_info['device_udid']
    pkg = device_info['app_package']
    ensure_package_installed(udid, pkg)
    output = adb_shell(udid, 'monkey', '-p', pkg, '-c', 'android.intent.category.LAUNCHER', '1', timeout=30)
    logger.info('[ADB Monkey 실행] %s\n%s', pkg, output)
    if not re.search(r'(?m)^Events injected:\s*1\s*$', output):
        raise RuntimeError('Monkey가 앱 실행 이벤트를 완료하지 못했습니다: ' + output[:1000])
    # A successful command is insufficient: Recorder checks actual foreground after this hook.

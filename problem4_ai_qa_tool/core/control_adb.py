import os
import time
import psutil
import subprocess
import logging
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from ppadb.client import Client as AdbClient
from ppadb.device import Device
from google_play_scraper import app as play_app

# 로깅 설정
logger = logging.getLogger(__name__)

# 앱 이름 캐싱 파일 경로 (프로젝트 루트에 생성됨)
CACHE_FILE = "app_name_cache.json"


def init_adb_client(adb_host_ip: str = "127.0.0.1", adb_port: int = 5037) -> AdbClient:
    adb_client = AdbClient(host=adb_host_ip, port=adb_port)
    try:
        logger.info(f'ADB client 버전: {adb_client.version()}')
    except RuntimeError as runtime_error:
        logger.warning(f'ADB 연결 실패. ADB를 동작시킨 후에 연결해주세요. {adb_host_ip}:{adb_port}. Error: {runtime_error}')
        if adb_host_ip == "127.0.0.1" or adb_host_ip.lower() == "localhost":
            logger.info("ADB 서버를 재기동 합니다.")
            try:
                for process in psutil.process_iter(["name"]):
                    if "adb" in process.info["name"]:
                        logger.info(f'adb 프로세스 종료: {process.info["name"]}')
                        subprocess.run(["adb", "-P", str(adb_port), "kill-server"], check=False, capture_output=True)
                        break

                logger.info(f'ADB 서버를 기동합니다. Port: {adb_port}')
                start_result = subprocess.run(["adb", "-P", str(adb_port), "start-server"], check=True,
                                              capture_output=True, text=True)
                logger.debug(f'ADB start-server output: {start_result.stdout.strip()}')
                time.sleep(1)
                adb_client.version()

            except (subprocess.CalledProcessError, FileNotFoundError) as proc_err:
                logger.error(f'ADB 서버 재시작 실패: {proc_err}')
                raise FileNotFoundError(f'Failed to start/restart local ADB server: {proc_err}') from proc_err
            except RuntimeError as final_e:
                logger.error(f'ADB 서버 재시작 이후에도 연결이 확인되지 않습니다.: {final_e}')
                raise RuntimeError(f'Still unable to connect to ADB server after restart: {final_e}') from final_e

    logger.info(f"ADB 서버 연결 완료. ADB 버전: {adb_client.version()}")
    return adb_client


def init_adb_devices(adb_client: AdbClient) -> dict[str, Device]:
    adb_devices: dict[str, Device] = {}
    if not adb_client:
        logger.error("adb_client 변수가 초기화되지 않음")
        return adb_devices

    try:
        device_list: list[Device] = adb_client.devices()
    except RuntimeError as runtime_error:
        logger.error(f'adb devices 목록 불러오기 실패: {runtime_error}')
        return adb_devices

    if not device_list:
        logger.warning("adb 서버에 연결 된 장치 없음")
        return adb_devices

    for device in device_list:
        device_serial = str(device.serial).strip()
        try:
            state = device.get_state()
            logger.debug(f"[{device_serial}] State: {state}")
            if state == "device":
                adb_devices[device_serial] = device
            elif state == "unauthorized":
                logger.warning(f"[{device_serial}] 장치가 unauthorized 상태입니다. 디버깅 허용을 진행해 주세요.")
            elif state == "offline":
                logger.warning(f"[{device_serial}] 장치가 offline 상태입니다.")
            else:
                logger.warning(f"[{device_serial}] 알 수 없는 오류입니다. state = {state}")
        except RuntimeError as runtime_error:
            logger.error(f'[{device_serial}] 장치 상태를 확인할 수 없습니다. error: {runtime_error}')
        except Exception as other_exception:
            logger.error(f'[{device_serial}] 예상하지 못한 에러입니다. error: {other_exception}')

    if not adb_devices:
        logger.warning("adb 서버에 인증 된 장치가 연결되지 않음")
    return adb_devices


def init_adb_device(adb_devices: dict, device_udid: str) -> Device | None:
    adb_device = adb_devices.get(device_udid)
    if adb_device is None:
        logger.error(f'UDID({device_udid}) 장치를 adb_devices 리스트에서 찾을 수 없습니다.')
    return adb_device


def get_device_resolution(adb_device: Device) -> dict[str, int]:
    device_resolution: dict = {"x": 0, "y": 0}
    wm_size_result = str(adb_device.shell("wm size"))
    if wm_size_result == "None":
        logger.error(f'[{adb_device.serial}] "wm size" 결과물이 None 입니다.')
        return device_resolution

    size_tag = "Override size:" if "Override" in wm_size_result else "Physical size:"
    if size_tag not in wm_size_result:
        logger.error(f"[{adb_device.serial}] wm size 결과물에서 size_tag를 찾을 수 없습니다. wm_size_result: {wm_size_result}")
        return device_resolution

    size_parts = wm_size_result.split(size_tag)
    split_result = size_parts[1].strip().split("x")

    if len(split_result) != 2:
        logger.error(f"[{adb_device.serial}] 해상도 분리에 실패하였습니다. wm_size_result: {wm_size_result}")
        return device_resolution

    device_resolution["x"] = int(split_result[0])
    device_resolution["y"] = int(split_result[1])
    return device_resolution


def get_android_veresion_float(platform_version: str) -> float:
    parts = platform_version.split('.', 1)
    if len(parts) == 1:
        parsed_version_string = parts[0]
    else:
        major_minor_part = parts[1].replace('.', '')
        parsed_version_string = f'{parts[0]}.{major_minor_part}'
    return float(parsed_version_string)


def get_adb_device_info(adb_device: Device, device_number: int) -> dict:
    device_udid = str(adb_device.serial).strip()
    device_name = str(adb_device.shell("getprop ro.product.model")).strip()
    platform_version = str(adb_device.shell("getprop ro.build.version.release")).strip()
    device_resolution = get_device_resolution(adb_device)
    platform_version_float = get_android_veresion_float(platform_version)

    top_command = "top -b -n 1 | grep -v 'grep' | grep 'PID'" if platform_version_float >= 10 else "top -d 0.5 -n 1 | grep -v 'grep' | grep 'PID'"
    grep_output = str(adb_device.shell(top_command)).strip()
    if grep_output == "None":
        logger.warning(f'[{device_udid}] grep_output == {grep_output}')
    elif "S[%CPU]" in grep_output:
        grep_output = grep_output.replace("S[%CPU]", "S [%CPU]")

    grep_first_row = grep_output.split()

    device_info = {
        "adb_device": adb_device,
        "device_udid": device_udid,
        "device_name": device_name,
        "device_number": device_number,
        "platform_name": "Android",
        "platform_version": platform_version,
        "platform_version_float": platform_version_float,
        "device_resolution": device_resolution,
        "grep_first_row": grep_first_row
    }
    return device_info


def fetch_device_info_dict(adb_devices: dict[str, Device]) -> dict:
    device_info_dict: dict = {}
    with ThreadPoolExecutor(max_workers=len(adb_devices)) as executor:
        future_to_udid = {
            executor.submit(get_adb_device_info, adb_device, index): udid for index, (udid, adb_device) in
            enumerate(adb_devices.items())
        }
        for future in as_completed(future_to_udid):
            udid = future_to_udid[future]
            try:
                single_device_info = future.result()
                device_info_dict[udid] = single_device_info
            except Exception as exc:
                logger.error(f'{udid} generated an exception: {exc}')
    return device_info_dict


def capture_screen(adb_device: Device, img_name: str, save_path: str) -> str:
    if not os.path.exists(save_path):
        try:
            os.makedirs(save_path, exist_ok=True)
        except OSError as error:
            logger.error(f'[{adb_device.serial}] 폴더 생성에 실패하였습니다. save_path: {save_path} / Error: {error}')
            raise OSError(f'Failed to create directory {save_path}: {error}') from error

    img_full_path = os.path.join(save_path, f'{img_name}.png')
    try:
        capture_result = adb_device.screencap()
        with open(img_full_path, "wb") as img_file:
            img_file.write(capture_result)
        logger.info(f'[{adb_device.serial}] 스크린샷 저장 완료: {img_full_path}')
        return img_full_path
    except RuntimeError as runtime_error:
        logger.error(f'{adb_device.serial}] 스크린 캡쳐 실패. Error: {runtime_error}')
        raise RuntimeError(f'Screen capture failed for {adb_device.serial}: {runtime_error}') from runtime_error
    except IOError as io_error:
        logger.error(f'스크린샷 저장 실패. Error: {io_error}')
        raise IOError(f'Failed to save screenshot to {img_full_path}: {io_error}') from io_error
    except Exception as unkwown_exception:
        logger.error(f'[{adb_device.serial}] 스크린샷 도중 예상치 못한 예외 발생. Error: {unkwown_exception}')
        raise Exception(
            f'Unexpected error during screen capture for {adb_device.serial}: {unkwown_exception}') from unkwown_exception


def send_tap(adb_device: Device, x: int, y: int, delay_sec: float = 0.5) -> bool:
    try:
        adb_device.shell(f'input tap {x} {y}')
        time.sleep(delay_sec)
        return True
    except RuntimeError as runtime_error:
        logger.error(f'[{adb_device.serial}] send_tap({x},{y}) 실패. Error: {runtime_error}')
        return False


def get_permission_positions(adb_device: Device) -> dict[str, str]:
    permission_positions: dict = {"owner": "root", "group": "root"}
    system_info = str(adb_device.shell("ls -ld /system")).strip()
    if not system_info:
        logger.warning(f'[{adb_device.serial}] system_info가 비어있습니다.')
        return permission_positions

    system_info_fields = system_info.split()
    try:
        owner_index = system_info_fields.index("root")
        permission_positions["owner"] = owner_index
    except ValueError:
        logger.warning(f'[{adb_device.serial}] 장치에 /system 폴더가 root 권한을 가지고 있지 않습니다.')
        return permission_positions

    try:
        group_index = system_info_fields.index("root", owner_index + 1)
        permission_positions["group"] = group_index
    except ValueError:
        logger.warning(f'[{adb_device.serial}] 그룹 권한을 받아 올 수 없습니다.')
        return permission_positions

    return permission_positions


def clear_device_status(device_info: dict) -> bool:
    adb_device: Device = device_info["adb_device"]
    platform_version_float: float = device_info["platform_version_float"]

    adb_device.shell("svc wifi disable")
    time.sleep(1)
    adb_device.shell("svc wifi enable")
    adb_device.uninstall('io.appium.uiautomator2.server')
    adb_device.uninstall('io.appium.uiautomator2.server.test')

    adb_device.shell('am force-stop kr.mappers.AtlanSmart')
    adb_device.shell('am force-stop kr.mappers.atlantruck')
    adb_device.shell('am force-stop kr.mappers.atlansdk')
    adb_device.shell('am force-stop kr.mappers.atlanappmetersdksample')
    adb_device.shell('am force-stop kr.mappers.composetest')

    adb_device.shell("settings put system screen_brightness_mode 0")
    adb_device.shell("settings put system screen_brightness 5")

    if platform_version_float >= 11:
        adb_device.shell("cmd media_session volume --set 1")
    else:
        adb_device.shell("media volume --stream 3 --set 1")
    return True


# ==========================================
# 앱 이름 및 Activity 매핑 로직
# ==========================================
def get_korean_app_name(pkg: str, cache: dict) -> tuple:
    if pkg in cache and isinstance(cache[pkg], list):
        return cache[pkg][0], pkg, cache[pkg][1]
    try:
        result = play_app(pkg, lang='ko', country='kr')
        app_name = str(result.get('title', pkg)).split(' -')[0].strip()
        app_name = app_name.replace("{", "").replace("}", "")
        icon_url = result.get('icon', None)
        return app_name, pkg, icon_url
    except Exception:
        fallback_name = pkg.split('.')[-1].capitalize()
        return fallback_name, pkg, None


def get_installed_packages(device_udid: str) -> list:
    logger.info("단말기 패키지 목록 스캔 중...")
    try:
        cmd = f"adb -s {device_udid} shell pm list packages -3"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        raw_packages = []

        for line in res.stdout.splitlines():
            if line.startswith("package:"):
                raw_packages.append(line.replace("package:", "").strip())

        cache = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception:
                pass

        result_list = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_pkg = {executor.submit(get_korean_app_name, pkg, cache): pkg for pkg in raw_packages}
            for future in as_completed(future_to_pkg):
                app_name, pkg, icon_url = future.result()
                result_list.append((app_name, pkg, icon_url))
                cache[pkg] = [app_name, icon_url]

        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)

        return sorted(result_list, key=lambda x: x[0].lower())
    except Exception as e:
        logger.error(f"패키지 목록 조회 실패: {e}")
        return []


def adb_shell(device_udid: str, *args: str, timeout=20) -> str:
    """Checked argv execution for app preparation; no CMD/Android shell pipes."""
    adb = shutil.which('adb')
    if not adb:
        candidate = os.path.join(os.environ.get('ANDROID_HOME', ''), 'platform-tools', 'adb.exe')
        if os.path.isfile(candidate):
            adb = candidate
    if not adb:
        raise FileNotFoundError('ADB 실행 파일을 찾지 못했습니다.')
    result = subprocess.run([adb, '-s', device_udid, 'shell', *args], capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError('ADB 명령 실패: ' + (result.stderr.strip() or result.stdout.strip())[:1000])
    return result.stdout.strip()


def ensure_package_installed(device_udid: str, package_name: str):
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', package_name):
        raise ValueError('Target App에서 단말에 설치된 앱 패키지를 선택하세요.')
    if not adb_shell(device_udid, 'pm', 'path', package_name).startswith('package:'):
        raise RuntimeError(f'단말에 {package_name} 패키지가 설치되어 있지 않습니다.')


def get_main_activity(device_udid: str, package_name: str) -> str:
    """Resolve the same MAIN/LAUNCHER intent used by an app icon."""
    ensure_package_installed(device_udid, package_name)
    output = adb_shell(device_udid, 'cmd', 'package', 'resolve-activity', '--brief',
                       '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', package_name)
    for line in reversed(output.splitlines()):
        if line.strip().startswith(package_name + '/'):
            return line.strip().split('/', 1)[1]
    raise RuntimeError(f'{package_name}의 실행 가능한 MAIN/LAUNCHER Activity를 찾지 못했습니다.')


def get_foreground_activity(device_udid: str) -> tuple[str, str]:
    output = adb_shell(device_udid, 'dumpsys', 'activity', 'activities')
    match = re.search(r'(?:topResumedActivity|mResumedActivity)\s*[:=]\s*ActivityRecord\{[^\n]*?\s([\w.]+)/([^\s}]+)', output)
    return (match.group(1), match.group(2)) if match else ('', '')


def get_app_permission_activity(device_udid: str, package_name: str):
    """A live target-owned Android permission prompt is part of app startup."""
    output = adb_shell(device_udid, 'dumpsys', 'activity', 'activities')
    resumed = re.search(r'(?:topResumedActivity|mResumedActivity)\s*[:=]\s*ActivityRecord\{[^\n]*?\s([\w.]+)/([^\s}]+)', output)
    if not resumed or resumed.group(1) not in ('com.android.permissioncontroller', 'com.google.android.permissioncontroller'):
        return None
    component = '/'.join(resumed.groups())
    for block in re.split(r'(?m)^\s*\* Hist\s+#\d+:', output)[1:]:
        if component not in block.splitlines()[0]:
            continue
        if not re.search(r'launchedFromPackage=' + re.escape(package_name) + r'\b', block):
            return None
        target = re.search(r'resultTo=ActivityRecord\{[^\n]*?\s' + re.escape(package_name) + r'/([^\s}]+)', block)
        if not target:
            return None
        try:
            alive = adb_shell(device_udid, 'pidof', package_name).strip()
        except RuntimeError:
            return None
        return target.group(1) if alive else None
    return None


def wait_for_app_foreground(device_udid: str, package_name: str, timeout=10):
    deadline = time.monotonic() + timeout
    consecutive = 0
    foreground = ('', '')
    while time.monotonic() < deadline:
        foreground = get_foreground_activity(device_udid)
        permission_activity = (get_app_permission_activity(device_udid, package_name)
                               if foreground[0] in ('com.android.permissioncontroller', 'com.google.android.permissioncontroller') else None)
        consecutive = consecutive + 1 if foreground[0] == package_name or permission_activity else 0
        if consecutive >= 3:
            if permission_activity:
                logger.info('[APP 진입] 대상 앱의 Android 권한 안내창이 표시되어 있습니다.')
            return permission_activity or foreground[1]
        time.sleep(.4)
    raise RuntimeError(f'{package_name}이 화면에 유지되지 않습니다. 현재 화면: {foreground[0] or "확인 불가"}. '
                       '단말 아이콘으로 앱을 연 뒤 시작 방식에서 "현재 열린 앱에 연결"을 선택하세요.')


def clear_app_data(device_udid: str, package_name: str):
    if adb_shell(device_udid, 'pm', 'clear', package_name) != 'Success':
        raise RuntimeError(f'{package_name} 앱 데이터 초기화에 실패했습니다.')


def launch_app(device_udid: str, package_name: str, activity: str):
    # Preserve an app already opened manually instead of killing/relaunching it.
    if get_foreground_activity(device_udid)[0] != package_name:
        output = adb_shell(device_udid, 'am', 'start', '-W', '-n', f'{package_name}/{activity}',
                           '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER',
                           '-f', '0x10200000', timeout=30)
        if re.search(r'(?im)^\s*(error|exception|status:\s*(?!ok\b)\w+)', output):
            raise RuntimeError('앱 실행 요청 실패: ' + output[:1000])
    return wait_for_app_foreground(device_udid, package_name)


def launch_app_with_monkey(device_udid: str, package_name: str):
    """Launch one package through ADB Monkey, then verify the actual foreground."""
    ensure_package_installed(device_udid, package_name)
    if get_foreground_activity(device_udid)[0] != package_name:
        logger.info('[앱 실행 방식] ADB Monkey: %s', package_name)
        output = adb_shell(device_udid, 'monkey', '-p', package_name,
                           '-c', 'android.intent.category.LAUNCHER', '1', timeout=30)
        logger.info('[ADB Monkey 결과] %s', output)
        if not re.search(r'(?m)^Events injected:\s*1\s*$', output):
            raise RuntimeError('Monkey가 앱 실행 이벤트를 완료하지 못했습니다: ' + output[:1000])
    return wait_for_app_foreground(device_udid, package_name)


if __name__ == '__main__':
    local_adb_client = init_adb_client(adb_host_ip="127.0.0.1")
    all_adb_devices = init_adb_devices(local_adb_client)

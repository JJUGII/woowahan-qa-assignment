import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import json
import time
import logging
import sys
from pathlib import Path
import toml
from selenium.webdriver.common.by import By
from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.webelement import WebElement
from appium.webdriver.webdriver import WebDriver
from appium.options.common.base import AppiumOptions

logger = logging.getLogger(__name__)


# [수정] clear_data 파라미터 추가
def set_appium_capabilities(single_device_info: dict, auto_permissions: bool = False, app_path: str = "",
                            clear_data: bool = False) -> dict:
    appium_capabilities = dict()

    appium_capabilities["platformName"] = single_device_info["platform_name"]
    appium_capabilities["appium:udid"] = single_device_info["device_udid"]
    appium_capabilities["appium:deviceName"] = single_device_info["device_name"]
    appium_capabilities["appium:platformVersion"] = single_device_info["platform_version"]
    appium_capabilities["appium:mjpegServerPort"] = 51000 + single_device_info["device_number"]
    appium_capabilities[
        "appium:mjpegScreenshotUrl"] = f'http://127.0.0.1:{appium_capabilities["appium:mjpegServerPort"]}'
    appium_capabilities["appium:newCommandTimeout"] = 300000
    appium_capabilities["appium:language"] = "ko"
    appium_capabilities["appium:locale"] = "KR"
    appium_capabilities["appium:wdaLocalPort"] = 53000 + single_device_info["device_number"]

    if not app_path == "":
        appium_capabilities["appium:app"] = app_path

    if single_device_info["platform_name"] == "Android":
        appium_capabilities["appium:automationName"] = "uiautomator2"

        target_pkg = single_device_info.get("app_package", "")
        target_act = single_device_info.get("app_activity", "")

        if target_pkg: appium_capabilities["appium:appPackage"] = target_pkg
        if target_act: appium_capabilities["appium:appActivity"] = target_act

        appium_capabilities["appium:autoGrantPermissions"] = auto_permissions
        appium_capabilities["appium:dontStopAppOnReset"] = False

        # [수정] UI 스위치 선택값에 따른 초기화 로직 적용
        if clear_data:
            appium_capabilities["appium:noReset"] = False
        else:
            appium_capabilities["appium:noReset"] = True

        appium_capabilities["appium:adbExecTimeout"] = 300000
        appium_capabilities["appium:uiautomator2ServerInstallTimeout"] = 600000

    elif single_device_info["platform_name"] == "iOS":
        appium_capabilities["appium:automationName"] = "XCUITest"

    return appium_capabilities


def save_device_toml(single_device_info: dict, toml_dir: str) -> str:
    toml_file_path = ""
    try:
        os.makedirs(toml_dir, exist_ok=True)
    except OSError as os_error:
        logger.error(f'{toml_dir} 생성에 실패 함. Error: {os_error}')
        return toml_file_path

    toml_data: dict = {
        "server": {"port": None},
        "node": {"detect-drivers": None},
        "relay": {"url": None, "status-endpoint": None, "configs": [None, None]}
    }

    toml_data["server"]["port"] = str(55000 + single_device_info["device_number"])
    toml_data["node"]["detect-drivers"] = str(False)
    toml_data["relay"]["url"] = "http://127.0.0.1:" + str(56000 + single_device_info["device_number"])
    toml_data["relay"]["status-endpoint"] = "/status"
    toml_data["relay"]["configs"][0] = "1"

    appium_options = {key: str(value) for key, value in single_device_info["appium_capabilities"].items()}

    toml_data["relay"]["configs"][1] = str(appium_options)
    toml_file_name = single_device_info["device_udid"] + ".toml"
    toml_file_path = os.path.join(toml_dir, toml_file_name)

    try:
        with open(toml_file_path, "w") as toml_file:
            toml.dump(toml_data, toml_file)

        fr = open(toml_file_path, "r")
        lines = fr.readlines()
        fr.close()

        fw = open(toml_file_path, "w")
        for line in lines:
            replaced_line = line.replace(",]", " ]")
            replaced_line = replaced_line.replace("\'", "\\\"")
            fw.write(replaced_line)
        fw.close()
    except Exception as e:
        logger.error(f'[{single_device_info["device_name"]}] toml 파일 저장 실패. Error: {e}')
        return toml_file_path

    return toml_file_path


def project_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def find_node_command() -> str:
    bundled = project_root() / '.tools' / 'node' / 'node.exe'
    if bundled.is_file():
        return str(bundled)
    found = shutil.which('node')
    if found:
        return found
    for directory in (os.environ.get('ProgramFiles', r'C:\Program Files'),
                      os.environ.get('ProgramW6432', r'C:\Program Files')):
        candidate = os.path.join(directory, 'nodejs', 'node.exe')
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError('Node.js 실행 파일을 찾지 못했습니다. Node.js 설치 경로를 확인하세요.')


def find_appium_command() -> str:
    """
    appium 실행 파일 경로를 찾는다.
    exe 를 탐색기나 바로가기로 실행하면 appium 설치 전의 PATH 를 물려받아
    'appium' 을 찾지 못하는 경우가 있어, npm 전역 설치 폴더를 직접 확인한다.
    """
    # Prefer the project runtime; independent of the launching CMD/user npm prefix.
    local_entry = project_root() / '.tools' / 'appium' / 'node_modules' / 'appium' / 'index.js'
    if local_entry.is_file():
        return str(local_entry)

    found = shutil.which("appium")
    if found:
        return found

    candidate_dirs = []
    try:
        npm_prefix = subprocess.run("npm prefix -g", shell=True, capture_output=True, text=True,
                                    timeout=15).stdout.strip()
        if npm_prefix:
            candidate_dirs.append(npm_prefix)
    except Exception:
        pass
    if os.environ.get("APPDATA"):
        candidate_dirs.append(os.path.join(os.environ["APPDATA"], "npm"))
    candidate_dirs.append(os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm"))

    for candidate_dir in candidate_dirs:
        candidate = os.path.join(candidate_dir, "appium.cmd")
        if os.path.isfile(candidate):
            return candidate

    raise FileNotFoundError('Appium을 찾지 못했습니다. 프로젝트 .tools/appium 또는 npm 전역 설치를 확인하세요.')


def get_appium_launch_command() -> list[str]:
    command = find_appium_command()
    if Path(command).suffix.lower() == '.js':
        return [find_node_command(), command]
    # Standard npm shim: invoke its actual JS entry without CMD quoting/PATH lookup.
    entry = Path(command).parent / 'node_modules' / 'appium' / 'index.js'
    if entry.is_file():
        return [find_node_command(), str(entry)]
    return [command]


def build_appium_env(appium_path: str) -> dict:
    """appium 폴더와 node 폴더를 PATH 앞에 붙인 환경변수를 만든다."""
    env = os.environ.copy()
    local_entry = project_root() / '.tools' / 'appium' / 'node_modules' / 'appium' / 'index.js'
    if os.path.normcase(os.path.abspath(appium_path)) == os.path.normcase(str(local_entry)):
        env['APPIUM_HOME'] = str(project_root() / '.tools' / 'appium-home')
    extra_dirs = []
    if os.path.isabs(appium_path):
        extra_dirs.append(os.path.dirname(appium_path))
    if not shutil.which("node"):
        node_dir = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs")
        if os.path.isfile(os.path.join(node_dir, "node.exe")):
            extra_dirs.append(node_dir)
    if extra_dirs:
        env["PATH"] = os.pathsep.join(extra_dirs + [env.get("PATH", "")])
    return env


def start_appium_server(single_device_info: dict, log_dir: str) -> subprocess.Popen:
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as os_error:
        logger.error(f'{log_dir} 생성 실패. Error: {os_error}')
        raise

    appium_driver_option = single_device_info["appium_capabilities"]["appium:automationName"]
    default_capabilities = json.dumps(single_device_info["appium_capabilities"])

    appium_port = 56000 + single_device_info["device_number"]
    appium_log_name = single_device_info["device_name"] + "_Appium.log"
    appium_log_path = os.path.join(log_dir, appium_log_name)
    launch_command = get_appium_launch_command()
    appium_path = launch_command[-1]
    logger.info(f'Appium 실행 파일: {appium_path}')
    appium_command = launch_command + ['--address', '127.0.0.1', '-p', str(appium_port), '--use-drivers', str(appium_driver_option),
                                       '--default-capabilities', default_capabilities, '--relaxed-security']
    use_shell = Path(launch_command[0]).suffix.lower() in {'.cmd', '.bat'}
    if use_shell:
        appium_command = subprocess.list2cmdline(appium_command)

    with open(appium_log_path, "w", encoding='utf-8') as log_file:
        appium_process = subprocess.Popen(appium_command, shell=use_shell, stdout=log_file,
                                          stderr=subprocess.STDOUT,
                                          env=build_appium_env(appium_path),
                                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if appium_process.pid < 0:
        logger.warning(f'[{single_device_info["device_name"]}] Appium Server 시작 실패')

    return appium_process


def start_selenium_node(single_device_info: dict, selenium_bin_path: str, toml_file_path: str,
                        log_dir: str) -> subprocess.Popen:
    path_check_array = [selenium_bin_path, toml_file_path, log_dir]
    for check_target in path_check_array:
        if not os.path.exists(check_target):
            logger.error(f'{check_target} 존재하지 않음')
            raise OSError

    selenium_log_name = single_device_info["device_name"] + "_Selenium_Node.log"
    selenium_log_path = os.path.join(log_dir, selenium_log_name)
    selenium_command = f'java -jar {selenium_bin_path} node --config {toml_file_path}'
    try:
        with open(selenium_log_path, "w") as log_file:
            selenium_node_process = subprocess.Popen(selenium_command, shell=True, stdout=log_file)
    except subprocess.SubprocessError as subprocess_error:
        logger.error(f'셀레니움 노드 실행 실패. Error: {subprocess_error}')
        raise subprocess.SubprocessError

    return selenium_node_process


def start_selenium_hub(selenium_bin_path: str, log_dir: str) -> subprocess.Popen:
    if not os.path.exists(selenium_bin_path):
        logger.error(f'{selenium_bin_path} 존재하지 않음')
        raise OSError

    selenium_hub_log_name = "Selenium_Hub.log"
    selenium_hub_log_path = os.path.join(log_dir, selenium_hub_log_name)
    selenium_hub_command = f'java -jar {selenium_bin_path} hub'
    try:
        with open(selenium_hub_log_path, "w") as log_file:
            selenium_hub_process = subprocess.Popen(selenium_hub_command, shell=True, stdout=log_file)
    except subprocess.SubprocessError as subprocess_error:
        logger.error(f'셀레니움 허브 실행 실패. Error: {subprocess_error}')
        raise subprocess.SubprocessError

    return selenium_hub_process


def check_selenium_ready(server_url: str, timeout: int = 30) -> bool:
    selenium_ready: bool = False
    for loop_count in range(timeout):
        try:
            response = requests.get(f'{server_url}/status', timeout=(2, 2))
            if response.status_code == 200 and response.json().get('value', {}).get('ready', False):
                selenium_ready = True
                break
        except requests.exceptions.RequestException as request_error:
            if loop_count < timeout - 1:
                time.sleep(1)
            else:
                logger.error(f'셀레니움 준비 확인 실패. Error: {request_error}')
                raise requests.exceptions.RequestException(request_error)
    return selenium_ready


def close_appium_session(driver, process, server_url='http://127.0.0.1:56000'):
    """Delete the session while its server is alive; stop only our own process."""
    if driver is not None:
        reachable = False
        if process is None or process.poll() is None:
            try:
                reachable = requests.get(server_url + '/status', timeout=(1, 1)).status_code == 200
            except requests.RequestException:
                pass
        try:
            if reachable:
                driver.quit()
            else:
                driver.command_executor.close()
        except Exception:
            logger.debug('이전 Appium 세션 연결은 이미 종료되었습니다.')
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def check_appium_ready(server_url: str, timeout: int = 30):
    return check_selenium_ready(server_url, timeout)


def init_appium_driver(single_device_info: dict, server_ip: str = "127.0.0.1") -> WebDriver:
    appium_capabilities: dict = single_device_info["appium_capabilities"]
    device_name = single_device_info["device_name"]
    appium_port = 56000 + single_device_info["device_number"]
    server_url = f'http://{server_ip}:{appium_port}'
    logger.info(f'[{device_name}] Appium Driver 초기화 시작. Server URL: {server_url}')
    try:
        options = AppiumOptions().load_capabilities(appium_capabilities)
        appium_driver = WebDriver(command_executor=server_url, options=options)
        logger.info(f'[{device_name}] 세션 로드 완료. Session ID: {appium_driver.session_id}')
    except Exception as error:
        logger.error(f'[{device_name}] Appium Driver 초기화 실패. Error: {error}')
        raise Exception(error)
    return appium_driver


def fetch_appium_driver(device_info_dict: dict) -> dict:
    with ThreadPoolExecutor(max_workers=len(device_info_dict)) as executor:
        future_to_udid = {
            executor.submit(init_appium_driver, device_info_dict[udid]): udid for udid in device_info_dict
        }
        for future in as_completed(future_to_udid):
            udid = future_to_udid[future]
            try:
                device_info_dict[udid]["appium_driver"] = future.result()
            except Exception as exc:
                logger.error(f'Error for {udid}: {exc}')
    return device_info_dict


def get_by_method(common_by: str):
    by_methods = {
        "ID": By.ID, "XPATH": By.XPATH, "LINK_TEXT": By.LINK_TEXT,
        "PARTIAL_LINK_TEXT": By.PARTIAL_LINK_TEXT, "NAME": By.NAME,
        "TAG_NAME": By.TAG_NAME, "CLASS_NAME": By.CLASS_NAME, "CSS_SELECTOR": By.CSS_SELECTOR,
        "IOS_PREDICATE": AppiumBy.IOS_PREDICATE, "IOS_CLASS_CHAIN": AppiumBy.IOS_CLASS_CHAIN,
        "ANDROID_UIAUTOMATOR": AppiumBy.ANDROID_UIAUTOMATOR, "ANDROID_VIEWTAG": AppiumBy.ANDROID_VIEWTAG,
        "ANDROID_DATA_MATCHER": AppiumBy.ANDROID_DATA_MATCHER, "ANDROID_VIEW_MATCHER": AppiumBy.ANDROID_VIEW_MATCHER,
        "ACCESSIBILITY_ID": AppiumBy.ACCESSIBILITY_ID, "IMAGE": AppiumBy.IMAGE, "CUSTOM": AppiumBy.CUSTOM
    }
    if common_by not in by_methods:
        logger.error(f'Invalid common_by. common_by: {common_by}')
        raise ValueError(f'지원되지 않는 common_by 변수입니다. {common_by}')
    return by_methods[common_by]


def find_elements_with_options(appium_driver: WebDriver, common_by: str, find_target: str, timeout: int = 5) -> list:
    target_elements = []
    if not appium_driver:
        logger.error(f'appium_driver is None')
        raise ValueError("appium_driver 연결 확인 불가")
    if timeout < 1: timeout = 1

    by_method = get_by_method(common_by)
    appium_driver.implicitly_wait(timeout)
    target_elements = appium_driver.find_elements(by=by_method, value=find_target)

    if len(target_elements) == 0:
        device_name = appium_driver.capabilities.get("deviceName")
        logger.debug(f'[{device_name}] There is no elements.')
        raise Exception(f'{timeout} 초 동안 {find_target} 을 찾지 못했습니다.')
    return target_elements


def find_element_with_options(appium_driver: WebDriver, common_by: str, find_target: str,
                              timeout: int = 5) -> WebElement:
    try:
        target_elements = find_elements_with_options(appium_driver, common_by, find_target, timeout)
        target_element = target_elements[0]
    except Exception as e:
        device_name = appium_driver.capabilities.get("deviceName")
        logger.debug(f'[{device_name}] There is no element. Error: {e}')
        raise Exception(f'{timeout} 초 동안 {find_target} 을 찾지 못했습니다.')
    else:
        return target_element


def get_element_center_location(element: WebElement) -> tuple[int, int]:
    location = element.location
    size = element.size
    try:
        center_x = location['x'] + (size['width'] // 2)
        center_y = location['y'] + (size['height'] // 2)
        center_location = (round(center_x), round(center_y))
    except Exception as e:
        logger.error(f'Element 중심 좌표 계산 중 오류 발생. Error: {e}')
        raise Exception(f'Element 중심 좌표 계산 중 오류 발생: {str(e)}')
    else:
        return center_location

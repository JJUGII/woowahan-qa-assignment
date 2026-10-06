"""Own one device session; never attach to or stop another Recorder's session."""
from io import BytesIO
import socket
import threading
import time
from PIL import Image

from core import control_adb, control_appium
from recorder.ai_recommender import verify_live_selector
from recorder.writer_agent import Screen, IDENTITY


class WriterDevice:
    def __init__(self):
        self.lock = threading.RLock()
        self.driver = self.process = None
        self.info = None

    @staticmethod
    def discover():
        return control_adb.init_adb_devices(control_adb.init_adb_client())

    def connect(self, adb_device):
        with self.lock:
            if self.driver:
                raise ValueError('이미 연결되어 있습니다.')
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1', 56000)) == 0:
                    raise ValueError('기존 Recorder/Appium이 사용 중입니다. 기존 프로그램에서 연결을 종료한 뒤 다시 연결하세요.')
            self.info = control_adb.get_adb_device_info(adb_device, 0)
            caps = control_appium.set_appium_capabilities(self.info, auto_permissions=False, clear_data=False)
            caps.update({'appium:autoLaunch': False, 'appium:dontStopAppOnReset': True,
                         'appium:shouldTerminateApp': False, 'appium:skipDeviceInitialization': True})
            self.info['appium_capabilities'] = caps
            try:
                self.process = control_appium.start_appium_server(self.info, str(control_appium.project_root() / 'LOG'))
                if not control_appium.check_selenium_ready('http://127.0.0.1:56000', timeout=30):
                    raise ValueError('휴대폰 연결 서버가 준비되지 않았습니다.')
                if self.process.poll() is not None:
                    raise ValueError('시작한 연결 서버가 종료됐습니다.')
                self.driver = control_appium.init_appium_driver(self.info)
            except Exception:
                self.close()
                raise ValueError('휴대폰 연결에 실패했습니다. USB 디버깅 승인과 Appium 설치를 확인하세요.') from None

    def capture(self):
        with self.lock:
            if not self.driver:
                raise ValueError('휴대폰을 먼저 연결하세요.')
            screen = Screen.parse(self.driver.page_source)
            picture = Image.open(BytesIO(self.driver.get_screenshot_as_png())).convert('RGB')
            size = self.driver.get_window_size()
            return screen, picture, (size['width'], size['height'])

    def screen(self):
        with self.lock:
            if not self.driver:
                raise ValueError('휴대폰을 먼저 연결하세요.')
            return Screen.parse(self.driver.page_source)

    def perform(self, action, original, cancel, record, provider='사용자'):
        with self.lock:
            if cancel.is_set():
                return False
            fresh = self.screen()
            if fresh.signature != original.signature:
                raise ValueError('화면이 바뀌었습니다. 최신 화면을 확인한 뒤 다시 진행하세요.')
            kind = action['action']
            if kind in {'tap', 'input', 'assert'}:
                key = action['target']
                attrs = original.elements[key]['attrs']
                actual = fresh.elements.get(key, {}).get('attrs', {})
                if any(actual.get(k) != attrs.get(k) for k in IDENTITY):
                    raise ValueError('대상 요소가 바뀌었습니다.')
                step = original.step(key, 'ASSERT' if kind == 'assert' else 'CLICK', provider)
                element = verify_live_selector(self.driver, step)
                if not element.is_displayed():
                    raise ValueError('요소가 표시되지 않습니다.')
                if cancel.is_set():
                    return False
                if kind == 'assert':
                    record({'kind': 'selector', 'step': step, 'description': step.description})
                    return True
                element.click()
                record({'kind': 'selector', 'step': step, 'description': step.description})
                if kind == 'input':
                    if cancel.is_set():
                        return False
                    focused = self.driver.switch_to.active_element
                    if focused.id != element.id:
                        raise ValueError('입력 포커스가 바뀌었습니다. 입력을 중단했습니다.')
                    focused.send_keys(action['text'])
                    record({'kind': 'input', 'text': action['text'], 'description': '텍스트 입력'})
            elif kind == 'back':
                self.driver.back()
                record({'kind': 'back', 'description': '뒤로 가기'})
            elif kind == 'swipe':
                size = self.driver.get_window_size()
                w, h = size['width'], size['height']
                coords = {'up': (.5, .75, .5, .3), 'down': (.5, .3, .5, .75),
                          'left': (.8, .5, .2, .5), 'right': (.2, .5, .8, .5)}[action['direction']]
                coords = tuple(round(v * (w if i % 2 == 0 else h)) for i, v in enumerate(coords))
                if cancel.is_set():
                    return False
                self.driver.swipe(*coords, 400)
                record({'kind': 'swipe', 'coords': coords, 'description': '스크롤 ' + action['direction']})
            elif kind == 'wait':
                start = time.monotonic()
                cancel.wait(action['seconds'])
                seconds = round(time.monotonic() - start, 2)
                record({'kind': 'wait', 'seconds': seconds, 'description': f'{seconds}초 대기'})
            else:
                raise ValueError('실행할 수 없는 동작입니다.')
            return True

    def close(self):
        with self.lock:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except Exception:
                    pass
                self.process = None

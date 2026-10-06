"""Local preferences. API keys are encrypted with Windows DPAPI, never plain JSON."""
import base64
import copy
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

from core.control_appium import project_root
from recorder.ai_services import SERVICE_PRESETS, CUSTOM_SERVICE, service_for_url

AI_MODES = ['기존 Recorder', '규칙 기반 데모 (LLM 미사용)', 'LLM (설정된 API)']
START_MODES = ['홈 아이콘 터치로 실행', 'ADB Monkey로 실행', 'Activity 직접 실행',
               '사전 스크립트로 실행', '현재 열린 앱에 연결']


class SettingsError(ValueError):
    pass


def _dpapi(value, decrypt=False):
    if os.name != 'nt':
        raise SettingsError('API 키 저장은 Windows에서 지원합니다. 저장 옵션을 끄고 이번 실행에서 사용하세요.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = Blob()
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise SettingsError('Windows에서 API 키를 보호하거나 불러오지 못했습니다. 키를 다시 입력하세요.')
    try:
        return ctypes.string_at(destination.data, destination.size)
    finally:
        kernel.LocalFree(destination.data)


def protect_key(value):
    return 'windows-dpapi-v1:' + base64.b64encode(_dpapi(value.encode('utf-8'))).decode('ascii')


def unprotect_key(value):
    try:
        if not value.startswith('windows-dpapi-v1:'):
            raise ValueError()
        return _dpapi(base64.b64decode(value.split(':', 1)[1], validate=True), decrypt=True).decode('utf-8')
    except (ValueError, UnicodeError) as exc:
        raise SettingsError('저장된 API 키를 불러오지 못했습니다. 키를 다시 입력하세요.') from exc


def defaults():
    address = os.getenv('AI_RECORDER_BASE_URL', '')
    service = service_for_url(address)
    return {'version': 1, 'ai': {'service': service, 'base_url': address or SERVICE_PRESETS['OpenAI'],
                               'model': os.getenv('AI_RECORDER_MODEL', ''), 'timeout': 40,
                               'remember_key': True, 'mode': AI_MODES[0]},
            'general': {'auto_scan': True, 'log_font_size': 12}, 'apps': {}}


def validate_settings(data):
    result = copy.deepcopy(data)
    ai, general = result.get('ai', {}), result.get('general', {})
    if ai.get('mode') not in AI_MODES or not isinstance(ai.get('remember_key'), bool):
        raise SettingsError('AI 추천 모드와 API 키 저장 옵션을 확인하세요.')
    if any(not isinstance(ai.get(k), str) for k in ('base_url', 'model')):
        raise SettingsError('AI 연결 주소와 모델 이름을 입력하세요.')
    # Migrate old settings using their actual URL; never re-route an existing key.
    ai['service'] = (CUSTOM_SERVICE if ai.get('service') == CUSTOM_SERVICE and not ai['base_url'].strip()
                     else service_for_url(ai['base_url']))
    if ai['service'] == 'OpenAI' and not ai['base_url'].strip():
        ai['base_url'] = SERVICE_PRESETS['OpenAI']
    if type(ai.get('timeout')) is not int or not 5 <= ai['timeout'] <= 120:
        raise SettingsError('AI 응답 대기 시간은 5~120초입니다.')
    if type(general.get('auto_scan')) is not bool or general.get('log_font_size') not in (11, 12, 13, 14, 15):
        raise SettingsError('자동 단말 검색과 로그 글자 크기를 확인하세요.')
    if not isinstance(result.get('apps'), dict):
        raise SettingsError('앱별 준비 설정 형식이 잘못됐습니다.')
    for app in result['apps'].values():
        if not isinstance(app, dict) or app.get('start_mode') not in START_MODES:
            raise SettingsError('앱 시작 방식을 확인하세요.')
        if any(type(app.get(k)) is not bool for k in ('onboarding', 'record_clear', 'test_clear')):
            raise SettingsError('앱 준비 옵션을 확인하세요.')
        if app['onboarding'] and (app['record_clear'] or app['test_clear']):
            raise SettingsError('웜 스타트 사전 작업에서는 앱 데이터 초기화를 해제하세요.')
        if app['start_mode'] in (START_MODES[0], START_MODES[4]) and (app['record_clear'] or app['test_clear']):
            raise SettingsError('홈 아이콘 실행/현재 앱 연결에서는 앱 데이터 초기화를 해제하세요.')
        if any(not isinstance(app.get(k), str) for k in ('icon_text', 'pre_script')):
            raise SettingsError('홈 아이콘 이름과 사전 스크립트를 확인하세요.')
        if app['start_mode'] == START_MODES[0] and not app['icon_text'].strip():
            raise SettingsError('홈 아이콘 이름을 입력하세요.')
        address = app.get('test_address')
        if address and (not isinstance(address, dict) or any(not isinstance(address.get(k), str)
                         or not address[k].strip() for k in ('query', 'result_text', 'detail'))):
            raise SettingsError('테스트 주소의 검색 문구, 결과 문구, 상세주소를 모두 입력하세요.')
    result['version'] = 1
    return result


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else project_root() / 'recorder_settings.json'
        self.api_key = os.getenv('AI_RECORDER_API_KEY', '')
        self.notice = ''

    def load(self):
        data = defaults()
        if not self.path.exists():
            return data
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            for section in ('ai', 'general', 'apps'):
                if isinstance(saved.get(section), dict):
                    data[section].update(saved[section])
            data = validate_settings(data)
            encrypted = saved.get('api_key_dpapi')
            if encrypted and data['ai']['remember_key']:
                try:
                    self.api_key = unprotect_key(encrypted)
                except (SettingsError, AttributeError):
                    self.api_key = ''
                    self.notice = '저장된 API 키를 불러오지 못했습니다. 환경설정에서 다시 입력하세요.'
            return data
        except (OSError, ValueError, TypeError, AttributeError):
            self.notice = '일부 저장 설정을 불러오지 못했습니다. 환경설정에서 다시 저장하세요.'
            return defaults()

    def save(self, data, api_key):
        clean = validate_settings(data)
        # Whitelist top-level fields; no cleartext key or unrelated fields can leak to disk.
        stored = {k: clean[k] for k in ('version', 'ai', 'general', 'apps')}
        stored['ai'] = {k: clean['ai'][k] for k in ('service', 'base_url', 'model', 'timeout', 'remember_key', 'mode')}
        stored['general'] = {k: clean['general'][k] for k in ('auto_scan', 'log_font_size')}
        stored['apps'] = {pkg:{k:app.get(k) for k in ('start_mode','icon_text','pre_script','onboarding',
                            'record_clear','test_clear','test_address')} for pkg, app in clean['apps'].items()}
        if api_key and clean['ai']['remember_key']:
            stored['api_key_dpapi'] = protect_key(api_key)
        temporary = self.path.with_suffix('.tmp')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)
        except OSError as exc:
            raise SettingsError('환경설정 파일을 저장하지 못했습니다. 폴더 권한을 확인하세요.') from exc
        self.api_key = api_key
        return clean

import sys
import os
import cv2
import numpy as np
import base64
import time
import logging
import subprocess
import importlib
import threading
import requests
import json
import queue
import psutil
import customtkinter as ctk
from io import BytesIO
from tkinter import filedialog, messagebox
from PIL import ImageFont, ImageDraw, Image

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

import core.control_adb as control_adb
import core.control_appium as control_appium
from recorder.ui_inspector import get_element_by_click
from recorder.viewport import RecorderViewport, recorder_shortcut
from recorder.window_keys import WindowModeKeys
from recorder.code_builder import CodeBuilder
from recorder.kotlin_builder import KotlinCodeBuilder
from recorder.pre_script import validate_pre_script, run_pre_script
from recorder.app_launcher import launch_from_home_icon
from recorder.onboarding import prepare_onboarding
from recorder.ai_dialog import RecommendationDialog
from recorder.settings import SettingsStore
from recorder.ai_services import create_provider
from recorder.settings_panel import SettingsPanel
from recorder.dashboard import Dashboard
from recorder.theme import apply_theme
from recorder.ai_recommender import (DemoProvider, RecommendationError,
                                     confirm_step, verify_live_selector, xpath_literal)

# ==========================================
# [UI 디자인 설정]
# ==========================================
apply_theme()
BG_COLOR = "#F3F8F8"
FRAME_COLOR = "#FFFFFF"
BORDER_COLOR = "#DCE8E8"
TEXT_MAIN = "#173A3B"
TEXT_SUB = "#647B7B"
BTN_MAIN = "#2AC1BC"
BTN_HOVER = "#22ADA8"
BTN_SUB = "#FDFDFD"
BTN_SUB_HOVER = "#F6F6F6"

UI_FONT = ("맑은 고딕", 12)
TITLE_FONT = ("맑은 고딕", 14, "bold")
LOG_FONT = ("Consolas", 11)

CONFIG_FILE = "device_config.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget

    def emit(self, record):
        msg = self.format(record)

        def append():
            self.text_widget.configure(state="normal")
            self.text_widget.insert("end", msg + "\n")
            self.text_widget.see("end")
            self.text_widget.configure(state="disabled")

        self.text_widget.after(0, append)


def execute_adb_command_direct(udid: str, command: str, wait=False):
    try:
        cmd = f"adb -s {udid} {command}"
        if wait:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.returncode != 0: logger.error(f"[ADB Error] {res.stderr.strip()}")
        else:
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.error(f"ADB Error: {e}")


def get_best_locator(el: dict, x: int, y: int) -> tuple:
    if not el: return "COORDINATE", f"{x}, {y}"
    res_id = el.get('resource-id', '').strip()
    if res_id: return "ID", res_id
    content_desc = el.get('content-desc', '').strip()
    if content_desc: return "ACCESSIBILITY_ID", content_desc
    text_val = el.get('text', '').strip()
    cls_val = el.get('class', '').strip()
    if text_val and cls_val: return "XPATH", f"//{cls_val}[@text='{text_val}']"
    return "COORDINATE", f"{x}, {y}"


def kill_zombie_appium():
    """포트 충돌 방지를 위해 기존에 떠있는 Appium 노드 프로세스를 강제 종료합니다."""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            name = proc.info.get('name', '')
            cmdline = proc.info.get('cmdline', [])
            if name and 'node' in name.lower() and cmdline and any('appium' in str(c).lower() for c in cmdline):
                proc.kill()
                logger.info("기존 Appium 프로세스 종료 완료 (포트 확보)")
    except Exception:
        pass


class AtlanRecorderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AI Visual Test Recorder")
        self.geometry("1180x920")
        self.minsize(1000, 760)
        self.configure(fg_color=BG_COLOR)

        self.device_info = None
        self.target_udid = None
        self.appium_driver = None
        self.appium_process = None
        self.device_configs = self.load_device_config()
        self.settings_store = SettingsStore()
        self.preferences = self.settings_store.load()

        self.dev_status_var = ctk.StringVar(value="단말 검색을 눌러 연결하세요")
        self.pre_script_var = ctk.StringVar()
        self.scenario_name_var = ctk.StringVar(value="test_scenario")
        self.script_language_var = ctk.StringVar(value='Python')
        self.test_script_var = ctk.StringVar()
        self.apk_path_var = ctk.StringVar(value="")
        self.home_icon_text_var = ctk.StringVar(value='')
        self.onboarding_var = ctk.BooleanVar(value=False)

        self.rec_clear_data_var = ctk.BooleanVar(value=False)
        self.test_clear_data_var = ctk.BooleanVar(value=False)
        self.ai_mode_var = ctk.StringVar(value=self.preferences['ai']['mode'])
        self.rec_start_mode_var = ctk.StringVar(value='현재 열린 앱에 연결')
        self._ai_provider = None

        self.placeholder_icon = ctk.CTkImage(Image.new("RGBA", (32, 32), (0, 0, 0, 0)), size=(32, 32))

        self.setup_ui()
        self.on_record_start_mode_change(self.rec_start_mode_var.get())
        self.setup_custom_logger()

        if self.preferences['general']['auto_scan']:
            self._scan_after = self.after(500, self.scan_device)
        if self.settings_store.notice:
            logger.warning(self.settings_store.notice)

    def load_device_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_device_config(self, udid, pkg):
        self.device_configs[udid] = pkg
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.device_configs, f, ensure_ascii=False, indent=4)

    def set_active_device(self, udid, devices):
        self.target_udid = udid
        self.device_info = control_adb.fetch_device_info_dict({udid: devices[udid]})[self.target_udid]

        dev_name = self.device_info['device_name']
        self.dev_status_var.set(f"연결됨  ,   {dev_name}")

        self.lbl_status.configure(font=("맑은 고딕", 13, "bold"), text_color='#087A75')
        logger.info(f"Active Device 설정 완료: {dev_name}")

        last_pkg = self.device_configs.get(self.target_udid)
        if last_pkg:
            self.apk_path_var.set(last_pkg)
            self.apply_app_launch_profile(last_pkg)
            logger.info(f"[{udid}] 설정 로드: {last_pkg}")

    def apply_app_launch_profile(self, pkg):
        self._profile_package = pkg
        self.home_icon_text_var.set('')
        self.onboarding_var.set(False)
        if hasattr(self, 'test_clear_data_var'):
            self.test_clear_data_var.set(False)
        if hasattr(self, 'pre_script_var'):
            self.pre_script_var.set('')
        self.rec_start_mode_var.set('현재 열린 앱에 연결')
        profile = {}
        try:
            path = control_appium.project_root() / 'app_launch_profiles.json'
            with path.open(encoding='utf-8') as source:
                profile = json.load(source).get(pkg, {})
            self.onboarding_var.set(profile.get('prepare_onboarding') is True)
            if profile.get('mode') == 'home_icon' and isinstance(profile.get('icon_text'), str):
                self.home_icon_text_var.set(profile['icon_text'])
                self.rec_start_mode_var.set('홈 아이콘 터치로 실행')
        except (OSError, ValueError, AttributeError):
            logger.info('앱 실행 프로필이 없거나 형식이 맞지 않아 현재 앱 연결을 사용합니다.')
        self.rec_clear_data_var.set(False)
        saved = getattr(self, 'preferences', {}).get('apps', {}).get(pkg, {})
        if saved:
            self.rec_start_mode_var.set(saved['start_mode'])
            self.home_icon_text_var.set(saved['icon_text'])
            self.onboarding_var.set(saved['onboarding'])
            self.rec_clear_data_var.set(saved['record_clear'])
            self.test_clear_data_var.set(saved['test_clear'])
            self.pre_script_var.set(saved['pre_script'])
        if hasattr(self, 'settings_panel'):
            self.settings_panel.load_app(saved.get('test_address') if saved else profile.get('test_address'))
        self.on_record_start_mode_change(self.rec_start_mode_var.get())

    def on_target_app_changed(self):
        pkg = self.apk_path_var.get().strip()
        if pkg and pkg != getattr(self, '_profile_package', None):
            self.apply_app_launch_profile(pkg)

    def setup_custom_logger(self):
        handler = TextHandler(self.log_textbox)
        handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        logging.getLogger().addHandler(handler)
        self._text_handler = handler

    def get_app_folder_name(self) -> str:
        val = self.apk_path_var.get().strip()
        if not val: return "Common"
        if val.endswith(".apk"): return os.path.splitext(os.path.basename(val))[0]
        return val

    def setup_ui(self):
        from recorder.theme import SIDEBAR, SOFT
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        sidebar = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, width=190)
        sidebar.grid(row=0, column=0, sticky='nsew')
        sidebar.grid_propagate(False)
        ctk.CTkLabel(sidebar, text='AI VISUAL', text_color='#2AC1BC', font=('맑은 고딕',13,'bold')).pack(anchor='w', padx=24, pady=(32,3))
        ctk.CTkLabel(sidebar, text='Test Recorder', text_color='white', font=('맑은 고딕',21,'bold')).pack(anchor='w', padx=24, pady=(0,28))
        self.nav_buttons = {}
        for page, title in (('home','홈'), ('settings','환경설정')):
            button = ctk.CTkButton(sidebar, text=title, height=44, width=152, anchor='w',
                font=('맑은 고딕',14,'bold'), fg_color='transparent', hover_color='#245657', text_color='#D9EFEF',
                command=lambda p=page:self.show_page(p))
            button.pack(padx=18, pady=5)
            self.nav_buttons[page] = button
        ctk.CTkLabel(sidebar, text='화면 선택\nAI 추천\n사용자 확인\n스크립트 생성', font=('맑은 고딕',12),
            text_color='#97B9B9', justify='left', anchor='w').pack(anchor='w', padx=24, pady=(32,0))
        ctk.CTkLabel(sidebar, text='Android QA Workspace', font=('맑은 고딕',10),
            text_color='#97B9B9').pack(side='bottom', pady=24)
        workspace = ctk.CTkFrame(self, fg_color=BG_COLOR, corner_radius=0)
        workspace.grid(row=0, column=1, sticky='nsew')
        header = ctk.CTkFrame(workspace, fg_color='transparent')
        header.pack(fill='x', padx=26, pady=(22,18))
        self.page_title = ctk.CTkLabel(header, text='테스트 워크스페이스', font=('맑은 고딕',24,'bold'))
        self.page_title.pack(side='left')
        self.ai_badge = ctk.CTkLabel(header, text='', font=('맑은 고딕',12,'bold'),
            fg_color=SOFT, corner_radius=12, height=34, text_color='#087A75')
        self.ai_badge.pack(side='right', padx=4)
        content = ctk.CTkFrame(workspace, fg_color='transparent')
        content.pack(fill='both', expand=True, padx=22, pady=(0,18))
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.home_panel = Dashboard(content, self)
        self.settings_panel = SettingsPanel(content, self)
        for variable in (self.ai_mode_var, self.rec_start_mode_var, self.onboarding_var,
                         self.rec_clear_data_var, self.test_clear_data_var):
            variable.trace_add('write', lambda *_:self.refresh_summary())
        self.show_page('home')
        self.refresh_summary()

    def show_page(self, page):
        if page == 'settings' and (self.btn_rec.cget('state') == 'disabled' or self.btn_run.cget('state') == 'disabled'):
            messagebox.showinfo('작업 진행 중', '녹화, 테스트가 끝난 뒤 환경설정을 변경하세요.')
            return
        self.home_panel.grid_remove()
        self.settings_panel.grid_remove()
        panel = self.settings_panel if page == 'settings' else self.home_panel
        panel.grid(row=0, column=0, sticky='nsew')
        self.page_title.configure(text='환경설정' if page == 'settings' else '테스트 워크스페이스')
        for name, button in self.nav_buttons.items():
            button.configure(fg_color=BTN_MAIN if name == page else 'transparent',
                             text_color=TEXT_MAIN if name == page else '#D9EFEF',
                             hover_color=BTN_HOVER if name == page else '#245657')

    def refresh_summary(self):
        if not hasattr(self, 'home_panel'):
            return
        mode = self.ai_mode_var.get()
        ai = self.preferences['ai']
        badge = ('AI 설정됨 ,  ' + ai['model']) if mode == 'LLM (설정된 API)' and ai['model'] and ai['base_url'] else (
            'AI 연결 설정 필요' if mode == 'LLM (설정된 API)' else '규칙 기반 데모' if mode.startswith('규칙') else '기존 Recorder')
        self.ai_badge.configure(text='  '+badge[:42]+'  ')
        preparation = '권한, 필수 약관 사전 처리' if self.onboarding_var.get() else '현재 화면부터 기록'
        self.home_panel.record_summary.set(self.rec_start_mode_var.get()+'\n'+preparation+' ,  '+
            ('데이터 초기화' if self.rec_clear_data_var.get() else '데이터 유지'))
        self.home_panel.replay_summary.set(self.rec_start_mode_var.get()+'\n'+
            ('데이터 초기화 후 재생' if self.test_clear_data_var.get() else '준비된 앱 상태에서 재생'))

    def open_work_folder(self, name):
        path = control_appium.project_root() / name
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def destroy(self):
        handler = getattr(self, '_text_handler', None)
        if handler:
            logging.getLogger().removeHandler(handler)
        # Child widgets also schedule DPI, scrollbar and icon callbacks.
        for callback in self.tk.call('after', 'info'):
            self.tk.call('after', 'cancel', callback)
        super().destroy()

    def browse_file(self, var, types=[("Python Files", "*.py")]):
        path = filedialog.askopenfilename(initialdir=os.getcwd(), filetypes=types)
        if path: var.set(path)

    def browse_script_file(self):
        app_folder = self.get_app_folder_name()
        init_dir = os.path.abspath(os.path.join("generated_scripts", app_folder))
        if not os.path.exists(init_dir): init_dir = os.path.abspath("generated_scripts")
        path = filedialog.askopenfilename(initialdir=init_dir, filetypes=[("Python Files", "*.py")])
        if path: self.test_script_var.set(path)

    def browse_pre_script(self):
        self.browse_file(self.pre_script_var)
        if self.pre_script_var.get().strip():
            self.rec_start_mode_var.set('사전 스크립트로 실행')
            self.on_record_start_mode_change('사전 스크립트로 실행')

    def show_package_selector(self):
        if not self.target_udid:
            messagebox.showwarning("Warning", "단말기를 먼저 선택해주세요.")
            return

        packages = control_adb.get_installed_packages(self.target_udid)
        if not packages: return

        dialog = ctk.CTkToplevel(self)
        dialog.title("App List")
        dialog.geometry("600x750")
        dialog.attributes("-topmost", True)

        search_entry = ctk.CTkEntry(dialog, placeholder_text="Search package or name...", font=UI_FONT)
        search_entry.pack(fill="x", padx=20, pady=15)

        scroll_frame = ctk.CTkScrollableFrame(dialog, fg_color="#FFFFFF", border_width=1, border_color=BORDER_COLOR)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        all_buttons = []

        def on_select(pkg):
            self.apk_path_var.set(pkg)
            self.apply_app_launch_profile(pkg)
            self.save_device_config(self.target_udid, pkg)
            logger.info(f"[SUCCESS] 앱 선택 완료: {pkg}")
            dialog.destroy()

        def load_icon_async(btn, url, name_text):
            try:
                res = requests.get(url, timeout=3)
                if res.status_code == 200:
                    img = Image.open(BytesIO(res.content)).convert("RGBA")
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(32, 32))
                    self.after(0, lambda: btn.configure(image=ctk_img, text=f"  {name_text}"))
            except:
                pass

        for app_name, pkg, icon_url in packages:
            app_name_str = str(app_name).strip()
            pkg_str = str(pkg).strip()
            display_text = f"{app_name_str}    [{pkg_str}]"

            btn = ctk.CTkButton(
                scroll_frame,
                text=f"  {display_text}",
                image=self.placeholder_icon,
                compound="left",
                anchor="w",
                font=("맑은 고딕", 12, "bold"),
                height=50,
                fg_color="transparent",
                text_color=TEXT_MAIN,
                hover_color="#F2F2F2",
                command=lambda p=pkg_str: on_select(p)
            )
            btn.pack(fill="x", pady=2, padx=5)
            all_buttons.append((btn, app_name_str, pkg_str))

            if icon_url:
                threading.Thread(target=load_icon_async, args=(btn, icon_url, display_text), daemon=True).start()

        search_entry.bind("<KeyRelease>", lambda e: self.filter_list(search_entry.get(), all_buttons))

    def filter_list(self, query, buttons):
        q = query.lower()
        for btn, name, pkg in buttons:
            if q in name.lower() or q in pkg.lower():
                btn.pack(fill="x", pady=2, padx=5)
            else:
                btn.pack_forget()

    def scan_device(self):
        try:
            client = control_adb.init_adb_client()
            devices = control_adb.init_adb_devices(client)

            if not devices:
                logger.warning("연결된 단말기가 없습니다. USB 디버깅 상태를 확인해주세요.")
                self.lbl_status.configure(font=UI_FONT, text_color=TEXT_SUB)
                self.dev_status_var.set("[Ready] 단말기 연결 대기 중...")
                return

            device_count = len(devices)
            if device_count == 1:
                udid = list(devices.keys())[0]
                self.set_active_device(udid, devices)
            else:
                self.show_device_selector(devices)

        except Exception as e:
            logger.error(f"단말기 Scan 실패: {e}")

    def show_device_selector(self, devices):
        dialog = ctk.CTkToplevel(self)
        dialog.title("단말기 선택")
        dialog.geometry("450x300")
        dialog.attributes("-topmost", True)

        ctk.CTkLabel(dialog, text="연결된 단말기가 2대 이상입니다.\n테스트를 진행할 단말기를 선택해주세요.", font=TITLE_FONT).pack(pady=20)

        for udid, device in devices.items():
            try:
                dev_name = str(device.shell("getprop ro.product.model")).strip()
            except:
                dev_name = "Unknown Device"

            btn_text = f"{dev_name}  ({udid})"

            btn = ctk.CTkButton(
                dialog,
                text=btn_text,
                font=("맑은 고딕", 12, "bold"),
                height=45,
                fg_color=BTN_MAIN,
                text_color=TEXT_MAIN,
                command=lambda u=udid: [self.set_active_device(u, devices), dialog.destroy()]
            )
            btn.pack(fill="x", padx=30, pady=5)

    def on_record_start_mode_change(self, mode):
        if mode in ('현재 열린 앱에 연결', '홈 아이콘 터치로 실행'):
            self.rec_clear_data_var.set(False)
            self.rec_clear_switch.configure(state='disabled')
        else:
            self.rec_clear_switch.configure(state='normal')

    def start_recording_thread(self):
        if not self.target_udid:
            return
        try:
            self._record_language = self.script_language_var.get()
            builder_type = KotlinCodeBuilder if self._record_language == 'Kotlin (UIAutomator)' else CodeBuilder
            builder_type(self.scenario_name_var.get())
            control_appium.get_appium_launch_command()
            if self.rec_start_mode_var.get() == '사전 스크립트로 실행':
                validate_pre_script(self.pre_script_var.get().strip())
            mode = self.ai_mode_var.get()
            self._ai_provider = (create_provider(service=self.preferences['ai'].get('service'), base_url=self.preferences['ai']['base_url'],
                                 model=self.preferences['ai']['model'], api_key=self.settings_store.api_key,
                                 timeout=self.preferences['ai']['timeout']) if mode == 'LLM (설정된 API)' else
                                 DemoProvider() if mode == '규칙 기반 데모 (LLM 미사용)' else None)
        except (ValueError, OSError, SyntaxError) as exc:
            messagebox.showerror('Recorder 설정', str(exc))
            return
        self.btn_rec.configure(state='disabled')
        self.btn_run.configure(state='disabled')
        self.language_menu.configure(state='disabled')
        threading.Thread(target=self.run_recording_guarded, daemon=True).start()

    def run_recording_guarded(self):
        try:
            self.run_recorder()
        except Exception as exc:
            logger.exception('Recorder 준비 실패: %s', exc)
            self.after(0, lambda msg=str(exc): messagebox.showerror('Recorder를 시작하지 못했습니다', msg))
        finally:
            self.close_appium_session()
            self.after(0, lambda: self.btn_rec.configure(state='normal'))
            self.after(0, lambda: self.btn_run.configure(state='normal'))
            self.after(0, lambda: self.language_menu.configure(state='normal'))

    def close_appium_session(self):
        driver, process = self.appium_driver, self.appium_process
        self.appium_driver, self.appium_process = None, None
        control_appium.close_appium_session(driver, process)

    def prepare_appium_session(self, clear_data, attach=False, pre_script_path=None, launch_method='monkey', icon_text=None):
        """One checked app startup path shared by recording and replay."""
        control_appium.get_appium_launch_command()
        if launch_method not in ('monkey', 'activity', 'home_icon'):
            raise ValueError('지원하지 않는 앱 실행 방식입니다.')
        if launch_method == 'home_icon' and not icon_text:
            raise ValueError('홈 화면에 표시된 앱 아이콘 이름을 입력하세요.')
        if launch_method == 'home_icon' and clear_data:
            raise ValueError('홈 아이콘 실행은 기존 앱 데이터를 유지합니다. 테스트 실행의 앱 데이터 초기화를 해제하세요.')
        if attach and pre_script_path:
            raise ValueError('현재 열린 앱 연결과 사전 스크립트 실행은 동시에 사용할 수 없습니다.')
        # Check syntax/entry point before resetting data or opening a session.
        if pre_script_path is not None:
            pre_script_path = validate_pre_script(pre_script_path)
        pkg = self.apk_path_var.get().strip()
        udid = self.target_udid
        onboarding_enabled = hasattr(self, 'onboarding_var') and self.onboarding_var.get()
        if onboarding_enabled and clear_data:
            raise ValueError('웜 스타트 사전 작업은 앱 상태를 유지합니다. 앱 데이터 초기화를 해제하세요.')
        control_adb.ensure_package_installed(udid, pkg)
        if attach:
            clear_data = False
            foreground, act = control_adb.get_foreground_activity(udid)
            if foreground != pkg:
                act = control_adb.get_app_permission_activity(udid, pkg)
                if not act:
                    raise RuntimeError(f'선택 앱 {pkg}을 단말에서 먼저 열어주세요. 현재 화면: {foreground or "확인 불가"}')
        else:
            act = control_adb.get_main_activity(udid, pkg)
        self.close_appium_session()
        startup = '현재 앱 연결' if attach else '사전 스크립트' if pre_script_path else launch_method
        logger.info('[앱 준비] Target: %s / Activity: %s / 시작 방식: %s / 사전 스크립트: %s',
                    pkg, act, startup, pre_script_path or '없음')
        info = self.device_info.copy()
        info.update({"device_number": 0, "app_package": pkg, "app_activity": act})
        info.pop("appium_capabilities", None)
        # The application owns the optional reset. Appium must not reset/relaunch it a second time.
        caps = control_appium.set_appium_capabilities(info, auto_permissions=not onboarding_enabled, clear_data=False)
        caps.update({'appium:autoLaunch': False, 'appium:dontStopAppOnReset': True,
                     'appium:shouldTerminateApp': False})
        if attach or pre_script_path or launch_method in ('monkey', 'home_icon'):
            caps['appium:skipDeviceInitialization'] = True
        info["appium_capabilities"] = caps
        if clear_data:
            logger.info('사용자가 선택한 앱 데이터 초기화를 1회 수행합니다: %s', pkg)
            control_adb.clear_app_data(udid, pkg)
        else:
            logger.info('앱 데이터 유지: %s', pkg)
        self.appium_process = control_appium.start_appium_server(info, os.path.join(os.getcwd(), 'LOG'))
        if not control_appium.check_selenium_ready('http://127.0.0.1:56000', timeout=30):
            raise RuntimeError('Appium 서버 준비 시간이 초과되었습니다. LOG의 Appium 로그를 확인하세요.')
        res = control_appium.fetch_appium_driver({udid: info})
        self.appium_driver = res[udid]['appium_driver']
        info['appium_driver'] = self.appium_driver
        if pre_script_path:
            run_pre_script(pre_script_path, info)
        if attach or pre_script_path:
            actual_activity = control_adb.wait_for_app_foreground(udid, pkg)
        elif launch_method == 'home_icon':
            actual_activity = launch_from_home_icon(info, icon_text)
        elif launch_method == 'monkey':
            actual_activity = control_adb.launch_app_with_monkey(udid, pkg)
        else:
            actual_activity = control_adb.launch_app(udid, pkg, act)
        if onboarding_enabled:
            profile_path = control_appium.project_root() / 'app_launch_profiles.json'
            try:
                with profile_path.open(encoding='utf-8') as source:
                    profile = json.load(source).get(pkg, {})
                if profile.get('test_address'):
                    info['onboarding_address'] = profile['test_address']
            except (OSError, ValueError, AttributeError):
                logger.warning('테스트 주소 프로필을 읽지 못했습니다. 주소 자동 입력을 건너뜁니다.')
            saved_app = getattr(self, 'preferences', {}).get('apps', {}).get(pkg, {})
            if 'test_address' in saved_app:
                info.pop('onboarding_address', None)
                if saved_app['test_address']:
                    info['onboarding_address'] = saved_app['test_address']
            prepare_onboarding(info)
        logger.info('[APP READY] %s / %s / 사전 작업: %s', pkg,
                    info.get('onboarding_preparation', {}).get('start_activity', actual_activity), onboarding_enabled)
        return info

    def run_recorder(self):
        # Check runtime before reading other state, and never record a failed startup.
        control_appium.get_appium_launch_command()
        attach = self.rec_start_mode_var.get() == '현재 열린 앱에 연결'
        options = {'attach': attach}
        logger.info('[Recorder 시작 설정] 방식: %s / 초기화: %s',
                    self.rec_start_mode_var.get(), self.rec_clear_data_var.get())
        if self.rec_start_mode_var.get() == 'Activity 직접 실행':
            options['launch_method'] = 'activity'
        elif self.rec_start_mode_var.get() == '홈 아이콘 터치로 실행':
            options.update(launch_method='home_icon', icon_text=self.home_icon_text_var.get().strip())
        if self.rec_start_mode_var.get() == '사전 스크립트로 실행':
            options['pre_script_path'] = self.pre_script_var.get().strip()
        info = self.prepare_appium_session(self.rec_clear_data_var.get(), **options)
        self.show_opencv_window(info)

    def auto_capture_crop(self, x, y, st):
        if st["last_frame"] is None:
            return None

        app_folder = self.get_app_folder_name()
        img_dir = os.path.join("resources", "images", app_folder)
        os.makedirs(img_dir, exist_ok=True)
        img_name = f"cap_{int(time.time())}.png"
        save_path = os.path.join(img_dir, img_name)

        img_h, img_w = st["last_frame"].shape[:2]
        point = st['viewport'].point(x, y, image=True)
        if point is None:
            return None
        cx, cy = point

        crop_size = 60
        y1, y2 = max(0, cy - crop_size), min(img_h, cy + crop_size)
        x1, x2 = max(0, cx - crop_size), min(img_w, cx + crop_size)

        cropped = st["last_frame"][y1:y2, x1:x2]

        if cropped.size > 0:
            cv2.imwrite(save_path, cropped)
            logger.info(f"[IMAGE CAPTURED] {img_name} 저장 완료")
            return os.path.join(app_folder, img_name).replace("\\", "/")
        return None

    def show_opencv_window(self, info):
        language = getattr(self, '_record_language', 'Python')
        builder_type = KotlinCodeBuilder if language == 'Kotlin (UIAutomator)' else CodeBuilder
        builder = builder_type(self.scenario_name_var.get(), preparation=info.get('onboarding_preparation'),
                               test_address=info.get('onboarding_address'))
        if isinstance(builder, KotlinCodeBuilder):
            builder.app_package = info.get('app_package')
        win = f"AI Visual Recorder - {builder.scenario_name} (C:Click A:Assert I:Input T:Wait B:Back Q:Save)"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL | cv2.WINDOW_FREERATIO)
        mode_keys = WindowModeKeys(win)
        dw, dh = info["device_resolution"]["x"], info["device_resolution"]["y"]
        xml_src = ""
        st = {"drag": False, "sx": 0, "sy": 0, "ww": 400, "wh": 1000, "mode": "CLICK", "last_el": None,
              "last_frame": None, "pending": False, "raw_w": dw, "raw_h": dh, 'viewport': None}
        shown_size = None
        ai_results = queue.Queue()
        pending_selection = None
        dialog_holder = []
        recorder_closed = threading.Event()

        def open_review(element, snapshot, mode):
            if not recorder_closed.is_set():
                dialog = RecommendationDialog(self, self._ai_provider, snapshot, element, mode, ai_results.put)
                dialog_holder.append(dialog)

        try:
            pil_font_bold = ImageFont.truetype("malgunbd.ttf", 16)
            pil_font = ImageFont.truetype("malgun.ttf", 13)
        except:
            pil_font_bold = ImageFont.load_default()
            pil_font = ImageFont.load_default()

        def on_m(event, x, y, flags, p):
            nonlocal xml_src, pending_selection
            if st['pending'] or st['viewport'] is None:
                return
            point = st['viewport'].point(x, y)
            if point is None:
                if event == cv2.EVENT_LBUTTONUP:
                    st['drag'] = False
                return
            rx, ry = point

            if event == cv2.EVENT_LBUTTONDOWN:
                st.update({"drag": True, "sx": rx, "sy": ry})
            elif event == cv2.EVENT_LBUTTONUP:
                if not st['drag']:
                    return
                st["drag"] = False
                dist = ((rx - st["sx"]) ** 2 + (ry - st["sy"]) ** 2) ** 0.5

                if dist < 25:
                    if xml_src:
                        el = get_element_by_click(xml_src, rx, ry)
                        st["last_el"] = el

                        has_xml_attr = el and (el.get('resource-id') or el.get('text') or el.get('content-desc'))
                        loc_type, loc_val = get_best_locator(el, rx, ry)

                        if isinstance(builder, KotlinCodeBuilder):
                            try:
                                builder.validate_click_action(el if has_xml_attr else None)
                            except ValueError as exc:
                                self.after(0, lambda msg=str(exc): messagebox.showinfo('Kotlin 기록', msg))
                                return

                        if self._ai_provider is not None and has_xml_attr:
                            st['pending'] = True
                            pending_selection = (dict(el), st['mode'], rx, ry)
                            self.after(0, lambda e=dict(el), snapshot=xml_src, mode=st['mode']:
                                       open_review(e, snapshot, mode))
                            return

                        if st["mode"] == "CLICK":
                            execute_adb_command_direct(self.target_udid, f"shell input tap {rx} {ry}")
                            if has_xml_attr:
                                builder.add_click_action(el=el)
                                logger.info(f"[저장됨] 식별자: {loc_type} / 대상: {loc_val}")
                            else:
                                img_path = self.auto_capture_crop(x, y, st)
                                if img_path:
                                    builder.add_click_action(img_name=img_path)
                                    logger.warning(f"[WARNING] [저장됨] 속성 없음 -> Airtest 이미지 캡처 클릭")
                                    st["last_el"] = {"resource-id": "N/A", "text": "N/A (이미지 클릭)", "class": "Airtest"}

                        elif st["mode"] == "ASSERT":
                            if has_xml_attr:
                                logger.info(f"[ASSERT-XML PREP] 속성 선택 팝업 호출")
                                self.after(0, lambda: self.show_assert_attribute_selector(el, builder, st))
                            else:
                                img_path = self.auto_capture_crop(x, y, st)
                                if img_path:
                                    logger.info(f"[ASSERT-IMAGE] 이미지 검증 스크립트 추가")
                                    builder.add_assertion_action(img_name=img_path)
                                    st["mode"] = "CLICK"
                                    logger.info("-> 모드가 'CLICK'으로 자동 복귀되었습니다.")

                else:
                    logger.info(f"[SWIPE] ({st['sx']}, {st['sy']}) -> ({rx}, {ry})")
                    execute_adb_command_direct(self.target_udid,
                                               f"shell input swipe {st['sx']} {st['sy']} {rx} {ry} 400")
                    builder.add_swipe_action(st['sx'], st['sy'], rx, ry)

        cv2.setMouseCallback(win, on_m)

        while True:
            try:
                if st['pending'] and pending_selection is not None:
                    try:
                        result = ai_results.get_nowait()
                    except queue.Empty:
                        result = 'waiting'
                    if result != 'waiting':
                        if result is not None:
                            element, mode, selected_x, selected_y = pending_selection
                            try:
                                step = confirm_step(original_element=element,
                                                    fresh_xml=self.appium_driver.page_source,
                                                    mode=mode, **result)
                                verify_live_selector(self.appium_driver, step)
                                if isinstance(builder, KotlinCodeBuilder):
                                    builder.validate_confirmed_step(step)
                                if step.mode == 'CLICK':
                                    execute_adb_command_direct(self.target_udid,
                                        f'shell input tap {selected_x} {selected_y}')
                                builder.add_confirmed_step(step)
                                logger.info('[추천 STEP] 사용자 확인 및 재검증 완료: %s', step.description)
                                if mode == 'ASSERT':
                                    st['mode'] = 'CLICK'
                            except Exception as exc:
                                error = (str(exc) if isinstance(exc, RecommendationError) else
                                         'Appium 동작/검증에 실패했습니다. 요소를 다시 선택하세요.')
                                self.after(0, lambda msg=error: messagebox.showerror('기록하지 않았습니다', msg))
                        st['pending'] = False
                        pending_selection = None
                if not st['pending']:
                    img_b64 = self.appium_driver.get_screenshot_as_base64()
                    xml_src = self.appium_driver.page_source
                    nparr = np.frombuffer(base64.b64decode(img_b64), np.uint8)
                    img = cv2.imdecode(nparr, 1)
                    st["last_frame"] = img.copy()
                    st['raw_w'], st['raw_h'] = img.shape[1], img.shape[0]
                else:
                    img = st['last_frame'].copy()

                h, w = img.shape[:2]
                viewport = RecorderViewport.create(w, h, dw, dh)
                if st['viewport'] != viewport:
                    st['drag'] = False
                st['viewport'] = viewport
                st['ww'], st['wh'] = viewport.width, viewport.height
                disp = cv2.resize(img, (st['ww'], st['wh']))

                text_color = (192, 103, 0) if st["mode"] == "CLICK" else (0, 0, 255)
                cv2.putText(disp, 'REVIEW PENDING' if st['pending'] else f"MODE: {st['mode']}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_color, 2,
                            cv2.LINE_AA)

                panel_w = 320
                panel = np.full((st['wh'], panel_w, 3), 245, dtype=np.uint8)
                pil_img = Image.fromarray(cv2.cvtColor(panel, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(pil_img)
                draw.text((16, 20), '클릭 C/ㅊ ,  검증 A/ㅁ', font=pil_font_bold, fill=(23,58,59))
                lines = (['AI: 요소 선택 → 속성 버튼', 'AI 우선순위 추천 (선택)', '속성 선택 후 동작, 기록']
                         if self._ai_provider is not None else ['기존 Recorder: 즉시 동작, 기록'])
                for index, line in enumerate(lines):
                    draw.text((16, 52+index*25), line, font=pil_font, fill=(23,58,59))
                draw.text((16, 135), 'Q/ㅂ 저장 ,  드래그: 스와이프', font=pil_font, fill=(80,80,80))
                if st["last_el"]:
                    draw.text((20, 180), "[ 엘리먼트 정보 ]", font=pil_font_bold, fill=(0, 0, 0))
                    y_off = 220
                    for k, label in [('resource-id', 'ID'), ('text', 'Text'), ('content-desc', 'Desc'),
                                     ('class', 'Class'), ('package', 'Package')]:
                        val = st["last_el"].get(k, 'N/A')
                        if len(val) > 35: val = val[:32] + "..."

                        draw.text((20, y_off), f"[{label}]", font=pil_font_bold, fill=(80, 80, 80))
                        draw.text((20, y_off + 25), val, font=pil_font, fill=(20, 20, 20))
                        y_off += 65

                panel = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

                final_disp = np.hstack((disp, panel))
                cv2.imshow(win, final_disp)
                if shown_size != final_disp.shape[:2]:
                    cv2.resizeWindow(win, final_disp.shape[1], final_disp.shape[0])
                    shown_size = final_disp.shape[:2]

            except Exception as e:
                logger.error(f"Streaming error: {e}")
                break

            key = cv2.waitKeyEx(100)
            action = recorder_shortcut(key)
            physical_mode = mode_keys.take()
            if action in (None, 'ASSERT', 'CLICK'):
                action = physical_mode or action
            if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                break
            if st['pending']:
                continue

            if action == 'SAVE':
                break
            elif action == 'ASSERT':
                st["mode"] = "ASSERT"
            elif action == 'CLICK':
                st["mode"] = "CLICK"
            elif action == 'INPUT':
                self.after(0, lambda: self.ask_and_send_input(builder))
            elif action == 'SLEEP':
                self.after(0, lambda: self.ask_and_add_sleep(builder))
            elif action == 'BACK':
                execute_adb_command_direct(self.target_udid, "shell input keyevent 4")
                builder.add_back_action()

        recorder_closed.set()
        for dialog in dialog_holder:
            if not dialog.closed:
                self.after(0, dialog.cancel)
        mode_keys.close()
        cv2.destroyWindow(win)

        app_folder = self.get_app_folder_name()
        script_dir = os.path.abspath(os.path.join("generated_scripts", app_folder))
        os.makedirs(script_dir, exist_ok=True)
        filename = builder.filename if isinstance(builder, KotlinCodeBuilder) else f"test_{builder.scenario_name}.py"
        final_path = os.path.join(script_dir, filename)

        builder.generate_script(final_path)
        logger.info(f"[SUCCESS] 스크립트 저장 완료: {final_path}")
        if isinstance(builder, KotlinCodeBuilder):
            logger.info('[Kotlin] Android Studio의 androidTest에서 실행하세요. 현재 앱 준비 상태를 사전에 맞춰야 합니다.')
        self.after(0, lambda: self.test_script_var.set(final_path))

    def show_assert_attribute_selector(self, el, builder, st_dict):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Assert Criteria")
        dialog.geometry("400x320")
        dialog.attributes("-topmost", True)
        ctk.CTkLabel(dialog, text="검증 기준을 선택하세요.", font=TITLE_FONT).pack(pady=15)

        def on_sel(t, v):
            try:
                builder.add_custom_assertion(t, v)
            except ValueError as exc:
                messagebox.showerror('기록하지 않았습니다', str(exc), parent=dialog)
                return
            logger.info(f"[ASSERT-XML] 스크립트 추가 완료: {t}")
            st_dict["mode"] = "CLICK"
            dialog.destroy()

        for k, label, loc_t in [('resource-id', 'ID', 'ID'), ('text', 'Text', 'XPATH'),
                                ('content-desc', 'Desc', 'ACCESSIBILITY_ID')]:
            val = el.get(k)
            if val:
                actual_val = f"//*[@text={xpath_literal(val)}]" if loc_t == 'XPATH' else val
                ctk.CTkButton(dialog, text=f"{label}: {val[:30]}", font=UI_FONT, fg_color=BTN_MAIN, text_color=TEXT_MAIN,
                              command=lambda lt=loc_t, lv=actual_val: on_sel(lt, lv)).pack(pady=5, padx=20, fill="x")

    def ask_and_add_sleep(self, builder):
        val = ctk.CTkInputDialog(text="몇 초 동안 대기할까요?", title="대기").get_input()
        if val: builder.add_sleep_action(float(val))

    def ask_and_send_input(self, builder):
        val = ctk.CTkInputDialog(text="전송할 텍스트:", title="입력").get_input()
        if val:
            self.appium_driver.switch_to.active_element.send_keys(val)
            builder.add_input_action(val)

    def run_test_thread(self):
        path = self.test_script_var.get().strip()
        if path.lower().endswith('.kt'):
            messagebox.showinfo('Kotlin 테스트 실행',
                'Kotlin 파일은 Android Studio의 src/androidTest/java/generated/recorder에 넣고 AndroidJUnitRunner로 실행하세요.\n'
                '이 화면의 직접 재생은 Python 전용입니다. 앱 시작 화면과 권한, 약관, 주소는 먼저 준비하세요.')
            return
        if not path or not self.device_info: return
        self.btn_run.configure(state="disabled")
        self.btn_rec.configure(state="disabled")
        threading.Thread(target=self.run_test, args=(path,), daemon=True).start()

    def run_test(self, path):
        """테스트 시나리오 실행 (Appium + Airtest 하이브리드)"""
        if str(path).lower().endswith('.kt'):
            self.after(0, lambda: messagebox.showinfo('Kotlin 테스트 실행',
                'Kotlin 테스트는 Android Studio의 androidTest에서 실행하세요. 직접 재생은 Python 전용입니다.'))
            return
        try:
            control_appium.get_appium_launch_command()
            udid = self.target_udid
            pkg = self.apk_path_var.get().strip()
            is_clear_data = self.test_clear_data_var.get()

            logger.info("=" * 40)
            logger.info(f"테스트 실행 시작 - {os.path.basename(path)}")
            logger.info(f"대상 패키지: {pkg} / 데이터 초기화: {is_clear_data}")
            logger.info("=" * 40)

            startup_mode = self.rec_start_mode_var.get()
            options = {'attach': startup_mode == '현재 열린 앱에 연결'}
            if startup_mode == '사전 스크립트로 실행':
                options['pre_script_path'] = self.pre_script_var.get().strip()
            elif startup_mode == 'Activity 직접 실행':
                options['launch_method'] = 'activity'
            elif startup_mode == '홈 아이콘 터치로 실행':
                options.update(launch_method='home_icon', icon_text=self.home_icon_text_var.get().strip())
            info = self.prepare_appium_session(is_clear_data, **options)

            from airtest.core.api import connect_device, G, set_current
            from airtest.core.settings import Settings as ST

            ST.FIND_TIMEOUT = 20
            ST.OPDELAY = 1.0

            # [핵심] 기존 연결 리스트를 완전히 비워 인덱스 에러 원천 차단
            G.DEVICE_LIST = []

            # JAVASCREENCAP 방식을 사용하여 Minicap 호환성 문제 해결
            uri = f"android://127.0.0.1:5037/{udid}?cap_method=JAVASCREENCAP&touch_method=MAXTOUCH&ori_method=ADBORI"
            logger.info(f"Airtest 연결 시도 (Safe Mode): {udid}")

            connect_device(uri)
            # 객체 대신 인덱스 0을 넘겨 현재 활성화된 장치를 확실히 지정
            set_current(0)

            mod_n = os.path.basename(path).replace(".py", "")
            sys.path.append(os.path.dirname(path))

            if mod_n in sys.modules:
                mod = importlib.reload(sys.modules[mod_n])
            else:
                mod = importlib.import_module(mod_n)

            if hasattr(mod, mod_n):
                logger.info(f"시나리오 실행 시작: {mod_n}")
                getattr(mod, mod_n)(info)
                logger.info("[SUCCESS] 모든 테스트 스텝을 성공적으로 완료했습니다.")
            else:
                logger.error(f"실행 실패: 스크립트 내에 {mod_n} 함수를 찾을 수 없습니다.")

        except Exception as e:
            logger.error(f"[ERROR] 실행 도중 예외 발생: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            self.close_appium_session()
            self.after(0, lambda: self.btn_run.configure(state="normal"))
            self.after(0, lambda: self.btn_rec.configure(state="normal"))

if __name__ == "__main__":
    app = AtlanRecorderGUI()
    app.mainloop()

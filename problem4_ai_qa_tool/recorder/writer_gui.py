"""Focused script-writing surface. Worker threads never access Tk variables."""
import copy
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import ImageTk

from core.control_appium import project_root
from recorder.ai_services import create_provider, SERVICE_NAMES, SERVICE_PRESETS, CUSTOM_SERVICE
from recorder.settings import SettingsStore
from recorder.writer_agent import Planner, needs_confirmation
from recorder.writer_device import WriterDevice
from recorder.writer_session import WriterSession, run_agent
from recorder.writer_usage import UsageLedger, Rates, PRESETS, PRICING_DATE, money
from recorder.model_picker import ModelPicker

BG, CARD, BORDER = '#10151e', '#192231', '#2a374a'
TEXT, MUTED, ACCENT = '#eef3fa', '#a6b5c9', '#537df7'


class ScriptWriterGUI(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode('dark')
        super().__init__()
        self.title('Android Script Studio')
        self.geometry('1220x900')
        self.minsize(1060, 800)
        self.configure(fg_color=BG)
        self.store = SettingsStore()
        self.settings = self.store.load()
        self.root_dir = project_root()
        self.preferences_path = self.root_dir / 'writer_preferences.json'
        self.preferences = {}
        if self.preferences_path.exists():
            try:
                self.preferences = json.loads(self.preferences_path.read_text(encoding='utf-8'))
                if not isinstance(self.preferences, dict):
                    self.preferences = {}
            except (OSError, ValueError):
                pass
        self.ledger = UsageLedger(self.root_dir / 'LOG' / 'writer_usage.jsonl')
        self.device, self.session = WriterDevice(), WriterSession()
        self.events, self.frames = queue.Queue(), queue.Queue(maxsize=1)
        self.closing, self.preview_stop = False, threading.Event()
        self.busy, self.connected = False, False
        self.preview_screen = self.preview_image = self.logical_size = None
        self.worker = self.preview_worker = None
        self.instruction_history = ''
        self.displayed_steps = 0
        self._build()
        self._controls()
        self.protocol('WM_DELETE_WINDOW', self._close)
        self.after(100, self._poll)
        if self.store.notice or self.ledger.notice:
            self._message(self.store.notice or self.ledger.notice)

    def label(self, parent, text, **kw):
        return ctk.CTkLabel(parent, text=text, text_color=TEXT, **kw)

    def button(self, parent, text, command, primary=False, **kw):
        return ctk.CTkButton(parent, text=text, command=command, height=34,
                             fg_color=ACCENT if primary else BORDER, hover_color='#4264b6', **kw)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(self, fg_color='transparent')
        top.grid(row=0, column=0, sticky='ew', padx=24, pady=(20, 12))
        top.grid_columnconfigure(1, weight=1)
        self.label(top, 'Android Script Studio', font=ctk.CTkFont(size=23, weight='bold')).grid(row=0, column=0)
        self.device_status = self.label(top, '휴대폰 연결 전')
        self.device_status.grid(row=0, column=1, sticky='e', padx=16)
        self.connect_button = self.button(top, '휴대폰 연결', self._connect_dialog)
        self.connect_button.grid(row=0, column=2, padx=5)
        self.config_button = self.button(top, 'AI 설정', self._settings_dialog, width=90)
        self.config_button.grid(row=0, column=3)

        goal_card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        goal_card.grid(row=1, column=0, sticky='ew', padx=24, pady=(0, 14))
        goal_card.grid_columnconfigure(1, weight=1)
        self.label(goal_card, '어떤 테스트를 만들까요?', font=ctk.CTkFont(size=15, weight='bold')).grid(row=0, column=0, padx=16, pady=14)
        self.goal = ctk.CTkEntry(goal_card, height=38, placeholder_text='예: 앱 최초 실행부터 주문 버튼이 표시되는 화면까지 이동')
        self.goal.grid(row=0, column=1, columnspan=3, sticky='ew', padx=(0,16), pady=12)
        self.label(goal_card, '도착 문구 ,  정확히 일치').grid(row=1, column=0, padx=16, pady=(0,12))
        self.arrival = ctk.CTkEntry(goal_card, placeholder_text='예: 주문하기')
        self.arrival.grid(row=1, column=1, sticky='ew', padx=(0,12), pady=(0,12))
        self.initial = ctk.CTkOptionMenu(goal_card, values=['현재 화면에서 시작', '최초 실행 화면을 직접 준비'], width=190,
                                         fg_color=BORDER, command=self._initial_changed)
        self.initial.grid(row=1, column=2, padx=(0,12), pady=(0,12))
        self.ready = ctk.CTkCheckBox(goal_card, text='시작 화면 준비 완료', width=160)
        self.ready.grid(row=1, column=3, padx=(0,16), pady=(0,12))
        self.ready.select()

        body = ctk.CTkFrame(self, fg_color='transparent')
        body.grid(row=2, column=0, sticky='nsew', padx=24)
        body.grid_columnconfigure(0, weight=0, minsize=380)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        phone = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12, width=380)
        phone.grid(row=0, column=0, sticky='nsew', padx=(0,14))
        phone.grid_columnconfigure(0, weight=1)
        phone.grid_rowconfigure(1, weight=1)
        self.label(phone, '휴대폰 화면', font=ctk.CTkFont(size=16, weight='bold')).grid(row=0, column=0, pady=12)
        self.canvas = tk.Canvas(phone, bg='#090d14', highlightthickness=0, width=350, height=440)
        self.canvas.grid(row=1, column=0, sticky='nsew', padx=14)
        self.canvas.create_text(175, 180, text='휴대폰을 연결하면 화면이 표시됩니다.\n\n요소를 누르면 동작, 검증을 기록할 수 있어요.',
                                fill=MUTED, font=('맑은 고딕', 11), justify='center')
        self.canvas.bind('<Button-1>', self._pick_element)
        self.canvas.bind('<Configure>', lambda e: self._draw_phone())
        controls = ctk.CTkFrame(phone, fg_color='transparent')
        controls.grid(row=2, column=0, pady=12)
        self.manual_buttons = []
        for text, action in [('뒤로', {'action':'back'}), ('위로 스크롤', {'action':'swipe','direction':'up'}),
                             ('아래로', {'action':'swipe','direction':'down'}), ('1초 대기', {'action':'wait','seconds':1})]:
            button = self.button(controls, text, lambda a=action: self._manual(a), width=78)
            button.pack(side='left', padx=3)
            self.manual_buttons.append(button)

        right = ctk.CTkFrame(body, fg_color='transparent')
        right.grid(row=0, column=1, sticky='nsew')
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        steps_card = ctk.CTkFrame(right, fg_color=CARD)
        steps_card.grid(row=0, column=0, sticky='nsew', pady=(0,12))
        steps_card.grid_columnconfigure(0, weight=1)
        steps_card.grid_rowconfigure(1, weight=1)
        self.steps_label = self.label(steps_card, '작성한 단계  0', font=ctk.CTkFont(size=16, weight='bold'))
        self.steps_label.grid(row=0, column=0, sticky='w', padx=16, pady=12)
        self.new_button = self.button(steps_card, '새 시나리오', self._new, width=100)
        self.new_button.grid(row=0, column=1, padx=12)
        self.steps_box = ctk.CTkTextbox(steps_card, fg_color=CARD, text_color=TEXT, height=150, wrap='word')
        self.steps_box.grid(row=1, column=0, columnspan=2, sticky='nsew', padx=10, pady=(0,12))
        self.steps_box.configure(state='disabled')

        ai_card = ctk.CTkFrame(right, fg_color=CARD)
        ai_card.grid(row=1, column=0, sticky='nsew')
        ai_card.grid_columnconfigure(0, weight=1)
        ai_card.grid_rowconfigure(1, weight=1)
        self.label(ai_card, 'AI와 함께 작성', font=ctk.CTkFont(size=16, weight='bold')).grid(row=0, column=0, sticky='w', padx=16, pady=12)
        self.chat = ctk.CTkTextbox(ai_card, fg_color=CARD, text_color=TEXT, height=150, wrap='word')
        self.chat.grid(row=1, column=0, sticky='nsew', padx=10)
        self.chat.configure(state='disabled')
        self._message('목표와 도착 문구를 입력하세요. AI가 화면을 확인하고 한 단계씩 진행합니다.\n화면의 문구, 요소 정보와 목표가 설정된 API로 전송됩니다.')
        prompt_line = ctk.CTkFrame(ai_card, fg_color='transparent')
        prompt_line.grid(row=2, column=0, sticky='ew', padx=14, pady=8)
        prompt_line.grid_columnconfigure(0, weight=1)
        self.instruction = ctk.CTkEntry(prompt_line, placeholder_text='추가 지시 ,  질문에 대한 답변 ,  테스트 입력값')
        self.instruction.grid(row=0, column=0, sticky='ew', padx=(0,8))
        self.send_button = self.button(prompt_line, '지시 반영', self._add_instruction, width=84)
        self.send_button.grid(row=0, column=1)
        action_line = ctk.CTkFrame(ai_card, fg_color='transparent')
        action_line.grid(row=3, column=0, sticky='ew', padx=14, pady=(0,12))
        self.start_button = self.button(action_line, 'AI 자동 작성', self._start, True, width=145)
        self.start_button.pack(side='left', padx=(0,8))
        self.suggest_button = self.button(action_line, '다음 동작 추천', lambda: self._start(True), width=125)
        self.suggest_button.pack(side='left', padx=(0,8))
        self.pause_button = self.button(action_line, '일시정지', self._pause, width=90)
        self.pause_button.pack(side='left')

        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.grid(row=3, column=0, sticky='ew', padx=24, pady=(12,18))
        footer.grid_columnconfigure(0, weight=1)
        self.status = self.label(footer, '준비됨', anchor='w')
        self.status.grid(row=0, column=0, sticky='w')
        self.cost = self.label(footer, '', anchor='w', font=ctk.CTkFont(size=12))
        self.cost.grid(row=1, column=0, sticky='w')
        self.button(footer, '비용 상세', self._cost_dialog, width=85).grid(row=0, column=1, rowspan=2, padx=8)
        self.language = ctk.CTkOptionMenu(footer, values=['Python', 'Kotlin'], width=100, fg_color=BORDER)
        self.language.grid(row=0, column=2, rowspan=2, padx=8)
        self.save_button = self.button(footer, '스크립트 저장', self._export, True, width=130)
        self.save_button.grid(row=0, column=3, rowspan=2)
        self._update_cost()

    def _initial_changed(self, value):
        self.ready.deselect() if value.startswith('최초') else self.ready.select()
        if value.startswith('최초'):
            self._message('휴대폰을 원하는 최초 실행 상태로 직접 준비하세요. 앱 실행부터 기록하려면 홈 화면에서 시작하세요. 데이터 초기화, 앱 실행은 자동으로 수행하지 않습니다.')

    def _append(self, box, text):
        box.configure(state='normal')
        box.insert('end', text + '\n\n')
        box.see('end')
        box.configure(state='disabled')

    def _message(self, text):
        self._append(self.chat, text)

    def _emit(self, kind, data):
        self.events.put((kind, data))

    def _job(self, function):
        if self.busy:
            return
        self.busy = True
        self._controls()
        def work():
            try:
                function()
            except ValueError as exc:
                self._emit('error', str(exc))
            except Exception:
                self._emit('error', '작업을 완료하지 못했습니다. 연결 상태와 최신 화면을 확인하고 다시 진행하세요.')
            finally:
                self._emit('idle', '')
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _controls(self):
        for widget in [self.connect_button, self.config_button, self.new_button, self.start_button,
                       self.suggest_button, self.save_button, self.goal, self.arrival, self.initial, self.ready,
                       *self.manual_buttons]:
            widget.configure(state='disabled' if self.busy else 'normal')
        self.pause_button.configure(state='normal' if self.busy and self.connected else 'disabled')
        if self.connected:
            self.connect_button.configure(state='disabled', text='연결됨')

    def _poll(self):
        if self.closing and not self.busy:
            self._finish_close()
            return
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind in {'message', 'error'}:
                    self._message(data)
                    if kind == 'error':
                        self.status.configure(text='멈춤 ,  확인 필요')
                elif kind == 'status':
                    self.status.configure(text=data[:90])
                elif kind == 'step':
                    self.displayed_steps += 1
                    self.steps_label.configure(text=f'작성한 단계  {self.displayed_steps}')
                    self._append(self.steps_box, f'{self.displayed_steps:02}  •  {data["description"]}')
                elif kind == 'connected':
                    self.connected = True
                    self.device_status.configure(text=data)
                    self._start_preview()
                elif kind == 'devices':
                    self._show_devices(data)
                elif kind == 'complete':
                    self.status.configure(text='도착 확인 완료 ,  저장할 수 있습니다')
                elif kind == 'idle':
                    self.busy = False
                    self._controls()
                    if self.session.cancel.is_set():
                        self.status.configure(text='일시정지 ,  진행 중이던 동작은 기록에 남습니다')
                    elif self.status.cget('text').endswith('…'):
                        self.status.configure(text='대기 ,  내용을 확인하고 이어서 진행하세요')
                self._update_cost()
        except queue.Empty:
            pass
        try:
            self.preview_screen, self.preview_image, self.logical_size = self.frames.get_nowait()
            self._draw_phone()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _connect_dialog(self):
        self.status.configure(text='연결 가능한 휴대폰을 찾고 있습니다…')
        self._job(lambda: self._emit('devices', WriterDevice.discover()))

    def _show_devices(self, devices):
        if not devices:
            self._message('연결 가능한 휴대폰이 없습니다. USB 디버깅을 승인하세요.')
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title('휴대폰 연결')
        dialog.geometry('460x230')
        dialog.transient(self)
        self.label(dialog, '기록할 휴대폰을 선택하세요. 현재 앱 상태를 유지합니다.').pack(pady=20)
        selected = ctk.CTkOptionMenu(dialog, values=list(devices), width=320)
        selected.pack(pady=10)
        def connect():
            device = devices[selected.get()]
            dialog.destroy()
            self.session.cancel.clear()
            self.status.configure(text='휴대폰에 연결하고 있습니다…')
            def work():
                self.device.connect(device)
                self._emit('connected', self.device.info['device_name'])
            self._job(work)
        self.button(dialog, '연결', connect, True).pack(pady=16)

    def _start_preview(self):
        def preview():
            while not self.preview_stop.is_set():
                try:
                    frame = self.device.capture()
                    try:
                        self.frames.get_nowait()
                    except queue.Empty:
                        pass
                    self.frames.put_nowait(frame)
                except Exception:
                    self._emit('status', '화면을 읽지 못했습니다. 휴대폰 연결을 확인하세요.')
                self.preview_stop.wait(1.2)
        self.preview_worker = threading.Thread(target=preview, daemon=True)
        self.preview_worker.start()

    def _draw_phone(self):
        if self.preview_image is None:
            return
        w, h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        img = self.preview_image.copy()
        img.thumbnail((w, h))
        self.phone_size = img.size
        self.phone_offset = ((w-img.width)//2, (h-img.height)//2)
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.delete('all')
        self.canvas.create_image(*self.phone_offset, anchor='nw', image=self.photo)

    def _pick_element(self, event):
        if self.busy or not self.preview_screen or not self.logical_size:
            return
        ox, oy = self.phone_offset
        pw, ph = self.phone_size
        if not (ox <= event.x <= ox+pw and oy <= event.y <= oy+ph):
            return
        screen = self.preview_screen
        key = screen.at((event.x-ox)/pw*self.logical_size[0], (event.y-oy)/ph*self.logical_size[1])
        if not key:
            self._message('이 위치에서 유일한 요소를 찾지 못했습니다. 다른 요소를 선택하세요.')
            return
        attrs = screen.elements[key]['attrs']
        dialog = ctk.CTkToplevel(self)
        dialog.title('단계 기록')
        dialog.geometry('480x320')
        dialog.transient(self)
        self.label(dialog, (attrs.get('text') or attrs.get('content-desc') or attrs.get('resource-id'))[:100],
                   wraplength=420).pack(padx=20, pady=20)
        self.label(dialog, '실제 휴대폰에서 동작한 후 단계에 추가합니다.').pack(pady=4)
        def action(kind, text=''):
            dialog.destroy()
            self._manual({'action':kind, 'target':key, 'text':text}, screen)
        self.button(dialog, '누르기', lambda: action('tap'), True).pack(pady=8)
        self.button(dialog, '표시 검증', lambda: action('assert')).pack(pady=8)
        if 'EditText' in attrs.get('class','') or attrs.get('editable') == 'true':
            value = ctk.CTkEntry(dialog, placeholder_text='추가로 입력할 문구', width=300)
            value.pack(pady=8)
            self.button(dialog, '텍스트 입력', lambda: action('input', value.get())).pack(pady=8)

    def _manual(self, action, screen=None):
        if self.busy or not self.connected:
            return
        screen = screen or self.preview_screen
        if screen is None:
            return
        if needs_confirmation(action, screen) and not messagebox.askyesno('실제 동작 확인',
                '주문, 결제, 권한, 동의와 관련된 요소입니다. 실제 휴대폰에서 이 동작을 실행할까요?', parent=self):
            return
        self.session.cancel.clear()
        self._remember_goal()
        def record(row):
            self.session.records.append(row)
            self._emit('step', row)
        def work():
            self.device.perform(action, screen, self.session.cancel, record)
            self._emit('status', '수동 단계 기록 완료')
        self._job(work)

    def _remember_goal(self):
        self.session.goal, self.session.arrival, self.session.initial = self.goal.get().strip(), self.arrival.get().strip(), self.initial.get()

    def _add_instruction(self):
        value = self.instruction.get().strip()
        if not value:
            return
        self._pause()
        self.instruction_history = (self.instruction_history + '\n' + value)[-2000:]
        self._message('사용자: ' + value + '\n진행이 멈춘 뒤 AI 자동 작성을 누르면 반영됩니다.')
        self.instruction.delete(0, 'end')

    def _planner(self):
        ai = self.settings['ai']
        provider = create_provider(service=ai['service'], base_url=ai['base_url'], model=ai['model'],
                                   api_key=self.store.api_key, timeout=ai['timeout'])
        pref = self.preferences
        rates = pref.get('rates') if (pref.get('model') == ai['model'] and pref.get('base_url') == ai['base_url']) else None
        if rates is None and ai['base_url'] == SERVICE_PRESETS['OpenAI']:
            rates = PRESETS.get(ai['model'])
        if not isinstance(rates, (list, tuple)) or len(rates) != 4:
            raise ValueError('AI 설정에서 선택한 모델의 단가를 입력하세요.')
        return Planner(provider, self.ledger, Rates(*rates), self.session.id, pref.get('budget', '0.10'))

    def _start(self, recommend_only=False):
        if self.busy:
            return
        if not self.connected:
            self._message('휴대폰을 먼저 연결하세요.')
            return
        self._remember_goal()
        if not self.session.goal or not self.session.arrival or not self.ready.get():
            self._message('목표, 도착 문구를 입력하고 시작 화면 준비를 확인하세요.')
            return
        if self.instruction.get().strip():
            self._add_instruction()
        try:
            planner = self._planner()
        except ValueError as exc:
            self._message(str(exc))
            return
        self.session.cancel.clear()
        instruction = self.instruction_history
        self._job(lambda: run_agent(self.device, self.session, planner, instruction, self._emit,
                                   recommend_only=recommend_only))

    def _pause(self):
        self.session.cancel.set()
        if self.busy:
            self.status.configure(text='멈추는 중 ,  진행 중인 요청/동작이 끝나면 멈춥니다…')

    def _new(self):
        if self.busy:
            return
        if self.session.records and not messagebox.askyesno('새 시나리오', '현재 단계를 비우고 새로 작성할까요? 저장하지 않은 단계는 사라집니다.', parent=self):
            return
        self.session = WriterSession()
        self.displayed_steps = 0
        self.instruction_history = ''
        self.steps_box.configure(state='normal')
        self.steps_box.delete('1.0','end')
        self.steps_box.configure(state='disabled')
        self.steps_label.configure(text='작성한 단계  0')
        self._message('새 시나리오를 시작했습니다. 휴대폰 화면은 현재 상태를 유지합니다.')
        self._update_cost()

    def _export(self):
        if self.busy:
            return
        name = ctk.CTkInputDialog(text='시나리오 이름 (영문, 숫자, 밑줄)', title='스크립트 저장').get_input()
        if not name:
            return
        directory = filedialog.askdirectory(parent=self, title='저장할 폴더', initialdir=str(self.root_dir / 'generated_scripts'))
        if not directory:
            return
        self._remember_goal()
        try:
            path = self.session.export(directory, name, self.language.get())
            self._message('저장 완료: ' + str(path) + ('\nKotlin은 Android Studio의 androidTest에서 실행하세요.' if self.language.get() == 'Kotlin' else ''))
        except (OSError, ValueError) as exc:
            self._message(str(exc))

    def _update_cost(self):
        total, count, unknown = self.ledger.totals(self.session.id)
        won = ''
        try:
            rate = self.preferences.get('exchange', '')
            if rate:
                won = f' ,  약 ₩{total * money(rate):,.1f}'
        except ValueError:
            pass
        self.cost.configure(text=f'이번 시나리오 추정 ${total:.6f}{won} ,  API {count}회' +
                            (f' ,  비용 미확인 {unknown}회' if unknown else ''))

    def _cost_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title('API 비용 상세')
        dialog.geometry('720x520')
        dialog.transient(self)
        box = ctk.CTkTextbox(dialog, wrap='word')
        box.pack(fill='both', expand=True, padx=18, pady=18)
        total, count, unknown = self.ledger.totals(self.session.id)
        today, calls, missing = self.ledger.totals(today=True)
        text = f'이번 시나리오: ${total:.6f} / {count}회 / 비용 미확인 {unknown}회\n오늘 이 작성기: ${today:.6f} / {calls}회 / 비용 미확인 {missing}회\n\n'
        text += 'API 반환 사용량 × 요청 시점 단가로 계산한 추정치입니다. 실제 청구액, 계정 전체 잔액은 아닙니다.\n예산은 다음 요청 전 보수적 예상으로 제한하며 공급자의 청구 한도를 보장하지 않습니다.\n입력(캐시 제외) + 캐시 읽기 + 캐시 쓰기 + 출력으로 계산합니다. 추론 토큰은 출력에 포함합니다.\n\n'
        for row in self.ledger.rows:
            if row['scenario'] == self.session.id:
                counts = row['counts']
                text += row['date'][11:19] + '  ' + row['model'] + '  ' + (f'${money(row["cost"]):.6f}' if row['cost'] is not None else '사용량 미수신') + '\n'
                text += f'  토큰: {counts}\n  USD/백만 토큰: {row["rates"]}\n'
        box.insert('1.0', text + '\n' + self.ledger.notice)
        box.configure(state='disabled')

    def _settings_dialog(self):
        if self.busy:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title('AI 연결 및 비용 설정')
        dialog.geometry('700x810')
        dialog.transient(self)
        dialog.grab_set()
        form = ctk.CTkScrollableFrame(dialog, fg_color=CARD)
        form.pack(fill='both', expand=True, padx=16, pady=16)
        form.grid_columnconfigure(1, weight=1)
        ai = self.settings['ai']
        fields = {}
        def entry(row, title, value, show=None, variable=None):
            self.label(form, title).grid(row=row, column=0, sticky='w', padx=10, pady=6)
            widget = ctk.CTkEntry(form, show=show, textvariable=variable)
            if variable is None:
                widget.insert(0, str(value))
            widget.grid(row=row, column=1, sticky='ew', padx=10, pady=6)
            return widget
        service = ctk.CTkOptionMenu(form, values=SERVICE_NAMES)
        service.set(ai['service'])
        self.label(form, 'AI 서비스').grid(row=0, column=0, padx=10, pady=8, sticky='w')
        service.grid(row=0, column=1, sticky='ew', padx=10)
        address_var = tk.StringVar(master=dialog, value=ai['base_url'])
        key_var = tk.StringVar(master=dialog, value=self.store.api_key)
        fields['base_url'] = entry(1, 'API 기본 주소', ai['base_url'], variable=address_var)
        key = entry(2, 'API Key', self.store.api_key, show='•', variable=key_var)
        self.label(form, '모델 선택').grid(row=3, column=0, sticky='w', padx=10, pady=6)
        fields['model'] = ModelPicker(form, model=ai['model'],
            provider_factory=lambda: create_provider(service=service.get(), base_url=address_var.get(),
                api_key=key_var.get(), timeout=ai['timeout'], require_model=False),
            preferred_models=lambda: list(PRESETS) if service.get() == 'OpenAI' else [],
            on_change=lambda model: preset(),
            on_status=lambda text: notice.configure(text=text),
            on_busy=lambda busy: save_button.configure(state='disabled' if busy else 'normal'))
        fields['model'].grid(row=3, column=1, sticky='ew', padx=10, pady=6)
        remember = ctk.CTkCheckBox(form, text='이 PC에 키를 암호화해 저장')
        remember.grid(row=4, column=1, sticky='w', padx=10, pady=8)
        if ai['remember_key']:
            remember.select()
        self.label(form, f'USD / 백만 토큰 ,  공식 단가 기준 {PRICING_DATE}\nStandard ,  짧은 문맥 ,  다른 모델은 직접 입력', wraplength=510).grid(row=5,column=0,columnspan=2,pady=12)
        rates = self.preferences.get('rates') if self.preferences.get('model') == ai['model'] and self.preferences.get('base_url') == ai['base_url'] else None
        rates = rates or (PRESETS.get(ai['model']) if ai['service'] == 'OpenAI' else None) or ('','','','')
        rate_fields = [entry(i+6, label, value) for i, (label, value) in enumerate(zip(['일반 입력', '캐시 읽기', '캐시 쓰기', '출력'], rates))]
        budget = entry(10, '시나리오 예산 USD', self.preferences.get('budget', '0.10'))
        exchange = entry(11, '원/USD 환율 (선택)', self.preferences.get('exchange',''))
        def preset():
            values = PRESETS.get(fields['model'].get().strip()) if service.get() == 'OpenAI' else None
            for widget, value in zip(rate_fields, values or ('','','','')):
                widget.delete(0,'end'); widget.insert(0,value)
            if values:
                notice.configure(text=f'{fields["model"].get()} ,  등록된 Standard 단가를 자동 적용했습니다.\n조회 결과가 있으면 ▼에서 다른 모델을 선택할 수 있습니다.')
            else:
                notice.configure(text='이 모델의 단가는 등록되어 있지 않습니다. 단가를 직접 입력하세요.' if fields['model'].get()
                                 else 'API Key 입력 후 [모델 목록 조회]를 누르고 모델을 선택하세요.')
        self.button(form, '등록된 공식 단가 적용', preset).grid(row=12, column=0, columnspan=2, pady=10)
        def service_changed(value):
            fields['base_url'].delete(0,'end')
            fields['base_url'].insert(0, SERVICE_PRESETS.get(value,''))
            key.delete(0,'end')
            for widget in rate_fields:
                widget.delete(0,'end')
        service.configure(command=service_changed)
        address_var.trace_add('write', lambda *_: fields['model'].invalidate(clear_model=True))
        key_var.trace_add('write', lambda *_: fields['model'].invalidate())
        notice = self.label(form, 'API Key 입력 후 [모델 목록 조회]를 누르세요.\n모델을 선택하면 등록된 단가가 자동 입력됩니다.', wraplength=590)
        notice.grid(row=13, column=0, columnspan=2, pady=10)
        def save():
            try:
                model, base = fields['model'].get().strip(), fields['base_url'].get().strip()
                provider = create_provider(service=service.get(), base_url=base, model=model, api_key=key.get(), timeout=ai['timeout'])
                values = [str(money(w.get())) for w in rate_fields]
                cap = money(budget.get())
                if cap <= 0:
                    raise ValueError('예산은 0보다 커야 합니다.')
                fx = exchange.get().strip()
                if fx and money(fx) <= 0:
                    raise ValueError('환율은 0보다 커야 합니다.')
                updated = copy.deepcopy(self.settings)
                updated['ai'].update(service=service.get(), base_url=provider.base_url, model=model,
                                     remember_key=bool(remember.get()))
                prefs = {'model':model, 'base_url':provider.base_url, 'rates':values, 'budget':str(cap), 'exchange':fx}
                temp = self.preferences_path.with_suffix('.tmp')
                temp.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding='utf-8')
                self.settings = self.store.save(updated, key.get())
                temp.replace(self.preferences_path)
                self.preferences = prefs
                dialog.destroy()
                self._message('AI 설정을 저장했습니다.')
                self._update_cost()
            except (ValueError, OSError) as exc:
                notice.configure(text=str(exc))
        save_button = self.button(form, '저장', save, True)
        save_button.grid(row=14, column=0, columnspan=2, pady=12)
        return dialog

    def _close(self):
        if self.closing:
            return
        if self.session.records and not messagebox.askyesno('종료', '스크립트를 저장했는지 확인하세요. 작성기를 종료할까요?', parent=self):
            return
        self.closing = True
        self._pause()
        self.preview_stop.set()
        self.status.configure(text='진행 중인 요청의 비용을 기록한 뒤 연결을 정리합니다…')

    def _finish_close(self):
        self.busy = True
        def finish():
            self.device.close()
            self._emit('closed', '')
        worker = threading.Thread(target=finish, daemon=True)
        worker.start()
        def wait():
            if worker.is_alive():
                self.after(100, wait)
            else:
                self.destroy()
        wait()

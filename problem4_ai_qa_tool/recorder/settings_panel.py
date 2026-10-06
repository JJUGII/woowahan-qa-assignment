"""Settings view; HTTP workers use immutable snapshots and a UI-polled queue."""
import copy
import queue
import threading
import customtkinter as ctk

from recorder.ai_recommender import RecommendationError
from recorder.ai_services import SERVICE_NAMES, SERVICE_PRESETS, CUSTOM_SERVICE, service_for_url, create_provider
from recorder.model_catalog import recorder_models, model_description
from recorder.settings import AI_MODES, START_MODES, SettingsError
from recorder.theme import BG, CARD, BORDER, TEXT, MUTED, MINT, MINT_HOVER, SOFT, FONT, TITLE


class SettingsPanel(ctk.CTkFrame):
    def __init__(self, parent, host):
        super().__init__(parent, fg_color=BG)
        self.host = host
        self.results = queue.Queue()
        self.connection_generation = 0
        self.poll_job = None
        self.model_results = queue.Queue()
        self.models_generation = 0
        self.models_poll_job = None
        self.available_models = []
        self.show_all_models = ctk.BooleanVar(value=False)
        ai, general = host.preferences['ai'], host.preferences['general']
        unfinished_custom = ai.get('service') == CUSTOM_SERVICE and not ai['base_url'].strip()
        address = ai['base_url'].strip() if unfinished_custom else (ai['base_url'].strip() or SERVICE_PRESETS['OpenAI'])
        self.base_url = ctk.StringVar(value=address)
        self.service = ctk.StringVar(value=CUSTOM_SERVICE if unfinished_custom else service_for_url(address))
        self.last_service = self.service.get()
        self.model = ctk.StringVar(value=ai['model'])
        self.api_key = ctk.StringVar(value=host.settings_store.api_key)
        self.timeout = ctk.StringVar(value=str(ai['timeout']))
        self.remember_key = ctk.BooleanVar(value=ai['remember_key'])
        self.auto_scan = ctk.BooleanVar(value=general['auto_scan'])
        self.log_size = ctk.StringVar(value=str(general['log_font_size']))
        self.query, self.result_text, self.detail = (ctk.StringVar(value='') for _ in range(3))
        self.tabs = ctk.CTkTabview(self, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        self.tabs.pack(fill='both', expand=True, pady=(0, 12))
        for name in ('AI 연결', '앱 준비', '일반'):
            self.tabs.add(name)
        self.make_ai(self.scroller('AI 연결'))
        self.make_app(self.scroller('앱 준비'))
        self.make_general(self.scroller('일반'))
        footer = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        footer.pack(fill='x')
        self.status = ctk.CTkLabel(footer, text='변경 후 저장하면 다음 실행에도 적용됩니다.',
                                   text_color=MUTED, font=FONT, wraplength=570, justify='left', anchor='w')
        self.status.pack(side='left', fill='x', expand=True, padx=20, pady=16)
        ctk.CTkButton(footer, text='설정 저장', width=140, height=42, font=TITLE,
                       command=self.save).pack(side='right', padx=18, pady=14)
        for variable in (self.base_url, self.model, self.api_key, self.timeout):
            variable.trace_add('write', self.invalidate_connection)
        for variable in (self.base_url, self.api_key, self.timeout):
            variable.trace_add('write', self.invalidate_models)
        self.base_url.trace_add('write', self.sync_service_address)
        self.model.trace_add('write', self.update_model_description)
        self.update_model_description()

    def scroller(self, tab):
        frame = ctk.CTkScrollableFrame(self.tabs.tab(tab), fg_color=CARD)
        frame.pack(fill='both', expand=True)
        return frame

    def heading(self, parent, title, description):
        ctk.CTkLabel(parent, text=title, font=TITLE, anchor='w').pack(fill='x', padx=18, pady=(18, 4))
        ctk.CTkLabel(parent, text=description, font=FONT, text_color=MUTED, justify='left',
                       anchor='w', wraplength=740).pack(fill='x', padx=18, pady=(0, 16))

    def field(self, parent, title, variable, placeholder='', show=None):
        ctk.CTkLabel(parent, text=title, anchor='w', font=FONT).pack(fill='x', padx=18, pady=(9, 5))
        entry = ctk.CTkEntry(parent, textvariable=variable, placeholder_text=placeholder,
                              font=FONT, height=38, show=show)
        entry.pack(fill='x', padx=18, pady=(0, 4))
        if placeholder:
            ctk.CTkLabel(parent, text=placeholder, font=('맑은 고딕',11), text_color=MUTED,
                           anchor='w').pack(fill='x', padx=18, pady=(0,4))
        return entry

    def make_ai(self, parent):
        self.heading(parent, 'AI 추천 연결', 'AI 서비스를 선택하고 API Key를 입력하세요. 연결 주소는 자동으로 설정됩니다.')
        row = ctk.CTkFrame(parent, fg_color='transparent')
        row.pack(fill='x', padx=18, pady=(0,14))
        self.test_button = ctk.CTkButton(row, text='AI 연결 테스트', height=38, width=160,
                                         command=self.test_connection)
        self.test_button.pack(side='left')
        self.connection_status = ctk.CTkLabel(row, text='아직 연결을 확인하지 않았습니다.', anchor='w',
                                               text_color=MUTED, font=FONT, wraplength=480)
        self.connection_status.pack(side='left', padx=14)
        ctk.CTkLabel(parent, text='추천 모드', anchor='w', font=FONT).pack(fill='x', padx=18, pady=(0, 6))
        ctk.CTkOptionMenu(parent, values=AI_MODES, variable=self.host.ai_mode_var,
                          height=38, font=FONT, command=lambda _: self.host.refresh_summary()).pack(fill='x', padx=18)
        ctk.CTkLabel(parent, text='AI 서비스', anchor='w', font=FONT).pack(fill='x', padx=18, pady=(9,5))
        ctk.CTkOptionMenu(parent, values=SERVICE_NAMES, variable=self.service, height=38, font=FONT,
                          command=self.change_service).pack(fill='x', padx=18, pady=(0,4))
        self.service_hint = ctk.CTkLabel(parent, text='', text_color=MUTED, anchor='w', font=('맑은 고딕',11))
        self.service_hint.pack(fill='x', padx=18, pady=(0,4))
        self.custom_address = ctk.CTkFrame(parent, fg_color='transparent')
        self.field(self.custom_address, 'API 기본 주소', self.base_url, '서비스의 Chat Completions 호환 기본 주소')
        self.key_row = ctk.CTkFrame(parent, fg_color='transparent')
        self.key_row.pack(fill='x')
        self.key_entry = self.field(self.key_row, 'API Key', self.api_key, '선택한 서비스에서 발급받은 키를 입력하세요.', show='•')
        self.render_service_address()
        options = ctk.CTkFrame(parent, fg_color='transparent')
        options.pack(fill='x', padx=18, pady=8)
        self.show_key = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(options, text='키 표시', variable=self.show_key, width=105, font=FONT,
                         command=lambda:self.key_entry.configure(show='' if self.show_key.get() else '•')).pack(side='left')
        ctk.CTkCheckBox(options, text='이 PC에 키 저장 (Windows 암호화)', variable=self.remember_key,
                         font=FONT).pack(side='left', padx=12)
        ctk.CTkLabel(parent, text='사용할 모델', anchor='w', font=FONT).pack(fill='x', padx=18, pady=(9,5))
        row = ctk.CTkFrame(parent, fg_color='transparent')
        row.pack(fill='x', padx=18, pady=(0,4))
        self.model_combo = ctk.CTkComboBox(row, variable=self.model, values=[], font=FONT, height=38)
        self.model_combo.pack(side='left', fill='x', expand=True, padx=(0,10))
        self.models_button = ctk.CTkButton(row, text='모델 목록 가져오기', height=38, width=160,
                                           command=self.fetch_models)
        self.models_button.pack(side='right')
        self.models_status = ctk.CTkLabel(parent, text='목록에서 선택하면 이름이 자동 입력됩니다. 직접 입력도 가능합니다.',
                                           anchor='w', justify='left', wraplength=740, text_color=MUTED,
                                           font=('맑은 고딕',11))
        self.models_status.pack(fill='x', padx=18, pady=(0,4))
        self.full_models_checkbox = ctk.CTkCheckBox(parent, text='전체 모델 보기 (고급)', variable=self.show_all_models,
                                                     font=('맑은 고딕',11), command=self.update_model_choices)
        self.full_models_checkbox.pack(anchor='w', padx=18, pady=(6,4))
        self.model_help = ctk.CTkLabel(parent, text='', anchor='w', justify='left', wraplength=740,
                                       text_color=MUTED, font=('맑은 고딕',11))
        self.model_help.pack(fill='x', padx=18, pady=(0,4))
        self.field(parent, '응답 대기 시간 (초, 5~120)', self.timeout)
        ctk.CTkLabel(parent, text='연결 테스트에는 샘플 버튼 정보만 사용합니다. 실제 앱 화면은 보내지 않습니다.\n'
                    '녹화 중에는 선택 요소의 속성과 테스트 의도를 보내며, 기대값은 직접 확인합니다.',
                    font=('맑은 고딕', 12), text_color=MUTED, anchor='w', justify='left').pack(fill='x', padx=18, pady=(8, 18))

    def make_app(self, parent):
        self.heading(parent, '앱 실행과 사전 작업', '선택한 앱별로 저장합니다. 웜 스타트는 권한, 동의, 주소 상태를 유지합니다.')
        self.app_label = ctk.CTkLabel(parent, textvariable=self.host.apk_path_var, anchor='w',
                                      font=TITLE, text_color=TEXT, fg_color=SOFT, corner_radius=8, height=42)
        self.app_label.pack(fill='x', padx=18, pady=(0, 12))
        ctk.CTkLabel(parent, text='앱 시작 방식', anchor='w', font=FONT).pack(fill='x', padx=18, pady=(4, 6))
        ctk.CTkOptionMenu(parent, values=START_MODES, variable=self.host.rec_start_mode_var, font=FONT, height=38,
                          command=self.host.on_record_start_mode_change).pack(fill='x', padx=18)
        self.field(parent, '홈 화면의 앱 아이콘 이름', self.host.home_icon_text_var)
        self.field(parent, '사전 실행 스크립트', self.host.pre_script_var)
        ctk.CTkButton(parent, text='사전 스크립트 찾기', fg_color=SOFT, hover_color=BORDER, text_color=TEXT,
                       command=self.host.browse_pre_script).pack(anchor='w', padx=18, pady=8)
        ctk.CTkSwitch(parent, text='권한, 필수 약관 사전 처리 (녹화, 재생 공통)', variable=self.host.onboarding_var,
                       font=FONT).pack(anchor='w', padx=18, pady=12)
        self.host.rec_clear_switch = ctk.CTkSwitch(parent, text='녹화 전 앱 데이터 초기화',
                                                   variable=self.host.rec_clear_data_var, font=FONT)
        self.host.rec_clear_switch.pack(anchor='w', padx=18, pady=8)
        ctk.CTkSwitch(parent, text='테스트 실행 전 앱 데이터 초기화', variable=self.host.test_clear_data_var,
                       font=FONT).pack(anchor='w', padx=18, pady=8)
        ctk.CTkLabel(parent, text='권한 사전 처리와 초기화는 함께 사용하지 않습니다.\n'
                    '약관, 주소 자동 처리는 현재 배달의민족 앱에 맞춰져 있습니다.',
                    anchor='w', justify='left', text_color=MUTED, font=('맑은 고딕', 12)).pack(fill='x', padx=18, pady=8)
        self.heading(parent, '테스트 주소', '최초 주소 설정 화면이 나타날 때만 입력합니다. 이미 설정된 주소는 유지합니다.')
        self.field(parent, '주소 검색 문구', self.query)
        self.field(parent, '검색 결과에 표시되는 정확한 문구', self.result_text)
        self.field(parent, '상세주소', self.detail)

    def make_general(self, parent):
        self.heading(parent, '기본 동작', '시작할 때의 단말 검색과 작업 기록 표시를 설정합니다.')
        ctk.CTkSwitch(parent, text='프로그램 시작 시 단말 자동 검색', variable=self.auto_scan,
                       font=FONT).pack(anchor='w', padx=18, pady=12)
        ctk.CTkLabel(parent, text='로그 글자 크기', font=FONT, anchor='w').pack(fill='x', padx=18, pady=8)
        ctk.CTkOptionMenu(parent, variable=self.log_size, values=['11','12','13','14','15'], height=38,
                          font=FONT).pack(fill='x', padx=18)
        self.heading(parent, '작업 폴더', '생성한 스크립트와 실행 로그를 바로 확인할 수 있습니다.')
        for title, folder in (('생성 스크립트 폴더 열기', 'generated_scripts'), ('실행 로그 폴더 열기', 'LOG')):
            ctk.CTkButton(parent, text=title, fg_color=SOFT, hover_color=BORDER, text_color=TEXT,
                           height=38, command=lambda f=folder:self.host.open_work_folder(f)).pack(fill='x', padx=18, pady=6)

    def load_app(self, address=None):
        address = address or {}
        for variable, key in ((self.query,'query'), (self.result_text,'result_text'), (self.detail,'detail')):
            variable.set(address.get(key, ''))

    def render_service_address(self):
        if self.service.get() == CUSTOM_SERVICE:
            self.custom_address.pack(fill='x', before=self.key_row)
            text = '기타 서비스는 기본 주소를 지정하세요. Chat Completions 호환 API를 지원합니다.'
        else:
            self.custom_address.pack_forget()
            text = '이 서비스의 공식 연결 주소를 자동으로 사용합니다. 주소 입력은 필요 없습니다.'
        self.service_hint.configure(text=text)

    def sync_service_address(self, *_):
        self.service.set(service_for_url(self.base_url.get()))
        self.last_service = self.service.get()
        self.render_service_address()

    def change_service(self, selected):
        previous = self.last_service
        if selected == previous:
            return
        # Different services must not silently receive the previous service's key.
        self.api_key.set('')
        self.model.set('')
        self.show_all_models.set(False)
        self.base_url.set(SERVICE_PRESETS.get(selected, ''))
        self.service.set(selected)
        self.last_service = selected
        self.render_service_address()
        self.invalidate_connection()
        self.invalidate_models()

    def invalidate_connection(self, *_):
        self.connection_generation += 1
        self.connection_status.configure(text='설정이 변경됐습니다. 연결을 다시 확인하세요.', text_color=MUTED)

    def ai_snapshot(self):
        try:
            timeout = int(self.timeout.get())
        except ValueError as exc:
            raise SettingsError('AI 응답 대기 시간은 5~120초의 숫자입니다.') from exc
        return {'service':self.service.get(), 'base_url':self.base_url.get().strip(), 'model':self.model.get().strip(),
                'api_key':self.api_key.get().strip(), 'timeout':timeout}

    def invalidate_models(self, *_):
        self.models_generation += 1
        self.available_models = []
        self.model_combo.configure(values=[])
        self.models_status.configure(text='주소나 키가 변경됐습니다. 모델 목록을 다시 가져오세요.', text_color=MUTED)

    def fetch_models(self):
        if self.models_button.cget('state') == 'disabled':
            return
        try:
            provider = create_provider(**self.ai_snapshot(), require_model=False)
        except (SettingsError, RecommendationError) as exc:
            self.models_status.configure(text=str(exc), text_color='#AA4C34')
            return
        self.models_button.configure(state='disabled')
        self.models_status.configure(text='사용 가능한 모델 목록을 가져오고 있습니다…', text_color=MUTED)
        generation = self.models_generation
        def worker():
            try:
                self.model_results.put((generation, True, provider.list_models()))
            except Exception as exc:
                self.model_results.put((generation, False, str(exc) if isinstance(exc, RecommendationError)
                                         else '모델 목록 처리 오류입니다.'))
        threading.Thread(target=worker, daemon=True).start()
        self.models_poll_job = self.after(100, self.poll_models)

    def poll_models(self):
        self.models_poll_job = None
        try:
            generation, success, result = self.model_results.get_nowait()
        except queue.Empty:
            self.models_poll_job = self.after(100, self.poll_models)
            return
        self.models_button.configure(state='normal')
        if generation != self.models_generation:
            self.models_status.configure(text='주소나 키가 변경됐습니다. 모델 목록을 다시 가져오세요.', text_color=MUTED)
            return
        if not success:
            self.models_status.configure(text=result, text_color='#AA4C34')
            return
        self.available_models = result
        self.update_model_choices()

    def update_model_description(self, *_):
        self.model_help.configure(text=model_description(self.service.get(), self.model.get().strip()))

    def update_model_choices(self):
        recommended_view = self.service.get() == 'OpenAI' and not self.show_all_models.get()
        choices = recorder_models(self.service.get(), self.available_models) if recommended_view else self.available_models
        self.model_combo.configure(values=choices)
        if choices and not self.model.get().strip() and (recommended_view or len(choices) == 1):
            self.model.set(choices[0])
        if recommended_view and choices:
            text = f'조회된 {len(self.available_models)}개 중 Recorder 추천 {len(choices)}개를 표시합니다. 연결 테스트 후 저장하세요.'
        elif recommended_view and self.available_models:
            text = '조회된 목록에 대표 추천 모델이 없습니다. 전체 모델 보기를 켜거나 직접 입력하세요.'
        elif self.available_models:
            text = f'전체 모델 {len(choices)}개를 표시합니다. 사용할 모델을 선택하고 연결 테스트를 진행하세요.'
        else:
            text = '모델 목록을 가져오면 Recorder 추천 모델을 표시합니다.'
        self.models_status.configure(text=text, text_color='#087A75' if choices else MUTED)
        self.update_model_description()

    def test_connection(self):
        try:
            provider = create_provider(**self.ai_snapshot())
        except (SettingsError, RecommendationError) as exc:
            self.connection_status.configure(text=str(exc), text_color='#AA4C34')
            return
        self.test_button.configure(state='disabled')
        self.connection_status.configure(text='모델 연결과 JSON 응답을 확인하고 있습니다…', text_color=MUTED)
        generation = self.connection_generation
        def worker():
            try:
                self.results.put((generation, True, provider.check_connection()))
            except Exception as exc:
                self.results.put((generation, False, str(exc) if isinstance(exc, RecommendationError) else '연결 테스트 처리 오류입니다.'))
        threading.Thread(target=worker, daemon=True).start()
        self.poll_job = self.after(100, self.poll_connection)

    def poll_connection(self):
        try:
            generation, success, text = self.results.get_nowait()
        except queue.Empty:
            self.poll_job = self.after(100, self.poll_connection)
            return
        self.test_button.configure(state='normal')
        if generation != self.connection_generation:
            self.connection_status.configure(text='설정이 변경됐습니다. 현재 설정으로 다시 테스트하세요.', text_color=MUTED)
            return
        self.connection_status.configure(text=text, text_color='#087A75' if success else '#AA4C34')

    def save(self):
        try:
            snapshot = self.ai_snapshot()
            data = copy.deepcopy(self.host.preferences)
            data['ai'] = {k:snapshot[k] for k in ('service','base_url','model','timeout')}
            data['ai'].update(remember_key=self.remember_key.get(), mode=self.host.ai_mode_var.get())
            data['general'] = {'auto_scan':self.auto_scan.get(), 'log_font_size':int(self.log_size.get())}
            if data['ai']['mode'] == AI_MODES[2]:
                create_provider(**snapshot)
            pkg = self.host.apk_path_var.get().strip()
            if pkg:
                address = {'query':self.query.get().strip(), 'result_text':self.result_text.get().strip(),
                           'detail':self.detail.get().strip()}
                data['apps'][pkg] = {'start_mode':self.host.rec_start_mode_var.get(),
                    'icon_text':self.host.home_icon_text_var.get().strip(), 'pre_script':self.host.pre_script_var.get().strip(),
                    'onboarding':self.host.onboarding_var.get(), 'record_clear':self.host.rec_clear_data_var.get(),
                    'test_clear':self.host.test_clear_data_var.get(), 'test_address':address if any(address.values()) else None}
            self.host.preferences = self.host.settings_store.save(data, snapshot['api_key'])
            self.host.log_textbox.configure(font=('Consolas', data['general']['log_font_size']))
            self.host.refresh_summary()
            self.status.configure(text='저장했습니다. 다음 녹화, 테스트와 다음 실행에 적용됩니다.', text_color='#087A75')
        except (ValueError, SettingsError, OSError) as exc:
            self.status.configure(text=str(exc), text_color='#AA4C34')

    def destroy(self):
        if self.poll_job:
            self.after_cancel(self.poll_job)
        if self.models_poll_job:
            self.after_cancel(self.models_poll_job)
        super().destroy()

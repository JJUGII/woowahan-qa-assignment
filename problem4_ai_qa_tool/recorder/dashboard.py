"""Home view focused on selecting the app, recording, and replaying."""
import customtkinter as ctk
from recorder.theme import BG, CARD, BORDER, TEXT, MUTED, MINT, MINT_HOVER, SOFT, FONT, TITLE


class Dashboard(ctk.CTkScrollableFrame):
    def __init__(self, parent, host):
        super().__init__(parent, fg_color=BG)
        self.host = host
        self.grid_columnconfigure((0,1), weight=1, uniform='actions')
        hero = ctk.CTkFrame(self, fg_color=SOFT, corner_radius=18)
        hero.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0,16))
        ctk.CTkLabel(hero, text='화면을 보며 테스트를 기록하세요', font=('맑은 고딕', 25, 'bold'),
                       anchor='w').pack(fill='x', padx=25, pady=(20,5))
        ctk.CTkLabel(hero, text='요소 선택부터 검증, 스크립트 생성까지 한곳에서.', font=FONT,
                       text_color=MUTED, anchor='w').pack(fill='x', padx=25, pady=(0,20))

        connection = self.card(1, 0, '01  단말과 대상 앱', '연결된 Android 단말에서 테스트할 앱을 선택하세요.', 2)
        row = ctk.CTkFrame(connection, fg_color=BG, corner_radius=10)
        row.pack(fill='x', padx=20, pady=(0,12))
        host.lbl_status = ctk.CTkLabel(row, textvariable=host.dev_status_var, font=FONT, text_color=MUTED, anchor='w')
        host.lbl_status.pack(side='left', padx=14, pady=12)
        ctk.CTkButton(row, text='단말 검색', width=110, height=34, font=FONT,
                       command=host.scan_device).pack(side='right', padx=12, pady=8)
        app_row = ctk.CTkFrame(connection, fg_color='transparent')
        app_row.pack(fill='x', padx=20, pady=(0,20))
        target_entry = ctk.CTkEntry(app_row, textvariable=host.apk_path_var, placeholder_text='앱을 선택하거나 패키지명을 입력하세요',
                                     font=FONT, height=38)
        target_entry.pack(side='left', fill='x', expand=True, padx=(0,8))
        target_entry.bind('<FocusOut>', lambda _: host.on_target_app_changed())
        ctk.CTkButton(app_row, text='앱 선택', width=90, height=38, command=host.show_package_selector).pack(side='left', padx=4)
        self.secondary(app_row, 'APK 찾기', lambda:host.browse_file(host.apk_path_var, [('APK Files','*.apk')]), 90).pack(side='left', padx=(4,0))

        record = self.card(2, 0, '02  스크립트 녹화', '화면의 요소를 선택해 동작과 검증을 기록합니다.')
        ctk.CTkLabel(record, text='시나리오 이름', font=FONT, anchor='w').pack(fill='x', padx=20, pady=(4,6))
        ctk.CTkEntry(record, textvariable=host.scenario_name_var, font=FONT, height=38,
                      placeholder_text='예: home_search').pack(fill='x', padx=20)
        ctk.CTkLabel(record, text='영문, 숫자, 밑줄을 사용하세요.', font=('맑은 고딕', 11),
                       text_color=MUTED, anchor='w').pack(fill='x', padx=20, pady=(4,12))
        ctk.CTkLabel(record, text='생성 언어', font=FONT, anchor='w').pack(fill='x', padx=20, pady=(0,6))
        host.language_menu = ctk.CTkOptionMenu(record, values=['Python', 'Kotlin (UIAutomator)'],
                         variable=host.script_language_var, font=FONT, height=38)
        host.language_menu.pack(fill='x', padx=20)
        ctk.CTkLabel(record, text='Kotlin: Android Studio에서 실행 ,  이미지 동작 제외',
                       font=('맑은 고딕',11), text_color=MUTED, anchor='w', wraplength=330).pack(fill='x', padx=20, pady=(4,12))
        self.record_summary = ctk.StringVar(value='')
        ctk.CTkLabel(record, textvariable=self.record_summary, font=('맑은 고딕',12), text_color=MUTED,
                       justify='left', anchor='w', height=65, wraplength=330).pack(fill='x', padx=20, pady=(0,8))
        host.btn_rec = ctk.CTkButton(record, text='녹화 시작', height=48, font=TITLE,
                                     command=host.start_recording_thread)
        host.btn_rec.pack(fill='x', padx=20, pady=(8,20))

        replay = self.card(2, 1, '03  테스트 재생', 'Python은 여기서 재생하고, Kotlin은 Android Studio에서 실행합니다.')
        ctk.CTkLabel(replay, text='테스트 스크립트', font=FONT, anchor='w').pack(fill='x', padx=20, pady=(4,6))
        row = ctk.CTkFrame(replay, fg_color='transparent')
        row.pack(fill='x', padx=20)
        ctk.CTkEntry(row, textvariable=host.test_script_var, font=FONT, height=38,
                      placeholder_text='Python 스크립트 선택').pack(side='left', fill='x', expand=True, padx=(0,7))
        self.secondary(row, '찾기', host.browse_script_file, 60).pack(side='right')
        ctk.CTkLabel(replay, text='생성한 스크립트를 선택해 재생하세요.', font=('맑은 고딕',11),
                       text_color=MUTED, anchor='w').pack(fill='x', padx=20, pady=(4,12))
        self.replay_summary = ctk.StringVar(value='')
        ctk.CTkLabel(replay, textvariable=self.replay_summary, font=('맑은 고딕',12), text_color=MUTED,
                       justify='left', anchor='w', height=65, wraplength=330).pack(fill='x', padx=20, pady=(0,8))
        host.btn_run = ctk.CTkButton(replay, text='테스트 실행', height=48, font=TITLE, fg_color=TEXT,
                                     hover_color='#245657', text_color='white', command=host.run_test_thread)
        host.btn_run.pack(fill='x', padx=20, pady=(8,20))

        log = self.card(3, 0, '작업 기록', '연결, 준비, 기록, 테스트 결과를 확인하세요.', 2)
        host.log_textbox = ctk.CTkTextbox(log, height=160, font=('Consolas',host.preferences['general']['log_font_size']),
                                          fg_color='#F8FBFB', text_color=TEXT, corner_radius=10)
        host.log_textbox.pack(fill='both', expand=True, padx=20, pady=(0,18))
        host.log_textbox.configure(state='disabled')

    def secondary(self, parent, text, command, width=110):
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=38, font=FONT,
                             fg_color=CARD, hover_color=SOFT, text_color=TEXT, border_width=1, border_color=BORDER)

    def card(self, row, col, title, description, span=1):
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        card.grid(row=row, column=col, columnspan=span, sticky='nsew', padx=(0,8) if col==0 and span==1 else (8,0) if span==1 else 0, pady=(0,16))
        ctk.CTkLabel(card, text=title, font=TITLE, anchor='w').pack(fill='x', padx=20, pady=(18,5))
        ctk.CTkLabel(card, text=description, font=('맑은 고딕',12), text_color=MUTED,
                       anchor='w', wraplength=340 if span==1 else 700, justify='left').pack(fill='x', padx=20, pady=(0,16))
        return card

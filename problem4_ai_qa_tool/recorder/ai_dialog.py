"""Compact property choices; Python owns selector validation and presence checks."""
import queue
import threading
import customtkinter as ctk
from recorder.ai_recommender import recommend, RecommendationError, selector_candidates, DemoProvider
from recorder import theme as t

PROPERTY_NAMES = {'ID': 'ID', 'ACCESSIBILITY_ID': '접근성 설명', 'XPATH': '텍스트'}
PROPERTY_REASONS = {
    'ID': '문구와 언어에 의존하지 않는 ID입니다.',
    'ACCESSIBILITY_ID': '접근성 설명으로 찾습니다. 문구 변경 영향을 받습니다.',
    'XPATH': '텍스트와 요소 종류로 찾습니다. 문구 변경 영향을 받습니다.',
}


class RecommendationDialog(ctk.CTkToplevel):
    def __init__(self, parent, provider, xml_source, element, mode, on_result):
        super().__init__(parent)
        self.title('AI Visual Test Recorder — 속성 선택')
        self.geometry('620x640')
        self.minsize(540, 480)
        self.configure(fg_color=t.BG)
        self.attributes('-topmost', True)
        self.provider, self.xml_source, self.element = provider, xml_source, element
        self.mode, self.on_result = mode, on_result
        self.candidates = selector_candidates(xml_source, element)
        self.reset_ranking()
        self.is_demo = isinstance(provider, DemoProvider)
        self.results = queue.Queue()
        self.closed, self.busy, self.poll_job = False, False, None
        self.ranking_source = '프로그램 기본 순서'
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        heading = '클릭할 요소의 속성을 선택하세요' if mode == 'CLICK' else '표시를 확인할 요소의 속성을 선택하세요'
        ctk.CTkLabel(self, text=heading, font=t.TITLE).pack(padx=20, pady=(20, 8))
        instruction = ('버튼을 누르면 현재 화면을 재검증한 뒤 클릭하고 기록합니다.' if mode == 'CLICK' else
                       '요구사항상 이 요소가 보여야 한다면 버튼을 눌러 표시 확인을 기록하세요.\n'
                       '문구가 올바른지는 이 검증으로 판단하지 않습니다.')
        ctk.CTkLabel(self, text=instruction, font=t.FONT, wraplength=560).pack(padx=20, pady=(0, 10))
        self.order_label = ctk.CTkLabel(self, text='', font=t.FONT, text_color=t.MUTED)
        self.order_label.pack(padx=20, anchor='w')
        self.choices = ctk.CTkScrollableFrame(self, fg_color='transparent')
        self.choices.pack(fill='both', expand=True, padx=14, pady=6)
        self.choice_buttons = {}
        self.status = ctk.CTkLabel(self, text='', font=t.FONT, wraplength=560, text_color=t.MUTED)
        self.status.pack(padx=20, pady=6)
        footer = ctk.CTkFrame(self, fg_color='transparent')
        footer.pack(fill='x', padx=20, pady=(4, 18))
        self.request_button = ctk.CTkButton(footer, text='데모 우선순위 보기' if self.is_demo else 'AI 우선순위 추천', command=self.request,
                                            fg_color=t.MINT, hover_color=t.MINT_HOVER, text_color=t.TEXT)
        self.request_button.pack(side='left')
        ctk.CTkButton(footer, text='취소', command=self.cancel, fg_color=t.CARD,
                      text_color=t.TEXT, border_width=1, border_color=t.BORDER).pack(side='right')
        disclosure = ('규칙 기반 데모입니다. 실제 LLM 호출이나 외부 전송은 없습니다.' if self.is_demo else
                      'AI 추천 시 선택 요소의 속성과 후보 정보를 전송합니다. 전체 XML, 스크린샷은 전송하지 않습니다.')
        ctk.CTkLabel(self, text=disclosure,
                      font=('맑은 고딕', 11), text_color=t.MUTED, wraplength=560).pack(padx=20, pady=(0, 12))
        self.render_choices()

    def reset_ranking(self):
        self.recommendation = {
            'selectors': [{'candidate_id': c.id, 'reason': PROPERTY_REASONS[c.strategy]}
                          for c in self.candidates if c.usable],
            'assertions': [], 'step_description': '',
        }
        self.ranking_source = '프로그램 기본 순서'

    def render_choices(self):
        for widget in self.choices.winfo_children():
            widget.destroy()
        self.choice_buttons = {}
        self.order_label.configure(text=self.ranking_source + ' ,  위쪽부터 추천')
        by_id = {c.id: c for c in self.candidates}
        rows = [(by_id[r['candidate_id']], r['reason']) for r in self.recommendation['selectors']]
        # AI can return a subset; retain remaining properties after its recommendations.
        included = {c.id for c, _ in rows}
        rows.extend((c, PROPERTY_REASONS[c.strategy]) for c in self.candidates if c.id not in included)
        priority = 0
        for candidate, reason in rows:
            if candidate.usable:
                priority += 1
            rank = f'{priority}순위' if candidate.usable else '사용 불가'
            value = dict(candidate.attributes).get('text', candidate.value)
            value = value.replace('\r', ' ').replace('\n', ' ')
            value = value if len(value) <= 64 else value[:61] + '…'
            label = f'{rank}  ,   {PROPERTY_NAMES[candidate.strategy]}\n{value}'
            card = ctk.CTkFrame(self.choices, fg_color=t.CARD, border_color=t.BORDER, border_width=1)
            card.pack(fill='x', pady=5)
            button = ctk.CTkButton(card, text=label, height=56, anchor='w', font=t.FONT,
                                  fg_color=t.MINT if candidate.usable and priority == 1 else t.SOFT,
                                  hover_color=t.MINT_HOVER, text_color=t.TEXT,
                                  state='normal' if candidate.usable and not self.busy else 'disabled',
                                  command=lambda cid=candidate.id: self.select(cid))
            button.pack(fill='x', padx=8, pady=(8, 2))
            self.choice_buttons[candidate.id] = button
            note = reason if candidate.usable else '중복되거나 현재 화면에서 찾을 수 없어 선택할 수 없습니다.'
            note = note.removeprefix(candidate.evidence).lstrip(' .·:')
            if len(note) > 130:
                note = note[:127] + '…'
            ctk.CTkLabel(card, text=f'{candidate.evidence} ,  {note}', font=('맑은 고딕', 11),
                         text_color=t.MUTED, wraplength=520, justify='left').pack(fill='x', padx=10, pady=(0, 8))
        if not any(c.usable for c in self.candidates):
            self.status.configure(text='유일하게 찾을 수 있는 속성이 없습니다. 취소 후 다른 요소를 선택하세요.')
            self.request_button.configure(state='disabled')

    def request(self):
        if self.closed or self.busy or not any(c.usable for c in self.candidates):
            return
        self.busy = True
        self.request_button.configure(state='disabled')
        self.render_choices()
        self.status.configure(text='규칙 기반 데모를 준비하고 있습니다…' if self.is_demo else
                              'AI가 속성 우선순위를 추천하고 있습니다…')

        def worker():
            try:
                intent = '속성 선택 버튼의 우선순위만 추천한다. ' + (
                    '선택한 요소를 클릭할 대상이다.' if self.mode == 'CLICK' else '선택한 요소의 표시 여부를 확인할 대상이다.')
                self.results.put(('ok', recommend(self.provider, self.xml_source, self.element, self.mode, intent)))
            except Exception as exc:
                self.results.put(('error', str(exc) if isinstance(exc, RecommendationError) else '추천 처리 오류입니다.'))

        threading.Thread(target=worker, daemon=True).start()
        self.poll_job = self.after(100, self.poll)

    def poll(self):
        self.poll_job = None
        if self.closed:
            return
        try:
            status, value = self.results.get_nowait()
        except queue.Empty:
            self.poll_job = self.after(100, self.poll)
            return
        self.busy = False
        self.request_button.configure(state='normal')
        if status == 'error':
            self.reset_ranking()
            self.render_choices()
            self.status.configure(text=value + ' 기본 순서에서 선택하거나 다시 추천을 요청하세요.')
            return
        self.candidates, self.recommendation = value
        self.ranking_source = self.provider.name + ' 추천 순서'
        self.render_choices()
        self.status.configure(text='추천 순서와 이유를 확인하고 속성 버튼을 선택하세요.')

    def select(self, candidate_id):
        if self.closed or self.busy:
            return
        candidate = next((c for c in self.candidates if c.id == candidate_id and c.usable), None)
        if candidate is None:
            return
        # The button explicitly confirms presence. Model assertions and descriptions are
        # not used to decide the requirement or to turn observed text into an expected value.
        label = self.element.get('content-desc') or self.element.get('text') or self.element.get('resource-id') or '선택한 요소'
        description = label[:420] + (' 요소를 클릭한다.' if self.mode == 'CLICK' else ' 요소가 표시되는지 확인한다.')
        selectors = list(self.recommendation['selectors'])
        if candidate_id not in {r['candidate_id'] for r in selectors}:
            selectors.append({'candidate_id': candidate_id, 'reason': PROPERTY_REASONS[candidate.strategy]})
        reviewed = {'selectors': selectors, 'step_description': description,
                    'assertions': ([{'kind': 'visible', 'reason': '사용자가 요구사항에 따라 요소 표시 확인을 선택했습니다.',
                                     'expected_value': None, 'requires_user_confirmation': True}]
                                   if self.mode == 'ASSERT' else [])}
        self.finish({'candidates': self.candidates, 'recommendation': reviewed,
                     'candidate_id': candidate_id, 'assertion': 'visible' if self.mode == 'ASSERT' else None,
                     'expected_value': True if self.mode == 'ASSERT' else None, 'confirmed': True,
                     'description': description, 'provider': self.ranking_source})

    def cancel(self):
        self.finish(None)

    def finish(self, result):
        if not self.closed:
            self.closed = True
            if self.poll_job is not None:
                self.after_cancel(self.poll_job)
                self.poll_job = None
            try:
                self.on_result(result)
            finally:
                self.destroy()

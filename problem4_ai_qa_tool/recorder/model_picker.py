"""Async model discovery for a settings dialog; all Tk access stays on its thread."""
import queue
import threading
import tkinter as tk
import customtkinter as ctk

from recorder.ai_recommender import RecommendationError


class ModelPicker(ctk.CTkFrame):
    def __init__(self, master, *, model, provider_factory, preferred_models, on_change, on_status, on_busy):
        super().__init__(master, fg_color='transparent')
        self.provider_factory, self.preferred_models = provider_factory, preferred_models
        self.on_change, self.on_status, self.on_busy = on_change, on_status, on_busy
        self.results = queue.Queue()
        self.generation, self.loading, self.closed, self.timer = 0, False, False, None
        self.value = tk.StringVar(master=self, value=model)
        self.grid_columnconfigure(0, weight=1)
        self.combo = ctk.CTkComboBox(self, variable=self.value, values=[model] if model else [],
                                    width=230, state='normal')
        self.combo.grid(row=0, column=0, sticky='ew', padx=(0,8))
        self.fetch_button = ctk.CTkButton(self, text='모델 목록 조회', width=120, command=self.fetch)
        self.fetch_button.grid(row=0, column=1)
        self.trace = self.value.trace_add('write', lambda *_: self.on_change(self.get()))

    def get(self):
        return self.value.get().strip()

    def set(self, model):
        self.value.set(model)

    def invalidate(self, clear_model=False):
        self.generation += 1
        self.combo.configure(values=[])
        if clear_model:
            self.set('')
        self.on_status('연결 설정이 변경되었습니다. 모델 목록을 다시 조회하세요.')

    def fetch(self):
        if self.loading or self.closed:
            return
        try:
            provider = self.provider_factory()  # Captures credentials on the Tk thread.
        except RecommendationError as exc:
            self.on_status(str(exc))
            return
        self.loading = True
        self.generation += 1
        generation = self.generation
        self.fetch_button.configure(state='disabled', text='조회 중…')
        self.on_busy(True)
        self.on_status('모델 목록을 가져오고 있습니다…')

        def work():
            try:
                result = ('models', provider.list_models())
            except RecommendationError as exc:
                result = ('error', str(exc))
            except Exception:
                # Never display exception text that could contain an API key or response body.
                result = ('error', '목록을 가져오지 못했습니다. 연결 설정을 확인하고 다시 조회하세요.')
            self.results.put((generation, *result))

        threading.Thread(target=work, daemon=True).start()
        self.timer = self.after(75, self._poll)

    def _poll(self):
        self.timer = None
        if self.closed:
            return
        try:
            generation, kind, value = self.results.get_nowait()
        except queue.Empty:
            self.timer = self.after(75, self._poll)
            return
        self.loading = False
        self.fetch_button.configure(state='normal', text='모델 목록 조회')
        self.on_busy(False)
        if generation != self.generation:
            return  # Do not apply a response for another key/service/address.
        if kind == 'error':
            self.on_status(value + '\n목록 조회를 지원하지 않는 서비스는 모델명을 직접 입력할 수 있습니다.')
            return
        preferred = [model for model in self.preferred_models() if model in value]
        available = preferred + [model for model in value if model not in preferred]
        self.combo.configure(values=available)
        self.on_status(f'{len(available)}개 모델을 가져왔습니다. 오른쪽 ▼에서 선택하세요.\n목록 포함 여부가 이 작성기의 JSON 동작 지원을 보장하지는 않습니다.')
        # Preserve an available saved/manual selection. Only auto-select a known priced model.
        if self.get() not in available:
            self.set(preferred[0] if preferred else '')
        elif not self.get():
            self.on_change('')

    def destroy(self):
        self.closed = True
        self.generation += 1
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self.value.trace_remove('write', self.trace)
        super().destroy()

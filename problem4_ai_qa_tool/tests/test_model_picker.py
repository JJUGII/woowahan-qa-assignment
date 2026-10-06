import os
import threading
import time
import unittest
from unittest.mock import Mock
import customtkinter as ctk

from recorder.ai_recommender import RecommendationError
from recorder.model_picker import ModelPicker


@unittest.skipUnless(os.name == 'nt', 'Windows Tk UI')
class ModelPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = ctk.CTk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        for timer in cls.root.tk.call('after','info'):
            cls.root.tk.call('after','cancel',timer)
        cls.root.destroy()

    def setUp(self):
        self.provider = Mock()
        self.provider.list_models.return_value = ['gpt-6-astra','gpt-6-luna','unknown']
        self.factory = Mock(return_value=self.provider)
        self.change, self.status, self.busy = Mock(), Mock(), Mock()
        self.picker = ModelPicker(self.root, model='', provider_factory=self.factory,
            preferred_models=lambda:['gpt-6-luna','gpt-6-astra'], on_change=self.change,
            on_status=self.status, on_busy=self.busy)
        self.picker.pack()

    def tearDown(self):
        if not self.picker.closed:
            self.picker.destroy()

    def complete(self):
        deadline = time.monotonic()+3
        while self.picker.loading and time.monotonic()<deadline:
            self.root.update()
            time.sleep(.02)
        self.assertFalse(self.picker.loading)

    def test_fetch_without_model_selects_available_priced_model(self):
        self.picker.fetch()
        self.complete()
        self.assertEqual(self.picker.get(),'gpt-6-luna')
        self.assertEqual(self.picker.combo.cget('values'),['gpt-6-luna','gpt-6-astra','unknown'])
        self.change.assert_called_with('gpt-6-luna')
        self.assertEqual(self.picker.fetch_button.cget('state'),'normal')

    def test_existing_model_is_preserved_and_manual_input_supported(self):
        self.picker.set('unknown')
        self.picker.fetch()
        self.complete()
        self.assertEqual(self.picker.get(),'unknown')
        self.picker.set('custom-model')
        self.change.assert_called_with('custom-model')

    def test_unpriced_list_does_not_silently_choose_an_arbitrary_model(self):
        self.provider.list_models.return_value = ['audio-model','custom-model']
        self.picker.fetch()
        self.complete()
        self.assertEqual(self.picker.get(),'')
        self.assertEqual(self.picker.combo.cget('values'),['audio-model','custom-model'])

    def test_credential_change_discards_old_response_without_duplicate_request(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.provider.list_models.side_effect = lambda: (release.wait(2) and ['gpt-6-luna'])
        self.picker.fetch()
        self.picker.fetch()
        self.assertEqual(self.factory.call_count,1)
        self.picker.invalidate(clear_model=True)
        release.set()
        self.complete()
        self.assertEqual(self.picker.get(),'')
        self.assertEqual(self.picker.combo.cget('values'),[])

    def test_error_is_redacted_and_can_retry(self):
        self.provider.list_models.side_effect = RuntimeError('secret-key-that-must-not-appear')
        self.picker.fetch()
        self.complete()
        self.assertNotIn('secret-key',str(self.status.call_args_list))
        self.provider.list_models.side_effect = None
        self.picker.fetch()
        self.complete()
        self.assertEqual(self.picker.get(),'gpt-6-luna')

    def test_missing_key_does_not_start_network_work(self):
        self.factory.side_effect = RecommendationError('API Key를 입력하세요.')
        self.picker.fetch()
        self.provider.list_models.assert_not_called()
        self.assertFalse(self.picker.loading)

    def test_close_discards_late_result(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.provider.list_models.side_effect = lambda: (release.wait(2) and ['gpt-6-luna'])
        self.picker.fetch()
        self.picker.destroy()
        before = self.status.call_count
        release.set()
        for _ in range(10):
            self.root.update()
            time.sleep(.02)
        self.assertEqual(self.status.call_count,before)
        self.change.assert_not_called()

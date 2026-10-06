"""Property UI: async ranking never performs a click or defines expected text."""
import json
from pathlib import Path
import threading
import time
import unittest
import customtkinter as ctk
from recorder.ai_dialog import RecommendationDialog
from recorder.ai_recommender import DemoProvider, confirm_step, RecommendationError
from recorder.ui_inspector import get_element_by_click

XML = (Path(__file__).parent / 'fixtures/login.xml').read_text(encoding='utf-8')


class PropertyDialogTests(unittest.TestCase):
    def setUp(self):
        self.app = ctk.CTk()
        self.app.withdraw()
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            if not dialog.closed:
                dialog.cancel()
        for job in self.app.tk.call('after', 'info'):
            self.app.after_cancel(job)
        self.app.destroy()

    def make(self, provider=None, xml=XML, mode='CLICK'):
        results = []
        element = get_element_by_click(xml, 200, 250)
        dialog = RecommendationDialog(self.app, provider or DemoProvider(), xml, element, mode, results.append)
        dialog.withdraw()
        self.dialogs.append(dialog)
        return dialog, results

    def wait(self, dialog):
        deadline = time.monotonic() + 4
        while dialog.busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.02)
        self.assertFalse(dialog.busy)

    def test_ai_reorders_buttons_but_does_not_apply_or_use_model_assertion(self):
        class Reverse(DemoProvider):
            def recommend(self, payload):
                result = json.loads(super().recommend(payload))
                result['selectors'].reverse()
                result['assertions'] = [result['assertions'][1]]  # text_equals, not visible
                result['step_description'] = '모델이 정한 텍스트가 정답이다'
                return json.dumps(result)
        dialog, results = self.make(Reverse(), mode='ASSERT')
        dialog.request()
        self.wait(dialog)
        self.assertEqual(list(dialog.choice_buttons), ['s3', 's2', 's1'])
        self.assertEqual(results, [])
        dialog.choice_buttons['s3'].invoke()
        self.assertEqual(results[0]['assertion'], 'visible')
        self.assertIs(results[0]['expected_value'], True)
        self.assertNotIn('정답', results[0]['description'])
        confirm_step(original_element=dialog.element, fresh_xml=XML, mode='ASSERT', **results[0])

    def test_missing_ai_choice_retains_other_valid_property(self):
        class Subset(DemoProvider):
            def recommend(self, payload):
                result = json.loads(super().recommend(payload))
                result['selectors'] = result['selectors'][2:]
                return json.dumps(result)
        dialog, results = self.make(Subset())
        dialog.request()
        self.wait(dialog)
        self.assertEqual(list(dialog.choice_buttons), ['s3', 's1', 's2'])
        dialog.choice_buttons['s1'].invoke()
        step = confirm_step(original_element=dialog.element, fresh_xml=XML, mode='CLICK', **results[0])
        self.assertEqual(step.strategy, 'ID')
        self.assertIsNone(step.assertion)

    def test_duplicate_property_disabled_and_direct_select_rejected(self):
        from xml.etree import ElementTree as ET
        root = ET.fromstring(XML)
        selected = get_element_by_click(XML, 200, 250)
        ET.SubElement(root, 'node', {'resource-id': selected['resource-id']})
        dialog, results = self.make(xml=ET.tostring(root, encoding='unicode'))
        self.assertEqual(dialog.choice_buttons['s1'].cget('state'), 'disabled')
        dialog.select('s1')
        self.assertEqual(results, [])
        dialog.choice_buttons['s2'].invoke()
        self.assertEqual(results[0]['candidate_id'], 's2')

    def test_invalid_ai_response_falls_back_to_local_choices(self):
        class Invalid(DemoProvider):
            def recommend(self, payload):
                return '{}'
        dialog, results = self.make(Invalid())
        dialog.request()
        self.wait(dialog)
        self.assertEqual(results, [])
        self.assertEqual(dialog.ranking_source, '프로그램 기본 순서')
        dialog.choice_buttons['s1'].invoke()
        self.assertEqual(results[0]['provider'], '프로그램 기본 순서')

    def test_cancel_pending_request_cancels_poll_and_returns_only_once(self):
        release = threading.Event()
        class Delayed(DemoProvider):
            def recommend(self, payload):
                release.wait(2)
                return super().recommend(payload)
        dialog, results = self.make(Delayed())
        try:
            dialog.request()
            dialog.select('s1')
            self.assertEqual(results, [])
            dialog.cancel()
            dialog.cancel()
            self.assertIsNone(dialog.poll_job)
            self.assertEqual(results, [None])
            release.set()
            self.app.update()
            self.assertEqual(results, [None])
        finally:
            release.set()

    def test_failed_retry_restores_default_order_reasons_and_recorded_source(self):
        class RetryFailure(DemoProvider):
            calls = 0
            def recommend(self, payload):
                self.calls += 1
                if self.calls > 1:
                    return '{}'
                result = json.loads(super().recommend(payload))
                result['selectors'].reverse()
                for row in result['selectors']:
                    row['reason'] = '이전 AI 추천 이유'
                return json.dumps(result)
        dialog, results = self.make(RetryFailure())
        dialog.request()
        self.wait(dialog)
        self.assertEqual(list(dialog.choice_buttons), ['s3', 's2', 's1'])
        dialog.request()
        self.wait(dialog)
        self.assertEqual(list(dialog.choice_buttons), ['s1', 's2', 's3'])
        self.assertEqual(dialog.ranking_source, '프로그램 기본 순서')
        self.assertTrue(all(r['reason'] != '이전 AI 추천 이유' for r in dialog.recommendation['selectors']))
        dialog.choice_buttons['s1'].invoke()
        self.assertEqual(results[0]['provider'], '프로그램 기본 순서')
        confirm_step(original_element=dialog.element, fresh_xml=XML, mode='CLICK', **results[0])

    def test_fresh_screen_is_still_required_after_one_button_choice(self):
        dialog, results = self.make()
        dialog.choice_buttons['s1'].invoke()
        with self.assertRaises(RecommendationError):
            confirm_step(original_element=dialog.element, fresh_xml='<hierarchy/>', mode='CLICK', **results[0])


if __name__ == '__main__':
    unittest.main()

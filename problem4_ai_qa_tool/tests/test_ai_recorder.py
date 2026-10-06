import ast
import base64
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET

from recorder.ai_recommender import (DemoProvider, CompatibleLLMProvider, RecommendationError,
                                     recommend, validate_response, confirm_step, verify_live_selector,
                                     selector_candidates, xpath_literal)
from recorder.code_builder import CodeBuilder
from recorder.ui_inspector import get_element_by_click, parse_bounds

XML = (Path(__file__).parent / 'fixtures' / 'login.xml').read_text(encoding='utf-8')


class Element:
    def __init__(self, text='로그인', displayed=True, enabled=True):
        self.text, self.displayed, self.enabled, self.clicks = text, displayed, enabled, 0

    def is_displayed(self):
        return self.displayed

    def is_enabled(self):
        return self.enabled

    def click(self):
        self.clicks += 1


class Driver:
    def __init__(self, elements):
        self.elements, self.lookups = elements, []
        self.page_source = XML

    def find_elements(self, by, value):
        self.lookups.append((by, value))
        return self.elements


class ImmediateWait:
    def __init__(self, driver, timeout):
        self.driver = driver

    def until(self, condition):
        result = condition(self.driver)
        if not result:
            raise AssertionError('condition failed')
        return result


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.element = get_element_by_click(XML, 200, 250)
        self.candidates, self.rec = recommend(DemoProvider(), XML, self.element, 'ASSERT', '로그인 버튼 확인')

    def step(self, **updates):
        args = dict(candidates=self.candidates, recommendation=self.rec, original_element=self.element,
                    fresh_xml=XML, candidate_id='s1', mode='ASSERT', assertion='visible',
                    expected_value=True, confirmed=True, description='로그인 버튼이 표시된다', provider='test')
        args.update(updates)
        return confirm_step(**args)

    def test_pick_preserves_accessibility_state_and_smallest_bounds(self):
        self.assertEqual(self.element['content-desc'], '로그인 시작')
        self.assertEqual(self.element['enabled'], 'true')
        self.assertIsNone(get_element_by_click(XML, 3000, 3000))
        self.assertEqual(parse_bounds('[-1,0][5,10]'), (-1, 0, 5, 10))

    def test_duplicate_ids_and_text_never_recommended(self):
        element = get_element_by_click(XML, 200, 650)
        candidates = selector_candidates(XML, element)
        self.assertTrue(all(c.match_count == 2 for c in candidates))
        with self.assertRaises(RecommendationError):
            recommend(DemoProvider(), XML, element, 'CLICK')

    def test_appium_class_tag_hierarchy_supported(self):
        tree = ET.fromstring(XML)
        for node in tree.iter('node'):
            node.tag = node.get('class')
        appium_xml = ET.tostring(tree, encoding='unicode')
        element = get_element_by_click(appium_xml, 200, 250)
        candidates, rec = recommend(DemoProvider(), appium_xml, element, 'ASSERT')
        self.assertEqual([c.match_count for c in candidates], [1, 1, 1])
        self.step(candidates=candidates, recommendation=rec, fresh_xml=appium_xml)

    def test_schema_rejects_untrusted_payloads(self):
        for raw in ['not json', '```json\n{}\n```', '[]', '{}', '{"selectors":[],"selectors":[]}']:
            with self.subTest(raw=raw), self.assertRaises(RecommendationError):
                validate_response(raw, self.candidates, 'ASSERT')
        mutations = [
            lambda r: r.update(code='import os'),
            lambda r: r['selectors'][0].update(candidate_id='invented'),
            lambda r: r['selectors'].append(r['selectors'][0]),
            lambda r: r['assertions'][0].update(expected_value='로그인'),
            lambda r: r['assertions'][0].update(requires_user_confirmation=False),
            lambda r: r['assertions'][0].update(kind='execute_code'),
            lambda r: r.update(step_description=''),
            lambda r: r.update(assertions=[]),
            lambda r: r['selectors'][0].update(candidate_id=[]),
        ]
        for mutation in mutations:
            r = json.loads(json.dumps(self.rec))
            mutation(r)
            with self.subTest(payload=r), self.assertRaises(RecommendationError):
                validate_response(json.dumps(r), self.candidates, 'ASSERT')

    def test_user_confirmation_and_expected_types(self):
        for kwargs in [dict(confirmed=False), dict(expected_value='true'), dict(expected_value=False),
                       dict(assertion='text_equals', expected_value=True), dict(mode='unknown')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(RecommendationError):
                self.step(**kwargs)
        self.assertFalse(self.step(assertion='enabled', expected_value=False).expected_value)
        self.assertEqual(self.step(assertion='text_equals', expected_value='').expected_value, '')

    def test_text_locator_cannot_be_its_own_oracle(self):
        with self.assertRaises(RecommendationError):
            self.step(candidate_id='s3', assertion='text_equals', expected_value='로그인')

    def test_stale_screen_and_new_duplicates_blocked(self):
        for fresh in [XML.replace('로그인"', '변경"'), XML.replace('enabled="true"', 'enabled="false"'),
                      XML.replace('</hierarchy>', ET.tostring(ET.fromstring(XML).find('.//node/node'), encoding='unicode') + '</hierarchy>')]:
            with self.subTest(fresh=fresh), self.assertRaises(RecommendationError):
                self.step(fresh_xml=fresh)

    def test_live_appium_count_and_clickability(self):
        step = self.step(mode='CLICK')
        for elements in [[], [Element(), Element()], [Element(enabled=False)], [Element(displayed=False)]]:
            with self.subTest(elements=elements), self.assertRaises(RecommendationError):
                verify_live_selector(Driver(elements), step)
        element = Element()
        self.assertIs(verify_live_selector(Driver([element]), step), element)

    def execute(self, step, elements):
        builder = CodeBuilder('demo')
        builder.add_confirmed_step(step)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test_demo.py'
            builder.generate_script(path)
            source = path.read_text(encoding='utf-8')
            ast.parse(source)
            sidecar = json.loads(path.with_suffix('.steps.json').read_text(encoding='utf-8'))
            self.assertEqual(sidecar['steps'][0]['expected_value'], step.expected_value)
            namespace = {}
            exec(compile(source, str(path), 'exec'), namespace)
            namespace['WebDriverWait'] = ImmediateWait
            with patch('core.control_airtest.init_airtest'):
                namespace['test_demo']({'appium_driver': Driver(elements), 'device_udid': 'fake'})
            return source

    def test_generated_templates_execute_click_visible_text_enabled(self):
        element = Element()
        self.execute(self.step(mode='CLICK'), [element])
        self.assertEqual(element.clicks, 1)
        self.execute(self.step(), [element])
        self.execute(self.step(assertion='text_equals', expected_value='로그인'), [element])
        self.execute(self.step(assertion='enabled', expected_value=False), [Element(enabled=False)])

    def test_generated_text_checks_requirement_not_observation(self):
        with self.assertRaises(AssertionError):
            self.execute(self.step(assertion='text_equals', expected_value='요구사항의 문구'), [Element()])

    def test_generated_replay_rejects_duplicate_and_missing(self):
        for elements in [[], [Element(), Element()]]:
            with self.subTest(elements=elements), self.assertRaises(AssertionError):
                self.execute(self.step(mode='CLICK'), elements)

    def test_overwriting_a_recording_does_not_keep_old_step_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test_demo.py'
            builder = CodeBuilder('demo')
            builder.add_confirmed_step(self.step())
            builder.generate_script(path)
            CodeBuilder('demo').generate_script(path)
            self.assertEqual(json.loads(path.with_suffix('.steps.json').read_text(encoding='utf-8'))['steps'], [])

    def test_quotes_newlines_and_code_in_descriptions_are_data_only(self):
        malicious = "로그인\n    raise RuntimeError('injected')"
        source = self.execute(self.step(description=malicious), [Element()])
        self.assertNotIn("\n    raise RuntimeError", source)
        builder = CodeBuilder('quotes')
        builder.add_click_action(el={'resource-id': 'app:id/quote\'"\\\n'})
        builder.add_input_action('한글\'"\\\n')
        builder.add_custom_assertion('XPATH', '//*[@text=' + xpath_literal('It\'s "OK"') + ']')
        ast.parse('\n'.join(builder.lines))
        with self.assertRaises(ValueError):
            CodeBuilder('../invalid')


class ProviderTests(unittest.TestCase):
    def test_real_local_http_contract_and_validated_response(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path, body))
                payload = json.loads(body['messages'][1]['content'])
                result = {'choices': [{'message': {'content': DemoProvider().recommend(payload)}}]}
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {'AI_RECORDER_BASE_URL': f'http://127.0.0.1:{server.server_port}/v1',
                                         'AI_RECORDER_MODEL': 'contract-fixture', 'AI_RECORDER_API_KEY': ''}):
                element = get_element_by_click(XML, 200, 250)
                _, response = recommend(CompatibleLLMProvider(), XML, element, 'CLICK', '로그인 시작')
                self.assertEqual(response['step_description'], '로그인 시작')
                self.assertEqual(seen[0][0], '/v1/chat/completions')
                self.assertEqual(seen[0][1]['response_format'], {'type': 'json_object'})
                self.assertNotIn('screenshot', seen[0][1]['messages'][1]['content'])
                self.assertNotIn('hierarchy', seen[0][1]['messages'][1]['content'])
                _, response = recommend(CompatibleLLMProvider(), XML, element, 'ASSERT', '우선순위만 추천')
                schema = json.loads(seen[-1][1]['messages'][0]['content'].split('Schema: ', 1)[1])
                self.assertEqual(schema['properties']['assertions']['minItems'], 1)
                self.assertTrue(response['assertions'])
                click_schema = json.loads(seen[0][1]['messages'][0]['content'].split('Schema: ', 1)[1])
                self.assertEqual(click_schema['properties']['assertions']['minItems'], 0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_endpoint_credentials_and_error_redaction(self):
        for url in ['', 'http://example.com/v1', 'https://secret@example.com/v1', 'https://example.com/v1?key=secret']:
            with self.subTest(url=url), patch.dict(os.environ, {'AI_RECORDER_BASE_URL': url, 'AI_RECORDER_MODEL': 'test'}):
                with self.assertRaises(RecommendationError):
                    CompatibleLLMProvider()
        with patch.dict(os.environ, {'AI_RECORDER_BASE_URL': 'https://example.com/v1', 'AI_RECORDER_MODEL': 'test'}):
            with patch('requests.post', return_value=SimpleNamespace(status_code=401, text='secret')):
                with self.assertRaises(RecommendationError) as error:
                    CompatibleLLMProvider().recommend({})
                self.assertNotIn('secret', str(error.exception))


class GuiTests(unittest.TestCase):
    def test_actual_tk_property_button_confirms_presence_without_text_oracle(self):
        from recorder.gui_manager import AtlanRecorderGUI
        from recorder.ai_dialog import RecommendationDialog
        with patch.object(AtlanRecorderGUI, 'scan_device'):
            app = AtlanRecorderGUI()
            app.withdraw()
            results = []
            dialog = RecommendationDialog(app, DemoProvider(), XML,
                                          get_element_by_click(XML, 200, 250), 'ASSERT', results.append)
            dialog.withdraw()
            try:
                self.assertEqual(results, [])
                self.assertEqual(len(dialog.choice_buttons), 3)
                dialog.choice_buttons['s1'].invoke()
                self.assertEqual(results[0]['assertion'], 'visible')
                self.assertIs(results[0]['expected_value'], True)
                self.assertEqual(results[0]['provider'], '프로그램 기본 순서')
                step = confirm_step(original_element=get_element_by_click(XML, 200, 250),
                                    fresh_xml=XML, mode='ASSERT', **results[0])
                self.assertEqual(step.assertion, 'visible')
            finally:
                if not dialog.closed:
                    dialog.cancel()
                app.destroy()

    def test_recorder_selection_review_live_click_and_save(self):
        import cv2
        import numpy as np
        from recorder.gui_manager import AtlanRecorderGUI
        element = Element()
        driver = Driver([element])
        frame = np.zeros((2400, 1080, 3), dtype=np.uint8)
        driver.get_screenshot_as_base64 = lambda: base64.b64encode(cv2.imencode('.png', frame)[1]).decode()
        mouse = []
        ticks = []

        def review(parent, provider, snapshot, el, mode, callback):
            candidates, rec = recommend(provider, snapshot, el, mode, '로그인을 시작한다')
            callback(dict(candidates=candidates, recommendation=rec, candidate_id='s1', assertion=None,
                          expected_value=None, confirmed=True, description='로그인을 시작한다', provider=provider.name))
            return SimpleNamespace(closed=True)

        def wait_key(delay):
            ticks.append(1)
            if len(ticks) == 1:
                mouse[0](cv2.EVENT_LBUTTONDOWN, 60, 75, 0, None)
                mouse[0](cv2.EVENT_LBUTTONUP, 60, 75, 0, None)
                return -1
            return ord('q')

        fake = SimpleNamespace(scenario_name_var=SimpleNamespace(get=lambda: 'integration'),
                               _ai_provider=DemoProvider(), appium_driver=driver, target_udid='fake',
                               after=lambda delay, fn: fn(), get_app_folder_name=lambda: 'demo',
                               test_script_var=SimpleNamespace(set=lambda path: None))
        with tempfile.TemporaryDirectory() as directory, patch('recorder.gui_manager.RecommendationDialog', side_effect=review), \
                patch('recorder.gui_manager.os.path.abspath', side_effect=lambda path: os.path.join(directory, path)), \
                patch('recorder.gui_manager.execute_adb_command_direct') as adb, \
                patch.object(cv2, 'namedWindow'), patch.object(cv2, 'setMouseCallback', side_effect=lambda name, cb: mouse.append(cb)), \
                patch.object(cv2, 'imshow'), patch.object(cv2, 'getWindowProperty', return_value=1), \
                patch.object(cv2, 'waitKeyEx', side_effect=wait_key), patch.object(cv2, 'resizeWindow'), patch.object(cv2, 'destroyWindow'):
            AtlanRecorderGUI.show_opencv_window(fake, {'device_resolution': {'x': 1080, 'y': 2400}})
            self.assertEqual(element.clicks, 0)
            adb.assert_called_once_with('fake', 'shell input tap 200 250')
            path = Path(directory) / 'generated_scripts' / 'demo' / 'test_integration.py'
            self.assertTrue(path.exists())
            self.assertIn('로그인을 시작한다', path.read_text(encoding='utf-8'))
            self.assertEqual(len(json.loads(path.with_suffix('.steps.json').read_text(encoding='utf-8'))['steps']), 1)

    def test_recorder_cancel_stale_and_duplicate_do_not_execute_or_record(self):
        import cv2
        import numpy as np
        from recorder.gui_manager import AtlanRecorderGUI
        for case in ['cancel', 'stale', 'duplicate', 'missing']:
            with self.subTest(case=case):
                element = Element()
                driver = Driver([element])
                frame = np.zeros((2400, 1080, 3), dtype=np.uint8)
                driver.get_screenshot_as_base64 = lambda: base64.b64encode(cv2.imencode('.png', frame)[1]).decode()
                mouse, ticks = [], []

                def review(parent, provider, snapshot, el, mode, callback):
                    if case == 'cancel':
                        callback(None)
                    else:
                        candidates, rec = recommend(provider, snapshot, el, mode)
                        if case == 'stale':
                            driver.page_source = XML.replace('로그인"', '다른 화면"')
                        elif case == 'duplicate':
                            driver.elements = [element, Element()]
                        elif case == 'missing':
                            driver.elements = []
                        callback(dict(candidates=candidates, recommendation=rec, candidate_id='s1',
                                      assertion=None, expected_value=None, confirmed=True,
                                      description='클릭', provider=provider.name))
                    return SimpleNamespace(closed=True)

                def wait_key(delay):
                    ticks.append(1)
                    if len(ticks) == 1:
                        mouse[0](cv2.EVENT_LBUTTONDOWN, 60, 75, 0, None)
                        mouse[0](cv2.EVENT_LBUTTONUP, 60, 75, 0, None)
                        return -1
                    return ord('q')

                fake = SimpleNamespace(scenario_name_var=SimpleNamespace(get=lambda: 'blocked'),
                                       _ai_provider=DemoProvider(), appium_driver=driver, target_udid='fake',
                                       after=lambda delay, fn: fn(), get_app_folder_name=lambda: 'demo',
                                       test_script_var=SimpleNamespace(set=lambda path: None))
                with tempfile.TemporaryDirectory() as directory, patch('recorder.gui_manager.RecommendationDialog', side_effect=review), \
                        patch('recorder.gui_manager.os.path.abspath', side_effect=lambda path: os.path.join(directory, path)), \
                        patch('recorder.gui_manager.execute_adb_command_direct') as adb, \
                        patch('recorder.gui_manager.messagebox.showerror') as errors, \
                        patch.object(cv2, 'namedWindow'), patch.object(cv2, 'setMouseCallback', side_effect=lambda name, cb: mouse.append(cb)), \
                        patch.object(cv2, 'imshow'), patch.object(cv2, 'getWindowProperty', return_value=1), \
                        patch.object(cv2, 'waitKeyEx', side_effect=wait_key), patch.object(cv2, 'resizeWindow'), patch.object(cv2, 'destroyWindow'):
                    AtlanRecorderGUI.show_opencv_window(fake, {'device_resolution': {'x': 1080, 'y': 2400}})
                    self.assertEqual(element.clicks, 0)
                    adb.assert_not_called()
                    path = Path(directory) / 'generated_scripts' / 'demo' / 'test_blocked.py'
                    self.assertNotIn('[STEP', path.read_text(encoding='utf-8'))
                    self.assertFalse(path.with_suffix('.steps.json').exists())
                    self.assertEqual(errors.call_count, 0 if case == 'cancel' else 1)


if __name__ == '__main__':
    unittest.main()

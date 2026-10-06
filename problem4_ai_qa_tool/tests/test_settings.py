import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, MagicMock, patch

from recorder.settings import SettingsStore, SettingsError, defaults, protect_key, unprotect_key
from recorder.ai_recommender import CompatibleLLMProvider, DemoProvider, RecommendationError
from recorder.ai_services import create_provider, SERVICE_PRESETS, CUSTOM_SERVICE
from recorder.model_catalog import recorder_models, OPENAI_RECORDER_MODELS


class SettingsTests(unittest.TestCase):
    def test_recorder_model_catalog_only_offers_discovered_representative_aliases(self):
        available = ['gpt-image-test', 'gpt-realtime-test', 'text-embedding-test', 'gpt-6-luna-snapshot',
                     'ft:gpt-4o-mini:custom', 'gpt-6.1-sol', 'gpt-6-luna', 'gpt-4o-mini', 'gpt-4.1-mini']
        self.assertEqual(recorder_models('OpenAI', available), list(OPENAI_RECORDER_MODELS))
        self.assertEqual(recorder_models('OpenAI', ['gpt-4o-mini']), ['gpt-4o-mini'])
        self.assertEqual(recorder_models('OpenAI', ['gpt-image-test']), [])
        self.assertEqual(recorder_models(CUSTOM_SERVICE, available), available)

    def test_service_presets_resolve_official_addresses_and_require_key(self):
        for service, address in SERVICE_PRESETS.items():
            with self.subTest(service=service):
                provider = create_provider(service=service, base_url='https://wrong.example.com',
                                           model='fixture', api_key='fixture-key')
                self.assertEqual(provider.base_url, address)
                self.assertIn(service, provider.name)
                with self.assertRaisesRegex(RecommendationError, 'API Key'):
                    create_provider(service=service, model='fixture', api_key='')
        provider = create_provider(service=CUSTOM_SERVICE, base_url='https://custom.example.com/v1',
                                   model='fixture', api_key='fixture-key')
        self.assertEqual(provider.base_url, 'https://custom.example.com/v1')
        with self.assertRaises(RecommendationError):
            create_provider(service='unsupported', model='fixture', api_key='fixture-key')

    def test_legacy_service_migration_preserves_destination_and_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            data = defaults()
            data['ai'].pop('service')
            data['ai']['base_url'] = 'https://custom.example.com/v1'
            data['api_key_dpapi'] = protect_key('legacy-key')
            path.write_text(json.dumps(data), encoding='utf-8')
            store = SettingsStore(path)
            ai = store.load()['ai']
            self.assertEqual(ai['service'], CUSTOM_SERVICE)
            self.assertEqual(ai['base_url'], 'https://custom.example.com/v1')
            self.assertEqual(store.api_key, 'legacy-key')

    def test_custom_unfinished_settings_are_not_changed_to_openai(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory)/'settings.json')
            data = defaults()
            data['ai'].update(service=CUSTOM_SERVICE, base_url='')
            store.save(data, 'custom-fixture-key')
            ai = store.load()['ai']
            self.assertEqual(ai['service'], CUSTOM_SERVICE)
            self.assertEqual(ai['base_url'], '')

    def model_response(self, data, status=200):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.iter_content.return_value = [json.dumps(data).encode()]
        return response

    def test_model_discovery_without_model_sends_auth_deduplicates_ids(self):
        provider = CompatibleLLMProvider('https://api.example.com/v1/', '', 'fixture-key', require_model=False)
        response = self.model_response({'data':[{'id':'b'}, {'id':'a'}, {'id':'b'}]})
        with patch('requests.get', return_value=response) as get:
            self.assertEqual(provider.list_models(), ['a','b'])
        self.assertEqual(get.call_args.args[0], 'https://api.example.com/v1/models')
        self.assertEqual(get.call_args.kwargs['headers'], {'Authorization':'Bearer fixture-key'})
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        with self.assertRaises(RecommendationError):
            CompatibleLLMProvider('http://remote.example.com/v1', '', '', require_model=False)

    def test_model_discovery_rejects_bad_empty_and_oversized_lists(self):
        provider = CompatibleLLMProvider('https://api.example.com/v1', '', '', require_model=False)
        for data in ({'data':[]}, {'data':[{'id':'bad\nname'}]}, {'data':[{}]}, {'models':[]}, ['unexpected']):
            with self.subTest(data=data), patch('requests.get', return_value=self.model_response(data)):
                with self.assertRaises(RecommendationError):
                    provider.list_models()
        response = self.model_response({})
        response.iter_content.return_value = [b'x' * (1024*1024+1)]
        with patch('requests.get', return_value=response):
            with self.assertRaisesRegex(RecommendationError, '너무 큽니다'):
                provider.list_models()

    def test_model_discovery_errors_do_not_echo_credentials_or_server_content(self):
        provider = CompatibleLLMProvider('https://api.example.com/v1', '', 'private-key', require_model=False)
        for status in (401,404,302):
            with patch('requests.get', return_value=self.model_response({'private':'server-secret'}, status)):
                with self.assertRaises(RecommendationError) as raised:
                    provider.list_models()
            self.assertIn(str(status), str(raised.exception))
            self.assertNotIn('private', str(raised.exception))
            self.assertNotIn('secret', str(raised.exception))

    def test_dpapi_roundtrip_is_not_plaintext(self):
        secret = 'fixture-key-DO-NOT-LOG'
        encrypted = protect_key(secret)
        self.assertNotIn(secret, encrypted)
        self.assertEqual(unprotect_key(encrypted), secret)

    def test_settings_save_restart_preserves_key_and_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory)/'settings.json')
            data = defaults()
            data['ai'].update(base_url='https://api.example.com/v1', model='fixture', mode='LLM (설정된 API)')
            data['general']['auto_scan'] = False
            store.save(data, 'fixture-only-key')
            text = store.path.read_text(encoding='utf-8')
            self.assertNotIn('fixture-only-key', text)
            self.assertIn('windows-dpapi-v1', text)
            restored = SettingsStore(store.path)
            self.assertEqual(restored.load()['ai']['model'], 'fixture')
            self.assertEqual(restored.api_key, 'fixture-only-key')
            self.assertFalse(restored.load()['general']['auto_scan'])

    def test_unchecked_key_storage_removes_previous_ciphertext_keeps_session_key(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory)/'settings.json')
            data = defaults()
            store.save(data, 'previous-key')
            data['ai']['remember_key'] = False
            store.save(data, 'session-only-key')
            self.assertEqual(store.api_key, 'session-only-key')
            text = store.path.read_text(encoding='utf-8')
            self.assertNotIn('api_key_dpapi', text)
            self.assertNotIn('session-only-key', text)

    def test_encrypt_failure_preserves_previous_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory)/'settings.json')
            store.save(defaults(), '')
            before = store.path.read_bytes()
            with patch('recorder.settings.protect_key', side_effect=SettingsError('cannot protect')):
                with self.assertRaises(SettingsError):
                    store.save(defaults(), 'new-key')
            self.assertEqual(store.path.read_bytes(), before)

    def test_invalid_encrypted_key_retains_nonsecret_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            data = defaults()
            data['ai']['model'] = 'keep-model'
            data['api_key_dpapi'] = 'invalid'
            path.write_text(json.dumps(data), encoding='utf-8')
            store = SettingsStore(path)
            loaded = store.load()
            self.assertEqual(loaded['ai']['model'], 'keep-model')
            self.assertEqual(store.api_key, '')
            self.assertTrue(store.notice)

    def test_corrupt_preferences_recover_without_echoing_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            path.write_text('raw-SECRET malformed', encoding='utf-8')
            store = SettingsStore(path)
            self.assertEqual(store.load()['ai']['mode'], '기존 Recorder')
            self.assertNotIn('SECRET', store.notice)

    def test_saving_does_not_serialize_extra_credential_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory)/'settings.json')
            data = defaults()
            data['api_key'] = data['ai']['api_key'] = data['general']['api_key'] = 'extra-secret'
            store.save(data, '')
            self.assertNotIn('extra-secret', store.path.read_text(encoding='utf-8'))

    def test_warm_reset_conflict_and_timeout_range_do_not_overwrite_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory)/'settings.json')
            for timeout in (0, 121, True):
                data = defaults(); data['ai']['timeout'] = timeout
                with self.assertRaises(SettingsError):
                    store.save(data, '')
            data = defaults()
            data['apps']['com.qa'] = dict(start_mode='홈 아이콘 터치로 실행', icon_text='QA', pre_script='',
                                         onboarding=True, record_clear=False, test_clear=True)
            with self.assertRaisesRegex(SettingsError, '초기화'):
                store.save(data, '')
            self.assertFalse(store.path.exists())

    def test_explicit_gui_credentials_override_environment_even_when_empty(self):
        with patch.dict(os.environ, {'AI_RECORDER_API_KEY':'env-key', 'AI_RECORDER_MODEL':'env-model'}):
            provider = CompatibleLLMProvider('https://api.example.com/v1/', 'gui-model', '')
            self.assertEqual(provider.api_key, '')
            self.assertEqual(provider.model, 'gui-model')
            self.assertEqual(provider.base_url, 'https://api.example.com/v1')

    def test_connection_check_rejects_200_non_json_recommendation(self):
        provider = CompatibleLLMProvider('https://api.example.com/v1', 'fixture', 'dummy')
        response = SimpleNamespace(status_code=200, json=lambda:{'choices':[{'message':{'content':'connected'}}]})
        with patch('requests.post', return_value=response):
            with self.assertRaises(RecommendationError):
                provider.check_connection()

    def test_auth_error_has_actionable_message_without_response_or_key(self):
        provider = CompatibleLLMProvider('https://api.example.com/v1', 'fixture', 'private-fixture-key')
        with patch('requests.post', return_value=SimpleNamespace(status_code=401, text='private-response')):
            with self.assertRaises(RecommendationError) as raised:
                provider.check_connection()
        self.assertIn('HTTP 401', str(raised.exception))
        self.assertIn('API 키', str(raised.exception))
        self.assertNotIn('private', str(raised.exception))


class SettingsGuiTests(unittest.TestCase):
    def make_app(self, directory):
        from recorder.gui_manager import AtlanRecorderGUI
        store = SettingsStore(Path(directory)/'settings.json')
        with patch('recorder.gui_manager.SettingsStore', return_value=store), patch.object(AtlanRecorderGUI, 'scan_device'):
            app = AtlanRecorderGUI()
        app.withdraw()
        return app, store

    def test_save_gui_ai_and_app_profile_reload_and_use_in_recording(self):
        from recorder.gui_manager import AtlanRecorderGUI
        with tempfile.TemporaryDirectory() as directory:
            app, store = self.make_app(directory)
            try:
                app.apk_path_var.set('com.sampleapp'); app.apply_app_launch_profile('com.sampleapp')
                panel = app.settings_panel
                panel.base_url.set('https://api.example.com/v1'); panel.model.set('gui-fixture')
                panel.api_key.set('dummy-gui-key'); app.ai_mode_var.set('LLM (설정된 API)')
                # 제출 폴더에 개인 app_launch_profiles.json이 없어도 같은 조건으로 검증한다.
                panel.query.set('QA 테스트 주소'); panel.result_text.set('QA 테스트 주소')
                panel.timeout.set('23'); panel.detail.set('2층'); panel.save()
                self.assertEqual(app.preferences['apps']['com.sampleapp']['test_address']['detail'], '2층')
                panel.detail.set('')
                app.apply_app_launch_profile('com.sampleapp')
                self.assertEqual(panel.detail.get(), '2층')
                self.assertEqual(store.api_key, 'dummy-gui-key')
                self.assertEqual(panel.key_entry.cget('show'), '•')
                restored = SettingsStore(store.path)
                self.assertEqual(restored.load()['ai']['timeout'], 23)
                app.target_udid = 'fake'
                with patch('recorder.gui_manager.control_appium.get_appium_launch_command'), \
                     patch.object(AtlanRecorderGUI, 'run_recording_guarded'):
                    app.start_recording_thread()
                self.assertEqual(app._ai_provider.model, 'gui-fixture')
                self.assertEqual(app._ai_provider.api_key, 'dummy-gui-key')
                self.assertEqual(app._ai_provider.timeout, 23)
            finally:
                app.destroy()

    def test_large_model_menu_defaults_to_four_and_full_view_does_not_request_or_save(self):
        with tempfile.TemporaryDirectory() as directory:
            app, store = self.make_app(directory)
            try:
                panel = app.settings_panel
                models = list(OPENAI_RECORDER_MODELS) + [f'other-model-{i}' for i in range(129)]
                panel.model.set('')
                panel.model_results.put((panel.models_generation, True, models))
                panel.poll_models()
                self.assertEqual(panel.model_combo.cget('values'), list(OPENAI_RECORDER_MODELS))
                self.assertEqual(panel.model.get(), 'gpt-6-luna')
                self.assertIn('133개', panel.models_status.cget('text'))
                self.assertIn('추천 4개', panel.models_status.cget('text'))
                with patch('requests.get') as get, patch('requests.post') as post:
                    panel.show_all_models.set(True); panel.update_model_choices()
                    self.assertEqual(len(panel.model_combo.cget('values')), 133)
                    panel.model.set('other-model-0')
                    panel.show_all_models.set(False); panel.update_model_choices()
                get.assert_not_called(); post.assert_not_called()
                self.assertEqual(panel.model_combo.cget('values'), list(OPENAI_RECORDER_MODELS))
                self.assertEqual(panel.model.get(), 'other-model-0')  # Keep the user's explicit choice.
                self.assertIn('추천 목록 밖', panel.model_help.cget('text'))
                self.assertFalse(store.path.exists())
                panel.api_key.set('changed-fixture')
                self.assertEqual(panel.available_models, [])
                self.assertEqual(panel.model_combo.cget('values'), [])
            finally:
                app.destroy()

    def test_no_recommended_model_does_not_invent_unavailable_id(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self.make_app(directory)
            try:
                panel = app.settings_panel
                panel.model.set('')
                panel.model_results.put((panel.models_generation, True, ['other-only']))
                panel.poll_models()
                self.assertEqual(panel.model_combo.cget('values'), [])
                self.assertEqual(panel.model.get(), '')
                self.assertIn('추천 모델이 없습니다', panel.models_status.cget('text'))
                panel.show_all_models.set(True); panel.update_model_choices()
                self.assertEqual(panel.model_combo.cget('values'), ['other-only'])
                self.assertEqual(panel.model.get(), 'other-only')
            finally:
                app.destroy()

    def test_service_switch_hides_address_and_clears_other_service_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            app, store = self.make_app(directory)
            try:
                panel = app.settings_panel
                self.assertEqual(panel.service.get(), 'OpenAI')
                self.assertEqual(panel.base_url.get(), SERVICE_PRESETS['OpenAI'])
                self.assertEqual(panel.custom_address.winfo_manager(), '')
                panel.api_key.set('openai-fixture-key'); panel.model.set('old-model')
                panel.service.set('Google Gemini'); panel.change_service('Google Gemini')
                self.assertEqual(panel.base_url.get(), SERVICE_PRESETS['Google Gemini'])
                self.assertEqual(panel.api_key.get(), '')
                self.assertEqual(panel.model.get(), '')
                panel.api_key.set('gemini-fixture-key'); panel.model.set('new-model')
                panel.save()
                self.assertEqual(store.load()['ai']['service'], 'Google Gemini')
                panel.service.set(CUSTOM_SERVICE); panel.change_service(CUSTOM_SERVICE)
                self.assertEqual(panel.custom_address.winfo_manager(), 'pack')
                self.assertEqual(panel.base_url.get(), '')
                panel.save()
                restored, _ = self.make_app(directory)
                try:
                    self.assertEqual(restored.settings_panel.service.get(), CUSTOM_SERVICE)
                    self.assertEqual(restored.settings_panel.base_url.get(), '')
                    self.assertEqual(restored.settings_panel.custom_address.winfo_manager(), 'pack')
                finally:
                    restored.destroy()
                panel.service.set('OpenAI'); panel.change_service('OpenAI')
                self.assertEqual(panel.custom_address.winfo_manager(), '')
            finally:
                app.destroy()

    def test_openai_model_lookup_uses_automatic_address_and_key(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self.make_app(directory)
            try:
                panel = app.settings_panel
                panel.api_key.set('fixture-key'); panel.model.set('')
                response = MagicMock()
                response.__enter__.return_value = response
                response.status_code = 200
                response.iter_content.return_value = [b'{"data":[{"id":"gpt-6-luna"}]}']
                with patch('requests.get', return_value=response) as get:
                    panel.fetch_models()
                    deadline = time.monotonic()+5
                    while panel.models_button.cget('state') == 'disabled' and time.monotonic()<deadline:
                        app.update(); time.sleep(.01)
                self.assertEqual(get.call_args.args[0], 'https://api.openai.com/v1/models')
                self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer fixture-key')
                self.assertEqual(panel.model.get(), 'gpt-6-luna')
                self.assertFalse(app.settings_store.path.exists())
            finally:
                app.destroy()

    def test_connection_probe_posts_synthetic_info_authorization_and_keeps_ui_responsive(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                seen.append((self.path, self.headers.get('Authorization'), None))
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'data':[{'id':'contract-fixture'}, {'id':'other-fixture'}]}).encode())
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path, self.headers.get('Authorization'), body))
                payload = json.loads(body['messages'][1]['content'])
                result = {'choices':[{'message':{'content':DemoProvider().recommend(payload)}}]}
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                app, store = self.make_app(directory)
                try:
                    panel = app.settings_panel
                    panel.base_url.set(f'http://127.0.0.1:{server.server_port}/v1')
                    panel.model.set(''); panel.api_key.set('fixture-key')
                    panel.fetch_models()
                    deadline = time.monotonic()+5
                    while panel.models_button.cget('state') == 'disabled' and time.monotonic()<deadline:
                        app.update(); time.sleep(.01)
                    self.assertEqual(panel.model_combo.cget('values'), ['contract-fixture','other-fixture'])
                    self.assertEqual(panel.model.get(), '')  # Multiple models need a user's selection.
                    self.assertEqual(seen.pop(0), ('/v1/models', 'Bearer fixture-key', None))
                    panel.model.set('contract-fixture')
                    panel.test_connection()
                    deadline = time.monotonic()+5
                    ticks = 0
                    while panel.test_button.cget('state') == 'disabled' and time.monotonic()<deadline:
                        app.update(); ticks += 1; time.sleep(.01)
                    self.assertGreater(ticks, 0)
                    self.assertIn('JSON 추천 검증 완료', panel.connection_status.cget('text'))
                    self.assertEqual(seen[0][0], '/v1/chat/completions')
                    self.assertEqual(seen[0][1], 'Bearer fixture-key')
                    message = seen[0][2]['messages'][1]['content']
                    self.assertIn('qa.recorder:id/test', message)
                    self.assertNotIn('com.sampleapp', message)
                    self.assertFalse(store.path.exists())  # Test does not secretly save credentials.
                finally:
                    app.destroy()
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=2)

    def test_stale_connection_result_does_not_validate_changed_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self.make_app(directory)
            try:
                panel = app.settings_panel
                generation = panel.connection_generation
                panel.model.set('changed')
                panel.results.put((generation, True, 'success'))
                panel.poll_connection()
                self.assertIn('다시 테스트', panel.connection_status.cget('text'))
            finally:
                app.destroy()

    def test_single_discovered_model_autoselects_but_never_replaces_user_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            app, store = self.make_app(directory)
            try:
                panel = app.settings_panel
                panel.base_url.set('https://custom.example.com/v1')
                panel.model.set('')
                panel.model_results.put((panel.models_generation, True, ['only-model']))
                panel.poll_models()
                self.assertEqual(panel.model.get(), 'only-model')
                panel.model.set('manual-model')
                panel.model_results.put((panel.models_generation, True, ['only-model']))
                panel.poll_models()
                self.assertEqual(panel.model.get(), 'manual-model')
                self.assertFalse(store.path.exists())
            finally:
                app.destroy()

    def test_changed_key_discards_old_model_list_and_clears_dropdown(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self.make_app(directory)
            try:
                panel = app.settings_panel
                old_generation = panel.models_generation
                panel.model_combo.configure(values=['old-model'])
                panel.api_key.set('changed-fixture-key')
                self.assertEqual(panel.model_combo.cget('values'), [])
                panel.model_results.put((old_generation, True, ['old-model']))
                panel.poll_models()
                self.assertEqual(panel.model_combo.cget('values'), [])
                self.assertIn('다시 가져오', panel.models_status.cget('text'))
            finally:
                app.destroy()

    def test_missing_model_does_not_launch_network_request(self):
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self.make_app(directory)
            try:
                panel = app.settings_panel
                panel.base_url.set('https://api.example.com/v1'); panel.model.set('')
                with patch('requests.post') as post:
                    panel.test_connection()
                post.assert_not_called()
                self.assertIn('모델', panel.connection_status.cget('text'))
            finally:
                app.destroy()


if __name__ == '__main__':
    unittest.main()

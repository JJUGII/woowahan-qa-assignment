import ast
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import requests

from recorder.writer_agent import Screen, Planner, validate_action, needs_confirmation
from recorder.writer_device import WriterDevice
from recorder.writer_session import WriterSession, run_agent
from recorder.writer_usage import Rates, UsageLedger, usage_counts


def xml(text='치킨', extra=''):
    return f'<hierarchy><node resource-id="qa:id/item" class="android.widget.Button" text="{text}" bounds="[0,0][100,100]" enabled="true"/>{extra}</hierarchy>'


def action(kind='tap', **kw):
    return dict(action=kind, target='e1' if kind in {'tap','input'} else '', text='', direction='', seconds=0, reason='다음 화면으로 이동합니다.', **kw)


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = UsageLedger(Path(self.temp.name)/'usage.jsonl')
        self.rates = Rates('2','0.1','2.5','10')

    def test_cache_nonadditive_and_reasoning_included(self):
        counts = usage_counts({'prompt_tokens':1000,'completion_tokens':100,
                               'prompt_tokens_details':{'cached_tokens':200,'cache_write_tokens':100},
                               'completion_tokens_details':{'reasoning_tokens':40}})
        self.assertEqual(counts, dict(input=700,cached=200,write=100,output=100))
        self.assertEqual(self.rates.cost(counts), Decimal('0.00267'))

    def test_missing_invalid_usage_is_unknown(self):
        for usage in [None,{}, {'prompt_tokens':1,'completion_tokens':True},
                      {'input_tokens':1,'output_tokens':2,'input_tokens_details':{'cached_tokens':2}}]:
            self.assertIsNone(usage_counts(usage))

    def test_persistence_scenario_and_today(self):
        self.ledger.record('one','model',self.rates,{'input_tokens':1000,'output_tokens':100},'ok')
        self.ledger.record('two','model',self.rates,None,'timeout')
        restored = UsageLedger(self.ledger.path)
        self.assertEqual(restored.totals('one'), (Decimal('.003'),1,0))
        self.assertEqual(restored.totals(today=True), (Decimal('.003'),2,1))
        self.assertNotIn('api_key', self.ledger.path.read_text())

    def test_unknown_or_insufficient_budget_blocks(self):
        with self.assertRaises(ValueError):
            self.ledger.check_budget('one','.0001',self.rates,{},1800)
        self.ledger.record('one','model',self.rates,None,'timeout')
        with self.assertRaises(ValueError):
            self.ledger.check_budget('one','100',self.rates,{},1800)

    def test_rates_reject_nan_and_negative(self):
        for value in ['NaN','Infinity','-1','']:
            with self.assertRaises(ValueError):
                Rates(value,'0','0','0')


class ScreenTests(unittest.TestCase):
    def test_duplicate_ids_choose_exact_text(self):
        screen = Screen.parse(xml(extra='<node resource-id="qa:id/item" class="android.widget.Button" text="피자" bounds="[0,110][100,200]"/>'))
        self.assertEqual(screen.elements['e1']['candidate'].strategy, 'XPATH')
        self.assertEqual(screen.at(50,150),'e2')
        self.assertEqual(screen.arrival('치킨'),'e1')
        self.assertIsNone(screen.arrival('치'))

    def test_password_not_sent(self):
        screen = Screen.parse(xml(extra='<node resource-id="qa:id/password" class="android.widget.EditText" text="secret" password="true" bounds="[0,110][100,200]"/>'))
        self.assertNotIn('secret', json.dumps(screen.summary()))

    def test_reject_unknown_target_and_code(self):
        screen = Screen.parse(xml())
        for raw in [dict(action(),target='e100'),dict(action(),code='os.system'),dict(action(),action='shell'),
                    dict(action('wait'),seconds=100),dict(action('input'),text='abc')]:
            with self.assertRaises(ValueError):
                validate_action(raw,screen)

    def test_confirmation_required_for_transactions_and_consent(self):
        for text in ['결제', '주문하기', '동의', '허용']:
            self.assertTrue(needs_confirmation(action(),Screen.parse(xml(text))))
        self.assertFalse(needs_confirmation(action(),Screen.parse(xml())))
        screen = Screen.parse(xml('확인', '<node text="결제 금액" class="android.widget.TextView" bounds="[0,100][100,200]"/>'))
        self.assertTrue(needs_confirmation(action(),screen))


class PlannerTests(unittest.TestCase):
    setUp = UsageTests.setUp
    def provider(self):
        return Mock(model='test',base_url='https://example.invalid/v1',api_key='secret-key',timeout=5)

    def response(self, content, usage):
        result = Mock(status_code=200)
        result.iter_content.return_value = [json.dumps({'usage':usage,'choices':[{'message':{'content':content}}]}).encode()]
        result.__enter__ = Mock(return_value=result)
        result.__exit__ = Mock(return_value=False)
        return result

    def test_invalid_action_still_charged(self):
        with patch('recorder.writer_agent.requests.post',return_value=self.response('{"action":"shell"}',{'prompt_tokens':1000,'completion_tokens':100})):
            with self.assertRaises(ValueError):
                Planner(self.provider(),self.ledger,self.rates,'one','1').next('goal','target','',[],Screen.parse(xml()))
        self.assertEqual(self.ledger.totals('one'),(Decimal('.003'),1,0))

    def test_budget_blocks_before_network(self):
        with patch('recorder.writer_agent.requests.post') as post:
            with self.assertRaises(ValueError):
                Planner(self.provider(),self.ledger,self.rates,'one','.00001').next('goal','target','',[],Screen.parse(xml()))
            post.assert_not_called()
        self.assertEqual(self.ledger.totals('one')[1],0)

    def test_valid_action_counts_once(self):
        with patch('recorder.writer_agent.requests.post',return_value=self.response(json.dumps(action()),{'input_tokens':1000,'output_tokens':100})) as post:
            returned = Planner(self.provider(),self.ledger,self.rates,'one','1').next('goal','target','',[],Screen.parse(xml()))
        self.assertEqual(returned['action'],'tap')
        self.assertEqual(self.ledger.totals('one')[1],1)
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertNotIn('secret-key', self.ledger.path.read_text())

    def test_timeout_is_unknown_and_blocks_following_call(self):
        planner = Planner(self.provider(),self.ledger,self.rates,'one','1')
        with patch('recorder.writer_agent.requests.post',side_effect=requests.Timeout()):
            with self.assertRaises(ValueError):
                planner.next('goal','target','',[],Screen.parse(xml()))
        self.assertEqual(self.ledger.totals('one'),(Decimal(0),1,1))
        with patch('recorder.writer_agent.requests.post') as post:
            with self.assertRaises(ValueError):
                planner.next('goal','target','',[],Screen.parse(xml()))
            post.assert_not_called()


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.session = WriterSession()
        self.session.goal = '치킨을 선택하고 주문 화면으로 간다'
        self.session.arrival = '주문하기'
        self.device, self.planner = Mock(), Mock()
        self.device.screen.return_value = Screen.parse(xml())
        self.planner.next.return_value = action()
        self.messages = []

    def emit(self, kind, data):
        self.messages.append((kind,data))

    def test_pause_discards_pending_response(self):
        def reply(*args):
            self.session.cancel.set()
            return action()
        self.planner.next.side_effect = reply
        run_agent(self.device,self.session,self.planner,'',self.emit)
        self.device.perform.assert_not_called()
        self.assertFalse(self.session.records)

    def test_arrival_assertion_without_api(self):
        self.device.screen.return_value = Screen.parse(xml('주문하기'))
        run_agent(self.device,self.session,self.planner,'',self.emit)
        self.planner.next.assert_not_called()
        self.assertEqual(self.device.perform.call_args.args[0]['action'],'assert')

    def test_manual_gate_and_recommend_only_do_not_act(self):
        self.device.screen.return_value = Screen.parse(xml('동의'))
        run_agent(self.device,self.session,self.planner,'',self.emit)
        self.device.perform.assert_not_called()
        self.device.screen.return_value = Screen.parse(xml())
        run_agent(self.device,self.session,self.planner,'',self.emit,recommend_only=True)
        self.device.perform.assert_not_called()

    def test_done_without_arrival_is_not_success(self):
        self.planner.next.return_value = action('done')
        run_agent(self.device,self.session,self.planner,'',self.emit)
        self.assertNotIn('complete',[kind for kind,_ in self.messages])

    def test_input_not_supplied_by_user_is_rejected(self):
        self.planner.next.return_value = dict(action('input'),text='invented address')
        run_agent(self.device,self.session,self.planner,'',self.emit)
        self.device.perform.assert_not_called()

    def test_unchanged_screen_stops_repeated_actions(self):
        with self.assertRaisesRegex(ValueError,'같은 화면'):
            run_agent(self.device,self.session,self.planner,'',self.emit)
        self.assertEqual(self.device.perform.call_count,3)

    def test_export_both_languages_preserves_actions(self):
        step = Screen.parse(xml()).step('e1')
        self.session.records = [{'kind':'selector','step':step,'description':'치킨 누르기'},
                                {'kind':'wait','seconds':1,'description':'1초 대기'},
                                {'kind':'input','text':'안녕 $test','description':'텍스트 입력'},
                                {'kind':'back','description':'뒤로'}]
        with tempfile.TemporaryDirectory() as directory:
            py = self.session.export(directory,'fixture','Python')
            kt = self.session.export(directory,'fixture','Kotlin')
            ast.parse(py.read_text(encoding='utf-8'))
            self.assertIn('\\$test',kt.read_text(encoding='utf-8'))
            metadata = json.loads(py.with_suffix('.scenario.json').read_text(encoding='utf-8'))
            self.assertEqual(len(metadata['steps']),4)
            with self.assertRaises(ValueError):
                self.session.export(directory,'fixture','Python')


class DeviceSafetyTests(unittest.TestCase):
    def test_existing_appium_is_not_reused_or_stopped(self):
        socket = Mock()
        socket.__enter__ = Mock(return_value=socket)
        socket.__exit__ = Mock(return_value=False)
        socket.connect_ex.return_value = 0
        with patch('recorder.writer_device.socket.socket',return_value=socket), patch('recorder.writer_device.control_appium.start_appium_server') as start:
            device = WriterDevice()
            with self.assertRaisesRegex(ValueError,'기존 Recorder'):
                device.connect(Mock())
            start.assert_not_called()
            self.assertIsNone(device.process)

    def test_stale_screen_does_not_tap(self):
        device = WriterDevice()
        device.driver = Mock(page_source=xml('changed'))
        with self.assertRaisesRegex(ValueError,'화면이 바뀌'):
            device.perform(action(),Screen.parse(xml()),threading.Event(),Mock())
        device.driver.find_elements.assert_not_called()

    def test_cancel_before_action_does_not_query_device(self):
        device = WriterDevice()
        device.driver = Mock()
        cancel = threading.Event(); cancel.set()
        self.assertFalse(device.perform(action(),Screen.parse(xml()),cancel,Mock()))
        device.driver.find_elements.assert_not_called()

    def test_input_partial_failure_preserves_completed_click(self):
        device = WriterDevice()
        device.driver = Mock(page_source=xml())
        element = Mock(id='same')
        element.is_displayed.return_value = True
        element.is_enabled.return_value = True
        element.send_keys.side_effect = RuntimeError('failed')
        device.driver.find_elements.return_value = [element]
        device.driver.switch_to.active_element = element
        rows = []
        with self.assertRaises(RuntimeError):
            device.perform(dict(action('input'),text='abc'),Screen.parse(xml()),threading.Event(),rows.append)
        self.assertEqual([r['kind'] for r in rows],['selector'])


if __name__ == '__main__':
    unittest.main()

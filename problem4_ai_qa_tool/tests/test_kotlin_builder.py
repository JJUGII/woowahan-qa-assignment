"""Kotlin export regressions: selector meaning, escaping, save and replay boundaries."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from recorder.ai_recommender import ConfirmedStep, xpath_literal
from recorder.kotlin_builder import KotlinCodeBuilder, kotlin_string, xpath_attributes


class KotlinBuilderTests(unittest.TestCase):
    def test_exact_selector_mapping_preserves_quotes_and_kotlin_interpolation(self):
        value = '후라이드 "치킨"\'s ${error("injected")}\n\\'
        xpath = "//*[@class='android.widget.TextView' and @text=" + xpath_literal(value) + ']'
        self.assertEqual(xpath_attributes(xpath), {'class': 'android.widget.TextView', 'text': value})
        b = KotlinCodeBuilder('order_flow')
        b.add_confirmed_step(ConfirmedStep('CLICK','XPATH',xpath,'클릭\n// 다음 줄',None,None,'test'))
        source = b.source()
        self.assertIn('By.clazz("android.widget.TextView").text(' + kotlin_string(value) + ')', source)
        self.assertIn('\\${error',source)
        self.assertNotIn('textContains',source)
        self.assertNotIn('\n// 다음 줄',source)

    def test_unknown_xpath_is_rejected_before_step_is_added(self):
        for xpath in ["//Button[1]", "//*[@text='x' or @text='y']", "//*[@text='x' and ]",
                      "//*[@text='x' and @text='y']", "//*[@index='1']", "//*[]"]:
            b=KotlinCodeBuilder('bad')
            with self.subTest(xpath=xpath), self.assertRaises(ValueError):
                b.add_custom_assertion('XPATH',xpath)
            self.assertEqual(b.lines,[])

    def test_supported_actions_and_requirement_assertions(self):
        b=KotlinCodeBuilder('actions', preparation={'ready':True}, app_package='com.example.qa')
        b.add_click_action({'resource-id':'qa:id/button'})
        b.add_click_action({'content-desc':'버튼'})
        b.add_click_action({'class':'android.widget.TextView','text':'치킨','package':'qa'})
        b.add_custom_assertion('XPATH',"//*[@text='접수 대기']")
        b.add_confirmed_step(ConfirmedStep('ASSERT','ID','qa:id/title','문구','text_equals','요구 문구','test'))
        b.add_confirmed_step(ConfirmedStep('ASSERT','ID','qa:id/pay','비활성','enabled',False,'test'))
        b.add_input_action('한글 $100\n"입력"')
        b.add_sleep_action(1.25)
        b.add_back_action()
        b.add_swipe_action(100,900,100,300,400)
        source=b.source()
        for fragment in ['By.res("qa:id/button")','By.desc("버튼")','it.text == "요구 문구"',
                         'it.isEnabled == false','Thread.sleep(1250L)','device.pressBack()',
                         'device.swipe(100, 900, 100, 300, 80)','By.focused(true)',
                         'matches.size <= 1','Until.findObject(selector)',
                         'Python preparation is not embedded','By.pkg("com.example.qa")']:
            self.assertIn(fragment,source)
        self.assertNotIn('force-stop',source)

    def test_missing_or_duplicate_elements_cannot_be_silent_success(self):
        b=KotlinCodeBuilder('visible')
        b.add_custom_assertion('ID','qa:id/result')
        source=b.source()
        self.assertIn('matches.size <= 1',source)
        self.assertIn('matches.singleOrNull()',source)
        self.assertIn('throw AssertionError',source)
        self.assertNotIn('?.click()',source)

    def test_image_actions_are_rejected_without_partial_code(self):
        b=KotlinCodeBuilder('image')
        for operation in [lambda:b.add_click_action(img_name='crop.png'),
                          lambda:b.add_assertion_action(img_name='crop.png')]:
            with self.assertRaises(ValueError):operation()
        self.assertEqual(b.lines,[])

    def test_invalid_expected_values_and_waits_are_rejected(self):
        b=KotlinCodeBuilder('invalid')
        for kind,value in [('visible',False),('enabled','false'),('text_equals',None)]:
            with self.assertRaises(ValueError):
                b.add_confirmed_step(ConfirmedStep('ASSERT','ID','qa:id/x','검증',kind,value,'test'))
        for seconds in [float('nan'),float('inf'),-1,'5']:
            with self.assertRaises(ValueError):b.add_sleep_action(seconds)
        self.assertEqual(b.lines,[])

    def test_save_preserves_python_and_refreshes_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            py=root/'test_export.py';py.write_text('# existing Python')
            b=KotlinCodeBuilder('export')
            b.add_confirmed_step(ConfirmedStep('ASSERT','ID','qa:id/x','표시','visible',True,'test'))
            kt=root/b.filename;b.generate_script(kt)
            self.assertIn('@Test',kt.read_text(encoding='utf-8'))
            self.assertEqual(len(json.loads(kt.with_suffix('.steps.json').read_text(encoding='utf-8'))['steps']),1)
            KotlinCodeBuilder('export').generate_script(kt)
            self.assertEqual(json.loads(kt.with_suffix('.steps.json').read_text(encoding='utf-8'))['steps'],[])
            with self.assertRaises(ValueError):b.generate_script(py)
            self.assertEqual(py.read_text(),'# existing Python')

    def test_kotlin_replay_is_blocked_before_device_or_runtime_access(self):
        from recorder.gui_manager import AtlanRecorderGUI
        host=SimpleNamespace(test_script_var=SimpleNamespace(get=lambda:'Recorded_demoTest.kt'),
                             after=lambda delay,fn:fn())
        with patch('recorder.gui_manager.messagebox.showinfo') as message, \
             patch('recorder.gui_manager.control_appium.get_appium_launch_command') as runtime:
            AtlanRecorderGUI.run_test_thread(host)
            AtlanRecorderGUI.run_test(host,'Recorded_demoTest.kt')
        self.assertEqual(message.call_count,2)
        runtime.assert_not_called()

    def test_home_language_selection_is_captured_before_recording_thread(self):
        from recorder.gui_manager import AtlanRecorderGUI
        from recorder.settings import SettingsStore
        with tempfile.TemporaryDirectory() as directory:
            store=SettingsStore(Path(directory)/'settings.json')
            with patch('recorder.gui_manager.SettingsStore',return_value=store), \
                 patch.object(AtlanRecorderGUI,'scan_device'), \
                 patch.object(AtlanRecorderGUI,'load_device_config',return_value={}):
                app=AtlanRecorderGUI()
            try:
                app.withdraw()
                self.assertEqual(app.script_language_var.get(),'Python')
                app.script_language_var.set('Kotlin (UIAutomator)')
                app.target_udid='fixture'
                app.ai_mode_var.set('기존 Recorder')
                with patch('recorder.gui_manager.control_appium.get_appium_launch_command'), \
                     patch('recorder.gui_manager.threading.Thread') as thread:
                    app.start_recording_thread()
                thread.return_value.start.assert_called_once()
                self.assertEqual(app._record_language,'Kotlin (UIAutomator)')
                self.assertEqual(app.language_menu.cget('state'),'disabled')
                app.script_language_var.set('Python')
                self.assertEqual(app._record_language,'Kotlin (UIAutomator)')
            finally:
                app.destroy()


if __name__ == '__main__':
    unittest.main()

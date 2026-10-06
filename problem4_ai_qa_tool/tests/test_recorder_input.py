import base64
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from recorder.viewport import RecorderViewport, recorder_shortcut
from recorder.window_keys import mode_from_message
from recorder.ui_inspector import get_element_by_click


class ViewportTests(unittest.TestCase):
    def test_portrait_scaled_screenshot_and_panel_boundaries(self):
        view = RecorderViewport.create(540, 1200, 1080, 2400)
        self.assertEqual((view.width, view.height), (324,720))
        self.assertEqual(view.point(60,75), (200,250))
        self.assertEqual(view.point(60,75,image=True), (100,125))
        for point in [(-1,75), (60,-1), (324,75), (60,720), (600,75)]:
            self.assertIsNone(view.point(*point))

    def test_rotated_screen_maps_to_current_orientation(self):
        view = RecorderViewport.create(2400,1080,1080,2400)
        self.assertEqual((view.device_width,view.device_height), (2400,1080))
        self.assertEqual((view.width,view.height), (840,378))
        self.assertEqual(view.point(420,189), (1200,540))

    def test_shared_xml_edges_select_only_the_node_under_the_point(self):
        xml = '<hierarchy><node text="left" bounds="[0,0][100,100]"/><node text="right" bounds="[100,0][200,100]"/></hierarchy>'
        self.assertEqual(get_element_by_click(xml,100,50)['text'], 'right')
        self.assertIsNone(get_element_by_click(xml,200,50))

    def test_unicode_capitals_and_extended_keys(self):
        for keys, action in [('aAㅁ','ASSERT'), ('cCㅊ','CLICK'), ('qQㅂ','SAVE'), ('iIㅑ','INPUT'), ('tTㅅ','SLEEP'), ('bBㅠ','BACK')]:
            for key in keys:
                self.assertEqual(recorder_shortcut(ord(key)), action)
        for key in (-1, 0x260000, 0x250000, ord('x')):
            self.assertIsNone(recorder_shortcut(key))
        self.assertEqual(recorder_shortcut(27), 'BACK')

    def test_windows_ime_and_english_messages_use_the_same_physical_mode_keys(self):
        for message in (0x0100,0x0290):
            self.assertEqual(mode_from_message(message,0x1E << 16), 'ASSERT')
            self.assertEqual(mode_from_message(message,0x2E << 16), 'CLICK')
            self.assertIsNone(mode_from_message(message,0x1E << 16,modified=True))
            self.assertIsNone(mode_from_message(message,(0x1E << 16) | (1 << 30)))
        self.assertIsNone(mode_from_message(0x0102,0x1E << 16))


class RecorderInputIntegrationTests(unittest.TestCase):
    def run_recorder(self, frame, xml, events, language='Python'):
        from recorder.gui_manager import AtlanRecorderGUI
        encoded = base64.b64encode(cv2.imencode('.png',frame)[1]).decode()
        mouse, calls, assertions, crops = [], [], [], []
        driver = SimpleNamespace(page_source=xml,get_screenshot_as_base64=lambda:encoded)
        def assertion(el,builder,state):
            assertions.append(el)
            builder.add_custom_assertion('ID',el['resource-id'])
            state['mode']='CLICK'
        host = SimpleNamespace(scenario_name_var=SimpleNamespace(get=lambda:'input_fixture'),
                    _record_language=language,
                    _ai_provider=None,appium_driver=driver,target_udid='fake',after=lambda delay,fn:fn(),
                    get_app_folder_name=lambda:'input_fixture',test_script_var=SimpleNamespace(set=lambda path:None),
                    show_assert_attribute_selector=assertion)
        host.auto_capture_crop=lambda x,y,st:AtlanRecorderGUI.auto_capture_crop(host,x,y,st)
        events = iter(events)
        def wait(_):
            key, operations = next(events)
            for event,x,y in operations:
                mouse[0](event,x,y,0,None)
            return key
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            (Path(directory)/'generated_scripts/input_fixture').mkdir(parents=True)
            stack.enter_context(patch('recorder.gui_manager.os.path.abspath',side_effect=lambda p:str(Path(directory)/p)))
            stack.enter_context(patch('recorder.gui_manager.os.makedirs'))
            stack.enter_context(patch('recorder.gui_manager.execute_adb_command_direct',side_effect=lambda udid,cmd:calls.append(cmd)))
            stack.enter_context(patch('recorder.gui_manager.messagebox.showinfo'))
            stack.enter_context(patch('recorder.gui_manager.WindowModeKeys',return_value=SimpleNamespace(take=lambda:None,close=lambda:None)))
            for name in ('namedWindow','resizeWindow','imshow','destroyWindow'):
                stack.enter_context(patch.object(cv2,name))
            stack.enter_context(patch.object(cv2,'setMouseCallback',side_effect=lambda name,cb:mouse.append(cb)))
            stack.enter_context(patch.object(cv2,'getWindowProperty',return_value=1))
            stack.enter_context(patch.object(cv2,'waitKeyEx',side_effect=wait))
            stack.enter_context(patch.object(cv2,'imwrite',side_effect=lambda path,img:crops.append(img.copy()) or True))
            AtlanRecorderGUI.show_opencv_window(host,{'device_resolution':{'x':1080,'y':2400}})
            filename = 'Recorded_input_fixtureTest.kt' if language == 'Kotlin (UIAutomator)' else 'test_input_fixture.py'
            script=(Path(directory)/'generated_scripts/input_fixture'/filename).read_text(encoding='utf-8')
        return calls,assertions,crops,script

    def click(self,x,y):
        return [(cv2.EVENT_LBUTTONDOWN,x,y),(cv2.EVENT_LBUTTONUP,x,y)]

    def test_tap_and_swipe_use_device_space_with_downscaled_screenshot(self):
        frame=np.zeros((1200,540,3),dtype=np.uint8)
        xml='<hierarchy><node resource-id="qa:id/button" bounds="[100,200][600,320]"/></hierarchy>'
        calls,_,_,script=self.run_recorder(frame,xml,[(-1,self.click(60,75)),
            (-1,[(cv2.EVENT_LBUTTONDOWN,60,300),(cv2.EVENT_LBUTTONUP,60,150)]),
            (-1,self.click(400,75)),(ord('q'),[])])
        self.assertEqual(calls,['shell input tap 200 250','shell input swipe 200 1000 200 500 400'])
        self.assertIn('qa:id/button',script)

    def test_hangul_assertion_and_click_switches_without_extra_tap(self):
        frame=np.zeros((2400,1080,3),dtype=np.uint8)
        xml='<hierarchy><node resource-id="qa:id/button" bounds="[100,200][600,320]"/></hierarchy>'
        calls,assertions,_,script=self.run_recorder(frame,xml,[(ord('ㅁ'),[]),(-1,self.click(60,75)),
            (ord('ㅊ'),[]),(-1,self.click(60,75)),(ord('ㅂ'),[])])
        self.assertEqual(len(assertions),1)
        self.assertEqual(calls,['shell input tap 200 250'])
        self.assertIn('visibility_of_element_located',script)

    def test_image_crop_uses_screenshot_pixels_and_ignores_orphan_release(self):
        frame=np.zeros((1200,540,3),dtype=np.uint8)
        frame[125,100]=(10,20,30)
        calls,_,crops,_=self.run_recorder(frame,'<hierarchy/>',[
            (-1,[(cv2.EVENT_LBUTTONUP,60,75)]),(-1,self.click(60,75)),(ord('q'),[])])
        self.assertEqual(calls,['shell input tap 200 250'])
        self.assertEqual(len(crops),1)
        self.assertEqual(tuple(crops[0][60,60]),(10,20,30))

    def test_kotlin_record_click_assert_swipe_and_save(self):
        frame=np.zeros((1200,540,3),dtype=np.uint8)
        xml='<hierarchy><node resource-id="qa:id/button" bounds="[100,200][600,320]"/></hierarchy>'
        calls,assertions,crops,script=self.run_recorder(frame,xml,[
            (-1,self.click(60,75)),(ord('a'),[]),(-1,self.click(60,75)),
            (-1,[(cv2.EVENT_LBUTTONDOWN,60,300),(cv2.EVENT_LBUTTONUP,60,150)]),
            (ord('q'),[])],language='Kotlin (UIAutomator)')
        self.assertEqual(len(calls),2)
        self.assertEqual(len(assertions),1)
        self.assertEqual(crops,[])
        self.assertIn('By.res("qa:id/button")',script)
        self.assertIn('device.swipe(200, 1000, 200, 500, 80)',script)
        self.assertIn('@Test',script)

    def test_kotlin_image_only_target_blocks_touch_and_recording(self):
        calls,_,crops,script=self.run_recorder(np.zeros((1200,540,3),dtype=np.uint8),'<hierarchy/>',[
            (-1,self.click(60,75)),(ord('q'),[])],language='Kotlin (UIAutomator)')
        self.assertEqual(calls,[])
        self.assertEqual(crops,[])
        self.assertNotIn('val element1',script)


if __name__=='__main__':
    unittest.main()

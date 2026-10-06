"""Smoke the real Tk composition without a device, network, or saved credentials."""
import os
from pathlib import Path
import tempfile
import unittest
import time
from unittest.mock import patch, Mock
import customtkinter as ctk

from recorder.settings import SettingsStore, defaults
from recorder.writer_gui import ScriptWriterGUI
from recorder.model_picker import ModelPicker


@unittest.skipUnless(os.name == 'nt', 'Windows desktop composition')
class WriterGUITests(unittest.TestCase):
    def test_discovery_fills_rates_and_changing_model_clears_old_rates(self):
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(Path(folder)/'settings.json')
            with patch('recorder.writer_gui.SettingsStore',return_value=store), patch.object(store,'load',return_value=defaults()), patch('recorder.writer_gui.project_root',return_value=Path(folder)):
                app = ScriptWriterGUI()
            try:
                dialog = app._settings_dialog()
                app.update()
                picker = next(w for w in descendants(dialog) if isinstance(w,ModelPicker))
                provider = Mock()
                provider.list_models.return_value = ['gpt-6-luna','gpt-6-astra','unknown']
                with patch('recorder.writer_gui.create_provider',return_value=provider) as factory:
                    picker.fetch()
                    deadline = time.monotonic()+3
                    while picker.loading and time.monotonic()<deadline:
                        app.update()
                        time.sleep(.02)
                    self.assertFalse(factory.call_args.kwargs['require_model'])
                entries = [w for w in descendants(dialog) if isinstance(w,ctk.CTkEntry)]
                self.assertEqual(picker.get(),'gpt-6-luna')
                values = [w.get() for w in entries]
                self.assertIn('0.125',values)
                self.assertIn('0.50',values)
                picker.set('gpt-6-astra')
                self.assertIn('12.50',[w.get() for w in entries])
                picker.set('unknown')
                self.assertNotIn('12.50',[w.get() for w in entries])
                self.assertNotIn('0.125',[w.get() for w in entries])
            finally:
                for timer in app.tk.call('after','info'):
                    app.tk.call('after','cancel',timer)
                app.destroy()

    def test_layout_dialogs_and_event_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(Path(folder)/'settings.json')
            with patch('recorder.writer_gui.SettingsStore',return_value=store), patch.object(store,'load',return_value=defaults()), patch('recorder.writer_gui.project_root',return_value=Path(folder)):
                app = ScriptWriterGUI()
            try:
                app.update()
                self.assertEqual(app.title(),'Android Script Studio')
                self.assertEqual(app.pause_button.cget('state'),'disabled')
                app.geometry('1060x800')
                app.update()
                self.assertLessEqual(app.save_button.winfo_rootx() + app.save_button.winfo_width(), app.winfo_rootx() + app.winfo_width())
                self.assertGreater(app.canvas.winfo_height(),100)
                app._emit('step',{'description':'테스트 버튼 누르기'})
                app._poll()
                self.assertIn('테스트 버튼',app.steps_box.get('1.0','end'))
                app._cost_dialog()
                app.update()
                app._settings_dialog()
                app.update()
                app._initial_changed('최초 실행 화면을 직접 준비')
                self.assertEqual(app.ready.get(),0)
                app.instruction.insert(0,'후라이드 선택')
                app._add_instruction()
                self.assertIn('후라이드',app.instruction_history)
                self.assertTrue(app.session.cancel.is_set())
            finally:
                # Stop scheduled callbacks before tearing down the Tcl interpreter.
                for timer in app.tk.call('after','info'):
                    app.tk.call('after','cancel',timer)
                app.destroy()

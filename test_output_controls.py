import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import threading
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import create_application
from output_controls import OutputControls
from editor_jobs import RenderRequest,render_image
from gpu_policy import Pacer,tile_size,use_mode,current_mode


class OutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.application=QApplication.instance() or create_application()

    def test_buttons_and_linked_dimensions(self):
        widget=OutputControls();widget.show();widget.set_source_size((640,425))
        QTest.mouseClick(widget.buttons[6],Qt.LeftButton)
        self.assertEqual(widget.width_pixels.value(),3840)
        self.assertEqual(widget.height_pixels.value(),2550)
        widget.width_pixels.setValue(3000)
        self.assertEqual(widget.height_pixels.value(),1992)
        self.assertAlmostEqual(widget.value,4.6875)
        self.assertEqual(widget.inference_factor,5)
        self.assertTrue(widget.custom.isChecked())
        widget.height_pixels.setValue(1700)
        self.assertEqual(widget.width_pixels.value(),2560)
        self.assertTrue(widget.buttons[4].isChecked())
        widget.setCurrentText('×1');self.assertEqual(widget.inference_factor,1)
        widget.set_source_size(None);self.assertFalse(widget.width_pixels.isEnabled())
        widget.close();widget.deleteLater()

    def test_custom_dimensions_are_exported_without_repeating_ai(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'source.png';Image.new('RGB',(64,40)).save(source)
            weights=Path(temporary)/'weights.pth';weights.write_bytes(b'model')
            request=RenderRequest(0,str(source),str(weights),5,128,False,0,1,0,0,output_scale=4.5)
            base=Image.new('RGBA',(320,200),(20,30,40,120));base.info['icc_profile']=b'profile'
            with patch('editor_jobs.process') as process:
                result=render_image(request,None,lambda *args:None,threading.Event(),cached_base=base,cached_key=request.key)
                self.assertEqual(result['image'].size,(288,180))
                self.assertEqual(result['image'].getchannel('A').getextrema(),(120,120))
                self.assertEqual(result['image'].info['icc_profile'],b'profile')
                self.assertEqual(request.key,replace(request,output_scale=4.8).key)
                process.assert_not_called()

    def test_gpu_policy_controls_real_waits_and_honours_cancel(self):
        with use_mode('eco'):
            self.assertEqual(current_mode(),'eco');self.assertEqual(tile_size(512),128)
        with use_mode('full'):self.assertEqual(tile_size(512),512)
        cancel=threading.Event()
        with patch('gpu_policy.time.perf_counter',return_value=12),patch.object(cancel,'wait',return_value=False) as wait:
            Pacer(cancel,'balanced').pause(10)
            self.assertAlmostEqual(wait.call_args.args[0],2/9)
        with patch('gpu_policy.time.perf_counter',return_value=12),patch.object(cancel,'wait') as wait:
            Pacer(cancel,'full').pause(10);wait.assert_not_called()

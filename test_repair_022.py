import os,threading,tempfile,unittest
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from dataclasses import replace
import numpy as np
from PIL import Image,ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import create_application,Studio
from level_controls import ThreeLevels
from portrait import paste_face,natural_hair
from editor_jobs import RenderRequest

application=QApplication.instance() or create_application()


class PortraitRepairTests(unittest.TestCase):
    def test_aligned_1024_face_does_not_shift_features(self):
        crop=Image.new('RGB',(512,512));ImageDraw.Draw(crop).ellipse((180,210,200,230),fill='white')
        outputs=[]
        for size in (512,1024):
            bg=Image.new('RGB',(400,400));rgb=np.asarray(crop.resize((size,size),Image.Resampling.NEAREST))
            paste_face(bg,rgb,np.ones((512,512),np.float32),np.array([[.5,0,20],[0,.5,30]],np.float32),1,1)
            y,x=np.where(np.asarray(bg)[:,:,0]>128);outputs.append((x.mean(),y.mean()))
        np.testing.assert_allclose(outputs[0],outputs[1],atol=.5)

    def test_main_hair_pass_does_not_overwrite_beard_or_face(self):
        source=Image.new('RGB',(100,120),'gray');background=Image.new('RGB',(400,480),(20,40,60))
        helper=SimpleNamespace(det_faces=[np.array([30,15,70,75])])
        labels=np.ones((512,512),np.uint8);labels[:100]=17
        heads=[dict(rect=(0,0,100,120),labels=labels,pbr=Image.new('RGB',(400,480),'white'))]
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'4x-PBRify_UpscalerV4.safetensors').write_bytes(b'fixture')
            with patch('core.MODELS',p),patch('core.upscale_image') as infer:
                natural_hair(source,background,helper,4,1,128,lambda *a:None,threading.Event(),heads=heads,scalp_only=True)
                infer.assert_not_called()
        self.assertEqual(background.getpixel((200,360)),(20,40,60))
        self.assertNotEqual(background.getpixel((200,40)),(20,40,60))

    def test_zero_and_full_hair_strength_have_different_source_endpoints(self):
        source=Image.new('RGB',(40,40),'gray');helper=SimpleNamespace(det_faces=[np.array([10,10,30,30])])
        heads=[dict(rect=(0,0,40,40),labels=np.full((512,512),17,np.uint8),pbr=Image.new('RGB',(160,160),'white'))]
        colors=[]
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'4x-PBRify_UpscalerV4.safetensors').write_bytes(b'fixture')
            with patch('core.MODELS',p):
                for strength in (0,1):
                    out=Image.new('RGB',(160,160),'white')
                    natural_hair(source,out,helper,4,strength,128,lambda *a:None,threading.Event(),heads=heads,scalp_only=True)
                    colors.append(out.getpixel((80,20)))
        self.assertEqual(colors,[(128,128,128),(255,255,255)])

    def test_dependency_change_invalidates_cached_face_but_effect_does_not(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);source=p/'source.png';model=p/'main.pth';cf=p/'codeformer.pth'
            Image.new('RGB',(16,16)).save(source);model.write_bytes(b'model');cf.write_bytes(b'face')
            r=RenderRequest(0,str(source),str(model),4,128,True,1,1,0,0,backend='studio')
            with patch('editor_jobs.MODELS',p):
                first=r.key;self.assertEqual(first,replace(r,effect=.6).key)
                st=cf.stat();os.utime(cf,ns=(st.st_atime_ns,st.st_mtime_ns+1000000000))
                self.assertNotEqual(first,r.key)

    def test_three_buttons_emit_once_and_no_refresh_button_exists(self):
        control=ThreeLevels('Test',(0,20,40),0);control.show();application.processEvents()
        changed=[];control.valueChanged.connect(changed.append)
        QTest.mouseClick(control.buttons[1],Qt.LeftButton);QTest.mouseClick(control.buttons[1],Qt.LeftButton)
        self.assertEqual(changed,[20]);self.assertEqual(sum(b.isChecked() for b in control.buttons),1)
        window=Studio(auto_process=False)
        self.assertFalse(hasattr(window,'run_button'));self.assertFalse(hasattr(window,'video_section'))
        self.assertEqual(len(window.effect.buttons),3);self.assertEqual(len(window.nature_repair.buttons),3)
        window.finish_close();window.deleteLater();control.close();control.deleteLater();application.processEvents()

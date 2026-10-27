import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,threading,unittest,xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import replace
from PIL import Image,ImageDraw
from PySide6.QtWidgets import QApplication
from app import Studio,create_application
from graphics import process,export_svg,rasterize
from core import save_unique,Cancelled
from editor_jobs import RenderRequest,render_image
from image_cache import ImageCache


class GraphicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.application=QApplication.instance() or create_application()

    def fixture(self,path):
        image=Image.new('RGBA',(96,64),(0,0,0,0));draw=ImageDraw.Draw(image)
        draw.rectangle((8,8,47,55),fill='#e90038');draw.ellipse((48,8,87,47),fill='#2525e8')
        image.save(path);return image

    def test_svg_real_paths_alpha_and_print_size(self):
        with tempfile.TemporaryDirectory() as t:
            source=Path(t)/'source.png';self.fixture(source)
            result=process(source,4,True,4,30,lambda *a:None,threading.Event())
            self.assertEqual(result.size,(384,256))
            self.assertEqual(result.getpixel((0,0))[3],0)
            self.assertEqual(result.getpixel((80,80))[:3],(233,0,56))
            root=ET.fromstring(export_svg(result,300));self.assertEqual(root.get('viewBox'),'0 0 96 64')
            self.assertTrue(root.get('width').endswith('in'))
            self.assertGreater(sum(n.tag.endswith('path') for n in root.iter()),0)
            self.assertFalse(any(n.tag.endswith('image') for n in root.iter()))
            first=save_unique(result,t,source,4,'SVG');second=save_unique(result,t,source,4,'SVG')
            self.assertNotEqual(first,second);ET.parse(first)

    def test_raster_retains_gradient_and_transparency(self):
        with tempfile.TemporaryDirectory() as t:
            source=Path(t)/'source.png'
            image=Image.linear_gradient('L').resize((80,80)).convert('RGBA');image.putalpha(123);image.save(source)
            result=process(source,2,False,2,100,lambda *a:None,threading.Event())
            self.assertGreater(len(result.convert('RGB').getcolors(10000)),64)
            self.assertEqual(result.getchannel('A').getextrema(),(123,123))
            with self.assertRaises(ValueError):save_unique(result,t,source,2,'SVG')
            self.assertFalse(list(Path(t).glob('*.tmp')))

    def test_format_scoped_and_photo_options_unchanged(self):
        window=Studio(auto_process=False)
        try:
            window.select_profile('graphics');self.assertGreaterEqual(window.export_format.findData('SVG'),0)
            window.export_format.setCurrentIndex(window.export_format.findData('SVG'))
            self.assertFalse(window.scale.vector_settings.isHidden())
            self.assertTrue(window.effect.isHidden());self.assertTrue(window.face_section.isHidden())
            window.select_profile('portrait');self.assertEqual(window.export_format.findData('SVG'),-1)
            self.assertEqual(window.export_format.currentData(),'PNG')
            self.assertTrue(window.scale.vector_settings.isHidden());self.assertFalse(window.effect.isHidden())
        finally:window.finish_close();window.deleteLater()

    def test_vector_metadata_survives_disk_cache_and_custom_scale(self):
        with tempfile.TemporaryDirectory() as t:
            source=Path(t)/'source.png';self.fixture(source)
            request=RenderRequest(0,str(source),'graphics',2,128,False,0,1,0,0,
                                  backend='graphics',vector=True,output_scale=1.5)
            base=process(source,2,True,4,30,lambda *a:None,threading.Event())
            cache=ImageCache(Path(t)/'cache',ram_mb=0)
            try:
                cache.put(request.key,base)
                result=render_image(request,cache,lambda *a:None,threading.Event())['image']
                self.assertEqual(result.size,(144,96));self.assertTrue(result.info.get('graphics_svg'))
                self.assertEqual(request.key,replace(request,output_scale=1.8).key)
                self.assertNotEqual(request.key,replace(request,vector=False).key)
                export_svg(result,300)
            finally:cache.close()

    def test_cancel_before_processing(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):process('missing.png',4,True,8,30,lambda *a:None,cancel)

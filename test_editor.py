"""Editor workflows for the consolidated restoration profiles."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
from PIL import Image
from PySide6.QtCore import Qt,QCoreApplication,QEvent,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QLabel
from app import Studio,create_application
from core import Cancelled
from image_cache import ImageCache

application=QApplication.instance() or create_application()


def until(condition,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        application.processEvents()
        if condition():return
        QTest.qWait(15)
    raise AssertionError('Editor operation timed out')


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=self.root/'first.png';self.other=self.root/'second.png'
        Image.new('RGB',(96,64),(180,30,20)).save(self.source)
        Image.new('RGB',(80,60),(20,70,190)).save(self.other)
        self.window=Studio();self.window.output=self.root;self.window.show();application.processEvents()
        self.inference=patch('studio_backend.run',side_effect=self.fake)
        self.model=self.inference.start()

    def fake(self,source,factor,*args,**kwargs):
        cancel=args[4]
        for _ in range(3):
            if cancel.is_set():raise Cancelled()
            time.sleep(.01)
        with Image.open(source) as im:result=im.resize((im.width*factor,im.height*factor))
        result.info['studio_stats']={'tiles':1,'ok':True}
        return result

    def tearDown(self):
        self.window.cancel();self.window.finish_close();self.inference.stop()
        self.window.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);application.processEvents()
        self.temp.cleanup()

    def render(self):
        self.window.request_render(force=True);revision=self.window._revision
        until(lambda:self.window._result_request is not None and self.window._result_request.revision==revision and self.window.worker is None and not self.window.debounce.isActive())
        return self.window._result

    def test_two_modes_and_no_speed_control(self):
        w=self.window
        self.assertEqual([w.models.itemText(i) for i in range(w.models.count())],['Пейзажи и интерьеры','Портреты','Графика и иллюстрации'])
        self.assertEqual(len({w.models.itemData(i) for i in range(2)}),2)
        self.assertFalse(hasattr(w,'quality'));self.assertFalse(hasattr(w,'auto'))
        for identifier in ('photo','portrait'):
            w.select_profile(identifier);w.model_info.hide();application.processEvents()
            self.assertEqual(w.light_section.isVisible(),identifier in ('photo','portrait'))
            self.assertEqual(w.face_section.isVisible(),identifier=='portrait');self.assertEqual(w.hair_section.isVisible(),identifier=='portrait')
            self.assertIn('Модель:',w.models.currentData(Qt.ToolTipRole))
        self.assertFalse(any(label.isVisible() and label.text() in ('Быстро','Тщательно','Фрагмент GPU','Вариант') for label in w.sidebar.findChildren(QLabel)))

    def test_auto_preview_effect_cache_export_jpeg_and_dpi(self):
        w=self.window;w.add_paths([str(self.source)]);until(lambda:w._result is not None and w.worker is None)
        w.effect.setValue(50);self.render();self.assertEqual(self.model.call_count,1)
        w.export_format.setCurrentIndex(1);w.dpi.setValue(600);w.export_current();until(lambda:w.io_worker is None)
        with Image.open(self.root/'PhotoRestoreStudio_x4.jpg') as im:self.assertEqual(im.info['dpi'],(600,600));self.assertEqual(im.size,(384,256))
        self.assertEqual(w.progress.height(),3)

    def test_cleanup_and_strength_change_inference_but_color_and_light_reuse_it(self):
        w=self.window;w.add_paths([str(self.source)]);self.render();self.assertEqual(self.model.call_count,1)
        w.nature_repair.setValue(70);self.render();self.assertEqual(self.model.call_count,2)
        w.effect.setValue(60);self.render();self.assertEqual(self.model.call_count,2)
        w.select_profile('portrait');w.light_faces.setChecked(False);self.render();count=self.model.call_count
        w.exposure.setValue(20);self.render();self.assertEqual(self.model.call_count,count)
        self.assertNotEqual(w._result.getpixel((10,10)),(180,30,20))

    def test_profiles_remember_independent_settings(self):
        w=self.window;w._auto_process=False;w.effect.setValue(80);w.nature_repair.setValue(20)
        w.select_profile('portrait');w.effect.setValue(60);w.exposure.setValue(10)
        w.select_profile('photo');self.assertEqual(w.effect.value(),80);self.assertEqual(w.nature_repair.value(),20)
        self.assertEqual(w.scoped_options()['exposure'],0)
        w.select_profile('portrait');self.assertEqual(w.effect.value(),60);self.assertEqual(w.exposure.value(),10)
        w.library_changed();self.assertEqual(w.effect.value(),60)

    def test_hair_can_work_without_face_replacement_and_remembers_strength(self):
        w=self.window;w._auto_process=False;w.select_profile('portrait');w.add_paths([str(self.source)])
        first=w.current_request();self.assertTrue(first.hair_natural and first.faces)
        w.faces.setChecked(False);w.hair_strength.setValue(40);hair=w.current_request()
        self.assertTrue(hair.hair_natural);self.assertFalse(hair.faces);self.assertNotEqual(first.key,hair.key)
        w.select_profile('photo');self.assertFalse(w.current_request().hair_natural)
        w.select_profile('portrait');self.assertTrue(w.current_request().hair_natural);self.assertEqual(w.hair_strength.value(),40)

    def test_interior_light_controls_reuse_the_neural_result(self):
        w=self.window;w.add_paths([str(self.source)]);self.render();before=self.model.call_count
        w.nature_scene.setCurrentIndex(w.nature_scene.findData('interior'));self.render()
        self.assertEqual(w.shadow_detail.value(),20);self.assertEqual(w.surface.value(),85)
        self.assertEqual(self.model.call_count,before)

    def test_details_are_automatic_and_folding_does_not_disable_hair(self):
        w=self.window;w._auto_process=False;w.add_paths([str(self.source)])
        self.assertFalse(hasattr(w,'sky_detail'));self.assertFalse(hasattr(w,'hair_natural'))
        self.assertTrue(w.current_request().automatic_detail)
        w.nature_section.set_expanded(False);self.assertTrue(w.current_request().automatic_detail)
        w.select_profile('portrait');self.assertFalse(w.current_request().automatic_detail)
        self.assertTrue(w.current_request().hair_natural)
        before=w.current_request().key;w.hair_section.set_expanded(False)
        self.assertTrue(w.current_request().hair_natural);self.assertEqual(before,w.current_request().key)
        w.select_profile('photo');self.assertTrue(w.current_request().automatic_detail)

    def test_close_drops_cached_stages_and_preserves_original(self):
        w=self.window;w.add_paths([str(self.source)]);self.render();self.assertGreater(w.image_cache.stats()['entries'],0)
        w.close_file(w.files.currentItem());application.processEvents()
        self.assertEqual(w.image_cache.stats()['entries'],0);self.assertIsNone(w._result);self.assertTrue(self.source.exists())
        self.assertFalse(w.export_button.isEnabled())

    def test_old_request_cannot_replace_new_document(self):
        w=self.window;w.add_paths([str(self.source)]);w.add_paths([str(self.other)])
        until(lambda:w._result_request is not None and w._result_request.source==str(self.other.resolve()) and w.worker is None)
        self.assertEqual(w._result.size,(320,240));self.assertEqual(w._result.getpixel((10,10)),(20,70,190))

    def test_custom_size_reuses_same_integer_inference(self):
        w=self.window;w.add_paths([str(self.source)]);self.render()
        w.scale.width_pixels.setValue(350);self.render();count=self.model.call_count
        w.scale.width_pixels.setValue(360);self.render()
        self.assertEqual(self.model.call_count,count);self.assertEqual(w._result.size,(360,240))

    def test_light_face_detection_has_no_extra_model_weights(self):
        from studio_backend import detect_regions
        self.assertEqual(detect_regions(self.source),[])

    def test_model_release_runs_after_failure_and_cache_is_bounded(self):
        from editor_jobs import render_image
        w=self.window;w._auto_process=False;w.add_paths([str(self.source)]);r=w.current_request()
        with patch('studio_backend.run',side_effect=RuntimeError('failed')),patch('core.release_models') as release:
            with self.assertRaises(RuntimeError):render_image(r,w.image_cache,lambda *a:None,threading.Event())
            release.assert_called_once()
        for i in range(2,7):
            w.scale.setCurrentText('×'+str(i));self.render()
        self.assertLessEqual(w.image_cache.stats()['entries'],3)

    def test_weekly_setting_and_clean_preserve_results(self):
        from storage import Storage
        from storage_ui import StorageDialog
        store=Storage(self.root/'isolated');(store.results/'keep.png').write_bytes(b'result');(store.models/'keep.pth').write_bytes(b'model')
        dialog=StorageDialog(self.window,store);self.window.storage_dialog=dialog
        dialog.weekly_updates.setChecked(False);dialog.gpu_buttons['full'].setChecked(True);dialog.apply();until(lambda:dialog.worker is None)
        saved=Storage(store.home).settings;self.assertFalse(saved['weekly_model_updates']);self.assertEqual(saved['gpu_mode'],'full')
        dialog.perform(True);until(lambda:dialog.worker is None)
        self.assertTrue((store.results/'keep.png').exists());self.assertTrue((store.models/'keep.pth').exists());dialog.close()

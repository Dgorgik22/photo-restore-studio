import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import string,tempfile,unittest
from pathlib import Path
from PIL import Image
from app import Studio,create_application
from storage import Storage
from i18n import tr,set_language,EN,RUS,apply


class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or create_application()

    def tearDown(self):set_language('ru',persist=False)

    def test_placeholders_and_repeated_translation_are_stable(self):
        formatter=string.Formatter()
        for source,target in EN.items():
            fields=lambda text:{field for _,field,_,_ in formatter.parse(text) if field is not None}
            self.assertEqual(fields(source),fields(target),source)
            set_language('en',persist=False)
            self.assertEqual(tr(tr(source)),tr(source),source)
        self.assertEqual(tr('D:/Портреты/фото.png'),'D:/Портреты/фото.png')

    def test_rendered_messages_switch_in_both_directions(self):
        set_language('en',persist=False)
        self.assertEqual(tr('Исходник: 640 × 425 px'),'Original: 640 × 425 px')
        self.assertEqual(tr('≈ 2 мин 03 с осталось'),'≈ 2 min 03 sec remaining')
        set_language('ru',persist=False)
        self.assertEqual(tr('Original: 640 × 425 px'),'Исходник: 640 × 425 px')

    def test_live_switch_preserves_file_settings_and_vector_format(self):
        with tempfile.TemporaryDirectory() as t:
            source=Path(t)/'Портреты.png';Image.new('RGB',(32,24),'red').save(source)
            window=Studio(auto_process=False);window.show()
            try:
                window.select_profile('graphics');window.add_paths([str(source)])
                window.export_format.setCurrentIndex(window.export_format.findData('SVG'))
                before=window.current_request();original=window._original.tobytes()
                set_language('en',persist=False);self.app.processEvents()
                self.assertEqual(window.models.currentText(),'Graphics & illustrations')
                self.assertEqual(window.export_button.text(),'Export SVG')
                self.assertEqual(window.current_request().key,before.key)
                self.assertEqual(window._revision,before.revision)
                self.assertEqual(window._original.tobytes(),original)
                self.assertEqual(window.files.topLevelItem(0).text(0),'Портреты.png')
                set_language('ru',persist=False);self.app.processEvents()
                self.assertEqual(window.models.currentText(),'Графика и иллюстрации')
                self.assertEqual(window.export_format.currentData(),'SVG')
            finally:window.finish_close();window.deleteLater()

    def test_language_setting_survives_reopening_and_rejects_bad_values(self):
        with tempfile.TemporaryDirectory() as t:
            store=Storage(Path(t)/'home');set_language('en',store=store)
            self.assertEqual(Storage(store.home).settings['language'],'en')
            with self.assertRaises(ValueError):store.save(language='de')

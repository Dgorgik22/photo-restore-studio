import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from storage import Storage,MARKER
from image_cache import ImageCache,inactive_sessions


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Storage(self.root/'app')

    def tearDown(self):
        self.temp.cleanup()

    def test_settings_survive_restart_and_custom_paths_are_isolated(self):
        cache = self.store.choose_parent(self.root/'other-drive','cache')
        scratch = self.store.choose_parent(self.root/'other-drive','scratch')
        self.store.save(cache_path=str(cache),scratch_path=str(scratch),ram_cache_mb=256,disk_cache_gb=2)
        reloaded = Storage(self.store.home)
        self.assertEqual(reloaded.cache,cache)
        self.assertEqual(reloaded.scratch,scratch)
        self.assertEqual(reloaded.settings['ram_cache_mb'],256)

    def test_cleanup_preserves_models_outputs_settings_and_active_paths(self):
        model = self.store.models/'model.pth'
        output = self.store.results/'photo.png'
        model.write_bytes(b'weights')
        output.write_bytes(b'user photo')
        cache = self.store.subdir('downloads')/'old.part'
        cache.write_bytes(b'junk')
        active = self.store.cache/'temp'/'active'
        active.mkdir(parents=True)
        (active/'in-use').write_bytes(b'keep')
        self.store.save()
        removed = self.store.clean(keep=[active])
        self.assertEqual(removed,4)
        self.assertTrue(model.exists() and output.exists() and self.store.settings_file.exists())
        self.assertTrue((active/'in-use').exists())
        self.assertTrue((self.store.cache/MARKER).exists())

    def test_foreign_nonempty_folders_and_protected_paths_are_rejected(self):
        foreign = self.root/'foreign'
        foreign.mkdir()
        (foreign/'user.txt').write_text('important')
        for path in (foreign,self.store.home,self.store.results,self.store.plugins,self.store.models):
            with self.subTest(path=path),self.assertRaises(ValueError):
                self.store._prepare(path,'cache')
        self.assertEqual((foreign/'user.txt').read_text(),'important')

    def test_cleanup_stops_after_cancellation_without_deleting_remaining_files(self):
        folder=self.store.subdir('downloads')
        for index in range(20):(folder/f'{index}.tmp').write_bytes(b'temporary')
        cancel=threading.Event();unlink=Path.unlink
        def remove_one(path,*args,**kwargs):
            unlink(path,*args,**kwargs)
            cancel.set()
        with patch.object(Path,'unlink',remove_one):removed=self.store.clean(cancel=cancel)
        self.assertEqual(removed,len(b'temporary'))
        self.assertEqual(len(list(folder.glob('*.tmp'))),19)
        self.assertTrue((self.store.cache/MARKER).exists())

    def test_cleanup_refuses_missing_or_forged_marker(self):
        marker = self.store.cache/MARKER
        marker.unlink()
        with self.assertRaises(OSError):
            self.store.clean()
        marker.write_text(json.dumps(dict(application='OtherApp',kind='cache')))
        with self.assertRaises(ValueError):
            self.store.clean()

    def test_ram_lru_spills_losslessly_and_reuses_disk_without_inference(self):
        cache = ImageCache(self.store.scratch,ram_mb=.002,disk_gb=1,available=lambda:8*1024**3)
        try:
            image = Image.new('RGBA',(20,20),(10,50,90,87))
            image.info['icc_profile'] = b'icc-roundtrip'
            cache.put(('first',),image)
            cache.put(('second',),image.copy())
            self.assertLessEqual(cache.stats()['ram_bytes'],cache.ram_limit)
            self.assertEqual(cache.stats()['spills'],1)
            restored = cache.get(('first',))
            self.assertEqual(restored.getpixel((0,0)),(10,50,90,87))
            self.assertEqual(restored.info['icc_profile'],b'icc-roundtrip')
            self.assertEqual(cache.stats()['disk_hits'],1)
            self.assertLessEqual(cache.stats()['ram_bytes'],cache.ram_limit)
            if os.name == 'nt':
                self.assertNotIn(cache.root,list(inactive_sessions(self.store.scratch)))
        finally:
            cache.close()
        self.assertFalse(cache.root.exists())

    def test_memory_pressure_spills_before_user_limit(self):
        cache = ImageCache(self.store.scratch,ram_mb=64,disk_gb=1,available=lambda:1)
        try:
            cache.put('pressure',Image.new('RGB',(30,20)))
            self.assertEqual(cache.stats()['ram_bytes'],0)
            self.assertGreater(cache.stats()['disk_bytes'],0)
            self.assertIsNotNone(cache.get('pressure'))
            self.assertEqual(cache.stats()['ram_bytes'],0)
        finally:
            cache.close()

    def test_disk_limit_evicts_oldest_scratch_entry(self):
        cache = ImageCache(self.store.scratch,ram_mb=0,disk_gb=1,available=lambda:1)
        cache.disk_limit = 1800
        try:
            cache.put('first',Image.new('RGB',(20,20)))
            cache.put('second',Image.new('RGB',(20,20)))
            self.assertIsNone(cache.get('first'))
            self.assertIsNotNone(cache.get('second'))
            self.assertLessEqual(cache.stats()['disk_bytes'],1800)
        finally:
            cache.close()

    def test_full_scratch_disk_does_not_block_finished_render(self):
        from editor_jobs import RenderRequest,RenderWorker
        source = self.root/'source.png'
        model = self.root/'model.pth'
        Image.new('RGB',(8,8)).save(source)
        model.write_bytes(b'mock model')
        request = RenderRequest(1,str(source),str(model),2,128,False,.5,1,0,0)
        cache = ImageCache(self.store.scratch,ram_mb=0,available=lambda:1)
        rendered = []
        try:
            worker = RenderWorker(request,image_cache=cache)
            worker.result.connect(rendered.append)
            with patch('editor_jobs.process',return_value=Image.new('RGB',(16,16))),patch.object(Image.Image,'save',side_effect=OSError('Disk full')):
                worker.run()
            self.assertEqual(rendered[0]['image'].size,(16,16))
            self.assertEqual(cache.stats()['ram_bytes'],0)
            self.assertTrue(cache.last_error)
        finally:
            cache.close()

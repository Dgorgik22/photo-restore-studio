import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from storage import Storage
from core import Cancelled
import model_updates as updates
FILENAME='fixture.safetensors';SHA256='a'*64


class UpdatesTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temporary.name)/'app')
        self.now=2000000000
        self.sources=patch.object(updates,'weight_sources',return_value=[('fixture','example/weights',FILENAME,SHA256,'Fixture')])
        self.sources.start()

    def tearDown(self):self.sources.stop();self.temporary.cleanup()

    def response(self,tag='v1',sha=SHA256):
        return lambda url:dict(tag_name=tag,html_url='https://github.com/example/model/releases/'+tag) if 'api.github.com' in url else dict(siblings=[dict(rfilename=FILENAME,lfs=dict(sha256=sha))])

    def check(self,tag='v1',sha=SHA256,now=None):
        with patch.object(updates,'REPOSITORIES',('example/model',)),patch.object(updates,'fetch',side_effect=self.response(tag,sha)):
            return updates.check(lambda *args:None,threading.Event(),self.store,self.now if now is None else now)

    def test_weekly_check_toggle_and_persistence(self):
        self.assertTrue(updates.due(self.store,self.now))
        self.check()
        self.assertFalse(updates.due(self.store,self.now+updates.WEEK-1))
        self.assertTrue(updates.due(self.store,self.now+updates.WEEK))
        self.store.save(weekly_model_updates=False,gpu_mode='full')
        restarted=Storage(self.store.home)
        self.assertFalse(updates.due(restarted,self.now+2*updates.WEEK))
        self.assertEqual(restarted.settings['gpu_mode'],'full')

    def test_new_release_and_changed_model_hash_are_detected(self):
        self.assertEqual(self.check()['new_count'],0)
        result=self.check('v2',sha='1'*64,now=self.now+updates.WEEK)
        self.assertEqual(result['new_count'],2)
        self.assertTrue(result['sources']['fixture']['available'])
        self.assertTrue(result['sources']['example/model']['available'])

    def test_failed_check_backs_off_and_never_downloads_weights(self):
        with patch.object(updates,'REPOSITORIES',('example/model',)),patch.object(updates,'fetch',side_effect=OSError('offline')) as network:
            result=updates.check(lambda *args:None,threading.Event(),self.store,self.now)
            urls=[call.args[0] for call in network.call_args_list]
        self.assertEqual(result['checked_at'],0)
        self.assertFalse(updates.due(self.store,self.now+3600))
        self.assertTrue(updates.due(self.store,self.now+86400))
        self.assertTrue(all('api.github.com' in url or 'huggingface.co/api/' in url for url in urls))

    def test_cancel_keeps_prior_snapshot(self):
        self.check();before=updates.state_file(self.store).read_bytes()
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):updates.check(lambda *args:None,cancel,self.store,self.now+updates.WEEK)
        self.assertEqual(before,updates.state_file(self.store).read_bytes())

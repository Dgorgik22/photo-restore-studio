import threading,unittest
import numpy as np
from PIL import Image,ImageFilter
from natural_detail import preserve_natural_detail
from core import Cancelled


class NaturalDetailTests(unittest.TestCase):
    def ripples(self):
        y,x=np.mgrid[:120,:160]
        wave=15*np.sin(y*.55+x*.02)+4*np.sin(y*1.1)
        rgb=np.stack([90+wave,145+wave,180+wave],2).round().clip(0,255).astype('uint8')
        return Image.fromarray(rgb)

    def foliage(self):
        y,x=np.mgrid[:120,:160]
        texture=12*np.sin(x*.55)*np.cos(y*.6)+7*np.cos((x+y)*.27)
        rgb=np.stack([65+texture,125+texture,45+texture],2).round().clip(0,255).astype('uint8')
        return Image.fromarray(rgb)

    def test_real_ripple_structure_is_recovered_from_source(self):
        original=self.ripples();base=original.filter(ImageFilter.GaussianBlur(2)).resize((640,480),Image.Resampling.LANCZOS)
        result=preserve_natural_detail(original,base,threading.Event())
        self.assertGreater(result.info['natural_detail_stats']['water_correction_source_pixels'],500)
        self.assertGreater(result.info['natural_detail_stats']['changed_pixels'],500)
        region=(40,200,600,420)
        self.assertGreater(np.asarray(result.crop(region).convert('L')).std(),np.asarray(base.crop(region).convert('L')).std())

    def test_foliage_recovers_texture_and_keeps_alpha_icc(self):
        original=self.foliage();base=original.filter(ImageFilter.GaussianBlur(2)).resize((640,480)).convert('RGBA')
        base.putalpha(87);base.info['icc_profile']=b'profile'
        result=preserve_natural_detail(original,base,threading.Event())
        self.assertGreater(result.info['natural_detail_stats']['foliage_correction_source_pixels'],500)
        self.assertEqual(result.getchannel('A').tobytes(),base.getchannel('A').tobytes())
        self.assertEqual(result.info['icc_profile'],b'profile')

    def test_flat_surfaces_and_existing_sharp_ripples_are_not_modified(self):
        for original in (Image.new('RGB',(160,120),(20,20,20)),Image.new('RGB',(160,120),(60,125,55)),self.ripples()):
            base=original.resize((640,480),Image.Resampling.LANCZOS)
            result=preserve_natural_detail(original,base,threading.Event())
            self.assertEqual(base.tobytes(),result.tobytes())

    def test_cancel_stops_the_automatic_stage(self):
        original=self.ripples();cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):preserve_natural_detail(original,original.resize((640,480)),cancel)

    def test_removed_sensor_noise_is_not_brought_back_as_foliage(self):
        rng=np.random.default_rng(8)
        noise=rng.normal(0,3,(120,160,1))
        original=Image.fromarray((np.array([65,125,45])+noise).round().clip(0,255).astype('uint8'))
        base=Image.new('RGB',(640,480),(65,125,45))
        result=preserve_natural_detail(original,base,threading.Event())
        self.assertEqual(result.tobytes(),base.tobytes())

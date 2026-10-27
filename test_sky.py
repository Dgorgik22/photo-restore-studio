import tempfile,threading,unittest
from pathlib import Path
import numpy as np
from PIL import Image,ImageFilter
from sky_detail import cloud_mask,refine_clouds
from core import Cancelled


class SkyTests(unittest.TestCase):
    def fixture(self):
        y,x=np.mgrid[:100,:160]
        shade=190+12*np.sin(x*.7)*np.cos(y*.35)
        rgb=np.repeat(shade[:,:,None],3,2).astype('uint8')
        for column in range(115,140):
            a=(column-115)/25
            rgb[:,column]=(rgb[:,column]*(1-a)+np.array([60,150,230])*a).round().astype('uint8')
        rgb[:,140:]=(60,150,230) # soft cloud boundary into adjacent blue sky
        rgb[70:]=(35,95,45)     # foliage is outside the cloud region
        return Image.fromarray(rgb)

    def test_local_cloud_pass_preserves_ground_alpha_and_colour_profile(self):
        original=self.fixture();base=original.resize((640,400)).filter(ImageFilter.GaussianBlur(5)).convert('RGBA')
        base.putalpha(123);base.info['icc_profile']=b'profile'
        with tempfile.TemporaryDirectory() as t:
            weight=Path(t)/'pbr.pth';weight.touch()
            def detail(crop,path,factor,tile,report,cancel):return crop.resize((crop.width*factor,crop.height*factor),Image.Resampling.LANCZOS)
            result=refine_clouds(original,base,4,128,lambda *a:None,threading.Event(),weight,detail)
        self.assertGreater(result.info['sky_detail_stats']['changed_pixels'],100)
        self.assertEqual(result.crop((0,320,640,400)).tobytes(),base.crop((0,320,640,400)).tobytes())
        self.assertEqual(result.getchannel('A').tobytes(),base.getchannel('A').tobytes())
        self.assertEqual(result.info['icc_profile'],b'profile')

    def test_smoother_secondary_model_does_not_erase_existing_texture(self):
        original=self.fixture();base=original.resize((640,400),Image.Resampling.LANCZOS)
        with tempfile.TemporaryDirectory() as t:
            weight=Path(t)/'pbr.pth';weight.touch()
            def smooth(crop,path,factor,tile,report,cancel):
                return crop.resize((crop.width*factor,crop.height*factor)).filter(ImageFilter.GaussianBlur(20))
            result=refine_clouds(original,base,4,128,lambda *a:None,threading.Event(),weight,smooth)
        before=np.asarray(base,dtype=np.int16);after=np.asarray(result,dtype=np.int16)
        self.assertLess(np.abs(after[:240,:450]-before[:240,:450]).mean(),.02)

    def test_flat_dark_or_plain_blue_areas_do_not_load_another_model(self):
        def forbidden(*args):raise AssertionError('unnecessary GPU pass')
        for colour in ((25,25,25),(50,145,235),(255,255,255)):
            original=Image.new('RGB',(160,100),colour);base=original.resize((640,400))
            result=refine_clouds(original,base,4,128,lambda *a:None,threading.Event(),upscale_fn=forbidden)
            self.assertIs(result,base)
            self.assertEqual(cloud_mask(np.asarray(original)).max(),0)

    def test_cancel_prevents_the_extra_pass(self):
        original=self.fixture();cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):refine_clouds(original,original.resize((640,400)),4,128,lambda *a:None,cancel)

    def test_hard_skyline_and_window_edges_protect_neutral_objects(self):
        snow=np.full((100,160,3),(40,130,230),np.uint8)
        snow[50:]=(225,225,230)
        self.assertEqual(cloud_mask(snow)[55:].max(),0)
        room=np.full((100,160,3),(190,190,195),np.uint8)
        room[15:85,105:155]=(20,20,20)
        room[20:80,110:150]=(40,130,230)
        self.assertEqual(cloud_mask(room).max(),0)

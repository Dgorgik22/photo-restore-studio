import threading,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
from portrait import facial_hair_mask,face_mask,prepare_head_bases
from portrait_texture import preserve_texture
from architecture_detail import regularize,window_grids
from core import Cancelled


class RepairTests(unittest.TestCase):
    def test_retired_experiment_cannot_silently_use_another_model(self):
        from studio_backend import run
        with self.assertRaisesRegex(ValueError,'удалён'):
            run('missing.png',4,1,0,True,lambda *args:None,threading.Event(),algorithm='seed')

    def test_beard_mask_does_not_select_a_mislabelled_nostril(self):
        rgb=np.full((512,512,3),(185,135,120),np.uint8);labels=np.ones((512,512),np.uint8)
        rgb[310:345,240:275]=(50,50,50)
        rgb[370:455:2,210:300]=(50,50,50);rgb[371:455:2,210:300]=(150,150,150)
        mask=facial_hair_mask(rgb,labels,nose_y=320)
        self.assertEqual(mask[310:345,240:275].max(),0)
        self.assertGreater(mask[390:440,220:290].max(),.15)

    def test_face_mask_does_not_leave_blurred_holes_at_eyes_and_nose(self):
        labels=np.ones((512,512),np.uint8);labels[300:340,240:280]=10;labels[225:250,170:215]=4
        mask=face_mask(labels)
        self.assertGreater(mask[320,257],.99);self.assertGreater(mask[240,193],.99)
        self.assertGreater(mask[370,180],.99)

    def test_hybrid_photo_head_does_not_overwrite_clothes(self):
        original=Image.new('RGB',(100,120),'gray');out=Image.new('RGB',(400,480),'blue')
        helper=SimpleNamespace(det_faces=[np.array([30,15,70,65])])
        labels=np.zeros((512,512),np.uint8);labels[100:400,100:400]=1
        with patch('portrait.parse_labels',return_value=labels),patch('core.upscale_image',side_effect=lambda im,p,f,*args:Image.new('RGB',(im.width*f,im.height*f),'red')):
            heads=prepare_head_bases(original,out,helper,4,128,lambda *args:None,threading.Event())
        self.assertEqual(len(heads),1);self.assertEqual(out.getpixel((200,460)),(0,0,255))
        self.assertNotEqual(out.getpixel((200,160)),(0,0,255))

    def test_skin_colour_variation_and_cloth_texture_are_preserved(self):
        y,x=np.mgrid[:120,:100];v=10*np.sin(x*.5)*np.cos(y*.4)
        rgb=np.stack([160+v,120+v,100+v],2).round().astype('uint8');source=Image.fromarray(rgb)
        base=source.filter(ImageFilter.GaussianBlur(2)).resize((400,480)).convert('RGBA');base.putalpha(91);base.info['icc_profile']=b'icc'
        result=preserve_texture(source,base,[[.3,.1,.7,.5]],threading.Event())
        self.assertGreater(result.info['portrait_texture_stats']['changed_pixels'],100)
        self.assertEqual(result.getchannel('A').tobytes(),base.getchannel('A').tobytes());self.assertEqual(result.info['icc_profile'],b'icc')

    def facade(self):
        im=Image.new('RGB',(120,100),(210,200,180));d=ImageDraw.Draw(im)
        for y in range(12,90,13):
            for x in range(12,110,10):d.rectangle((x,y,x+3,y+5),fill=(35,45,55))
        return im

    def test_repeated_windows_are_regularized_without_replacing_interiors(self):
        original=self.facade();base=original.resize((480,400),Image.Resampling.BILINEAR).convert('RGBA');base.putalpha(77)
        windows,_,_=window_grids(np.asarray(original));self.assertGreater(len(windows),12)
        result=regularize(original,base,threading.Event());self.assertGreater(result.info['architecture_stats']['windows'],12)
        self.assertEqual(result.getpixel((5,5)),base.getpixel((5,5)));self.assertEqual(result.getchannel('A').tobytes(),base.getchannel('A').tobytes())

    def test_noise_and_empty_sky_are_not_treated_as_facades(self):
        rng=np.random.default_rng(9)
        for original in [Image.new('RGB',(180,120),(60,150,240)),Image.fromarray(rng.integers(100,180,(120,180,3),np.uint8))]:
            base=original.resize((360,240));out=regularize(original,base,threading.Event())
            self.assertEqual(out.info['architecture_stats']['windows'],0);self.assertEqual(base.tobytes(),out.tobytes())

    def test_new_stages_support_cancel(self):
        im=self.facade();cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):regularize(im,im.resize((480,400)),cancel)
        with self.assertRaises(Cancelled):preserve_texture(im,im.resize((480,400)),[[0,0,1,1]],cancel)

import threading,unittest
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageFilter
from portrait import face_mask,refine_aligned_detail,aligned_reference,PARSENET_TO_CANONICAL
from portrait_texture import preserve_texture
from core import upscale_image


class SpeedMaterialTests(unittest.TestCase):
    def test_whole_head_mask_keeps_hair_but_excludes_clothing(self):
        labels=np.zeros((512,512),np.uint8);labels[50:130,150:350]=17;labels[130:420,150:350]=1;labels[420:]=16
        mask=face_mask(labels,hair_strength=1)
        self.assertGreater(mask[80,250],.99);self.assertEqual(mask[470,250],0)

    def test_uniform_margins_skip_inference_but_keep_exact_output_geometry(self):
        source=Image.new('RGB',(320,200),'white');source.paste((30,60,90),(130,70,190,150))
        original=upscale_image
        with patch('core.upscale_image',side_effect=lambda im,p,f,*args,**kw:im.resize((im.width*f,im.height*f),Image.Resampling.NEAREST)) as infer:
            result=original(source,'unused.pth',2,128,lambda *a:None,threading.Event())
        self.assertEqual(result.size,(640,400));self.assertEqual(result.getpixel((0,0)),(255,255,255))
        self.assertEqual(result.getpixel((300,200)),(30,60,90));self.assertEqual(infer.call_count,1)
        self.assertLess(infer.call_args.args[0].width,source.width)

    def test_native_parsenet_neck_hair_clothes_and_nose_are_not_confused(self):
        actual=PARSENET_TO_CANONICAL[np.array([2,13,17,18])]
        np.testing.assert_array_equal(actual,[10,17,14,16])

    def test_neck_is_restored_but_clothing_and_hair_stay_outside_face_mask(self):
        labels=np.zeros((512,512),np.uint8);labels[80:320,120:390]=1;labels[320:470,200:320]=14
        labels[390:,20:190]=16;labels[:80]=17
        mask=face_mask(labels)
        self.assertGreater(mask[380,260],.99)
        self.assertEqual(mask[420,100],0);self.assertEqual(mask[40,200],0)

    def test_detail_reuses_existing_pixels_without_model_inference(self):
        face=np.full((512,512,3),128,np.uint8);ref=np.full((1024,1024,3),210,np.uint8)
        with patch('core.upscale_image',side_effect=AssertionError('No new neural pass')):
            result=refine_aligned_detail(face,ref,np.ones((512,512),np.uint8),threading.Event())
        self.assertEqual(result.shape,(1024,1024,3));self.assertLessEqual(abs(result.astype(int)-128).max(),1)

    def test_aligned_reference_keeps_the_expected_position(self):
        y,x=np.mgrid[:180,:200];image=Image.fromarray(np.stack([x,y,x*0+100],2).astype(np.uint8))
        ref=aligned_reference(image,np.array([[.25,0,20],[0,.25,30]],np.float32))
        self.assertLessEqual(abs(int(ref[400,400,0])-70),1);self.assertLessEqual(abs(int(ref[400,400,1])-80),1)

    def test_cloth_recovery_does_not_touch_the_restored_face(self):
        y,x=np.mgrid[:120,:100];v=10*np.sin(x*.5)*np.cos(y*.4)
        source=Image.fromarray(np.stack([160+v,120+v,100+v],2).round().astype('uint8'))
        base=source.filter(ImageFilter.GaussianBlur(2)).resize((400,480))
        result=preserve_texture(source,base,[[.3,.1,.7,.5]],threading.Event(),skin_detail=False)
        self.assertEqual(result.crop((120,40,280,150)).tobytes(),base.crop((120,40,280,150)).tobytes())
        self.assertGreater(result.info['portrait_texture_stats']['changed_pixels'],100)

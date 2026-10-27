import tempfile,threading,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import numpy as np
from PIL import Image
from surface_light import preserve_surface_light
from portrait import facial_hair_mask
from editor_jobs import RenderRequest,render_image
from image_cache import ImageCache


class QualityTests(unittest.TestCase):
    def test_light_preservation_does_not_blur_fine_texture(self):
        x=np.arange(256);wave=np.sin(x*np.pi/2)*.04
        ref=np.tile(.65+wave,(128,1));fresh=np.tile(.8+wave,(128,1))
        with tempfile.TemporaryDirectory() as t:
            source=Path(t)/'source.png'
            Image.fromarray(np.repeat((ref*255).round().astype('uint8')[:,:,None],3,2)).save(source)
            image=Image.fromarray(np.repeat((fresh*255).round().astype('uint8')[:,:,None],3,2))
            out=np.asarray(preserve_surface_light(source,image,1),np.float32)[:,:,0]
            before=np.asarray(image,np.float32)[:,:,0]
            self.assertGreater(np.std(out[:,24:-24]),np.std(before[:,24:-24])*.95)
            self.assertLess(abs(out.mean()-ref.mean()*255),abs(before.mean()-ref.mean()*255))

    def test_shadow_detail_does_not_make_noise_on_flat_dark_surfaces(self):
        with tempfile.TemporaryDirectory() as t:
            source=Path(t)/'source.png';image=Image.new('RGBA',(53,77),(20,20,20,101));image.info['icc_profile']=b'profile'
            image.convert('RGB').save(source)
            result=preserve_surface_light(source,image,.85,100)
            self.assertEqual(result.tobytes(),image.tobytes());self.assertEqual(result.info['icc_profile'],b'profile')

    def test_facial_hair_mask_excludes_eyes_lips_and_background(self):
        rgb=np.full((512,512,3),(185,130,110),np.uint8);labels=np.ones((512,512),np.uint8)
        rgb[320:455:2,220:300]=(70,73,72);rgb[321:455:2,220:300]=(150,152,151)
        labels[350:375,230:290]=11;labels[:150]=0;labels[200:240,160:215]=4
        mask=facial_hair_mask(rgb,labels)
        self.assertGreater(np.count_nonzero(mask>.15),100)
        self.assertEqual(mask[350:375,230:290].max(),0);self.assertEqual(mask[:150].max(),0)
        self.assertEqual(mask[200:240,160:215].max(),0)

    def test_post_effects_reuse_the_neural_result(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'source.png';Image.new('RGB',(16,16),'gray').save(source)
            model=root/'photo.pth';model.write_text('{}');cache=ImageCache(root,64,1)
            request=RenderRequest(0,str(source),str(model),2,128,False,0,1,0,0,backend='studio')
            try:
                with patch('studio_backend.run',return_value=Image.new('RGB',(32,32),'white')) as infer:
                    render_image(request,cache,lambda *a:None,threading.Event())
                    render_image(replace(request,effect=.5),cache,lambda *a:None,threading.Event())
                    self.assertEqual(infer.call_count,1);self.assertEqual(infer.call_args.kwargs['algorithm'],'photo')
                    self.assertFalse(infer.call_args.kwargs['faces'] or infer.call_args.kwargs['hair'])
                self.assertNotEqual(request.key,replace(request,automatic_detail=True).key)
            finally:cache.close()

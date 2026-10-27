import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from lighting import correct_light,face_light_mask
from portrait import face_mask,paste_face,enhance,natural_hair
from editor_jobs import RenderRequest,render_image
from image_cache import ImageCache


class PortraitTests(unittest.TestCase):
    def setUp(self):
        # Unit tests must not rely on bundled weights that may have been retired.
        self.weights=tempfile.TemporaryDirectory()
        directory=Path(self.weights.name)
        for filename in ('GFPGANv1.4.pth','codeformer.pth','4x-PBRify_UpscalerV4.safetensors','RealESRNet_x4plus.pth','SwinIR-M_x4_GAN.pth'):
            (directory/filename).write_bytes(b'unit-fixture')
        self.model_paths=patch('core.MODELS',directory)
        self.model_paths.start()
        self.store_models=patch('portrait.STORE.models',directory)
        self.store_models.start()

    def tearDown(self):
        self.store_models.stop();self.model_paths.stop();self.weights.cleanup()

    def test_face_feather_does_not_replace_hair_labels(self):
        labels = np.zeros((512,512),np.uint8)
        labels[100:400,100:400] = 1
        labels[:160,:] = 17
        mask = face_mask(labels)
        self.assertTrue(np.all(mask[:160,:] == 0))
        self.assertGreater(mask[250,250],.99)
        self.assertEqual(mask[0,0],0)

    def test_face_composite_changes_only_local_mask(self):
        background = Image.new('RGB',(300,300),(20,40,60))
        rgb = np.full((512,512,3),(200,150,100),np.uint8)
        mask = np.zeros((512,512),np.float32)
        mask[100:300,100:300] = 1
        paste_face(background,rgb,mask,np.array([[.5,0,0],[0,.5,0]],np.float32),1,1)
        self.assertEqual(background.getpixel((100,100)),(200,150,100))
        self.assertEqual(background.getpixel((10,10)),(20,40,60))
        self.assertEqual(background.getpixel((290,290)),(20,40,60))

    def test_enhance_retains_alpha_profile_and_regions(self):
        original = Image.new('RGB',(64,64),'gray')
        upscaled = Image.new('RGBA',(128,128),(20,40,60,79))
        upscaled.info['icc_profile'] = b'profile'
        helper = SimpleNamespace(cropped_faces=[np.zeros((512,512,3),np.uint8)],
            inverse_affine_matrices=[np.array([[.25,0,0],[0,.25,0]],np.float32)],
            align_warp_face=lambda:None,get_inverse_affine=lambda value:None)
        with patch('portrait.analyze',return_value=(helper,[[0,0,1,1]])),patch('portrait.parse_labels',return_value=np.ones((512,512),np.uint8)),patch('portrait.restore_crop',return_value=np.full((512,512,3),128,np.uint8)):
            result = enhance(original,upscaled,2,dict(faces=True,face_strength=.6),lambda *a:None,threading.Event())
        self.assertEqual(result.mode,'RGBA')
        self.assertTrue(np.all(np.array(result.getchannel('A')) == 79))
        self.assertEqual(result.info['icc_profile'],b'profile')
        self.assertEqual(result.info['portrait_regions'],[[0,0,1,1]])

    def test_hair_pass_is_masked_and_can_reuse_cached_model_output(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = ImageCache(directory,64,1)
            try:
                original = Image.new('RGB',(100,100),'gray')
                background = Image.new('RGB',(400,400),(20,40,60))
                helper = SimpleNamespace(det_faces=[np.array([20,30,50,60])])
                labels = np.zeros((512,512),np.uint8)
                labels[60:300,60:300] = 17
                def soft(image,model,factor,*args):
                    return Image.new('RGB',(image.width*factor,image.height*factor),(160,180,200))
                with patch('portrait.parse_labels',return_value=labels),patch('core.upscale_image',side_effect=soft) as inference:
                    for _ in range(2):
                        affected = natural_hair(original,background,helper,4,.8,128,lambda *a:None,threading.Event(),cache,'source')
                    self.assertEqual(affected,1)
                    self.assertEqual(inference.call_count,1)
                self.assertEqual(background.getpixel((399,399)),(20,40,60))
                self.assertNotEqual(background.getpixel((100,100)),(20,40,60))
            finally:
                cache.close()

    def test_face_strength_reuses_neural_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = ImageCache(directory,64,1)
            original = Image.new('RGB',(64,64),'gray')
            background = Image.new('RGB',(128,128),(20,40,60))
            helper = SimpleNamespace(cropped_faces=[np.zeros((512,512,3),np.uint8)],
                inverse_affine_matrices=[np.array([[.25,0,0],[0,.25,0]],np.float32)],
                align_warp_face=lambda:None,get_inverse_affine=lambda value:None)
            try:
                with patch('portrait.analyze',return_value=(helper,[[0,0,1,1]])),patch('portrait.parse_labels',return_value=np.ones((512,512),np.uint8)),patch('portrait.restore_crop',return_value=np.full((512,512,3),180,np.uint8)) as neural:
                    first = enhance(original,background,2,dict(faces=True,face_strength=.3),lambda *a:None,threading.Event(),cache,'same-source')
                    second = enhance(original,background,2,dict(faces=True,face_strength=.9),lambda *a:None,threading.Event(),cache,'same-source')
                self.assertEqual(neural.call_count,1)
                self.assertNotEqual(first.tobytes(),second.tobytes())
            finally:
                cache.close()

    def test_background_is_reused_between_face_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source,model = root/'photo.png',root/'model.pth'
            Image.new('RGB',(16,16),'gray').save(source)
            model.write_bytes(b'mock')
            cache = ImageCache(root,64,1)
            request = RenderRequest(1,str(source),str(model),2,128,False,.6,1,0,0)
            def fake_face(original,background,*args):
                return background.copy()
            try:
                with patch('editor_jobs.process',return_value=Image.new('RGB',(32,32),'gray')) as inference,patch('portrait.enhance',side_effect=fake_face) as face:
                    for current in (request,replace(request,faces=True,face_model='gfpgan'),replace(request,faces=True,face_model='codeformer')):
                        render_image(current,cache,lambda *a:None,threading.Event())
                    self.assertEqual(inference.call_count,1)
                    self.assertEqual(face.call_count,2)
            finally:
                cache.close()

    def test_alternative_hair_model_routes_to_selected_weights(self):
        original = Image.new('RGB',(60,60),'gray')
        background = Image.new('RGB',(120,120))
        helper = SimpleNamespace(det_faces=[np.array([15,20,35,40])])
        with patch('portrait.parse_labels',return_value=np.full((512,512),17,np.uint8)),patch('core.upscale_image',return_value=Image.new('RGB',(120,120),'gray')) as inference:
            natural_hair(original,background,helper,2,.5,128,lambda *a:None,threading.Event(),model_id='swinir-photo')
        self.assertEqual(inference.call_args.args[1].name,'SwinIR-M_x4_GAN.pth')

    def test_lighting_regions_survive_scratch_and_new_metadata_replaces_old(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source,model = root/'photo.png',root/'model.pth'
            Image.new('RGB',(16,16),'gray').save(source)
            model.write_bytes(b'mock')
            cache = ImageCache(root,ram_mb=0,disk_gb=1)
            request = RenderRequest(1,str(source),str(model),2,128,False,.6,1,0,0)
            try:
                with patch('editor_jobs.process',return_value=Image.new('RGB',(32,32),'gray')) as inference,patch('studio_backend.detect_regions',return_value=[[.1,.1,.8,.8]]) as detector:
                    render_image(request,cache,lambda *a:None,threading.Event())
                    first = render_image(replace(request,exposure=20),cache,lambda *a:None,threading.Event())
                    second = render_image(replace(request,exposure=30),cache,lambda *a:None,threading.Event())
                    self.assertEqual(inference.call_count,1)
                    self.assertEqual(detector.call_count,1)
                    self.assertEqual(second['base'].info['portrait_regions'],[[.1,.1,.8,.8]])
                    self.assertNotEqual(first['image'].tobytes(),second['image'].tobytes())
            finally:
                cache.close()


class LightTests(unittest.TestCase):
    def test_neutral_is_exact_and_no_face_means_no_face_only_light(self):
        image = Image.new('RGBA',(13,17),(35,70,100,88))
        self.assertIs(correct_light(image),image)
        self.assertIs(correct_light(image,exposure=50,regions=[]),image)

    def test_exposure_and_temperature_preserve_alpha_and_icc(self):
        image = Image.new('RGBA',(20,20),(80,80,80,77))
        image.info['icc_profile'] = b'icc'
        output = correct_light(image,exposure=25,temperature=40)
        red,green,blue,alpha = output.getpixel((10,10))
        self.assertGreater(red,green)
        self.assertGreater(green,blue)
        self.assertGreater(blue,80)
        self.assertEqual(alpha,77)
        self.assertEqual(output.info['icc_profile'],b'icc')

    def test_shadows_and_highlights_target_their_tonal_ranges(self):
        image = Image.new('RGB',(20,10),(30,30,30))
        image.paste((230,230,230),(10,0,20,10))
        shadows = correct_light(image,shadows=50)
        self.assertGreater(shadows.getpixel((2,2))[0]-30,shadows.getpixel((12,2))[0]-230)
        highlights = correct_light(image,highlights=-50)
        self.assertGreater(230-highlights.getpixel((12,2))[0],30-highlights.getpixel((2,2))[0])

    def test_face_only_mask_preserves_far_background(self):
        image = Image.new('RGB',(200,200),(70,80,90))
        result = correct_light(image,exposure=50,regions=[[.3,.3,.7,.7]])
        self.assertEqual(result.getpixel((0,0)),image.getpixel((0,0)))
        self.assertGreater(result.getpixel((100,100))[0],70)

    def test_control_extremes_keep_valid_pixels(self):
        image = Image.effect_noise((31,129),90).convert('RGB')
        for value in (-100,100):
            result = correct_light(image,exposure=value,shadows=value,highlights=value,temperature=value)
            self.assertEqual(result.size,image.size)
            self.assertEqual(np.array(result).dtype,np.uint8)

import tempfile
import unittest
from pathlib import Path
from PIL import Image
from core import save_unique


class ExportTests(unittest.TestCase):
    def test_names_use_program_scale_and_unique_numbers_across_source_files(self):
        with tempfile.TemporaryDirectory() as directory:
            image=Image.new('RGB',(19,13))
            first=save_unique(image,directory,'original-one.jpg',4)
            second=save_unique(image,directory,'original-two.jpg',4)
            custom=save_unique(image,directory,'original-three.jpg',1.9,'JPEG')
            self.assertEqual(first.name,'PhotoRestoreStudio_x4.png')
            self.assertEqual(second.name,'PhotoRestoreStudio_x4_1.png')
            self.assertEqual(custom.name,'PhotoRestoreStudio_x1.9.jpg')

    def test_density_boundaries_preserve_pixels_in_both_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.new('RGB',(63,47),(28,120,200))
            for image_format in ('PNG','JPEG'):
                for dpi in (15,300,600):
                    with self.subTest(image_format=image_format,dpi=dpi):
                        path = save_unique(image,directory,'фото.png',4,image_format,dpi,95)
                        with Image.open(path) as opened:
                            self.assertEqual(opened.size,image.size)
                            self.assertEqual(opened.format,image_format)
                            self.assertAlmostEqual(opened.info['dpi'][0],dpi,delta=.02)
                            self.assertAlmostEqual(opened.info['dpi'][1],dpi,delta=.02)

    def test_jpeg_flattens_transparency_on_white_and_preserves_icc(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.new('RGBA',(32,32),(255,0,0,0))
            image.info['icc_profile'] = b'test-profile-roundtrip'
            path = save_unique(image,directory,'transparent.png',2,'JPEG',600,100)
            with Image.open(path) as opened:
                self.assertEqual(opened.mode,'RGB')
                self.assertEqual(opened.getpixel((16,16)),(255,255,255))
                self.assertEqual(opened.info['icc_profile'],image.info['icc_profile'])
            image.putalpha(128)
            path = save_unique(image,directory,'transparent.png',2,'JPEG',15,100)
            with Image.open(path) as opened:
                red,green,blue = opened.getpixel((16,16))
                self.assertGreaterEqual(red,253)
                self.assertAlmostEqual(green,127,delta=2)
                self.assertAlmostEqual(blue,127,delta=2)

    def test_png_keeps_alpha_and_icc(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.new('RGBA',(3,7),(22,55,88,77))
            image.info['icc_profile'] = b'test-profile-roundtrip'
            path = save_unique(image,directory,'source.png',8,'PNG',600)
            with Image.open(path) as opened:
                self.assertEqual(opened.getpixel((1,1)),(22,55,88,77))
                self.assertEqual(opened.info['icc_profile'],image.info['icc_profile'])

    def test_jpeg_does_not_overwrite_and_quality_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.effect_noise((64,64),80).convert('RGB')
            first = save_unique(image,directory,'source.jpg',2,'JPG',300,100)
            before = first.read_bytes()
            second = save_unique(image,directory,'source.jpg',2,'JPEG',300,10)
            self.assertEqual(first.suffix,'.jpg')
            self.assertNotEqual(first,second)
            self.assertEqual(first.read_bytes(),before)
            self.assertLess(second.stat().st_size,first.stat().st_size)

    def test_invalid_options_fail_before_creating_files(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Image.new('RGB',(2,2))
            for options in (dict(dpi=14),dict(dpi=601),dict(image_format='GIF'),dict(quality=0),dict(quality=101)):
                with self.subTest(options=options),self.assertRaises(ValueError):
                    save_unique(image,directory,'source.png',2,**options)
            self.assertEqual(list(Path(directory).iterdir()),[])

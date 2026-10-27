import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from core import tiled, save_unique, Cancelled, check_cancel


class NearestModel:
    scale = 2
    def __call__(self, tensor):
        return torch.nn.functional.interpolate(tensor, scale_factor=2, mode='nearest')


class CoreTests(unittest.TestCase):
    def test_local_pass_skips_tiles_outside_mask_but_keeps_their_source_pixels(self):
        image=Image.fromarray(np.random.default_rng(5).integers(0,256,(53,79,3),dtype=np.uint8))
        coverage=Image.new('L',image.size);coverage.paste(255,(0,0,79,17))
        calls=[]
        class Counter(NearestModel):
            def __call__(self,tensor):calls.append(1);return super().__call__(tensor)
        result=tiled(image,Counter(),17,'cpu',lambda *a:None,threading.Event(),coverage)
        self.assertEqual(len(calls),5)
        expected=np.repeat(np.repeat(np.asarray(image),2,axis=0),2,axis=1)
        np.testing.assert_array_equal(np.asarray(result)[:34],expected[:34])
        fallback=image.resize((158,106),Image.Resampling.LANCZOS)
        self.assertEqual(result.crop((0,34,158,106)).tobytes(),fallback.crop((0,34,158,106)).tobytes())

    def test_tiles_preserve_edges_and_odd_dimensions(self):
        array = np.random.default_rng(4).integers(0, 256, (53, 79, 3), dtype=np.uint8)
        actual = tiled(Image.fromarray(array), NearestModel(), 17, 'cpu', lambda *a: None, threading.Event())
        expected = np.repeat(np.repeat(array, 2, axis=0), 2, axis=1)
        np.testing.assert_array_equal(np.array(actual), expected)

    def test_cancel_prevents_inference(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            tiled(Image.new('RGB', (50, 50)), NearestModel(), 16, 'cpu', lambda *a: None, event)

    def test_output_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Image.new('RGBA', (12, 13), (10, 20, 30, 80))
            first = save_unique(image, folder, 'портрет.jpg', 4)
            second = save_unique(image, folder, 'портрет.jpg', 4)
            self.assertNotEqual(first, second)
            with Image.open(second) as opened:
                self.assertEqual(opened.getpixel((0, 0)), (10, 20, 30, 80))


if __name__ == '__main__':
    unittest.main()

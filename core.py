"""Local inference and explicit model downloads. No photos are uploaded."""
import json
import math
import os
import sys
import threading
import urllib.request
import errno
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from storage import STORE

import numpy as np
from PIL import Image, ImageOps, ImageFilter

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
DATA = STORE.subdir('diagnostics')
MODELS = STORE.models
MODELS.mkdir(parents=True, exist_ok=True)
CATALOG = json.loads((ROOT / 'catalog.json').read_text(encoding='utf-8'))
_model_cache = None


def release_models(keep_nature=False):
    global _model_cache
    _model_cache = None
    portrait = sys.modules.get('portrait')
    if portrait is not None:
        portrait.release_models()
    nature = sys.modules.get('nature')
    if nature is not None and not keep_nature:
        nature.release_models()
    import gc
    gc.collect()
    torch = sys.modules.get('torch')
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled('Операция отменена')


def download(entry, report, cancel, directory=None):
    target = Path(directory or MODELS) / entry['file']
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        return target
    part = STORE.subdir('downloads')/(entry['file']+'.'+uuid.uuid4().hex+'.part')
    try:
        headers = {'User-Agent': 'PhotoRestoreStudio/0.1', 'Range': 'bytes=0-0'}
        request = urllib.request.Request(entry['url'], headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            ranged = response.status == 206 and response.headers.get('Content-Range')
            size = int(response.headers['Content-Range'].split('/')[-1]) if ranged else 0
        if ranged:
            with part.open('wb') as output:
                output.truncate(size)
            def fetch(start):
                end = min(size-1, start+1024*1024-1)
                for attempt in range(3):
                    check_cancel(cancel)
                    try:
                        request = urllib.request.Request(entry['url'], headers={
                            'User-Agent': 'PhotoRestoreStudio/0.1', 'Range': f'bytes={start}-{end}'})
                        with urllib.request.urlopen(request, timeout=30) as response:
                            if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}':
                                raise IOError('Сервер вернул неверный диапазон загрузки')
                            data = response.read()
                        if len(data) != end-start+1:
                            raise IOError('Неполный фрагмент модели')
                        with part.open('r+b') as output:
                            output.seek(start)
                            output.write(data)
                        return len(data)
                    except Exception:
                        if attempt == 2:
                            raise
            received = 0
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(fetch, start) for start in range(0, size, 1024*1024)]
                for future in as_completed(futures):
                    received += future.result()
                    report(f"Загрузка {entry['name']}: {received // 1048576}/{size // 1048576} МБ", int(received*100/size))
            check_cancel(cancel)
            verify_download(part,entry,cancel)
            install_model(part,target)
            return target
        request = urllib.request.Request(entry['url'], headers={'User-Agent': 'PhotoRestoreStudio/0.1'})
        with urllib.request.urlopen(request, timeout=30) as response, part.open('wb') as output:
            total = int(response.headers.get('Content-Length', 0))
            received = 0
            while True:
                check_cancel(cancel)
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                report(f"Загрузка {entry['name']}: {received // 1048576} МБ", int(received * 100 / total) if total else 0)
            if received == 0 or (total and received != total):
                raise IOError('Модель загрузилась не полностью')
        verify_download(part,entry,cancel)
        install_model(part,target)
    finally:
        part.unlink(missing_ok=True)
    return target


def verify_download(path,entry,cancel):
    if entry.get('sha256'):
        from model_downloads import sha256
        if sha256(path,cancel)!=entry['sha256']:
            raise ValueError('Контрольная сумма модели не совпала. Повторите загрузку.')


def install_model(part,target):
    """Downloads may live on another volume; the final rename stays atomic."""
    try:
        os.replace(part,target)
    except OSError as error:
        if error.errno != errno.EXDEV and getattr(error,'winerror',None) != 17:
            raise
        temporary = target.with_name(target.name+'.install-'+uuid.uuid4().hex)
        try:
            shutil.copyfile(part,temporary)
            os.replace(temporary,target)
        finally:
            temporary.unlink(missing_ok=True)


def tiled(image, model, tile, device, report, cancel,coverage=None):
    import torch
    import time
    from gpu_policy import Pacer
    pacer=Pacer(cancel)
    w, h = image.size
    scale = model.scale
    result = image.resize((w*scale,h*scale),Image.Resampling.LANCZOS) if coverage is not None else Image.new('RGB', (w * scale, h * scale))
    total = ((w + tile - 1) // tile) * ((h + tile - 1) // tile)
    count = 0
    # Context around each tile is discarded, avoiding hard boundary padding.
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            check_cancel(cancel)
            if coverage is not None and not coverage.crop((x,y,min(w,x+tile),min(h,y+tile))).getbbox():
                count+=1;report(f'Обработка фрагмента {count}/{total}',int(count*100/total))
                continue
            started=time.perf_counter()
            left, top = max(0, x - 32), max(0, y - 32)
            right, bottom = min(w, x + tile + 32), min(h, y + tile + 32)
            arr = np.array(image.crop((left, top, right, bottom)), dtype=np.float32) / 255
            if np.all(arr.max(axis=(0,1))==arr.min(axis=(0,1))):
                color=tuple(int(round(v*255)) for v in arr[0,0])
                result.paste(Image.new('RGB',((min(w,x+tile)-x)*scale,(min(h,y+tile)-y)*scale),color),(x*scale,y*scale))
                count+=1;report(f'Обработка фрагмента {count}/{total}',int(count*100/total))
                continue
            tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(device=device,dtype=getattr(model,'dtype',torch.float32))
            with torch.inference_mode():
                prediction = model(tensor).float().clamp(0, 1).cpu()[0]
            pixels = (prediction.permute(1, 2, 0).numpy() * 255).round().astype(np.uint8)
            patch = Image.fromarray(pixels)
            patch = patch.crop(((x-left)*scale, (y-top)*scale,
                                (min(w,x+tile)-left)*scale, (min(h,y+tile)-top)*scale))
            result.paste(patch, (x*scale, y*scale))
            count += 1
            report(f'Обработка фрагмента {count}/{total}', int(count * 100 / total))
            if device=='cuda':pacer.pause(started)
    return result


def restore_faces(image, strength, report, cancel):
    from portrait import enhance
    return enhance(image.convert('RGB'),image,1,dict(faces=True,face_model='gfpgan',face_strength=strength),report,cancel)


def upscale_image(image,model_path,factor,tile,report,cancel,coverage=None,*,trim_frame=True):
    global _model_cache
    check_cancel(cancel)
    import torch
    from spandrel import ModelLoader, ImageModelDescriptor
    w, h = image.size
    if factor not in range(1, 9) or tile < 16:
        raise ValueError('Допустим масштаб ×1–×8 и фрагмент не менее 16 пикселей')
    if w * h * factor * factor > 120_000_000:
        raise ValueError('Результат больше 120 мегапикселей. Уменьшите масштаб или обрежьте исходник.')
    if trim_frame and coverage is None:
        from PIL import ImageChops
        background=image.getpixel((0,0))
        bounds=ImageChops.difference(image,Image.new(image.mode,image.size,background)).getbbox()
        if bounds is None:return Image.new('RGB',(w*factor,h*factor),background)
        left,top,right,bottom=bounds
        context=(max(0,left-32),max(0,top-32),min(w,right+32),min(h,bottom+32))
        if (context[2]-context[0])*(context[3]-context[1])<w*h*.8:
            inner=upscale_image(image.crop(context),model_path,factor,tile,report,cancel,trim_frame=False)
            out=Image.new('RGB',(w*factor,h*factor),background)
            cut=((left-context[0])*factor,(top-context[1])*factor,(right-context[0])*factor,(bottom-context[1])*factor)
            out.paste(inner.crop(cut),(left*factor,top*factor));out.info['inference_roi']=list(context)
            return out
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model_path = Path(model_path).resolve()
    cache_key = (str(model_path), model_path.stat().st_mtime_ns, device)
    if _model_cache is None or _model_cache[0] != cache_key:
        _model_cache = None
        if device == 'cuda':
            torch.cuda.empty_cache()
        # Retain Spandrel's restricted unpickler and fall back for old .pth formats.
        class MappedLoader(ModelLoader):
            def _load_pth(self,path):
                from spandrel.__helpers.unpickler import RestrictedUnpickle
                try:
                    return torch.load(path,map_location=self.device,pickle_module=RestrictedUnpickle,mmap=True)
                except RuntimeError as error:
                    if 'mmap' not in str(error).lower():
                        raise
                    return super()._load_pth(path)
        model = MappedLoader().load_from_file(str(model_path))
        if not isinstance(model, ImageModelDescriptor) or model.input_channels != 3 or model.output_channels != 3:
            raise ValueError('Нужна совместимая RGB-модель восстановления или апскейла')
        model = model.to(device).eval()
        if device=='cuda' and model.supports_half and model_path.name.startswith('RealESRGAN'):
            model=model.half()
        elif device=='cuda' and model.supports_bfloat16 and torch.cuda.is_bf16_supported():
            model=model.to(dtype=torch.bfloat16)
        _model_cache = (cache_key, model)
    else:
        model = _model_cache[1]
    report(f'Устройство: {device}; собственный масштаб модели ×{model.scale}', 0)
    shapes = [(w, h)]
    current_scale = model.scale
    while factor > current_scale and model.scale > 1:
        next_scale = min(factor, current_scale * model.scale)
        intermediate = (max(1, round(w * next_scale / model.scale)), max(1, round(h * next_scale / model.scale)))
        shapes.append(intermediate)
        current_scale = next_scale
    counts = [((width+tile-1)//tile)*((height+tile-1)//tile) for width,height in shapes]
    total = sum(counts)
    completed = 0
    for index, shape in enumerate(shapes):
        if index:
            image = image.resize(shape, Image.Resampling.LANCZOS)
        def stage_report(text, value, offset=completed, count=counts[index], stage=index+1):
            report(f'Проход {stage}/{len(shapes)} · {text}', int(96*(offset+count*value/100)/total))
        stage_coverage=coverage.resize(image.size,Image.Resampling.NEAREST) if coverage is not None else None
        image = tiled(image, model, tile, device, stage_report, cancel,stage_coverage)
        completed += counts[index]
    check_cancel(cancel)
    image = image.resize((w*factor, h*factor), Image.Resampling.LANCZOS)
    report('Подготовка результата',98)
    return image


def process(source,model_path,factor,tile,faces,strength,report,cancel):
    with Image.open(source) as opened:
        original = ImageOps.exif_transpose(opened).copy()
    rgb = original.convert('RGB')
    image = upscale_image(rgb,model_path,factor,tile,
        lambda text,value:report(text,int(value*.85) if faces else value),cancel)
    if faces:
        from portrait import enhance
        image = enhance(rgb,image,factor,dict(faces=True,face_model='gfpgan',face_strength=strength),
            lambda text,value:report(text,85+int(value*.13)),cancel)
    alpha = original.getchannel('A') if 'A' in original.getbands() else None
    icc = original.info.get('icc_profile')
    if alpha is not None:
        image.putalpha(alpha.resize(image.size, Image.Resampling.LANCZOS))
    if icc:
        image.info['icc_profile'] = icc
    report('Подготовка результата', 98)
    return image


def apply_effects(source, restored, effect=1.0, sharpness=0, smoothing=0,light=None):
    """Adjust a cached AI result without repeating inference. Preserve alpha and ICC."""
    with Image.open(source) as opened:
        original = ImageOps.exif_transpose(opened).convert('RGB')
    original = original.resize(restored.size, Image.Resampling.LANCZOS)
    result = Image.blend(original, restored.convert('RGB'), max(0.0, min(1.0, effect)))
    if smoothing:
        blurred = result.filter(ImageFilter.GaussianBlur(radius=0.85))
        result = Image.blend(result, blurred, max(0.0, min(1.0, smoothing/100)))
    if sharpness:
        result = result.filter(ImageFilter.UnsharpMask(radius=1.2, percent=int(sharpness*2), threshold=3))
    result.info.update(restored.info)
    if light:
        from lighting import correct_light
        result = correct_light(result,**light)
    if 'A' in restored.getbands():
        result.putalpha(restored.getchannel('A'))
    if restored.info.get('icc_profile'):
        result.info['icc_profile'] = restored.info['icc_profile']
    return result


def save_unique(image, directory, source, factor, image_format='PNG', dpi=300, quality=95):
    """Use the application name and actual scale; DPI remains metadata only."""
    image_format = image_format.upper()
    if image_format == 'JPG':
        image_format = 'JPEG'
    if image_format not in ('PNG', 'JPEG', 'SVG'):
        raise ValueError('Выберите формат PNG, JPEG или SVG для графики.')
    if not 15 <= dpi <= 600:
        raise ValueError('Разрешение печати должно быть от 15 до 600 DPI.')
    if not 1 <= quality <= 100:
        raise ValueError('Качество JPEG должно быть от 1 до 100.')
    if not math.isfinite(factor) or not 1 <= factor <= 8:
        raise ValueError('Масштаб экспорта должен быть от ×1 до ×8.')
    extension = {'JPEG':'jpg','PNG':'png','SVG':'svg'}[image_format]
    scale_name=f'{factor:.6g}'
    destination = Path(directory) / f'PhotoRestoreStudio_x{scale_name}.{extension}'
    index = 1
    while destination.exists():
        destination = Path(directory) / f'PhotoRestoreStudio_x{scale_name}_{index}.{extension}'
        index += 1
    temporary = destination.with_suffix('.tmp')
    try:
        if image_format=='SVG':
            from graphics import export_svg
            temporary.write_text(export_svg(image,dpi),encoding='utf-8')
            os.replace(temporary,destination)
            return destination
        options = dict(dpi=(dpi,dpi), icc_profile=image.info.get('icc_profile'))
        exported = image
        if image_format == 'JPEG':
            rgba = image.convert('RGBA')
            exported = Image.new('RGB', image.size, 'white')
            exported.paste(rgba, mask=rgba.getchannel('A'))
            options.update(quality=quality, subsampling=0)
        exported.save(temporary, format=image_format, **options)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination

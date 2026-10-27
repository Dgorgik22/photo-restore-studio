"""Photo, selective cloud detail and portrait restoration in an offline GPU process."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from PIL import Image,ImageOps
from core import check_cancel
from storage import STORE

VERSION='studio-restoration-v8-reused-detail'


def publish_progress(folder,message,percent):
    temporary=folder/'progress.tmp'
    temporary.write_text(json.dumps(dict(message=message,percent=percent)),encoding='utf-8')
    for _ in range(5):
        try:os.replace(temporary,folder/'progress.json');return
        except PermissionError:time.sleep(.015)


def clean_input(image,amount):
    """Conservative luminance/chroma cleanup at source resolution on the CPU."""
    import cv2
    import numpy as np
    if not amount:return image.copy()
    original=image.convert('RGB');result=Image.new('RGB',original.size)
    for top in range(0,original.height,256):
        start=max(0,top-16);end=min(original.height,top+256+16)
        pixels=np.asarray(original.crop((0,start,original.width,end)))
        cleaned=cv2.fastNlMeansDenoisingColored(pixels,None,4,6,7,21)
        patch=Image.fromarray(cleaned).crop((0,top-start,original.width,min(top+256,original.height)-start))
        result.paste(patch,(0,top))
    return Image.blend(original,result,max(0,min(1,amount)))


def detect_regions(source):
    """Lightweight face locator for local light controls; no extra neural weights."""
    import cv2
    import numpy as np
    with Image.open(source) as opened:im=ImageOps.exif_transpose(opened).convert('RGB')
    size=im.size;im.thumbnail((1600,1600))
    detector=cv2.CascadeClassifier(str(Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml'))
    faces=detector.detectMultiScale(cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2GRAY),1.1,5,minSize=(24,24))
    return [[float(x/im.width),float(y/im.height),float((x+w)/im.width),float((y+h)/im.height)] for x,y,w,h in faces]


def run(source,factor,strength,cleanup,protect,report,cancel,gpu_mode='balanced',*,generation=False,scene='mixed',faces=False,face_strength=.6,face_fidelity=.8,tile=128,model_path=None,hair=False,hair_strength=.65,algorithm='photo',auto_detail=False,vector=False,vector_colors=8,vector_smoothness=30):
    check_cancel(cancel)
    if algorithm not in ('photo','graphics'):raise ValueError('Этот экспериментальный обработчик удалён. Выберите действующий режим.')
    with Image.open(source) as opened:original=ImageOps.exif_transpose(opened).copy()
    if original.width*original.height*factor*factor>120_000_000:
        raise ValueError('Результат больше 120 мегапикселей. Уменьшите масштаб.')
    from core import release_models
    release_models()
    started=time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='restore-',dir=STORE.scratch) as temporary:
        folder=Path(temporary)
        (original if algorithm=='graphics' else original.convert('RGB')).save(folder/'source.png')
        payload=dict(folder=str(folder),factor=factor,strength=strength,cleanup=cleanup,protect=protect,gpu_mode=gpu_mode,
                     scene=scene,faces=faces,face_strength=face_strength,face_fidelity=face_fidelity,tile=tile,
                     model_path=str(model_path) if model_path else None,hair=hair,hair_strength=hair_strength,algorithm=algorithm,auto_detail=auto_detail,
                     vector=vector,vector_colors=vector_colors,vector_smoothness=vector_smoothness)
        request=folder/'request.json';request.write_text(json.dumps(payload),encoding='utf-8')
        command=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).with_name('app.py'))]
        with (folder/'worker.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen(command+['--studio-worker',str(request)],stdout=log,stderr=log,
                env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PYTHONIOENCODING':'utf-8'},
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            previous=None
            try:
                while process.poll() is None:
                    check_cancel(cancel)
                    if time.perf_counter()-started>3600:raise TimeoutError('Обработка превысила час. Уменьшите размер изображения.')
                    try:
                        progress=json.loads((folder/'progress.json').read_text(encoding='utf-8'))
                        if progress!=previous:report(progress['message'],progress['percent']);previous=progress
                    except (OSError,ValueError):pass
                    cancel.wait(.08)
            finally:
                if process.poll() is None:
                    from worker_process import stop_process_tree
                    stop_process_tree(process)
        check_cancel(cancel)
        status=json.loads((folder/'status.json').read_text(encoding='utf-8')) if (folder/'status.json').exists() else {}
        if process.returncode or not status.get('ok'):
            raise RuntimeError('Восстановление: '+status.get('error',(folder/'worker.log').read_text(encoding='utf-8',errors='replace')[-1800:]))
        with Image.open(folder/'result.png') as opened:result=opened.copy()
        if result.size!=(original.width*factor,original.height*factor):raise RuntimeError('Модель вернула неверный размер.')
        if algorithm=='graphics':
            result.info['graphics_mode']=True
            if (folder/'result.svg').exists():result.info['graphics_svg']=(folder/'result.svg').read_text(encoding='utf-8')
        else:
            if 'A' in original.getbands():result.putalpha(original.getchannel('A').resize(result.size,Image.Resampling.LANCZOS))
        if original.info.get('icc_profile') and not (algorithm=='graphics' and vector):result.info['icc_profile']=original.info['icc_profile']
        result.info['studio_stats']={**status,'seconds':round(time.perf_counter()-started,3)}
        for name in ('portrait_regions','portrait_stats','sky_detail_stats','natural_detail_stats','portrait_texture_stats','architecture_stats'):
            if status.get(name):result.info[name]=status[name]
        return result



def worker(request_file):
    data=json.loads(Path(request_file).read_text(encoding='utf-8'));folder=Path(data['folder'])
    def report(text,value):publish_progress(folder,text,value)
    try:
        if data.get('algorithm')=='graphics':
            import threading
            from graphics import process
            base=process(folder/'source.png',data['factor'],data.get('vector',False),data.get('vector_colors',8),
                         data.get('vector_smoothness',30),report,threading.Event())
            base.save(folder/'result.png',compress_level=1)
            if base.info.get('graphics_svg'):(folder/'result.svg').write_text(base.info['graphics_svg'],encoding='utf-8')
            (folder/'status.json').write_text(json.dumps(dict(ok=True,algorithm='graphics-v1',
                graphics_stats=base.info['graphics_stats'],torch_loaded='torch' in sys.modules)),encoding='utf-8')
            return 0
        if data.get('algorithm','photo')!='photo':raise ValueError('Этот экспериментальный обработчик удалён. Выберите действующий режим.')
        # Install/download code is never called while processing photographs.
        import urllib.request
        def offline(*args,**kwargs):raise RuntimeError('Сеть во время обработки отключена.')
        urllib.request.urlopen=offline
        import requests
        requests.sessions.Session.request=offline
        import torch,threading,gc
        timings={};stage=time.perf_counter()
        from core import upscale_image,MODELS,release_models
        from gpu_policy import use_mode
        torch.set_num_threads(max(1,min(8,(os.cpu_count() or 4)//2)))
        if torch.cuda.is_available():torch.cuda.reset_peak_memory_stats()
        cancel=threading.Event()
        with use_mode(data['gpu_mode']):
            with Image.open(folder/'source.png') as opened:original=opened.convert('RGB')
            timings['setup']=round(time.perf_counter()-stage,3);stage=time.perf_counter()
            report('Очистка JPEG и шума…',1)
            cleaned=clean_input(original,data['cleanup'])
            timings['cleanup']=round(time.perf_counter()-stage,3);stage=time.perf_counter()
            model_path=Path(data['model_path']) if data.get('model_path') else MODELS/'RealESRGAN_x4plus.pth'
            portrait_mode=bool(data['faces'] or data.get('hair'))
            effective_tile=data['tile']
            if portrait_mode and torch.cuda.is_available() and torch.cuda.mem_get_info()[0]<4*1024**3:
                effective_tile=min(effective_tile,256)
            native_factor=min(4,data['factor']) if portrait_mode else data['factor']
            base=upscale_image(cleaned,model_path,native_factor,effective_tile,
                lambda text,value:report(text,3+int(value*(.60 if data.get('auto_detail') else .82))),cancel)
            if native_factor!=data['factor']:base=base.resize((original.width*data['factor'],original.height*data['factor']),Image.Resampling.LANCZOS)
            timings['base']=round(time.perf_counter()-stage,3);stage=time.perf_counter()
            release_models()
            if data.get('auto_detail'):
                from sky_detail import refine_clouds
                base=refine_clouds(original,base,data['factor'],data['tile'],
                    lambda text,value:report(text,66+int(value*.18)),cancel)
                release_models()
                from natural_detail import preserve_natural_detail
                report('Проработка листвы и ряби воды…',85)
                base=preserve_natural_detail(original,base,cancel)
                from architecture_detail import regularize
                report('Восстановление геометрии фасадов…',94)
                base=regularize(original,base,cancel)
            if data['faces'] or data.get('hair'):
                from portrait import enhance
                base=enhance(original,base,data['factor'],dict(faces=data['faces'],face_model='codeformer',
                    face_strength=data['face_strength'],face_fidelity=data['face_fidelity'],hair_natural=data.get('hair',False),
                    hair_model='pbrify-detail',hair_strength=data.get('hair_strength',.65),tile=effective_tile,
                    portrait_detail=model_path.name=='4x-PBRify_UpscalerV4.safetensors'),
                    lambda text,value:report(text,85+int(value*.13)),cancel)
                from portrait_texture import preserve_texture
                base=preserve_texture(original,base,base.info.get('portrait_regions',[]),cancel,skin_detail=False)
            timings['detail']=round(time.perf_counter()-stage,3);stage=time.perf_counter()
            base.save(folder/'result.png',compress_level=1)
            timings['transport_save']=round(time.perf_counter()-stage,3)
            stats=dict(ok=True,algorithm=VERSION,size=list(base.size),mode=data.get('algorithm','photo'),
                inference_roi=base.info.get('inference_roi'),timings=timings,effective_tile=effective_tile,cleanup=data['cleanup'],base_neural_factor=native_factor,base_sampling_passes=1 if portrait_mode else None,
                peak_vram_mb=round(torch.cuda.max_memory_allocated()/1024**2) if torch.cuda.is_available() else 0,
                portrait_regions=base.info.get('portrait_regions',[]),portrait_stats=base.info.get('portrait_stats',{}),
                sky_detail_stats=base.info.get('sky_detail_stats',{}),natural_detail_stats=base.info.get('natural_detail_stats',{}),
                portrait_texture_stats=base.info.get('portrait_texture_stats',{}),architecture_stats=base.info.get('architecture_stats',{}))
            (folder/'status.json').write_text(json.dumps(stats),encoding='utf-8')
        release_models()
        return 0
    except Exception as error:
        import traceback
        traceback.print_exc()
        (folder/'status.json').write_text(json.dumps(dict(ok=False,error=str(error))),encoding='utf-8')
        return 1

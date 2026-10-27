"""One job dispatcher for the installed photo pipelines and imported upscalers."""
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from PIL import Image,ImageOps
from PySide6.QtCore import QThread,Signal
from core import process,apply_effects,save_unique,Cancelled,check_cancel,MODELS
from storage import STORE


@dataclass(frozen=True)
class RenderRequest:
    revision: int
    source: str
    model: str
    factor: int
    tile: int
    faces: bool
    face_strength: float
    effect: float
    sharpness: int
    smoothing: int
    face_model: str = 'codeformer'
    face_fidelity: float = .8
    hair_natural: bool = False
    hair_strength: float = .65
    exposure: int = 0
    shadows: int = 0
    highlights: int = 0
    temperature: int = 0
    light_faces: bool = True
    hair_model: str = 'pbrify-detail'
    nature_repair: float = 0
    output_scale: float = 0
    gpu_mode: str = 'balanced'
    backend: str = 'standard'
    surface_protection: float = 0
    shadow_detail: int = 0
    automatic_detail: bool = False
    vector: bool = False
    vector_colors: int = 8
    vector_smoothness: int = 30

    @property
    def export_factor(self):
        value=self.output_scale or self.factor
        return int(value) if value==int(value) else value

    @property
    def dependency_versions(self):
        paths=[]
        if self.automatic_detail:
            paths+=[MODELS/'4x-PBRify_UpscalerV4.safetensors']
        if self.hair_natural:
            from portrait import HAIR_MODELS
            paths+=[MODELS/HAIR_MODELS[self.hair_model]]
        if self.faces or self.hair_natural:
            paths+=[MODELS/'RealESRGAN_x4plus.pth',STORE.plugins/'gfpgan/weights/detection_Resnet50_Final.pth',
                    STORE.plugins/'gfpgan/weights/parsing_parsenet.pth']
        if self.faces:paths+=[MODELS/('codeformer.pth' if self.face_model=='codeformer' else 'GFPGANv1.4.pth')]
        return tuple((str(p),p.stat().st_mtime_ns if p.exists() else None) for p in paths)

    @property
    def background_key(self):
        source,model=Path(self.source),Path(self.model)
        if self.backend=='graphics':
            from graphics import VERSION
            return ('graphics',VERSION,str(source),source.stat().st_mtime_ns,self.factor,
                    self.vector,self.vector_colors if self.vector else 0,self.vector_smoothness if self.vector else 0)
        base=(str(source),source.stat().st_mtime_ns,str(model),model.stat().st_mtime_ns,self.factor,self.tile)
        if self.backend=='studio':
            from studio_backend import VERSION
            return ('studio',VERSION,*base,self.nature_repair,self.faces,self.face_strength if self.faces else 0,
                    self.face_fidelity if self.faces else 0,self.hair_natural,
                    self.hair_strength if self.hair_natural else 0,self.automatic_detail,self.dependency_versions)
        return ('upscale',*base)

    @property
    def key(self):
        if self.backend=='studio' or not (self.faces or self.hair_natural):return self.background_key
        return ('portrait',self.background_key,self.faces,self.face_model,self.face_strength,self.face_fidelity,
                self.hair_natural,self.hair_strength,self.hair_model,self.dependency_versions)

    @property
    def light_active(self):return any((self.exposure,self.shadows,self.highlights,self.temperature))


def render_image(r,image_cache,report,cancel,process_fn=None,cached_base=None,cached_key=None):
    from gpu_policy import use_mode
    try:
        with use_mode(r.gpu_mode):
            result=_render_image(r,image_cache,report,cancel,process_fn,cached_base,cached_key)
            if image_cache is not None:image_cache.retain_recent(3)
            return result
    finally:
        from core import release_models
        release_models()


def _render_image(r,image_cache,report,cancel,process_fn=None,cached_base=None,cached_key=None):
    key=r.key
    base=image_cache.get(key) if image_cache is not None else (cached_base if cached_key==key else None)
    if base is None:
        if r.backend in ('studio','graphics'):
            from studio_backend import run
            base=run(r.source,r.factor,0,r.nature_repair,True,report,cancel,r.gpu_mode,
                faces=r.faces,face_strength=r.face_strength,face_fidelity=r.face_fidelity,tile=r.tile,
                model_path=r.model,hair=r.hair_natural,hair_strength=r.hair_strength,
                auto_detail=r.automatic_detail,algorithm='graphics' if r.backend=='graphics' else 'photo',
                vector=r.vector,vector_colors=r.vector_colors,vector_smoothness=r.vector_smoothness)
        else:
            active=r.faces or r.hair_natural
            background=image_cache.get(r.background_key) if image_cache is not None and active else None
            if background is None:
                background=(process_fn or process)(r.source,r.model,r.factor,r.tile,False,r.face_strength,
                    lambda text,value:report(text,int(value*(.85 if active else 1))),cancel)
                check_cancel(cancel)
                if image_cache is not None and active:image_cache.put(r.background_key,background)
            base=background
            if active:
                from portrait import enhance
                with Image.open(r.source) as opened:original=ImageOps.exif_transpose(opened).convert('RGB')
                base=enhance(original,background,r.factor,
                    dict(faces=r.faces,face_model=r.face_model,face_strength=r.face_strength,face_fidelity=r.face_fidelity,
                         hair_natural=r.hair_natural,hair_strength=r.hair_strength,hair_model=r.hair_model,tile=r.tile),
                    lambda text,value:report(text,85+int(value*.13)),cancel,image_cache,r.background_key[1:3])
        if image_cache is not None:image_cache.put(key,base)
    check_cancel(cancel)
    if (r.light_active or r.surface_protection or r.shadow_detail) and r.light_faces and 'portrait_regions' not in base.info:
        from studio_backend import detect_regions
        report('Определение области лица для света',98)
        base.info['portrait_regions'] = detect_regions(r.source)
        if image_cache is not None:
            image_cache.put(key,base)
    light = dict(exposure=r.exposure,shadows=r.shadows,highlights=r.highlights,temperature=r.temperature,
                 regions=base.info.get('portrait_regions',[]) if r.light_faces else None) if r.light_active else None
    report('Применение настроек',98)
    final = base.copy() if r.backend=='graphics' else apply_effects(r.source,base,r.effect,r.sharpness,r.smoothing)
    if r.surface_protection or r.shadow_detail:
        from surface_light import preserve_surface_light
        final=preserve_surface_light(r.source,final,r.surface_protection,r.shadow_detail,
            base.info.get('portrait_regions',[]) if r.light_faces else None)
    if light:
        from lighting import correct_light
        final=correct_light(final,**light)
    check_cancel(cancel)
    if r.output_scale and abs(r.output_scale-r.factor)>1e-9:
        target=(max(1,round(base.width/r.factor*r.output_scale)),max(1,round(base.height/r.factor*r.output_scale)))
        metadata=final.info.copy()
        if r.backend=='graphics' and r.vector:
            from graphics import rasterize
            final=rasterize(base.info['graphics_svg'],target)
        else:final=final.resize(target,Image.Resampling.LANCZOS)
        final.info.update(metadata)
    return dict(request=r,key=key,base=base,image=final)

class RenderWorker(QThread):
    progress = Signal(str, int)
    result = Signal(object)
    error = Signal(str)
    def __init__(self, request, cached_base=None, cached_key=None, image_cache=None):
        super().__init__()
        self.request = request
        self.cancel = threading.Event()
        self.cached_base, self.cached_key = cached_base, cached_key
        self.image_cache = image_cache

    def run(self):
        r = self.request
        try:
            payload = render_image(r,self.image_cache,self.progress.emit,self.cancel,cached_base=self.cached_base,cached_key=self.cached_key)
            self.progress.emit('Готово', 100)
            self.result.emit(payload)
        except Cancelled:
            pass
        except Exception as error:
            self.error.emit(f'{type(error).__name__}: {error}')


class FileWorker(QThread):
    progress = Signal(str, int)
    completed = Signal(object)
    error = Signal(str)
    def __init__(self, action):
        super().__init__()
        self.action = action
        self.cancel = threading.Event()

    def run(self):
        try:
            self.completed.emit(self.action(self))
        except Cancelled:
            pass
        except Exception as error:
            self.error.emit(f'{type(error).__name__}: {error}')


class Estimate:
    def __init__(self):
        self.started = time.monotonic()
        self.last = 0
        self.samples = 0

    def update(self, percent, now=None):
        now = time.monotonic() if now is None else now
        if percent > self.last:
            self.last = percent
            self.samples += 1
        if percent >= 100:
            return 'Готово'
        elapsed = now-self.started
        if percent < 1 or self.samples < 2 or elapsed < .8:
            return 'Оценка времени…'
        seconds = max(1, round(elapsed*(100-percent)/percent))
        if seconds < 60:
            return f'≈ {seconds} с осталось'
        return f'≈ {seconds//60} мин {seconds%60:02d} с осталось'

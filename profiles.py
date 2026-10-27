"""Photo restoration and a separate model-free graphics pipeline."""
PRESETS = [
    dict(id='photo',title='Пейзажи и интерьеры',subtitle='Real-ESRGAN · вода, облака, архитектура и поверхности',
         model='realesrgan-photo',tools='landscape',effect=100,tile=256,nature_repair=0,
         surface_protection=70,shadow_detail=0,light_faces=False,nature_expanded=True),
    dict(id='portrait',title='Портреты',subtitle='PBRify · одежда и волосы, единое восстановление лица',
         model='pbrify-detail',tools='portrait',effect=100,tile=384,faces=True,face_model='codeformer',
         face_strength=100,face_fidelity=90,hair_strength=100,hair_model='pbrify-detail',
         nature_repair=0,surface_protection=75),
    dict(id='graphics',title='Графика и иллюстрации',subtitle='Чистые линии и оттенки · SVG-векторизация без нейросети',
         model='graphics',tools='graphics',effect=100,sharpness=0,smoothing=0,light_faces=False),
]


def resolve_profile(preset,quality=None):return {**preset,'quality':1}


def represented_models():return {preset['model'] for preset in PRESETS}


def confidence_threshold(sensitivity):return round(.7-.5*max(0,min(100,int(sensitivity)))/100,4)

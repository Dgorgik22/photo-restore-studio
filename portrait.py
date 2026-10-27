"""Restore aligned faces after upscale; hair uses its own masked, soft-model pass."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image,ImageFilter
from storage import STORE

_helper = None
_restorer = None
# ParseNet uses CelebAMask-HQ order; the rest of the editor uses BiSeNet order.
PARSENET_TO_CANONICAL=np.array([0,1,10,6,4,5,2,3,7,8,11,12,13,17,18,9,15,14,16],np.uint8)
HAIR_MODELS = {'realesrnet-soft':'RealESRNet_x4plus.pth','swinir-photo':'SwinIR-M_x4_GAN.pth',
               'realesrgan-photo':'RealESRGAN_x4plus.pth','pbrify-detail':'4x-PBRify_UpscalerV4.safetensors'}


def release_models():
    global _helper,_restorer
    _helper = _restorer = None


def face_helper(factor=1):
    global _helper
    import torch
    import torchvision.transforms.functional as functional
    sys.modules.setdefault('torchvision.transforms.functional_tensor',functional)
    if _helper is None:
        from facexlib.utils.face_restoration_helper import FaceRestoreHelper
        _helper = FaceRestoreHelper(factor,face_size=512,crop_ratio=(1,1),det_model='retinaface_resnet50',
            use_parse=True,device=torch.device('cuda' if torch.cuda.is_available() else 'cpu'),
            model_rootpath=str(STORE.plugins/'gfpgan'/'weights'))
    _helper.set_upscale_factor(factor)
    return _helper


def analyze(image,factor=1):
    helper = face_helper(factor)
    helper.clean_all()
    helper.read_image(np.array(image.convert('RGB'))[:,:,::-1].copy())
    helper.get_face_landmarks_5(resize=640,only_center_face=False,eye_dist_threshold=5)
    width,height = image.size
    regions = [[float(max(0,box[0])/width),float(max(0,box[1])/height),
                float(min(width,box[2])/width),float(min(height,box[3])/height)] for box in helper.det_faces]
    return helper,regions


def detect_regions(source):
    from PIL import ImageOps
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGB')
    return analyze(image)[1]


def parse_labels(helper,bgr):
    import cv2
    import torch
    array = cv2.resize(bgr,(512,512),interpolation=cv2.INTER_LINEAR)[:,:,::-1].copy()
    tensor = torch.from_numpy(array).permute(2,0,1).float().div_(127.5).sub_(1).unsqueeze(0).to(helper.device)
    with torch.inference_mode():
        labels = helper.face_parse(tensor)[0].argmax(dim=1).squeeze().cpu().numpy()
    return PARSENET_TO_CANONICAL[labels]


def restorer(identifier,device):
    global _restorer
    import torch
    from core import MODELS
    filename = 'codeformer.pth' if identifier == 'codeformer' else 'GFPGANv1.4.pth'
    path = MODELS/filename
    if not path.exists():
        raise ValueError(f'Установите {identifier.upper()} в библиотеке моделей.')
    key = identifier,str(device),path.stat().st_mtime_ns
    if _restorer is None or _restorer[0] != key:
        _restorer = None
        if identifier == 'codeformer':
            from third_party.codeformer.codeformer_arch import CodeFormer
            model = CodeFormer(dim_embd=512,codebook_size=1024,n_head=8,n_layers=9,connect_list=['32','64','128','256'])
        else:
            from gfpgan.archs.gfpganv1_clean_arch import GFPGANv1Clean
            model = GFPGANv1Clean(out_size=512,num_style_feat=512,channel_multiplier=2,decoder_load_path=None,
                fix_decoder=False,num_mlp=8,input_is_latent=True,different_w=True,narrow=1,sft_half=True)
        try:
            state = torch.load(path,map_location='cpu',weights_only=True,mmap=True)
        except RuntimeError as error:
            if 'mmap' not in str(error).lower():
                raise
            state = torch.load(path,map_location='cpu',weights_only=True)
        model.load_state_dict(state.get('params_ema',state.get('params',state)),strict=True)
        _restorer = key,model.eval().to(device)
    return _restorer[1]


def restore_crop(helper,crop,identifier,fidelity):
    import torch
    model = restorer(identifier,helper.device)
    tensor = torch.from_numpy(crop[:,:,::-1].copy()).permute(2,0,1).float().div_(127.5).sub_(1).unsqueeze(0).to(helper.device)
    with torch.inference_mode():
        output = model(tensor,w=float(fidelity),adain=True)[0] if identifier == 'codeformer' else model(tensor,return_rgb=False,weight=.5)[0]
    rgb = output[0].float().clamp(-1,1).add(1).mul(127.5).permute(1,2,0).cpu().numpy().round().astype(np.uint8)
    return rgb


def face_mask(labels,hair_strength=None):
    import cv2
    mask = np.isin(labels,list(range(1,15))).astype(np.float32)
    mask = cv2.GaussianBlur(mask,(0,0),8)
    # Explicitly exclude original hair/hat after feathering, avoiding hair-boundary replacement.
    mask[np.isin(labels,[16,17,18])] = 0
    if hair_strength is not None:
        hair=cv2.GaussianBlur((labels==17).astype(np.float32),(0,0),8)*max(0,min(1,hair_strength))
        mask=np.maximum(mask,hair);mask[np.isin(labels,[16,18])]=0
    mask[:8,:] = mask[-8:,:] = mask[:,:8] = mask[:,-8:] = 0
    return np.clip(mask,0,1)


def paste_face(background,rgb,mask,inverse,factor,strength):
    import cv2
    inverse = np.array(inverse,dtype=np.float32,copy=True)
    if factor > 1:
        inverse[:,2] += .5*factor
    height,width=rgb.shape[:2]
    ratios=np.array([512/width,512/height],np.float32)
    inverse[:,2]+=inverse[:,:2]@((ratios-1)*.5)
    inverse[:,:2]*=ratios
    if mask.shape!=(height,width):mask=cv2.resize(mask,(width,height),interpolation=cv2.INTER_LINEAR)
    corners = cv2.transform(np.array([[[0,0],[width,0],[width,height],[0,height]]],np.float32),inverse)[0]
    left,top = np.maximum(0,np.floor(corners.min(axis=0)).astype(int))
    right,bottom = np.minimum(background.size,np.ceil(corners.max(axis=0)).astype(int))
    if right <= left or bottom <= top:
        return
    inverse[:,2] -= [left,top]
    size = int(right-left),int(bottom-top)
    restored = cv2.warpAffine(rgb,inverse,size,flags=cv2.INTER_CUBIC).astype(np.float32)
    alpha = cv2.warpAffine(mask,inverse,size,flags=cv2.INTER_LINEAR).clip(0,1)[:,:,None]*strength
    original = np.array(background.crop((left,top,right,bottom)),dtype=np.float32)
    patch = (original*(1-alpha)+restored*alpha).clip(0,255).round().astype(np.uint8)
    background.paste(Image.fromarray(patch),(int(left),int(top)))


def facial_hair_mask(rgb,labels,face_box=None,nose_y=None):
    """Conservative beard/moustache mask from skin-relative colour and real texture."""
    import cv2
    h,w=labels.shape
    left,top,right,bottom=face_box or (w*.18,h*.12,w*.82,h*.93)
    fw,fh=right-left,bottom-top
    yy,xx=np.mgrid[:h,:w];gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV).astype(np.float32)/255
    cheeks=(labels==1)&(yy>top+.22*fh)&(yy<top+.5*fh)
    if np.count_nonzero(cheeks)<20:return np.zeros((h,w),np.float32)
    skin_luma=float(np.median(gray[cheeks]));skin_sat=float(np.median(hsv[:,:,1][cheeks]))
    dark=np.clip((skin_luma-gray-.035)/.18,0,1)
    grey=np.clip((skin_sat-hsv[:,:,1]-.035)/.13,0,1)
    texture=cv2.GaussianBlur(abs(gray-cv2.GaussianBlur(gray,(0,0),1.)),(0,0),1.5)
    texture=np.clip((texture-.003)/.015,0,1)
    start=max(top+.64*fh,(nose_y+.10*fh) if nose_y is not None else h*.69)
    region=(yy>start)&(yy<bottom+.07*fh)&(abs(xx-(left+right)/2)<fw*.46)
    allowed=np.isin(labels,[1,17])
    allowed&=~(cv2.dilate(np.isin(labels,[4,5,6,10,11,12,13]).astype(np.uint8),np.ones((9,9),np.uint8))>0)
    mask=np.maximum(dark,grey)*texture*region*allowed
    mask=cv2.GaussianBlur(mask.astype(np.float32),(0,0),1.5)
    mask[~allowed]=0
    return mask.clip(0,1)


def natural_hair(original,background,helper,factor,strength,tile,report,cancel,cache=None,source_key=None,model_id='pbrify-detail',heads=None,scalp_only=False):
    from core import MODELS,upscale_image,check_cancel
    model = MODELS/HAIR_MODELS[model_id]
    if not model.exists():
        raise ValueError('Установите выбранную модель волос в библиотеке.')
    affected = 0
    facial_pixels=0
    width,height = original.size
    for index,box in enumerate(helper.det_faces):
        check_cancel(cancel)
        x1,y1,x2,y2 = box[:4]
        fw,fh = x2-x1,y2-y1
        head=heads[index] if heads is not None else None
        rect = head['rect'] if head else (max(0,int(x1-.7*fw)),max(0,int(y1-.9*fh)),min(width,int(x2+.7*fw)),min(height,int(y2+.6*fh)))
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            continue
        crop = original.crop(rect)
        labels = head['labels'] if head else parse_labels(helper,np.array(crop)[:,:,::-1].copy())
        sample=np.array(crop.resize((512,512),Image.Resampling.LANCZOS))
        local_box=((x1-rect[0])/crop.width*512,(y1-rect[1])/crop.height*512,
                   (x2-rect[0])/crop.width*512,(y2-rect[1])/crop.height*512)
        landmarks=getattr(helper,'all_landmarks_5',[])
        nose_y=(landmarks[index][2][1]-rect[1])/crop.height*512 if index<len(landmarks) else None
        beard=facial_hair_mask(sample,labels,local_box,nose_y)
        facial_pixels+=int(np.count_nonzero(beard>.15))
        selected=(labels==17).astype(np.float32) if scalp_only else np.maximum(np.isin(labels,[2,3,17]).astype(np.float32),beard)
        forbidden=cv2_feature_mask(labels,local_box,landmarks[index] if index<len(landmarks) else None,rect)
        selected[forbidden]=0
        mask = Image.fromarray((selected*255).round().astype(np.uint8))
        if np.count_nonzero(selected>.15) < 32:
            continue
        key = ('hair-model',model_id,source_key,rect,factor,tile,model.stat().st_mtime_ns)
        soft = head['pbr'] if head else cache.get(key) if cache is not None else None
        target_size = crop.width*factor,crop.height*factor
        if soft is None:
            # Bound the optional head pass for large portraits; original low-res crops stay intact.
            crop.thumbnail((512,512),Image.Resampling.LANCZOS)
            local_factor = min(8,max(2,round(max(target_size[0]/crop.width,target_size[1]/crop.height))))
            soft = upscale_image(crop,model,local_factor,tile,lambda text,value:None,cancel).resize(target_size,Image.Resampling.LANCZOS)
            if cache is not None:
                cache.put(key,soft)
        alpha = mask.resize(target_size,Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(max(.7,factor*.5)))
        from PIL import ImageChops
        safe=Image.fromarray((~forbidden).astype(np.uint8)*255).resize(target_size,Image.Resampling.NEAREST)
        alpha=ImageChops.multiply(alpha,safe)
        if head:
            # Only one generated hair structure is used; the other endpoint is the source.
            soft=Image.blend(original.crop(rect).convert('RGB').resize(target_size,Image.Resampling.LANCZOS),soft,max(0,min(1,strength)))
        else:
            alpha = alpha.point(lambda value:round(value*strength))
        background.paste(soft,(rect[0]*factor,rect[1]*factor),alpha)
        affected += 1
        report(f'Волосы, борода и усы · область {index+1}/{len(helper.det_faces)}',60+int(35*(index+1)/len(helper.det_faces)))
    helper.hair_pass_stats={'facial_hair_pixels':facial_pixels}
    return affected


def cv2_feature_mask(labels,face_box,landmarks,rect):
    import cv2
    mask=cv2.dilate(np.isin(labels,[4,5,6,10,11,12,13]).astype(np.uint8),np.ones((9,9),np.uint8))>0
    if landmarks is not None:
        yy,xx=np.mgrid[:512,:512];fw=face_box[2]-face_box[0];fh=face_box[3]-face_box[1]
        for index in (0,1,2):
            x=(landmarks[index][0]-rect[0])/(rect[2]-rect[0])*512;y=(landmarks[index][1]-rect[1])/(rect[3]-rect[1])*512
            rx=fw*(.12 if index==2 else .1);ry=fh*(.08 if index==2 else .055)
            mask|=((xx-x)/max(rx,1))**2+((yy-y)/max(ry,1))**2<1
    return mask


def prepare_head_bases(original,result,helper,factor,tile,report,cancel,replace_face=True):
    """Reuse the full-image hair result; photo fallback is only for disabled face recovery."""
    from core import upscale_image,MODELS,check_cancel
    heads=[]
    for index,box in enumerate(helper.det_faces):
        check_cancel(cancel);x1,y1,x2,y2=box[:4];fw=x2-x1;fh=y2-y1
        rect=(max(0,int(x1-.3*fw)),max(0,int(y1-.55*fh)),min(original.width,int(x2+.3*fw)),min(original.height,int(y2+.15*fh)))
        if rect[2]<=rect[0] or rect[3]<=rect[1]:heads.append(None);continue
        crop=original.crop(rect).convert('RGB');target=(crop.width*factor,crop.height*factor)
        pbr=result.crop(tuple(int(v*factor) for v in rect));labels=parse_labels(helper,np.asarray(crop)[:,:,::-1].copy())
        if replace_face:
            photo=upscale_image(crop,MODELS/'RealESRGAN_x4plus.pth',min(4,factor),tile,lambda *args:None,cancel).resize(target,Image.Resampling.LANCZOS)
            selected=np.isin(labels,[*range(1,15),17]).astype(np.uint8)*255
            mask=Image.fromarray(selected).filter(ImageFilter.GaussianBlur(3)).resize(target,Image.Resampling.BILINEAR)
            result.paste(photo,(rect[0]*factor,rect[1]*factor),mask)
        heads.append(dict(rect=rect,pbr=pbr,labels=labels));report(f'Подготовка портрета · {index+1}/{len(helper.det_faces)}',12+int(15*(index+1)/len(helper.det_faces)))
    return heads


def refine_aligned_detail(rgb,reference,labels,cancel):
    """Reuse the existing upscale on the aligned grid; no model reload or new inference."""
    import cv2
    from core import check_cancel
    check_cancel(cancel)
    base=np.asarray(Image.fromarray(rgb).resize((1024,1024),Image.Resampling.LANCZOS),np.float32)/255
    ref=np.asarray(reference,np.float32)/255
    weights=np.array([.2126,.7152,.0722],np.float32)
    difference=(ref-base)@weights
    delta=np.clip(difference-cv2.GaussianBlur(difference,(0,0),.8),-.018,.018)*.5
    skin=cv2.resize(np.isin(labels,[1,14]).astype(np.float32),(1024,1024),interpolation=cv2.INTER_LINEAR)
    skin=cv2.GaussianBlur(skin,(0,0),2)
    return np.rint((base+delta[:,:,None]*skin[:,:,None])*255).clip(0,255).astype(np.uint8)


def aligned_reference(image,inverse):
    import cv2
    matrix=np.array(inverse,np.float32,copy=True)
    matrix[:,2]+=matrix[:,:2]@np.array([-.25,-.25],np.float32)
    matrix[:,:2]*=.5
    corners=cv2.transform(np.array([[[0,0],[1024,0],[1024,1024],[0,1024]]],np.float32),matrix)[0]
    left,top=np.maximum(0,np.floor(corners.min(0)).astype(int))
    right,bottom=np.minimum(image.size,np.ceil(corners.max(0)).astype(int))
    matrix[:,2]-=[left,top]
    patch=np.asarray(image.crop((left,top,right,bottom)).convert('RGB'))
    return cv2.warpAffine(patch,matrix,(1024,1024),flags=cv2.INTER_CUBIC|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REFLECT_101)


def enhance(original,upscaled,factor,options,report,cancel,cache=None,source_key=None):
    from core import check_cancel
    check_cancel(cancel)
    helper,regions = analyze(original,factor)
    result = upscaled.convert('RGB')
    stats = dict(faces=len(regions),hair_regions=0,face_model=options.get('face_model','gfpgan'),hair_model=options.get('hair_model','realesrnet-soft'))
    report(f'Найдено лиц: {len(regions)}',10)
    active_face=options.get('faces') and options.get('face_strength',.6)>0
    unified_hair=bool(options.get('portrait_detail') and active_face and options.get('hair_natural'))
    heads=prepare_head_bases(original,result,helper,factor,options.get('tile',256),report,cancel) if regions and options.get('portrait_detail') and not active_face else None
    stats['head_regions']=len(regions) if active_face else len(heads) if heads else 0
    stats['photo_head_regions']=len(heads) if heads and not active_face else 0
    stats['aligned_face_regions']=0;stats['aligned_detail_regions']=0;stats['neck_pixels']=0
    if regions and active_face:
        helper.align_warp_face()
        helper.get_inverse_affine(None)
        for index,(crop,inverse) in enumerate(zip(helper.cropped_faces,helper.inverse_affine_matrices)):
            check_cancel(cancel)
            labels = parse_labels(helper,crop)
            stats['neck_pixels']+=int(np.count_nonzero(labels==14))
            identifier = options.get('face_model','gfpgan')
            fidelity = options.get('face_fidelity',.8)
            weight = STORE.models/('codeformer.pth' if identifier == 'codeformer' else 'GFPGANv1.4.pth')
            detail=bool(options.get('portrait_detail') and abs(np.linalg.det(np.asarray(inverse)[:,:2]))>1.21)
            crop_key = ('face-crop-v3',source_key,index,identifier,weight.stat().st_mtime_ns,
                        fidelity if identifier == 'codeformer' else 0,detail)
            cached = cache.get(crop_key) if cache is not None else None
            if cached is None:
                restored = restore_crop(helper,crop,identifier,fidelity)
                from surface_light import preserve_face_lighting
                restored=preserve_face_lighting(crop[:,:,::-1],restored,labels==1)
                if detail:restored=refine_aligned_detail(restored,aligned_reference(upscaled,inverse),labels,cancel)
                if cache is not None:
                    cache.put(crop_key,Image.fromarray(restored))
            else:
                restored = np.asarray(cached)
            mask=face_mask(labels,options.get('hair_strength',1) if unified_hair else None)
            if unified_hair:stats['hair_regions']+=int(np.count_nonzero(labels==17)>32)
            stats['aligned_face_regions']+=1
            stats['aligned_detail_regions']+=int(detail)
            paste_face(result,restored,mask,inverse,factor,options.get('face_strength',.6))
            report(f"{options.get('face_model','gfpgan').upper()} · лицо {index+1}/{len(regions)}",20+int(35*(index+1)/len(regions)))
        report(f'Обработано лиц: {len(regions)}',58)
    if regions and not unified_hair and options.get('hair_natural') and (heads or options.get('hair_strength',.65)>0):
        stats['hair_regions']=natural_hair(original,result,helper,factor,options.get('hair_strength',.65),
            options.get('tile',128),report,cancel,cache,source_key,options.get('hair_model','pbrify-detail'),heads,scalp_only=bool(heads and active_face))
        stats.update(getattr(helper,'hair_pass_stats',{}))
    check_cancel(cancel)
    if 'A' in upscaled.getbands():
        result.putalpha(upscaled.getchannel('A'))
    result.info.update(upscaled.info)
    result.info['portrait_regions'] = regions
    result.info['portrait_stats'] = stats
    report('Портрет готов',99)
    return result

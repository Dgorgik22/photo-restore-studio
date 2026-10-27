"""Recover source-supported cloud texture erased by an upscaler, without new weights."""
import numpy as np
from PIL import Image,ImageOps

VERSION='cloud-texture-v3'


def cloud_mask(rgb):
    """Colour/context heuristic: bright neutral regions connected to upper sky."""
    import cv2
    rgb=rgb.astype(np.float32)/255
    red,green,blue=rgb.transpose(2,0,1)
    light=rgb@np.array([.2126,.7152,.0722],np.float32)
    saturation=(rgb.max(2)-rgb.min(2))/np.maximum(rgb.max(2),.01)
    blue_sky=(blue>red*1.06)&(blue>green*.98)&(light>.22)
    neutral=(saturation<.42)&(light>.43)
    # Sharp skyline/window edges are barriers: snow, facades and pale ceilings
    # must not join the sky simply because their colours are similar.
    gx=cv2.Sobel(rgb,cv2.CV_32F,1,0,ksize=3)
    gy=cv2.Sobel(rgb,cv2.CV_32F,0,1,ksize=3)
    gradient=np.sqrt(gx*gx+gy*gy).max(2)/8
    candidate=((blue_sky|neutral)&(gradient<.04)).astype('uint8')
    n,labels,stats,_=cv2.connectedComponentsWithStats(candidate,8)
    sky=np.zeros(candidate.shape,np.float32);height,width=sky.shape
    for index in range(1,n):
        x,y,w,h,area=stats[index]
        touches_upper=y==0 or (y<height*.2 and (x==0 or x+w==width))
        if touches_upper and area>height*width*.015 and w>width*.2:
            region=labels==index
            if float((blue_sky&(saturation>.24))[region].mean())>.04:sky[region]=1
    upper=np.clip((.75-np.arange(height)/height)/.15,0,1).astype(np.float32)[:,None]
    cloud=sky*upper*np.clip((.48-saturation)/.22,0,1)*np.clip((light-.43)/.18,0,1)
    # Keep foliage, dark frames and saturated blue sky out of the feathered mask.
    return cv2.GaussianBlur(cloud,(0,0),1.2)*neutral*sky


def preserve_sky_texture(source,image,amount=.85,cancel=None):
    if amount<=0:return image
    import cv2
    from core import check_cancel
    with Image.open(source) as opened:
        original=ImageOps.exif_transpose(opened).convert('RGB')
    if image.width<=original.width or image.height<=original.height:return image
    original.thumbnail((2048,2048),Image.Resampling.LANCZOS)
    rgb=np.asarray(original);mask=cloud_mask(rgb)
    if mask.max()<.01:return image
    weights=np.array([.2126,.7152,.0722],np.float32)
    ref=rgb.astype(np.float32)@weights/255
    small=np.asarray(image.convert('RGB').resize(original.size,Image.Resampling.LANCZOS),np.float32)@weights/255
    def band(value):return cv2.GaussianBlur(value,(0,0),.55)-cv2.GaussianBlur(value,(0,0),2.6)
    source_band=band(ref);ai_band=band(small)
    source_energy=np.sqrt(cv2.GaussianBlur(source_band**2,(0,0),2.2))
    ai_energy=np.sqrt(cv2.GaussianBlur(ai_band**2,(0,0),2.2))
    missing=np.clip((1-ai_energy/(source_energy+.0003))*3,0,1)
    reliable=np.clip((source_energy-.0015)/.004,0,1)
    delta=np.clip(source_band-ai_band,-.045,.045)*mask*missing*reliable*min(1,amount)
    if np.max(np.abs(delta))<.5/255:return image
    # Resize a single-channel, bounded residual in strips, not an RGB float canvas.
    output=image.convert('RGB');sx=image.width/original.width;sy=image.height/original.height
    for top in range(0,image.height,192):
        if cancel is not None:check_cancel(cancel)
        end=min(image.height,top+192)
        transform=np.array([[1/sx,0,.5/sx-.5],[0,1/sy,(top+.5)/sy-.5]],np.float32)
        patch_delta=cv2.warpAffine(delta,transform,(image.width,end-top),flags=cv2.INTER_CUBIC|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REPLICATE)
        pixels=np.asarray(image.crop((0,top,image.width,end)).convert('RGB'),np.float32)
        patch=Image.fromarray(np.clip(np.rint(pixels+patch_delta[:,:,None]*255),0,255).astype('uint8'))
        output.paste(patch,(0,top))
    output.info.update(image.info)
    output.info['sky_detail_stats']=dict(algorithm=VERSION,cloud_pixels=int(np.count_nonzero(mask>.1)),amount=amount)
    if 'A' in image.getbands():output.putalpha(image.getchannel('A'))
    return output


def refine_clouds(original,image,factor,tile,report,cancel,model_path=None,upscale_fn=None):
    """Run the existing detail model only over sky; never replace the whole photograph."""
    if factor<=1:return image
    import cv2,math
    from core import MODELS,upscale_image,check_cancel
    from pathlib import Path
    check_cancel(cancel)
    sample=original.convert('RGB');sample.thumbnail((2048,2048),Image.Resampling.LANCZOS)
    rgb=np.asarray(sample);mask=cloud_mask(rgb)
    weights=np.array([.2126,.7152,.0722],np.float32)
    source=rgb.astype(np.float32)@weights/255
    structure=cv2.GaussianBlur(source,(0,0),.55)-cv2.GaussianBlur(source,(0,0),2.6)
    energy=np.sqrt(cv2.GaussianBlur(structure**2,(0,0),2.2))
    mask*=np.clip((energy-.0015)/.004,0,1)
    gradient=cv2.magnitude(cv2.Sobel(source,cv2.CV_32F,1,0,ksize=3),cv2.Sobel(source,cv2.CV_32F,0,1,ksize=3))/8
    mask*=1-np.clip((gradient-.035)/.1,0,1)
    yy,xx=np.where(mask>.025)
    if len(xx)<64:return image
    model_path=Path(model_path) if model_path else MODELS/'4x-PBRify_UpscalerV4.safetensors'
    if not model_path.is_file():
        # The program still works when the optional local component is not installed.
        import tempfile
        from storage import STORE
        with tempfile.TemporaryDirectory(prefix='cloud-source-',dir=STORE.scratch) as temporary:
            path=Path(temporary)/'source.png';original.save(path)
            return preserve_sky_texture(path,image,.85,cancel)
    rx=original.width/sample.width;ry=original.height/sample.height
    left=max(0,math.floor(xx.min()*rx)-32);top=max(0,math.floor(yy.min()*ry)-32)
    right=min(original.width,math.ceil((xx.max()+1)*rx)+32);bottom=min(original.height,math.ceil((yy.max()+1)*ry)+32)
    report('Сохранение фактуры облаков…',0)
    cropped=original.crop((left,top,right,bottom)).convert('RGB')
    if upscale_fn is not None:
        detail=upscale_fn(cropped,model_path,factor,tile,report,cancel)
    else:
        coverage=Image.fromarray((mask>.025).astype('uint8')*255).transform(cropped.size,Image.Transform.EXTENT,
            (left/rx,top/ry,right/rx,bottom/ry),Image.Resampling.NEAREST)
        detail=upscale_image(cropped,model_path,factor,tile,report,cancel,coverage=coverage)
    output=image.convert('RGB');width=(right-left)*factor;height=(bottom-top)*factor
    sigma=max(1,2.5*factor);context=math.ceil(3*sigma)
    sx=sample.width/image.width;sy=sample.height/image.height
    changed=0
    for row in range(0,height,192):
        check_cancel(cancel);start=max(0,row-context);end=min(height,row+192+context)
        box=(left*factor,top*factor+start,right*factor,top*factor+end)
        primary=np.asarray(image.crop(box).convert('RGB'),np.float32)/255
        candidate=np.asarray(detail.crop((0,start,width,end)),np.float32)/255
        p=primary@weights;c=candidate@weights
        primary_band=p-cv2.GaussianBlur(p,(0,0),sigma)
        candidate_band=c-cv2.GaussianBlur(c,(0,0),sigma)
        primary_energy=cv2.GaussianBlur(primary_band**2,(0,0),factor*1.5)
        candidate_energy=cv2.GaussianBlur(candidate_band**2,(0,0),factor*1.5)
        # A smoother secondary model must never subtract existing cloud detail.
        advantage=np.clip((candidate_energy-primary_energy)/(candidate_energy+.000001)*3,0,1)
        transform=np.array([[sx,0,(left*factor+.5)*sx-.5],[0,sy,(top*factor+start+.5)*sy-.5]],np.float32)
        alpha=cv2.warpAffine(mask,transform,(width,end-start),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_CONSTANT)*advantage
        delta=np.clip(candidate_band-primary_band,-.075,.075)*alpha
        pixels=np.rint((primary+delta[:,:,None])*255).clip(0,255).astype('uint8')
        a=row-start;b=min(row+192,height)-start
        changed+=int(np.count_nonzero(np.abs(delta[a:b])>.5/255))
        output.paste(Image.fromarray(pixels[a:b]),(left*factor,top*factor+row))
    output.info.update(image.info)
    output.info['sky_detail_stats']=dict(algorithm=VERSION,method='pbrify-local-detail',
        crop=[left,top,right,bottom],cloud_pixels=len(xx),changed_pixels=changed)
    if 'A' in image.getbands():output.putalpha(image.getchannel('A'))
    return output

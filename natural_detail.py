"""Automatic, source-supported recovery of foliage texture and water ripples."""
import numpy as np
from PIL import Image

VERSION='natural-source-detail-v1'
LUMA=np.array([.2126,.7152,.0722],np.float32)


def analyze_texture(rgb):
    import cv2
    colour=rgb.astype(np.float32)/255
    red,green,blue=colour.transpose(2,0,1);light=colour@LUMA
    value=colour.max(2);saturation=(value-colour.min(2))/np.maximum(value,.01)
    smooth=cv2.GaussianBlur(light,(0,0),.65)
    band=smooth-cv2.GaussianBlur(light,(0,0),2.6)
    energy=np.sqrt(cv2.GaussianBlur(band*band,(0,0),2.5))
    noise=light-cv2.GaussianBlur(light,(0,0),.55)
    noise_energy=np.sqrt(cv2.GaussianBlur(noise*noise,(0,0),2.5))
    reliable=np.clip((energy-noise_energy*1.25-.0015)/.006,0,1)
    reliable*=np.clip((light-.04)/.1,0,1)*np.clip((.99-light)/.06,0,1)
    dx=cv2.Sobel(smooth,cv2.CV_32F,1,0,ksize=3)/8
    dy=cv2.Sobel(smooth,cv2.CV_32F,0,1,ksize=3)/8
    xx=cv2.GaussianBlur(dx*dx,(0,0),3);yy=cv2.GaussianBlur(dy*dy,(0,0),3)
    xy=cv2.GaussianBlur(dx*dy,(0,0),3)
    coherence=np.sqrt((xx-yy)**2+4*xy*xy)/(xx+yy+.00000001)
    green_leaf=(green>red*1.03)&(green>blue*1.12)&(saturation>.2)
    autumn_leaf=(red>green*1.08)&(green>blue*1.2)&(saturation>.25)
    foliage_colour=green_leaf|autumn_leaf
    foliage=foliage_colour*reliable*(1-np.clip((coherence-.65)/.35,0,1))
    water_colour=((blue>red*1.03)&(green>red*.97))|(saturation<.3)
    horizontal=np.clip(((yy-xx)/(xx+yy+.00000001)-.12)/.5,0,1)
    lower=np.clip((np.arange(rgb.shape[0])/rgb.shape[0]-.28)/.18,0,1).astype(np.float32)[:,None]
    water=water_colour*reliable*horizontal*np.clip((coherence-.25)/.45,0,1)*lower
    foliage=cv2.GaussianBlur(foliage.astype(np.float32),(0,0),.7)*foliage_colour
    water=cv2.GaussianBlur(water.astype(np.float32),(0,0),.7)*water_colour*lower
    return light,band,energy,foliage,water


def preserve_natural_detail(original,image,cancel):
    import cv2
    from core import check_cancel
    check_cancel(cancel)
    stats=dict(algorithm=VERSION,foliage_pixels=0,water_pixels=0,changed_pixels=0,
               foliage_correction_source_pixels=0,water_correction_source_pixels=0)
    if image.width<=original.width or image.height<=original.height:
        image.info['natural_detail_stats']=stats;return image
    sample=original.convert('RGB');sample.thumbnail((2048,2048),Image.Resampling.LANCZOS)
    _,reference_band,reference_energy,foliage,water=analyze_texture(np.asarray(sample))
    stats.update(foliage_pixels=int(np.count_nonzero(foliage>.05)),water_pixels=int(np.count_nonzero(water>.05)))
    if not stats['foliage_pixels'] and not stats['water_pixels']:
        image.info['natural_detail_stats']=stats;return image
    current=np.asarray(image.convert('RGB').resize(sample.size,Image.Resampling.LANCZOS),np.float32)@LUMA/255
    current_band=cv2.GaussianBlur(current,(0,0),.65)-cv2.GaussianBlur(current,(0,0),2.6)
    current_energy=np.sqrt(cv2.GaussianBlur(current_band*current_band,(0,0),2.5))
    missing=np.clip((.9-current_energy/(reference_energy+.000001))/.35,0,1)
    correction=np.clip(reference_band-current_band,-.022,.022)*missing
    strength=np.maximum(foliage*.65,water*.7)
    delta=correction*strength
    stats['foliage_correction_source_pixels']=int(np.count_nonzero(np.abs(correction*foliage*.65)>.5/255))
    stats['water_correction_source_pixels']=int(np.count_nonzero(np.abs(correction*water*.7)>.5/255))
    if np.max(np.abs(delta))<.5/255:
        image.info['natural_detail_stats']=stats;return image
    output=image.convert('RGB');sx=image.width/sample.width;sy=image.height/sample.height
    for top in range(0,image.height,192):
        check_cancel(cancel);bottom=min(image.height,top+192)
        transform=np.array([[1/sx,0,.5/sx-.5],[0,1/sy,(top+.5)/sy-.5]],np.float32)
        patch_delta=cv2.warpAffine(delta,transform,(image.width,bottom-top),
            flags=cv2.INTER_CUBIC|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REPLICATE)
        pixels=np.asarray(image.crop((0,top,image.width,bottom)).convert('RGB'),np.float32)
        patch=np.clip(np.rint(pixels+patch_delta[:,:,None]*255),0,255).astype('uint8')
        stats['changed_pixels']+=int(np.count_nonzero(np.any(patch!=pixels,axis=2)))
        output.paste(Image.fromarray(patch),(0,top))
    output.info.update(image.info);output.info['natural_detail_stats']=stats
    if 'A' in image.getbands():output.putalpha(image.getchannel('A'))
    return output

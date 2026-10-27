"""Fast tonal lighting correction; no generative relighting or new model weights."""
import numpy as np
from PIL import Image,ImageDraw,ImageFilter,ImageChops


def face_light_mask(size,regions):
    scale = min(1,1024/max(size))
    width,height = max(1,round(size[0]*scale)),max(1,round(size[1]*scale))
    mask = Image.new('L',(width,height))
    for left,top,right,bottom in regions:
        if right <= left or bottom <= top:
            continue
        single = Image.new('L',(width,height))
        ImageDraw.Draw(single).ellipse((left*width,top*height,right*width,bottom*height),fill=255)
        radius = max(.7,min((right-left)*width,(bottom-top)*height)*.12)
        mask = ImageChops.lighter(mask,single.filter(ImageFilter.GaussianBlur(radius)))
    return mask.resize(size,Image.Resampling.BILINEAR)


def correct_light(image,exposure=0,shadows=0,highlights=0,temperature=0,regions=None):
    if not any((exposure,shadows,highlights,temperature)):
        return image
    if regions is not None and not regions:
        return image
    mask = face_light_mask(image.size,regions) if regions is not None else None
    output = image.convert('RGB')
    for top in range(0,image.height,128):
        rect = (0,top,image.width,min(image.height,top+128))
        rgb = np.asarray(image.crop(rect).convert('RGB'),dtype=np.float32)/255
        linear = np.where(rgb <= .04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
        luma = rgb@np.array([.2126,.7152,.0722],dtype=np.float32)
        adjusted = linear.copy()
        s,h = shadows/100,highlights/100
        if s >= 0:
            adjusted += s*.12*((1-luma)**3)[:,:,None]
        else:
            adjusted *= (1+s*.8*((1-luma)**2))[:,:,None]
        if h >= 0:
            adjusted += h*.3*(luma**3)[:,:,None]
        else:
            adjusted *= (1+h*.7*(luma**2))[:,:,None]
        adjusted *= 2**(exposure/50)
        t = temperature/100
        adjusted *= np.array([1+.18*t,1,1-.18*t],dtype=np.float32)
        if mask is not None:
            weight = np.asarray(mask.crop(rect),dtype=np.float32)[:,:,None]/255
            adjusted = linear*(1-weight)+adjusted*weight
        adjusted = adjusted.clip(0,1)
        srgb = np.where(adjusted <= .0031308,adjusted*12.92,1.055*adjusted**(1/2.4)-.055)
        output.paste(Image.fromarray((srgb*255).clip(0,255).round().astype(np.uint8)),(0,top))
    if 'A' in image.getbands():
        output.putalpha(image.getchannel('A'))
    output.info.update(image.info)
    return output

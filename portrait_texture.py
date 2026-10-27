"""Source-supported skin colour variation and cloth detail, with no artificial pores."""
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
VERSION='portrait-source-texture-v1'


def preserve_texture(original,image,regions,cancel,skin_detail=True):
    from core import check_cancel
    import cv2
    check_cancel(cancel)
    if not regions:return image
    sample=original.convert('RGB');sample.thumbnail((2048,2048),Image.Resampling.LANCZOS)
    skin=Image.new('L',sample.size);cloth=Image.new('L',sample.size);ds=ImageDraw.Draw(skin);dc=ImageDraw.Draw(cloth)
    for x1,y1,x2,y2 in regions:
        x1*=sample.width;x2*=sample.width;y1*=sample.height;y2*=sample.height;fw=x2-x1;fh=y2-y1
        if skin_detail:ds.ellipse((x1,y1,x2,y2),fill=255)
        dc.rectangle((max(0,(x1+x2)/2-fw*1.5),y2+.05*fh,min(sample.width,(x1+x2)/2+fw*1.5),sample.height),fill=255)
    skin=np.asarray(skin.filter(ImageFilter.GaussianBlur(3)),np.float32)/255
    cloth=np.asarray(cloth.filter(ImageFilter.GaussianBlur(3)),np.float32)/255
    ref=np.asarray(sample,np.float32)/255;cur=np.asarray(image.convert('RGB').resize(sample.size,Image.Resampling.LANCZOS),np.float32)/255
    rb=cv2.GaussianBlur(ref,(0,0),.65)-cv2.GaussianBlur(ref,(0,0),3)
    cb=cv2.GaussianBlur(cur,(0,0),.65)-cv2.GaussianBlur(cur,(0,0),3)
    energy=np.sqrt(cv2.GaussianBlur(np.mean(rb**2,2),(0,0),2.5));ce=np.sqrt(cv2.GaussianBlur(np.mean(cb**2,2),(0,0),2.5))
    noise=ref-cv2.GaussianBlur(ref,(0,0),.5)
    reliable=np.clip((energy-np.sqrt(cv2.GaussianBlur(np.mean(noise**2,2),(0,0),2.5))*1.2-.001)/.006,0,1)
    gain=np.maximum(skin*.7,cloth*.75)*reliable*np.clip((.95-ce/(energy+.000001))/.4,0,1)
    delta=np.clip(rb-cb,-.025,.025)*gain[:,:,None]
    delta+=np.clip(cv2.GaussianBlur(ref,(0,0),4)-cv2.GaussianBlur(cur,(0,0),4),-.04,.04)*skin[:,:,None]*.45
    result=image.convert('RGB');sx=image.width/sample.width;sy=image.height/sample.height;changed=0
    for top in range(0,image.height,192):
        check_cancel(cancel);bottom=min(image.height,top+192)
        transform=np.array([[1/sx,0,.5/sx-.5],[0,1/sy,(top+.5)/sy-.5]],np.float32)
        correction=cv2.warpAffine(delta,transform,(image.width,bottom-top),flags=cv2.INTER_CUBIC|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REPLICATE)
        base=np.asarray(image.crop((0,top,image.width,bottom)).convert('RGB'),np.float32)
        pixels=np.rint(base+correction*255).clip(0,255).astype(np.uint8)
        changed+=int(np.count_nonzero(np.any(pixels!=base,2)));result.paste(Image.fromarray(pixels),(0,top))
    result.info.update(image.info);result.info['portrait_texture_stats']=dict(algorithm=VERSION,changed_pixels=changed)
    if 'A' in image.getbands():result.putalpha(image.getchannel('A'))
    return result

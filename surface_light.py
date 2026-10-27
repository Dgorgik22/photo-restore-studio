"""Source-guided lighting and bounded shadow detail, without synthesising reflections."""
import numpy as np
from PIL import Image,ImageOps


def preserve_surface_light(source,image,amount=.75,shadow_detail=0,regions=None):
    if not amount and not shadow_detail:return image
    if regions is not None and not regions:return image
    import cv2
    with Image.open(source) as opened:reference=ImageOps.exif_transpose(opened).convert('RGB').resize(image.size,Image.Resampling.LANCZOS)
    mask=None
    if regions is not None:
        from lighting import face_light_mask
        mask=face_light_mask(image.size,regions)
    output=image.convert('RGB');weights=np.array([.2126,.7152,.0722],np.float32)
    for top in range(0,image.height,192):
        start=max(0,top-24);end=min(image.height,top+192+24);box=(0,start,image.width,end)
        ref=np.asarray(reference.crop(box),np.float32)/255
        cur=np.asarray(image.crop(box).convert('RGB'),np.float32)/255
        light=cv2.GaussianBlur(ref@weights,(0,0),5)
        # A low-frequency DIFFERENCE restores illumination; the output is never blurred.
        correction=cv2.GaussianBlur(ref,(0,0),5)-cv2.GaussianBlur(cur,(0,0),5)
        extremes=np.maximum(np.clip((light-.5)/.4,0,1),np.clip((.24-light)/.22,0,1))[:,:,None]
        adjusted=cur+np.clip(correction,-.08,.08)*extremes*amount
        if shadow_detail:
            luma=cur@weights
            band=luma-cv2.GaussianBlur(luma,(0,0),1.2)
            # Weak, flat noise receives no local contrast gain.
            reliable=np.clip((abs(band)-.008)/.025,0,1)
            dark=np.clip((.4-luma)/.25,0,1)*np.clip((luma-.015)/.08,0,1)
            adjusted+=np.clip(band,-.035,.035)[:,:,None]*(reliable*dark)[:,:,None]*shadow_detail/100*.5
        if mask is not None:
            alpha=np.asarray(mask.crop(box),np.float32)[:,:,None]/255
            adjusted=cur+(adjusted-cur)*alpha
        patch=Image.fromarray((adjusted.clip(0,1)*255).round().astype(np.uint8))
        output.paste(patch.crop((0,top-start,image.width,min(top+192,image.height)-start)),(0,top))
    output.info.update(image.info)
    if 'A' in image.getbands():output.putalpha(image.getchannel('A'))
    return output


def preserve_face_lighting(original,restored,skin_mask):
    """Retain existing skin highlights and fine texture after a face-restoration network."""
    import cv2
    original=original.astype(np.float32)/255;fresh=restored.astype(np.float32)/255
    low_delta=cv2.GaussianBlur(original,(0,0),9)-cv2.GaussianBlur(fresh,(0,0),9)
    skin=cv2.GaussianBlur(skin_mask.astype(np.float32),(0,0),3)[:,:,None]
    fresh+=np.clip(low_delta,-.12,.12)*skin*.8
    fine=original-cv2.GaussianBlur(original,(0,0),1.)
    # Restore only modest, real source detail; no generated skin gloss or grain.
    fresh+=np.clip(fine,-.025,.025)*skin*.25
    return (fresh.clip(0,1)*255).round().astype(np.uint8)

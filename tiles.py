import math
import numpy as np
from PIL import Image

def axis_starts(length,tile=768,overlap=128):
    if length <= tile:
        return [0]
    starts = list(range(0,length-tile+1,tile-overlap))
    if starts[-1] != length-tile:
        starts.append(length-tile)
    return starts


def feather(width,height,left=0,top=0):
    x,y = np.ones(width,np.float32),np.ones(height,np.float32)
    if left:
        x[:left] = (1-np.cos(np.linspace(0,math.pi,left,dtype=np.float32)))/2
    if top:
        y[:top] = (1-np.cos(np.linspace(0,math.pi,top,dtype=np.float32)))/2
    return Image.fromarray((y[:,None]*x[None,:]*255).round().astype(np.uint8))


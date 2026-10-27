"""Conservative facade constraints from repeated, visible windows and straight edges."""
import numpy as np
from PIL import Image
VERSION='source-facade-grid-v1'


def window_grids(rgb):
    import cv2
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    dark=(cv2.GaussianBlur(gray.astype(np.float32),(0,0),2)-gray)>10
    n,labels,stats,centers=cv2.connectedComponentsWithStats(dark.astype(np.uint8),8)
    valid=[]
    for index in range(1,n):
        x,y,w,h,area=stats[index]
        if 2<=w<=12 and 2<=h<=16 and .25<w/h<1.5 and area/(w*h)>.48:
            valid.append([index,x,y,w,h,*centers[index]])
    if len(valid)<12:return [],stats,labels
    points=np.asarray(valid,np.float64);best={}
    def pitch(values,cross,size,cross_size):
        d=abs(values[:,None]-values);near=(abs(cross[:,None]-cross)<max(.8,cross_size*.4))&(d>size*1.25)&(d<size*5)
        values=d[near]
        if len(values)<12:return None
        bins=np.rint(values*2).astype(int);hist=np.bincount(bins);k=int(np.argmax(hist))
        return float(np.median(values[abs(values-k/2)<.5]))
    for top in range(0,rgb.shape[0],32):
        for left in range(0,rgb.shape[1],32):
            local=points[(points[:,5]>=left)&(points[:,5]<left+80)&(points[:,6]>=top)&(points[:,6]<top+80)]
            if len(local)<12:continue
            sizes,counts=np.unique(local[:,3:5].astype(int),axis=0,return_counts=True)
            for size in sizes[np.argsort(counts)[-3:]]:
                group=local[(abs(local[:,3]-size[0])<=max(.6,size[0]*.3))&(abs(local[:,4]-size[1])<=max(.6,size[1]*.3))]
                if len(group)<12:continue
                w,h=np.median(group[:,3:5],axis=0);gx=group[:,5];gy=group[:,6]
                ddx=gx[:,None]-gx;ddy=gy[:,None]-gy
                def slope(main,cross,size):
                    select=(abs(main)>size*1.25)&(abs(main)<size*5)&(abs(cross)<abs(main)*.25)
                    values=(cross[select]/main[select])
                    if len(values)<12:return 0.
                    bins=np.rint(values*100).astype(int)+25;hist=np.bincount(bins,minlength=51);v=(np.argmax(hist)-25)/100
                    return float(np.median(values[abs(values-v)<.025]))
                row_slope=slope(ddx,ddy,w);col_slope=slope(ddy,ddx,h)
                x=gx-col_slope*(gy-gy.mean());y=gy-row_slope*(gx-gx.mean())
                px=pitch(x,y,w,h);py=pitch(y,x,h,w)
                if px is None or py is None:continue
                phases=[];quality=[]
                for values,p in ((x,px),(y,py)):
                    z=np.exp(values*2j*np.pi/p).mean();quality.append(abs(z));phases.append(np.angle(z)*p/(2*np.pi))
                if min(quality)<.45:continue
                lattice=np.column_stack([np.rint((x-phases[0])/px),np.rint((y-phases[1])/py)])
                predicted=lattice*np.array([px,py])+phases
                selected=(abs(predicted[:,0]-x)<max(.8,w*.35))&(abs(predicted[:,1]-y)<max(.8,h*.35))
                group=group[selected];lattice=lattice[selected]
                if len(group)<12 or len(np.unique(lattice[:,0]))<3 or len(np.unique(lattice[:,1]))<3:continue
                occupancy=len(group)/(len(np.unique(lattice[:,0]))*len(np.unique(lattice[:,1])))
                if occupancy<.55:continue
                homography,inliers=cv2.findHomography(lattice,group[:,5:7],cv2.RANSAC,.85)
                if homography is None or inliers.mean()<.8:continue
                score=float(min(quality)*min(1,occupancy)*inliers.mean())
                for item,cell,ok in zip(group,lattice,inliers[:,0]):
                    if not ok:continue
                    c,r=cell
                    corners=np.array([[[c-w/px/2,r-h/py/2],[c+w/px/2,r-h/py/2],[c+w/px/2,r+h/py/2],[c-w/px/2,r+h/py/2]]],np.float32)
                    quad=cv2.perspectiveTransform(corners,homography)[0]
                    if not np.isfinite(quad).all() or not cv2.isContourConvex(quad):continue
                    if not .45*w*h<abs(cv2.contourArea(quad))<2*w*h:continue
                    index=int(item[0]);center=quad.mean(0)
                    if np.linalg.norm(center-item[5:7])>min(w,h)*.35:continue
                    if index not in best or best[index]['score']<score:
                        best[index]=dict(index=index,quad=quad,score=score)
    return list(best.values()),stats,labels


def regularize(original,image,cancel):
    import cv2
    from core import check_cancel
    check_cancel(cancel)
    sample=original.convert('RGB');sample.thumbnail((1800,1800),Image.Resampling.LANCZOS)
    rgb=np.asarray(sample);windows,stats,labels=window_grids(rgb)
    report=dict(algorithm=VERSION,windows=0,line_segments=0)
    if not windows:image.info['architecture_stats']=report;return image
    result=image.convert('RGB');sx=image.width/sample.width;sy=image.height/sample.height
    for item in windows:
        check_cancel(cancel);index=item['index'];x,y,w,h,_=stats[index]
        left=max(0,int((x-1)*sx));top=max(0,int((y-1)*sy));right=min(image.width,int((x+w+1)*sx));bottom=min(image.height,int((y+h+1)*sy))
        if right-left<4 or bottom-top<4:continue
        arr=np.asarray(result.crop((left,top,right,bottom)),np.float32)/255
        luma=arr@np.array([.2126,.7152,.0722],np.float32)
        low=float(np.percentile(luma,20));high=float(np.percentile(luma,85))
        if high-low<.06:continue
        tone_dark=np.median(arr[luma<=low],axis=0);tone_wall=np.median(arr[luma>=high],axis=0)
        quad=(item['quad']+.5)*[sx,sy]-.5-[left,top]
        mask=np.zeros(luma.shape,np.uint8);cv2.fillConvexPoly(mask,np.rint(quad).astype(np.int32),255)
        geo=cv2.GaussianBlur(mask.astype(np.float32)/255,(0,0),.45)
        radius=max(1,round(min(sx,sy)*.35));kernel=np.ones((radius*2+1,radius*2+1),np.uint8)
        edge=(cv2.dilate(mask,kernel).astype(np.float32)-cv2.erode(mask,kernel))/255
        darkness=np.clip((high-luma)/(high-low),0,1)
        change=(geo-darkness)*edge*.35*item['score']
        weight=abs(change)[:,:,None]
        tone=np.where((change>0)[:,:,None],tone_dark,tone_wall)
        fixed=np.rint((arr*(1-weight)+tone*weight)*255).clip(0,255).astype(np.uint8)
        result.paste(Image.fromarray(fixed),(left,top));report['windows']+=1
    # Reinforce only long existing facade edges near a confirmed window grid.
    segments=cv2.createLineSegmentDetector().detect(cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY))[0]
    if segments is not None:
        centers=np.array([item['quad'].mean(0) for item in windows])
        candidates=[]
        for segment in segments[:,0]:
            x1,y1,x2,y2=segment;dx=x2-x1;dy=y2-y1;length=np.hypot(dx,dy)
            if length<35 or min(abs(dx),abs(dy))/length>.14:continue
            center=np.array([(x1+x2)/2,(y1+y2)/2])
            if np.min(np.linalg.norm(centers-center,axis=1))>25:continue
            candidates.append((length,segment))
        for _,segment in sorted(candidates,key=lambda a:-a[0])[:80]:
            check_cancel(cancel);x1,y1,x2,y2=segment*np.array([sx,sy,sx,sy]);dx=x2-x1;dy=y2-y1;length=np.hypot(dx,dy)
            nx=-dy/length;ny=dx/length;pad=max(sx,sy)*2.5
            left=max(0,int(min(x1,x2)-pad));right=min(image.width,int(max(x1,x2)+pad+1))
            top=max(0,int(min(y1,y2)-pad));bottom=min(image.height,int(max(y1,y2)+pad+1))
            arr=np.asarray(result.crop((left,top,right,bottom)),np.float32)/255
            yy,xx=np.mgrid[top:bottom,left:right];dist=(xx-x1)*nx+(yy-y1)*ny;along=((xx-x1)*dx+(yy-y1)*dy)/length
            inside=(along>max(sx,sy)*2)&(along<length-max(sx,sy)*2)
            a=inside&(dist>sx*.6)&(dist<sx*1.5);b=inside&(dist<-sx*.6)&(dist>-sx*1.5)
            if a.sum()<10 or b.sum()<10:continue
            luma=arr@np.array([.2126,.7152,.0722],np.float32);contrast=float(np.median(luma[a])-np.median(luma[b]))
            if abs(contrast)<.08:continue
            scale=max(sx,sy);expected=contrast*.5*(np.tanh(dist/(scale*.35))-np.tanh(dist/(scale*1.5)))
            current=luma-cv2.GaussianBlur(luma,(0,0),scale*1.5)
            delta=np.clip(expected-current,-.03,.03)*inside*(abs(dist)<scale*1.2)*.22
            result.paste(Image.fromarray(np.rint((arr+delta[:,:,None])*255).clip(0,255).astype(np.uint8)),(left,top));report['line_segments']+=1
    result.info.update(image.info);result.info['architecture_stats']=report
    if 'A' in image.getbands():result.putalpha(image.getchannel('A'))
    return result

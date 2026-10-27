"""Offline illustration resizing and real SVG tracing; no neural weights."""
import io
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps, ImageFilter
from core import check_cancel

VERSION = 'graphics-v1'


def process(source, factor, vector, colors, smoothness, report, cancel):
    check_cancel(cancel)
    with Image.open(source) as opened:
        original = ImageOps.exif_transpose(opened).convert('RGBA')
        profile = opened.info.get('icc_profile')
    size = (round(original.width * factor), round(original.height * factor))
    if size[0] * size[1] > 120_000_000:
        raise ValueError('Результат больше 120 мегапикселей. Уменьшите масштаб.')
    if not vector:
        report('Сохранение линий и оттенков иллюстрации', 30)
        result = original.resize(size, Image.Resampling.LANCZOS)
        rgb = result.convert('RGB').filter(ImageFilter.UnsharpMask(radius=.6, percent=55, threshold=3))
        rgb.putalpha(result.getchannel('A'))
        rgb.info.update(graphics_mode=True, graphics_stats=dict(vector=False, algorithm=VERSION))
        if profile: rgb.info['icc_profile'] = profile
        check_cancel(cancel)
        return rgb
    if original.width * original.height > 16_000_000:
        raise ValueError('Для SVG используйте исходник до 16 мегапикселей. Векторизация не требует предварительного увеличения.')
    report('Выравнивание цветовых областей', 15)
    # Trace the source, not its enlarged pixels. Palette reduction is explicit and SVG-only.
    rgb = original.convert('RGB')
    if profile:
        from PIL import ImageCms
        rgb = ImageCms.profileToProfile(rgb, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                        ImageCms.createProfile('sRGB'), outputMode='RGB')
    prepared = flatten_palette(rgb,original.getchannel('A'),colors,cancel)
    prepared.putalpha(original.getchannel('A'))
    data = io.BytesIO(); prepared.save(data, format='PNG')
    check_cancel(cancel)
    report('Построение векторных контуров', 35)
    import vtracer
    svg = vtracer.convert_raw_image_to_svg(data.getvalue(), img_format='png', colormode='color',
        hierarchical='stacked', mode='spline', filter_speckle=round(smoothness * 8 / 100),
        color_precision=8, layer_difference=1, corner_threshold=60,
        length_threshold=3.5 + smoothness * .045, max_iterations=10,
        splice_threshold=45, path_precision=3)
    check_cancel(cancel)
    root = ET.fromstring(svg)
    root.set('viewBox', f'0 0 {original.width} {original.height}')
    root.set('width', str(size[0])); root.set('height', str(size[1]))
    svg = ET.tostring(root, encoding='unicode')
    report('Предпросмотр настоящего SVG', 85)
    result = rasterize(svg, size)
    result.info.update(graphics_mode=True, graphics_svg=svg,
                       graphics_stats=dict(vector=True, algorithm=VERSION, colors=colors,
                           paths=sum(node.tag.endswith('path') for node in root.iter())))
    check_cancel(cancel)
    return result


def flatten_palette(rgb,alpha,colors,cancel):
    """Perceptual clusters keep distinct hues instead of averaging pink and green."""
    import cv2
    import numpy as np
    sample=rgb.copy();sample.thumbnail((384,384))
    sample_rgb=np.asarray(sample)
    visible=np.asarray(alpha.resize(sample.size,Image.Resampling.NEAREST)).reshape(-1)>0
    pixels=sample_rgb.reshape(-1,3)[visible]
    if not len(pixels):return Image.new('RGBA',rgb.size)
    unique=len(np.unique(pixels,axis=0));count=min(max(2,min(64,int(colors))),unique)
    samples=cv2.cvtColor(pixels.reshape(-1,1,3),cv2.COLOR_RGB2LAB).reshape(-1,3).astype('float32')
    cv2.setRNGSeed(0)
    _,labels,centers=cv2.kmeans(samples,count,None,(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,40,.15),
                               3,cv2.KMEANS_PP_CENTERS)
    palette=np.array([pixels[labels[:,0]==i].mean(axis=0) for i in range(count)]).round().astype('uint8')
    result=Image.new('RGB',rgb.size)
    for top in range(0,rgb.height,64):
        check_cancel(cancel)
        strip=np.asarray(rgb.crop((0,top,rgb.width,min(top+64,rgb.height))))
        lab=cv2.cvtColor(strip,cv2.COLOR_RGB2LAB).astype('float32')
        nearest=((lab[:,:,None,:]-centers[None,None,:,:])**2).sum(axis=3).argmin(axis=2)
        result.paste(Image.fromarray(palette[nearest]),(0,top))
    result.putalpha(alpha)
    return result


def rasterize(svg, size):
    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    if not renderer.isValid(): raise ValueError('Не удалось прочитать векторный результат.')
    canvas = QImage(*size, QImage.Format_RGBA8888); canvas.fill(0)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter, QRectF(0, 0, *size))
    finally:
        painter.end()
    return Image.frombytes('RGBA', size, bytes(canvas.constBits()), 'raw', 'RGBA', canvas.bytesPerLine())


def export_svg(image, dpi):
    if not image.info.get('graphics_mode') or not image.info.get('graphics_svg'):
        raise ValueError('SVG доступен только для векторного результата режима «Графика и иллюстрации».')
    root = ET.fromstring(image.info['graphics_svg'])
    if any(node.tag.split('}')[-1] in ('image', 'script', 'foreignObject') for node in root.iter()):
        raise ValueError('SVG должен содержать только векторную графику.')
    root.set('width', f'{image.width / dpi:.8g}in')
    root.set('height', f'{image.height / dpi:.8g}in')
    return ET.tostring(root, encoding='unicode', xml_declaration=True)

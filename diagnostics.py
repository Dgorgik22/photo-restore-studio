"""Real offline GPU and editor validation for both consolidated profiles."""
import os,json,time,sys,threading,traceback
from pathlib import Path
from PIL import Image
from core import DATA,save_unique,Cancelled
from storage import STORE


def run():
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from app import Studio,create_application
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication,QEvent,Qt
    from studio_backend import run as restore
    import psutil
    application=QApplication.instance() or create_application()
    report=dict(version='0.25',frozen=bool(getattr(sys,'frozen',False)),executable=sys.executable,profiles=[])
    window=None
    try:
        source=DATA/'studio-input.png'
        with Image.open(STORE.settings_dir/'validation-samples/rtx-video/landscape-original.jpg') as im:
            im.crop((135,140,327,268)).save(source)
        window=Studio(auto_process=False);window.show();window.scale.setCurrentText('×2');window.add_paths([str(source)])
        if window.models.count()!=3 or hasattr(window,'quality') or hasattr(window,'auto'):raise AssertionError('Expected three modes')
        if hasattr(window,'run_button') or hasattr(window,'video_section'):raise AssertionError('Retired editor controls remain')
        if len(window.effect.buttons)!=3 or len(window.nature_repair.buttons)!=3:raise AssertionError('Three-level controls missing')
        if hasattr(window,'sky_detail') or hasattr(window,'hair_natural'):raise AssertionError('Automatic details still have manual checkboxes')
        def render():
            window.model_info.hide();window.request_render(force=True);revision=window._revision;deadline=time.monotonic()+240
            while time.monotonic()<deadline:
                application.processEvents();time.sleep(.015)
                if window._result_request and window._result_request.revision==revision and window.worker is None and not window.debounce.isActive():return window._result
                if window.worker is None and window.error_label.isVisible():raise AssertionError(window.error_label.text())
            raise TimeoutError('Editor render timed out')
        for identifier in ('photo','portrait'):
            window.select_profile(identifier)
            photo=DATA/'diagnostic_face.png' if identifier=='portrait' and (DATA/'diagnostic_face.png').exists() else source
            if str(photo.resolve())!=window._source:
                window.add_paths([str(photo)])
                for index in range(window.files.topLevelItemCount()):
                    item=window.files.topLevelItem(index)
                    if item.data(0,Qt.UserRole)==str(photo.resolve()):window.files.setCurrentItem(item);break
            image=render()
            stats=image.info.get('studio_stats',{})
            if not stats.get('ok'):raise AssertionError('No worker confirmation')
            if stats.get('comfy_stats'):raise AssertionError('Retired SDXL backend was used')
            if identifier=='portrait' and photo.name=='diagnostic_face.png' and not stats.get('portrait_stats',{}).get('faces'):
                raise AssertionError('Portrait face was not restored')
            if identifier=='portrait' and photo.name=='diagnostic_face.png' and not stats.get('portrait_stats',{}).get('hair_regions'):
                raise AssertionError('Automatic hair did not run')
            if identifier=='portrait' and not stats.get('portrait_stats',{}).get('aligned_face_regions'):
                raise AssertionError('Aligned face reconstruction was not used')
            report['profiles'].append(dict(id=identifier,size=list(image.size),stats=stats))
            window.grab().save(str(DATA/f'interface-{identifier}-0.25.png'))
        tiny=STORE.settings_dir/'validation-samples/quality-0.21/inputs/tiny-face.jpg'
        window.select_profile('portrait');window.scale.setCurrentText('×8');window.add_paths([str(tiny)])
        tiny_result=render();report['tiny_portrait']=tiny_result.info['studio_stats']
        if not report['tiny_portrait']['portrait_stats']['aligned_face_regions']:raise AssertionError('Tiny face reconstruction missing')
        if report['tiny_portrait']['base_neural_factor']!=4 or report['tiny_portrait']['base_sampling_passes']!=1:raise AssertionError('Repeated portrait generation at x8')
        if not report['tiny_portrait']['portrait_stats']['aligned_detail_regions']:raise AssertionError('Aligned detail refinement missing at x8')
        if not report['tiny_portrait']['portrait_stats'].get('neck_pixels'):raise AssertionError('Neck analysis missing')
        facade=STORE.settings_dir/'validation-samples/quality-0.21/inputs/city-facade.png'
        window.select_profile('photo');window.scale.setCurrentText('×2');window.add_paths([str(facade)])
        facade_result=render();report['architecture']=facade_result.info.get('architecture_stats',{})
        if report['architecture'].get('windows',0)<5:raise AssertionError('Facade window constraints were not used')
        cloud_source=DATA/'clouds-input.png'
        with Image.open(STORE.settings_dir/'validation-samples/quality-0.18/water-original.jpg') as im:
            im.resize((375,249),Image.Resampling.LANCZOS).save(cloud_source)
        window.select_profile('photo');window.add_paths([str(cloud_source)])
        image=render();cloud_stats=image.info.get('sky_detail_stats',{})
        if cloud_stats.get('method')!='pbrify-local-detail' or cloud_stats.get('changed_pixels',0)<100:
            raise AssertionError('Selective cloud detail did not run')
        report['clouds']=cloud_stats
        natural=image.info.get('natural_detail_stats',{})
        if natural.get('foliage_pixels',0)<100 or natural.get('water_pixels',0)<100:raise AssertionError('Automatic foliage/water detection did not run')
        report['automatic_natural_detail']=natural
        window.grab().save(str(DATA/'interface-clouds-0.25.png'))
        # Editing effects and custom sizes must reuse the neural result, including scratch metadata.
        window.image_cache.maintain(force=True);before=window.image_cache.stats()['disk_hits']
        window.effect.setValue(72);render()
        if window.image_cache.stats()['disk_hits']<=before:raise AssertionError('Scratch cache was not reused')
        before_key=window._result_request.key
        width=window._original.width
        window.scale.width_pixels.setValue(round(width*1.9));image=render()
        if window._result_request.key!=before_key:raise AssertionError('Custom resize unnecessarily repeated neural inference')
        report['custom_size']=list(image.size)
        report['exports']=[]
        for fmt,dpi in [('PNG',15),('JPEG',600)]:
            export_factor=window._result_request.export_factor
            path=save_unique(image,DATA,source,export_factor,image_format=fmt,dpi=dpi)
            with Image.open(path) as im:
                if im.size!=image.size or abs(im.info['dpi'][0]-dpi)>.02:raise AssertionError('Export mismatch')
                if not path.name.startswith(f'PhotoRestoreStudio_x{export_factor:.6g}'):raise AssertionError('Export name mismatch')
                report['exports'].append(dict(format=fmt,dpi=dpi,size=list(im.size),filename=path.name))
        report['cache']=window.image_cache.stats()
        dialog=window.open_storage();application.processEvents();dialog.grab().save(str(DATA/'settings-0.25.png'));dialog.close()
        window.show_model_info();application.processEvents();window.model_info.grab().save(str(DATA/'model-info-0.25.png'));window.model_info.hide()
        # Real offline vector worker, SVG export and format scoping.
        from PIL import ImageDraw
        graphic=DATA/'graphics-input.png';fixture=Image.new('RGBA',(120,80),(0,0,0,0))
        draw=ImageDraw.Draw(fixture);draw.rectangle((8,8,55,70),fill='#e90038');draw.ellipse((60,8,108,56),fill='#2525e8')
        fixture.save(graphic)
        window.select_profile('graphics');window.add_paths([str(graphic)])
        for i in range(window.files.topLevelItemCount()):
            item=window.files.topLevelItem(i)
            if item.data(0,Qt.UserRole)==str(graphic.resolve()):window.files.setCurrentItem(item);break
        window.export_format.setCurrentIndex(window.export_format.findData('SVG'))
        image=render()
        if not image.info.get('graphics_svg') or image.getpixel((0,0))[3]!=0:raise AssertionError('Vector/alpha missing')
        if image.info['studio_stats'].get('torch_loaded'):raise AssertionError('Graphics loaded torch')
        svg=save_unique(image,DATA,str(graphic),window.scale.value,image_format='SVG')
        import xml.etree.ElementTree as ET
        svg_root=ET.parse(svg).getroot()
        if not any(n.tag.endswith('path') for n in svg_root.iter()):raise AssertionError('No vector paths')
        if any(n.tag.endswith('image') for n in svg_root.iter()):raise AssertionError('Raster embedded in SVG')
        report['graphics']=dict(svg=str(svg),size=list(image.size),stats=image.info['studio_stats'])
        window.grab().save(str(DATA/'interface-graphics-0.25.png'))
        window.select_profile('photo')
        if window.export_format.findData('SVG')!=-1:raise AssertionError('SVG leaked into photo mode')
        # Cancel a real owned GPU worker after its first operation. Its entire process tree must exit.
        cancel=threading.Event();started=time.monotonic()
        try:
            restore(str(source),8,.4,.4,True,lambda t,p:cancel.set() if p>=3 else None,cancel,'full',model_path=str(STORE.models/'RealESRGAN_x4plus.pth'))
            raise AssertionError('Cancel did not interrupt GPU worker')
        except Cancelled:pass
        report['cancel_seconds']=round(time.monotonic()-started,3)
        leftovers=[p.pid for p in psutil.Process().children(recursive=True) if p.is_running()]
        if leftovers:raise AssertionError('Owned workers remain: '+str(leftovers))
        report['no_child_processes_after_work']=True
        report['parent_torch_loaded']='torch' in sys.modules
        report['parent_rss_mb']=round(psutil.Process().memory_info().rss/1024**2)
        window.close_current_file();application.processEvents()
        if window._result is not None:raise AssertionError('Closing file retained preview')
        report['ok']=True
    except Exception:
        report['ok']=False;report['error']=traceback.format_exc()
    finally:
        if window:window.finish_close()
        for widget in application.topLevelWidgets():
            if isinstance(widget,Studio):widget.finish_close()
        for widget in application.topLevelWidgets():widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);application.processEvents()
        report['shutdown_drained']=True
    (DATA/'diagnostics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['ok'] else 1

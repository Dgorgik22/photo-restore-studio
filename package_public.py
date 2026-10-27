"""Build independent standard ZIP release parts from an explicit clean allowlist."""
from pathlib import Path
import hashlib,json,zipfile

ROOT=Path(__file__).parent
HOME=ROOT/'PhotoRestoreStudio'
DEST=ROOT.parent/'Releases/PhotoRestoreStudio-0.25-alpha-lite'
LIMIT=1_600_000_000


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    DEST.mkdir(parents=True,exist_ok=False)
    files=[HOME/'PhotoRestoreStudio.exe']
    for name in ('libraries','plugins','licenses'):
        files.extend(p for p in (HOME/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts
                     and not p.is_symlink() and not p.is_junction())
    bins=[]
    for path in sorted(files,key=lambda p:p.stat().st_size,reverse=True):
        size=path.stat().st_size
        if size>LIMIT:raise ValueError('Individual file too large: '+str(path))
        bucket=next((b for b in bins if b['bytes']+size<=LIMIT),None)
        if bucket is None:bucket=dict(bytes=0,files=[]);bins.append(bucket)
        bucket['files'].append(path);bucket['bytes']+=size
    manifest=dict(version='0.25-alpha-lite',compression='ZIP/Deflate lossless',archives=[],
                  models={str(p.relative_to(HOME)):sha(p) for p in (HOME/'plugins').rglob('*') if p.is_file()},
                  unpacked_bytes=sum(p.stat().st_size for p in files),included_files=len(files))
    for index,bucket in enumerate(bins,1):
        destination=DEST/f'PhotoRestoreStudio-0.25-alpha-lite-part-{index:02}.zip'
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for path in sorted(bucket['files']):
                archive.write(path,'PhotoRestoreStudio/'+path.relative_to(HOME).as_posix())
            if index==1:archive.write(ROOT/'PUBLIC-ALPHA.md','PhotoRestoreStudio/README.md')
        with zipfile.ZipFile(destination) as archive:
            if archive.testzip() is not None:raise ValueError('ZIP integrity failure')
        size=destination.stat().st_size
        if size>=2*1024**3:raise ValueError('GitHub asset exceeds 2 GiB')
        manifest['archives'].append(dict(name=destination.name,bytes=size,sha256=sha(destination)))
        print(destination.name,size,flush=True)
    source=DEST/'PhotoRestoreStudio-0.25-alpha-lite-source.zip'
    modules={'app','architecture_detail','collect_licenses','core','diagnostics','disk_report','editor_jobs',
             'file_table','freeze','gpu_policy','graphics','i18n','image_cache','level_controls','library_ui','lighting',
             'model_downloads','model_info','model_updates','natural_detail','output_controls','portrait',
             'portrait_texture','profiles','sections','sky_detail','storage','storage_ui','studio_backend',
             'surface_light','theme','tiles','viewer','worker_process','package_public','prune_runtime'}
    with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in ROOT.glob('*.py'):
            if path.stem in modules or path.name.startswith('test_'):archive.write(path,'source/'+path.name)
        for name in ('requirements.txt','requirements-lock.txt','install.ps1','build.ps1','catalog.json','PUBLIC-ALPHA.md','.gitignore','Install-Alpha.ps1','Setup.cmd'):
            archive.write(ROOT/name,'source/'+name)
        for name in ('assets/brand','third_party/codeformer'):
            for path in (ROOT/name).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:archive.write(path,'source/'+path.relative_to(ROOT).as_posix())
        for name in ('assets/i18n.json','assets/licenses/Real-ESRGAN-BSD-3-Clause.txt',
                     'assets/licenses/PBRify-CC0.txt','assets/licenses/CodeFormer-SLab.txt'):
            archive.write(ROOT/name,'source/'+name)
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None:raise ValueError('Source ZIP integrity failure')
    manifest['source']=dict(name=source.name,bytes=source.stat().st_size,sha256=sha(source))
    manifest['download_bytes']=sum(p['bytes'] for p in manifest['archives'])
    manifest['fits_4gb_download']=manifest['download_bytes']<=4_000_000_000
    (DEST/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (DEST/'README.md').write_text((ROOT/'PUBLIC-ALPHA.md').read_text(encoding='utf-8'),encoding='utf-8')
    for name in ('Install-Alpha.ps1','Setup.cmd'):
        (DEST/name).write_bytes((ROOT/name).read_bytes())
    print(json.dumps({k:manifest[k] for k in ('unpacked_bytes','download_bytes','fits_4gb_download')}),flush=True)


if __name__=='__main__':main()

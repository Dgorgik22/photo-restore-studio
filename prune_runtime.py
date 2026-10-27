"""Remove unused PDF image support and unused Qt translations, never model weights."""
from pathlib import Path
import hashlib,json,sys


def prune(product):
    product=Path(product).resolve();qt=product/'libraries/PySide6'
    candidates=[qt/'Qt6Pdf.dll',qt/'plugins/imageformats/qpdf.dll']
    candidates += [p for p in (qt/'translations').glob('*.qm') if not p.stem.endswith(('_ru','_en'))]
    # Reused build runtimes may make PyInstaller collect the same CUDA DLL both
    # at the root and in its owning package. Torch adds torch/lib to DLL search.
    # Keep the package copy; never remove shared Microsoft runtime libraries.
    libraries=product/'libraries'
    for path in libraries.glob('*.dll'):
        if path.name.lower().startswith(('vcruntime','msvcp','concrt','api-ms-')):continue
        for folder in (libraries/'torch/lib',libraries/'torchvision'):
            owner=folder/path.name
            if owner.is_file() and owner.stat().st_size==path.stat().st_size:
                def digest(p):
                    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').digest()
                if digest(owner)==digest(path):candidates.append(path);break
    removed=[]
    for path in candidates:
        if not path.exists():continue
        if path.is_symlink() or path.resolve()!=path or not path.resolve().is_relative_to(product):
            raise ValueError('Linked runtime file rejected')
        removed.append(dict(path=str(path.relative_to(product)),bytes=path.stat().st_size));path.unlink()
    return removed


if __name__=='__main__':print(json.dumps(prune(sys.argv[1]),ensure_ascii=False))

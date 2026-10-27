"""Logical and allocated bytes on Windows, including transparent file compression."""
import ctypes
import json
import os
from pathlib import Path
import sys


def allocated(path):
    if os.name != 'nt':
        stat = path.stat()
        return getattr(stat,'st_blocks',0)*512 or stat.st_size
    high = ctypes.c_ulong()
    function = ctypes.windll.kernel32.GetCompressedFileSizeW
    function.argtypes = [ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)]
    function.restype = ctypes.c_ulong
    low = function(str(path),ctypes.byref(high))
    if low == 0xffffffff and ctypes.windll.kernel32.GetLastError():
        return path.stat().st_size
    return (high.value<<32)|low


def measure(path):
    logical = physical = count = 0
    for parent,dirs,files in os.walk(path,followlinks=False):
        dirs[:] = [name for name in dirs if not Path(parent,name).is_symlink() and not Path(parent,name).is_junction()]
        for name in files:
            file = Path(parent,name)
            try:
                logical += file.stat().st_size
                physical += allocated(file)
                count += 1
            except OSError:
                pass
    return dict(folder=str(path),logical_bytes=logical,allocated_bytes=physical,files=count)


if __name__ == '__main__':
    root = Path(__file__).parent
    report = [measure(path) for path in root.iterdir() if path.is_dir() and path.name != '__pycache__']
    destination = root/'PhotoRestoreStudio/storage/disk-report.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in report:
        print(row['folder'],f"logical={row['logical_bytes']/1024**3:.2f} GiB disk={row['allocated_bytes']/1024**3:.2f} GiB")

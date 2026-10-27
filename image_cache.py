"""Bounded LRU of AI results. Lossless spill files live on the chosen scratch disk."""
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from PIL import Image
from storage import memory_status


class ImageCache:
    def __init__(self,root,ram_mb=512,disk_gb=8,available=None):
        self.root = Path(root)/f'session-{os.getpid()}-{uuid.uuid4().hex}'
        self.root.mkdir(parents=True)
        self.lockfile = (self.root/'active.lock').open('w+b')
        self.lockfile.write(b'1')
        self.lockfile.flush()
        if os.name == 'nt':
            import msvcrt
            self.lockfile.seek(0)
            msvcrt.locking(self.lockfile.fileno(),msvcrt.LK_NBLCK,1)
        self.ram_limit = int(ram_mb*1024**2)
        self.disk_limit = int(disk_gb*1024**3)
        self.available = available or (lambda: memory_status()[1])
        self.entries = OrderedDict()
        self.lock = threading.RLock()
        self.hits = self.disk_hits = self.spills = 0
        self.last_error = ''

    def _path(self,key):
        return self.root/(hashlib.sha256(repr(key).encode('utf-8')).hexdigest()+'.tiff')

    def _memory_used(self):
        return sum(entry['bytes'] for entry in self.entries.values() if entry['image'] is not None)

    def put(self,key,image):
        with self.lock:
            previous = self.entries.pop(key,None)
            if previous is not None:
                previous['path'].unlink(missing_ok=True)
            self.entries[key] = dict(image=image,bytes=image.width*image.height*len(image.getbands()),path=self._path(key))
            self.maintain()

    def get(self,key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                return None
            self.entries.move_to_end(key)
            if entry['image'] is not None:
                self.hits += 1
                return entry['image']
            try:
                with Image.open(entry['path']) as opened:
                    image = opened.copy()
                    metadata = getattr(opened,'tag_v2',{}).get(270)
                    if metadata:
                        try:
                            image.info.update(json.loads(metadata))
                        except (ValueError,TypeError):
                            pass
            except (OSError,ValueError):
                self.entries.pop(key,None)
                return None
            self.disk_hits += 1
            os.utime(entry['path'],None)
            if entry['bytes'] <= self.ram_limit and self.available() > max(512*1024**2,entry['bytes']*2):
                entry['image'] = image
                self.maintain()
            return image

    def maintain(self,force=False):
        with self.lock:
            reserve = max(512*1024**2,memory_status()[0]//10)
            pressure = self.available() < reserve
            for key,entry in list(self.entries.items()):
                if entry['image'] is None:
                    continue
                if not force and not pressure and self._memory_used() <= self.ram_limit:
                    break
                if not entry['path'].exists():
                    temp = entry['path'].with_suffix('.tmp')
                    try:
                        metadata = {key:entry['image'].info[key] for key in ('portrait_regions','portrait_stats','nature_stats','experimental_stats','rtx_video_stats','studio_stats','seed_stats','sky_detail_stats','natural_detail_stats','portrait_texture_stats','architecture_stats','graphics_mode','graphics_svg','graphics_stats') if key in entry['image'].info}
                        entry['image'].save(temp,format='TIFF',compression='raw',tiffinfo={270:json.dumps(metadata)})
                        os.replace(temp,entry['path'])
                    except OSError as error:
                        self.last_error = str(error)
                        del self.entries[key]
                        continue
                    finally:
                        temp.unlink(missing_ok=True)
                entry['image'] = None
                self.spills += 1
            disk = sum(entry['path'].stat().st_size for entry in self.entries.values() if entry['path'].exists())
            for key,entry in list(self.entries.items()):
                if disk <= self.disk_limit:
                    break
                if entry['path'].exists():
                    disk -= entry['path'].stat().st_size
                    entry['path'].unlink()
                    if entry['image'] is None:
                        del self.entries[key]

    def stats(self):
        with self.lock:
            return dict(ram_bytes=self._memory_used(),disk_bytes=sum(entry['path'].stat().st_size for entry in self.entries.values() if entry['path'].exists()),
                        entries=len(self.entries),hits=self.hits,disk_hits=self.disk_hits,spills=self.spills,last_error=self.last_error)

    def discard_source(self,source):
        """Closing a document drops all cached stages, including their scratch files."""
        def contains(value):
            if isinstance(value,(tuple,list)):return any(contains(part) for part in value)
            return value==source
        with self.lock:
            for key in list(self.entries):
                if contains(key):
                    self.entries.pop(key)['path'].unlink(missing_ok=True)

    def retain_recent(self,count=3):
        """Keep only a small undo/re-edit window, even with a very large RAM preference."""
        with self.lock:
            while len(self.entries)>count:
                _,entry=self.entries.popitem(last=False)
                entry['path'].unlink(missing_ok=True)

    def close(self):
        with self.lock:
            self.entries.clear()
            if not self.lockfile.closed:
                self.lockfile.close()
            shutil.rmtree(self.root,ignore_errors=True)


def inactive_sessions(root):
    """Only abandoned sessions may be removed; another running app keeps its lock."""
    for path in Path(root).glob('session-*'):
        if not path.is_dir() or path.is_symlink() or path.is_junction():
            continue
        try:
            with (path/'active.lock').open('r+b') as handle:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            yield path
        except OSError:
            continue

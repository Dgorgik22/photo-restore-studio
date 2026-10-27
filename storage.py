"""Portable paths and guarded cleanup. Models/results are never cache targets."""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

APP_HOME = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent/'PhotoRestoreStudio'
MARKER = '.photo-restore-managed.json'


def memory_status():
    if os.name == 'nt':
        class Memory(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong),
                        ('total',ctypes.c_ulonglong),('available',ctypes.c_ulonglong),
                        ('page_total',ctypes.c_ulonglong),('page_available',ctypes.c_ulonglong),
                        ('virtual_total',ctypes.c_ulonglong),('virtual_available',ctypes.c_ulonglong),
                        ('extended',ctypes.c_ulonglong)]
        value = Memory()
        value.length = ctypes.sizeof(value)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            return value.total,value.available
    return 8*1024**3,4*1024**3


def folder_bytes(path):
    total = 0
    for parent,dirs,files in os.walk(path,followlinks=False):
        dirs[:] = [name for name in dirs if not Path(parent,name).is_symlink() and not Path(parent,name).is_junction()]
        for name in files:
            try:
                file = Path(parent,name)
                if not file.is_symlink():
                    total += file.stat().st_size
            except OSError:
                pass
    return total


class Storage:
    def __init__(self,home=APP_HOME):
        self.home = Path(home).resolve()
        self.plugins = self.home/'plugins'
        self.models = self.plugins/'models'
        self.results = self.home/'results'
        self.settings_dir = self.home/'storage'
        self.settings_file = self.settings_dir/'settings.json'
        for path in (self.models,self.results,self.settings_dir):
            path.mkdir(parents=True,exist_ok=True)
        defaults = dict(ram_cache_mb=512,disk_cache_gb=8,gpu_mode='balanced',weekly_model_updates=True,language='ru',
                        cache_path=str(self.settings_dir/'cache'),scratch_path=str(self.settings_dir/'scratch'))
        try:
            saved = json.loads(self.settings_file.read_text(encoding='utf-8'))
            if isinstance(saved,dict):
                defaults.update({key:saved[key] for key in defaults if key in saved})
        except (OSError,ValueError):
            pass
        self.settings = defaults
        self.settings['ram_cache_mb'] = max(64,min(16384,int(defaults['ram_cache_mb'])))
        self.settings['disk_cache_gb'] = max(1,min(256,int(defaults['disk_cache_gb'])))
        if self.settings['gpu_mode'] not in ('eco','balanced','full'):self.settings['gpu_mode']='balanced'
        if not isinstance(self.settings['weekly_model_updates'],bool):self.settings['weekly_model_updates']=True
        if self.settings['language'] not in ('ru','en'):self.settings['language']='ru'
        for kind in ('cache','scratch'):
            path = Path(self.settings[kind+'_path'])
            try:
                self._prepare(path,kind)
            except (OSError,ValueError):
                path = self.settings_dir/kind
                self._prepare(path,kind)
                self.settings[kind+'_path'] = str(path)

    @property
    def cache(self):
        return Path(self.settings['cache_path'])

    @property
    def scratch(self):
        return Path(self.settings['scratch_path'])

    def _prepare(self,path,kind):
        path = Path(path).absolute()
        if path.is_symlink() or path.is_junction() or path.resolve() != path:
            raise ValueError('Выберите обычную папку без ссылок и перенаправлений.')
        for protected in (self.plugins,self.results,self.home/'libraries'):
            if path == protected or path.is_relative_to(protected) or protected.is_relative_to(path):
                raise ValueError('Кэш должен храниться отдельно от программы, моделей и результатов.')
        if path == self.home or path == self.settings_dir or path == Path(path.anchor):
            raise ValueError('Нужна отдельная подпапка для временных данных.')
        marker = path/MARKER
        if path.exists() and any(path.iterdir()) and not marker.exists():
            raise ValueError('Папка содержит посторонние файлы. Выберите пустую подпапку.')
        if marker.exists():
            metadata = json.loads(marker.read_text(encoding='utf-8'))
            if metadata.get('kind') != kind or metadata.get('application') != 'PhotoRestoreStudio':
                raise ValueError('Эта папка не является кэшем программы нужного вида.')
        path.mkdir(parents=True,exist_ok=True)
        marker.write_text(json.dumps(dict(application='PhotoRestoreStudio',kind=kind,version=1)),encoding='utf-8')

    def choose_parent(self,parent,kind):
        if kind not in ('cache','scratch'):
            raise ValueError('Неизвестный вид хранилища.')
        target = Path(parent).resolve()/('PhotoRestoreStudioCache' if kind == 'cache' else 'PhotoRestoreStudioScratch')
        other = self.scratch if kind == 'cache' else self.cache
        if target == other or target.is_relative_to(other) or other.is_relative_to(target):
            raise ValueError('Кэш и рабочий диск должны храниться отдельно.')
        self._prepare(target,kind)
        return target

    def save(self,**changes):
        updated = {**self.settings,**changes}
        if updated['language'] not in ('ru','en'):raise ValueError('Unsupported language')
        if not 64 <= updated['ram_cache_mb'] <= 16384 or not 1 <= updated['disk_cache_gb'] <= 256:
            raise ValueError('Недопустимый лимит кэша.')
        if updated['gpu_mode'] not in ('eco','balanced','full') or not isinstance(updated['weekly_model_updates'],bool):
            raise ValueError('Недопустимый режим видеокарты или обновлений.')
        for kind in ('cache','scratch'):
            self._prepare(Path(updated[kind+'_path']),kind)
        temporary = self.settings_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,self.settings_file)
        self.settings = updated

    def bootstrap(self):
        """Redirect process-local temporary data before importing heavy libraries."""
        if hasattr(self,'temp_dir'):
            return
        self.temp_dir = self.cache/'temp'/f'session-{os.getpid()}-{uuid.uuid4().hex}'
        self.temp_dir.mkdir(parents=True,exist_ok=True)
        self.temp_lock = (self.temp_dir/'active.lock').open('w+b')
        self.temp_lock.write(b'1')
        self.temp_lock.flush()
        if os.name == 'nt':
            import msvcrt
            self.temp_lock.seek(0)
            msvcrt.locking(self.temp_lock.fileno(),msvcrt.LK_NBLCK,1)
        paths = dict(TEMP='temp',TMP='temp',TMPDIR='temp',MPLCONFIGDIR='matplotlib',
                     TORCH_HOME='torch',HF_HOME='huggingface',NUMBA_CACHE_DIR='numba',CUDA_CACHE_PATH='cuda')
        for variable,child in paths.items():
            directory = self.temp_dir if child == 'temp' else self.cache/child
            directory.mkdir(parents=True,exist_ok=True)
            os.environ[variable] = str(directory)
        tempfile.tempdir = str(self.temp_dir)

    def active_paths(self):
        keep = []
        for lockfile in self.cache.glob('temp/session-*/active.lock'):
            try:
                with lockfile.open('r+b') as handle:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                keep.append(lockfile.parent)
        for path in self.cache.glob('downloads/*.part'):
            if time.time()-path.stat().st_mtime < 3600:
                keep.append(path)
        return keep

    def subdir(self,name):
        if name not in ('downloads','updates','logs','diagnostics','previews','temp'):
            raise ValueError('Неизвестный раздел кэша.')
        path = self.cache/name
        path.mkdir(exist_ok=True)
        return path

    def clean(self,kind='cache',older_than=0,keep=(),cancel=None):
        root = self.cache if kind == 'cache' else self.scratch
        marker = root/MARKER
        metadata = json.loads(marker.read_text(encoding='utf-8'))
        if metadata.get('application') != 'PhotoRestoreStudio' or metadata.get('kind') != kind:
            raise ValueError('Очистка разрешена только для папки кэша этой программы.')
        if root.is_symlink() or root.is_junction() or root.resolve() != root:
            raise ValueError('Папка кэша перенаправлена. Очистка отменена.')
        protected = [Path(path).resolve() for path in keep]
        removed = 0
        visited = []
        for parent,dirs,files in os.walk(root,topdown=True,followlinks=False):
            if cancel is not None and cancel.is_set():
                return removed
            parent = Path(parent)
            # os.walk can enter junctions; never operate outside the verified root.
            if not parent.resolve().is_relative_to(root):
                dirs.clear()
                continue
            if any(parent.resolve() == path or parent.resolve().is_relative_to(path) for path in protected):
                dirs.clear()
                continue
            dirs[:] = [name for name in dirs if not (parent/name).is_symlink() and not (parent/name).is_junction()]
            visited.append(parent)
            for name in files:
                if cancel is not None and cancel.is_set():
                    return removed
                file = parent/name
                try:
                    if file == marker or file.is_symlink() or file.resolve() in protected or time.time()-file.stat().st_mtime < older_than:
                        continue
                    size = file.stat().st_size
                    file.unlink()
                    removed += size
                except OSError:
                    pass
        for directory in reversed(visited):
            if cancel is not None and cancel.is_set():
                break
            if directory == root:
                continue
            try:
                directory.rmdir()
            except OSError:
                pass
        return removed


STORE = Storage()
STORE.bootstrap()

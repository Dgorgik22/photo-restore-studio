"""Per-job GPU scheduling. No driver power limits or GPU clock changes."""
import threading
import time
from contextlib import contextmanager

MODES = {'eco':dict(tile=128,duty=.5,reserve=2.5),
         'balanced':dict(tile=384,duty=.9,reserve=2.),
         'full':dict(tile=512,duty=1.,reserve=1.5)}
_local = threading.local()


def current_mode():
    from storage import STORE
    return getattr(_local,'mode',STORE.settings.get('gpu_mode','balanced'))


@contextmanager
def use_mode(mode):
    if mode not in MODES:raise ValueError('Неизвестный режим видеокарты')
    old = getattr(_local,'mode',None)
    _local.mode = mode
    try:yield
    finally:
        if old is None:del _local.mode
        else:_local.mode = old


def tile_size(preferred,mode=None):
    return min(preferred,MODES[mode or current_mode()]['tile'])


class Pacer:
    def __init__(self,cancel,mode=None):
        self.cancel = cancel
        self.duty = MODES[mode or current_mode()]['duty']

    def pause(self,started):
        elapsed = time.perf_counter()-started
        wait = elapsed*(1/self.duty-1)
        if wait>0 and self.cancel.wait(wait):
            from core import check_cancel
            check_cancel(self.cancel)

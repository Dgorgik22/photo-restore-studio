"""Wait for every owned process to exit before releasing logs or scratch files."""
import os
import subprocess


def stop_process_tree(process):
    import psutil
    try:
        parent=psutil.Process(process.pid)
        owned=parent.children(recursive=True)+[parent]
    except psutil.NoSuchProcess:
        process.wait(10)
        return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)
    else:
        for child in reversed(owned):
            try:child.terminate()
            except psutil.NoSuchProcess:pass
    _,alive=psutil.wait_procs(owned,timeout=10)
    for child in alive:
        try:child.kill()
        except psutil.NoSuchProcess:pass
    _,alive=psutil.wait_procs(alive,timeout=5)
    process.wait(10)
    if alive:raise RuntimeError('Не удалось завершить дочерний процесс обработки.')

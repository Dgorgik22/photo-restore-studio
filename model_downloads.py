import hashlib,time,urllib.request
from pathlib import Path
from core import check_cancel

def sha256(path,cancel):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        while block := source.read(8*1024**2):
            check_cancel(cancel)
            digest.update(block)
    return digest.hexdigest()


def fetch(name,target,report,cancel,offset=0,total=1,expected_size=None,repository=None,revision=None):
    target = Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(3):
        check_cancel(cancel)
        received = target.stat().st_size if target.exists() else 0
        if expected_size and received == expected_size:
            return
        url = f'https://huggingface.co/{repository}/resolve/{revision}/{name}?download=true&prs={time.time_ns()}'
        headers = {'User-Agent':'PhotoRestoreStudio/0.17'}
        if received:
            headers['Range'] = f'bytes={received}-'
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=40) as response:
                if received and (response.status != 206 or not response.headers.get('Content-Range','').startswith(f'bytes {received}-')):
                    received = 0
                mode = 'ab' if received else 'wb'
                with target.open(mode) as output:
                    while block := response.read(1024**2):
                        check_cancel(cancel)
                        output.write(block)
                        received += len(block)
                        if expected_size:
                            report(f'Загрузка дорисовки: {(offset+received)/1e9:.2f} / {total/1e9:.2f} ГБ',
                                   min(85,int(85*(offset+received)/total)))
            if expected_size and received != expected_size:
                raise IOError('Не все данные модели были загружены. Повторите установку для продолжения.')
            return
        except (OSError,TimeoutError):
            if attempt == 2:
                raise


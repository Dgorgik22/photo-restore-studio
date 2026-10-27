"""Weekly metadata checks; no automatic model replacement or photograph upload."""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from core import check_cancel
from storage import STORE

WEEK = 7*86400
REPOSITORIES = ('Kim2091/Kim2091-Models','sczhou/CodeFormer','xinntao/Real-ESRGAN')


def state_file(store=STORE):
    return store.settings_dir/'model-updates.json'


def read_state(store=STORE):
    try:
        data=json.loads(state_file(store).read_text(encoding='utf-8'))
        if not isinstance(data,dict) or not isinstance(data.get('sources',{}),dict):return {}
        if any(not isinstance(data.get(key,0),(int,float)) for key in ('checked_at','attempted_at')):return {}
        active=set(REPOSITORIES)|{row[0] for row in weight_sources()}
        data['sources']={k:v for k,v in data.get('sources',{}).items() if k in active}
        data['new_count']=sum(bool(item.get('available')) for item in data['sources'].values())
        return data
    except (OSError,ValueError):return {}


def due(store=STORE,now=None):
    if not store.settings.get('weekly_model_updates',True):return False
    now=time.time() if now is None else now
    data=read_state(store)
    return now-data.get('checked_at',0)>=WEEK and now-data.get('attempted_at',0)>=86400


def fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':'PhotoRestoreStudio/0.16','Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=10) as response:
        return json.load(response)


def weight_sources():
    return []



def check(report,cancel,store=STORE,now=None):
    now=time.time() if now is None else now
    previous=read_state(store)
    active=set(REPOSITORIES)|{row[0] for row in weight_sources()}
    sources={key:value for key,value in previous.get('sources',{}).items() if key in active};errors=[];success=0
    for index,repository in enumerate(REPOSITORIES):
        check_cancel(cancel)
        try:
            try:release=fetch(f'https://api.github.com/repos/{repository}/releases/latest')
            except urllib.error.HTTPError as error:
                if error.code!=404:raise
                release={}
            tag=release.get('tag_name','')
            old=sources.get(repository,{})
            sources[repository]=dict(name=repository,version=tag,url=release.get('html_url',''),
                available=(tag!=old.get('version') if old else False) or old.get('available',False),
                kind='release',checked_at=now)
            success+=1
        except (OSError,ValueError,KeyError) as error:
            errors.append(repository+': '+str(error))
        report('Проверка новых версий моделей…',int((index+1)*85/len(REPOSITORIES)))
    for identifier,repository,filename,pinned_sha,title in weight_sources():
        check_cancel(cancel)
        try:
            data=fetch(f'https://huggingface.co/api/models/{repository}?blobs=true')
            weight=next(item for item in data['siblings'] if item['rfilename']==filename)
            sha=weight.get('lfs',{}).get('sha256')
            if not sha:raise ValueError('Источник не вернул контрольную сумму весов')
            sources[identifier]=dict(name=title,version=sha[:12],sha256=sha,
                url='https://huggingface.co/'+repository,available=sha!=pinned_sha,kind='weights',checked_at=now)
            success+=1
        except (OSError,ValueError,KeyError,StopIteration) as error:
            errors.append(title+': '+str(error))
    check_cancel(cancel)
    result=dict(sources=sources,attempted_at=now,checked_at=now if success else previous.get('checked_at',0),
                errors=errors,new_count=sum(bool(item.get('available')) for item in sources.values()),
                first_check=not bool(previous.get('sources')))
    target=state_file(store);temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temporary,target)
    report('Проверка обновлений завершена',100)
    return result


def summary(store=STORE):
    state=read_state(store)
    if not state.get('checked_at'):
        return 'Ещё не проверяли. При включении — раз в неделю во время работы программы.'
    date=time.strftime('%d.%m.%Y',time.localtime(state['checked_at']))
    count=state.get('new_count',0)
    text=f'Последняя проверка: {date}. '+(f'Новых версий или релизов: {count}.' if count else
        'Список релизов сохранён для сравнения.' if state.get('first_check') else 'Новых версий не обнаружено.')
    if state.get('errors'):text+=' Часть источников недоступна.'
    return text

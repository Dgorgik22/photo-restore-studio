"""Copy installed dependency license notices into the personal portable build."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

release = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / 'dist' / 'PhotoRestoreStudio'
target = release / 'licenses'
target.mkdir(parents=True, exist_ok=True)
inventory = []
# A lean UI build can reuse unchanged heavyweight runtimes from the installed app.
# Preserve their original license records when local metadata has no RECORD list.
previous = Path(__file__).parent/'PhotoRestoreStudio/licenses'
if previous.is_dir() and previous.resolve()!=target.resolve():
    shutil.copytree(previous,target,dirs_exist_ok=True)
    try:
        inventory=json.loads((previous/'dependencies.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):
        inventory=[]
for dist in importlib.metadata.distributions():
    name = dist.metadata.get('Name', 'unknown')
    entry={'name': name, 'version': dist.version,
                      'license': dist.metadata.get('License-Expression') or dist.metadata.get('License'),
                      'project_urls': dist.metadata.get_all('Project-URL') or []}
    old=next((item for item in inventory if item['name'].lower()==name.lower()),None)
    if old is None:inventory.append(entry)
    elif old['version']!=dist.version or dist.files:
        inventory[inventory.index(old)]=entry
    for file in dist.files or []:
        if not any('license' in part.lower() or 'copying' in part.lower() for part in file.parts):
            continue
        source = Path(dist.locate_file(file))
        if source.is_file():
            destination = target / name / Path(*file.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
(target / 'dependencies.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'License inventory: {len(inventory)} dependencies')

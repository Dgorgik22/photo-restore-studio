"""Two photo pipelines; no retired generative runtime in the portable build."""
from pathlib import Path
import sys
import PyInstaller.__main__
root=Path(__file__).parent
args=['--noconfirm','--windowed','--onedir','--name','PhotoRestoreStudio',
      '--icon',str(root/'assets/brand/photo-restore.ico'),'--version-file',str(root/'assets/brand/windows-version.txt'),
      '--contents-directory','libraries',
      '--add-data',f'{root/"catalog.json"};.',
      '--add-data',f'{root/"assets/brand"};assets/brand',
      '--add-data',f'{root/"assets/i18n.json"};assets',
      '--add-data',f'{root/"third_party/codeformer"};third_party/codeformer','--hidden-import','diagnostics']
for package in ('spandrel','cv2','facexlib','einops','psutil','vtracer'):
    args+=['--collect-all',package]
for module in ('restoration','restoration_assets','experimental','experimental_assets','segmentation',
               'experimental_ui','rtx_video','rtx_video_assets','nature_assets','nature','comfy_detail','comfy_assets',
               'seed_assets','seed_renderer','comfy','comfy_api','comfy_extras','comfy_kitchen','comfy_aimdo',
               'transformers','tokenizers','huggingface_hub','torchsde','kornia','sentencepiece',
               'diffusers','accelerate','gfpgan','basicsr','matplotlib','tensorboard','pytest','IPython','notebook'):
    args+=['--exclude-module',module]
args+=[str(root/'app.py')]+sys.argv[1:]
PyInstaller.__main__.run(args)

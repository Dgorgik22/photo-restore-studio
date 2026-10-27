import json
import shutil
import urllib.request
from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QPushButton, QFileDialog, QHBoxLayout, QProgressBar
from core import CATALOG, MODELS, download, check_cancel
from editor_jobs import FileWorker
from storage import STORE
from model_info import guide_text


class LibraryDialog(QDialog):
    modelsChanged = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Модели и плагины')
        self.resize(700, 610)
        self.worker = None
        layout = QVBoxLayout(self)
        heading = QLabel('Библиотека восстановления')
        heading.setObjectName('heading')
        layout.addWidget(heading)
        intro = QLabel('Модели и модули из официальных источников. Обработка фотографий выполняется локально.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.catalog_list = QListWidget()
        self.catalog_list.currentRowChanged.connect(self.describe)
        layout.addWidget(self.catalog_list,1)
        self.details = QLabel()
        self.details.setObjectName('muted')
        self.details.setWordWrap(True)
        self.details.setOpenExternalLinks(True)
        self.details.setMinimumHeight(105)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        self.download_button = QPushButton('Установить модель')
        self.download_button.clicked.connect(self.get_model)
        row.addWidget(self.download_button)
        self.import_button = QPushButton('Импорт весов…')
        self.import_button.clicked.connect(self.import_model)
        row.addWidget(self.import_button)
        layout.addLayout(row)
        self.updates_button = QPushButton('Проверить обновления моделей')
        self.updates_button.clicked.connect(self.check_updates)
        layout.addWidget(self.updates_button)
        self.status = QLabel('Совместимые веса .pth и .safetensors. Произвольный код плагинов не устанавливается.')
        self.status.setObjectName('muted')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.refresh()
        self.catalog_list.setCurrentRow(0)

    def refresh(self):
        selected = max(0,self.catalog_list.currentRow())
        self.catalog_list.clear()
        for entry in CATALOG:
            installed = (MODELS/entry['file']).exists()
            state = 'Установлена' if installed else 'Подключить SDK' if entry['kind']=='rtx-video' else 'Доступна загрузка'
            self.catalog_list.addItem(f"{entry['name']}  ·  {state}")
            self.catalog_list.item(self.catalog_list.count()-1).setToolTip(guide_text(MODELS/entry['file']))
        self.catalog_list.setCurrentRow(selected)

    def describe(self, row):
        if 0 <= row < len(CATALOG):
            entry = CATALOG[row]
            self.details.setText(f"<b>{entry['name']}</b><br>Модель: {entry['technical_name']}<br>{entry.get('description','')}<br>"
                                 f"Лицензия: {entry['license']} · <a style='color:#7bb8ff' href='{entry['source']}'>GitHub / источник</a>")
            self.download_button.setText('Подключить папку RTX Video SDK…' if entry['kind']=='rtx-video' else 'Установить модель')

    def start(self, action):
        if self.worker and self.worker.isRunning():
            return
        self.worker = FileWorker(action)
        self.worker.progress.connect(lambda text,value: (self.status.setText(text),self.progress.setValue(value)))
        self.worker.error.connect(self.status.setText)
        self.worker.completed.connect(lambda value: (self.refresh(),self.modelsChanged.emit(),self.status.setText(str(value or 'Готово'))))
        self.worker.finished.connect(self.task_finished)
        for button in (self.import_button,self.download_button,self.updates_button):
            button.setEnabled(False)
        self.worker.start()

    def task_finished(self):
        for button in (self.import_button,self.download_button,self.updates_button):
            button.setEnabled(True)

    def get_model(self):
        row = self.catalog_list.currentRow()
        if row >= 0:
            entry = CATALOG[row]
            def action(worker):
                download(entry,worker.progress.emit,worker.cancel)
                for dependency in entry.get('dependencies',[]):
                    download(dependency,worker.progress.emit,worker.cancel,STORE.plugins/'gfpgan'/'weights')
                return f"Установлена: {entry['name']}"
            self.start(action)

    def import_model(self):
        from i18n import tr
        file,_ = QFileDialog.getOpenFileName(self,tr('Импорт доверенной модели'),'',tr('Веса моделей (*.pth *.safetensors)'))
        if not file:
            return
        target = MODELS/Path(file).name
        if target.exists():
            self.status.setText('Модель с таким именем уже есть в библиотеке.')
            return
        def action(worker):
            check_cancel(worker.cancel)
            shutil.copy2(file,target)
            return f'Импортирована: {target.name}'
        self.start(action)

    def check_updates(self):
        self.parentWidget().check_model_updates(force=True)

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.status.setText('Отмена загрузки… Закройте окно после завершения текущего запроса.')
            event.ignore()
        else:
            event.accept()

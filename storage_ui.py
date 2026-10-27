from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
                              QSpinBox,QFileDialog,QDialogButtonBox,QScrollArea,QWidget,
                              QRadioButton,QButtonGroup,QCheckBox,QComboBox)
from editor_jobs import FileWorker
from core import release_models
from storage import folder_bytes,memory_status
from image_cache import ImageCache,inactive_sessions


def size_text(value):
    return f'{value/1024**3:.2f} ГБ' if value >= 1024**3 else f'{value/1024**2:.0f} МБ'


class StorageDialog(QDialog):
    def __init__(self,studio,store):
        super().__init__(studio)
        self.studio,self.store = studio,store
        self.worker = None
        self.setWindowTitle('Настройки программы')
        self.setWindowModality(Qt.WindowModal)
        self.resize(620,760)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.NoFrame)
        host=QWidget();layout = QVBoxLayout(host);scroll.setWidget(host);outer.addWidget(scroll)
        layout.setContentsMargins(22,20,22,20)
        layout.setSpacing(13)
        title = QLabel('Настройки программы')
        title.setObjectName('heading')
        layout.addWidget(title)
        language_row=QHBoxLayout();language_row.addWidget(QLabel('Язык / Language'),1)
        self.language_combo=QComboBox();self.language_combo.setAccessibleName('Язык интерфейса')
        self.language_combo.addItem('RUS','ru');self.language_combo.addItem('EN','en')
        self.language_combo.setCurrentIndex(self.language_combo.findData(store.settings.get('language','ru')))
        self.language_combo.currentIndexChanged.connect(self.change_language)
        language_row.addWidget(self.language_combo);layout.addLayout(language_row)
        language_note=QLabel('Выберите язык интерфейса. Изменение применяется сразу.')
        language_note.setWordWrap(True);language_note.setObjectName('muted');layout.addWidget(language_note)
        gpu_title=QLabel('Использование видеокарты');gpu_title.setObjectName('sectionTitle');layout.addWidget(gpu_title)
        modes=QHBoxLayout();self.gpu_group=QButtonGroup(self);self.gpu_buttons={}
        for mode,label in [('eco','Экономное'),('balanced','Среднее'),('full','Полная мощность')]:
            button=QRadioButton(label);button.setChecked(mode==store.settings['gpu_mode'])
            self.gpu_group.addButton(button);self.gpu_buttons[mode]=button;modes.addWidget(button)
        layout.addLayout(modes)
        gpu_note=QLabel('Экономное и среднее использование оставляют паузы между этапами. '
                       'Полная мощность выполняет обработку без пауз. Качество выбранной модели сохраняется.')
        gpu_note.setWordWrap(True);gpu_note.setObjectName('muted');layout.addWidget(gpu_note)
        updates_title=QLabel('Обновления моделей');updates_title.setObjectName('sectionTitle');layout.addWidget(updates_title)
        self.weekly_updates=QCheckBox('Проверять обновления моделей раз в неделю')
        self.weekly_updates.setChecked(store.settings['weekly_model_updates'])
        self.weekly_updates.toggled.connect(self.updates_toggled)
        layout.addWidget(self.weekly_updates)
        updates_note=QLabel('Проверка выполняется во время работы программы. Веса не скачиваются автоматически.')
        updates_note.setWordWrap(True);updates_note.setObjectName('muted');layout.addWidget(updates_note)
        self.updates_status=QLabel();self.updates_status.setWordWrap(True);self.updates_status.setObjectName('muted')
        self.updates_status.setOpenExternalLinks(True);layout.addWidget(self.updates_status)
        self.check_updates_button=QPushButton('Проверить сейчас')
        self.check_updates_button.clicked.connect(lambda:self.studio.check_model_updates(force=True))
        layout.addWidget(self.check_updates_button);self.refresh_updates()
        memory_title=QLabel('Память и рабочий диск');memory_title.setObjectName('sectionTitle');layout.addWidget(memory_title)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        row.addWidget(QLabel('Кэш результатов в ОЗУ'),1)
        self.ram = QSpinBox()
        self.ram.setRange(64,16384)
        self.ram.setSingleStep(128)
        self.ram.setSuffix(' МБ')
        self.ram.setValue(store.settings['ram_cache_mb'])
        row.addWidget(self.ram)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Лимит рабочего диска'),1)
        self.disk = QSpinBox()
        self.disk.setRange(1,256)
        self.disk.setSuffix(' ГБ')
        self.disk.setValue(store.settings['disk_cache_gb'])
        row.addWidget(self.disk)
        layout.addLayout(row)
        note = QLabel('Кэш хранит AI-результаты для повторного просмотра. При достижении лимита '
                      'или нехватке ОЗУ они переносятся на рабочий диск без потери качества. '
                      'Хранятся не более трёх последних результатов. Закрытие файла удаляет его кэш. '
                      'Нейросети работают в отдельном процессе: после задачи его ОЗУ и видеопамять освобождаются. '
                      'Лимит относится к кэшу, а не ко всей памяти программы и видеокарты.')
        note.setObjectName('muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.paths = dict(cache=store.cache,scratch=store.scratch)
        self.labels,self.choose_buttons = {},[]
        for kind,title in [('scratch','Рабочий диск'),('cache','Кэш, загрузки, обновления и журналы')]:
            label = QLabel(title)
            label.setObjectName('sectionTitle')
            layout.addWidget(label)
            row = QHBoxLayout()
            path_label = QLabel(str(self.paths[kind]))
            path_label.setWordWrap(True)
            path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.labels[kind] = path_label
            row.addWidget(path_label,1)
            button = QPushButton('Выбрать…')
            button.clicked.connect(lambda checked=False,k=kind:self.choose(k))
            self.choose_buttons.append(button)
            row.addWidget(button)
            layout.addLayout(row)
        location_note = QLabel('Выберите папку на нужном диске — программа создаст в ней свою подпапку. '
                               'Перенос общего кэша применяется полностью после перезапуска. '
                               'Модели: plugins · библиотеки: libraries · результаты: results.')
        location_note.setWordWrap(True)
        location_note.setObjectName('muted')
        layout.addWidget(location_note)
        tools = QHBoxLayout()
        self.free_button = QPushButton('Освободить память')
        self.free_button.clicked.connect(lambda:self.perform(False))
        tools.addWidget(self.free_button)
        self.clean_button = QPushButton('Очистить временные файлы')
        self.clean_button.clicked.connect(lambda:self.perform(True))
        tools.addWidget(self.clean_button)
        layout.addLayout(tools)
        self.status = QLabel('Исходники, результаты, настройки и установленные модели не очищаются.')
        self.status.setWordWrap(True)
        self.status.setObjectName('muted')
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Apply|QDialogButtonBox.Close)
        self.buttons.button(QDialogButtonBox.Apply).setText('Применить')
        self.buttons.button(QDialogButtonBox.Close).setText('Закрыть')
        self.buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        self.buttons.rejected.connect(self.close)
        outer.addWidget(self.buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(750)
        self.refresh()

    def change_language(self,*args):
        from i18n import set_language
        set_language(self.language_combo.currentData(),store=self.store)

    def busy(self):
        s = self.studio
        return bool((self.worker and self.worker.isRunning()) or s.worker or s.io_worker or s.cache_worker or s.update_worker or
                    s.debounce.isActive() or (s.library and s.library.worker and s.library.worker.isRunning()))

    def refresh(self):
        stats = self.studio.image_cache.stats()
        total,available = memory_status()
        self.summary.setText(f'ОЗУ компьютера: {size_text(total)} · свободно {size_text(available)}\n'
                             f"Кэш в ОЗУ: {size_text(stats['ram_bytes'])} · на рабочем диске: {size_text(stats['disk_bytes'])}")
        enabled = not self.busy()
        for button in self.choose_buttons+[self.free_button,self.clean_button,self.check_updates_button,self.buttons.button(QDialogButtonBox.Apply)]:
            button.setEnabled(enabled)
        if not enabled and not self.worker:
            self.status.setText('Настройки доступны после завершения текущей обработки или загрузки.')

    def choose(self,kind):
        from i18n import tr
        parent = QFileDialog.getExistingDirectory(self,tr('Выберите диск или папку'),str(self.paths[kind].parent))
        if parent:
            try:
                self.paths[kind] = self.store.choose_parent(parent,kind)
                self.labels[kind].setText(str(self.paths[kind]))
            except (OSError,ValueError) as error:
                self.status.setText(str(error))

    def apply(self):
        if self.busy():
            return
        try:
            self.store.save(ram_cache_mb=self.ram.value(),disk_cache_gb=self.disk.value(),
                            cache_path=str(self.paths['cache']),scratch_path=str(self.paths['scratch']),
                            gpu_mode=next(mode for mode,button in self.gpu_buttons.items() if button.isChecked()),
                            weekly_model_updates=self.weekly_updates.isChecked())
            previous = self.studio.image_cache
            self.studio.image_cache = ImageCache(self.store.scratch,self.ram.value(),self.disk.value())
            self.run(lambda worker: previous.close(),'Настройки сохранены. Применяются к следующей обработке.')
        except (OSError,ValueError) as error:
            self.status.setText(str(error))

    def perform(self,clear_disk):
        if self.busy():
            return
        cache = self.studio.image_cache
        def action(worker):
            if clear_disk:
                removed = folder_bytes(cache.root)
                cache.close()
                for path in inactive_sessions(self.store.scratch):
                    import shutil
                    shutil.rmtree(path)
                keep = self.store.active_paths()
                try:
                    removed += self.store.clean('cache',keep=keep)
                finally:
                    self.studio.image_cache = ImageCache(self.store.scratch,self.store.settings['ram_cache_mb'],self.store.settings['disk_cache_gb'])
            else:
                cache.maintain(force=True)
                removed = 0
            release_models()
            return removed
        self.run(action,'Временные файлы очищены. Модели и результаты сохранены.' if clear_disk else 'Кэш перенесён на рабочий диск, память моделей освобождена.')

    def refresh_updates(self):
        from model_updates import summary,read_state
        from html import escape
        text=escape(summary(self.store))
        for item in read_state(self.store).get('sources',{}).values():
            url=item.get('url','')
            if item.get('available') and url.startswith(('https://github.com/','https://huggingface.co/')):
                text+=f'<br><a href="{escape(url,quote=True)}">{escape(item["name"])} · {escape(item["version"])}</a>'
        self.updates_status.setText(text)

    def updates_toggled(self,enabled):
        if not enabled and self.studio.update_worker:self.studio.update_worker.cancel.set()

    def run(self,action,success):
        self.worker = FileWorker(action)
        self.worker.completed.connect(lambda value:self.status.setText(success+(f' Освобождено {size_text(value)}.' if isinstance(value,int) and value else '')))
        self.worker.error.connect(self.status.setText)
        self.worker.finished.connect(self.task_finished)
        self.status.setText('Выполнение…')
        self.worker.start()
        self.refresh()

    def task_finished(self):
        thread = self.worker
        self.worker = None
        thread.deleteLater()
        self.refresh()

    def closeEvent(self,event):
        if self.worker:
            event.ignore()
        else:
            self.timer.stop()
            event.accept()

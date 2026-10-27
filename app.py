import os
import sys
import time
BOOT_STARTED = time.perf_counter()
from pathlib import Path
from dataclasses import replace
from storage import STORE, memory_status
from PIL import Image, ImageOps
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QAction, QKeySequence, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QToolButton, QComboBox, QCheckBox, QSlider, QFileDialog,
    QProgressBar, QScrollArea, QFrame, QMenu, QSpinBox)
from core import CATALOG, DATA, MODELS, ROOT, process, apply_effects, save_unique, check_cancel
from viewer import ImageCanvas, AdjustmentSlider, icon
from profiles import PRESETS,resolve_profile,represented_models
from editor_jobs import RenderRequest, RenderWorker, FileWorker, Estimate,render_image
from library_ui import LibraryDialog
from theme import THEME
from model_info import ModelInfoCard, guide_text
from image_cache import ImageCache, inactive_sessions
from storage_ui import StorageDialog
from file_table import FileTable
from sections import ToolSection
from output_controls import OutputControls
from level_controls import ThreeLevels

if sys.stdout is None or sys.stderr is None:
    log_path = STORE.subdir('logs')/'runtime.log'
    if log_path.exists() and log_path.stat().st_size > 2*1024**2:
        try:
            log_path.replace(log_path.with_name('runtime.previous.log'))
        except OSError:
            pass
    runtime_log = log_path.open('a',encoding='utf-8',buffering=1)
    sys.stdout = sys.stdout or runtime_log
    sys.stderr = sys.stderr or runtime_log


class Studio(QMainWindow):
    def __init__(self, auto_process=True):
        super().__init__()
        from i18n import install
        install(QApplication.instance())
        self.setWindowTitle('Photo Restore Studio 0.25 — Alpha Lite')
        self.resize(1380,900)
        self.setMinimumSize(960,690)
        self.setAcceptDrops(True)
        self.worker = self.io_worker = self.library = None
        self.cache_worker = self.storage_dialog = self.update_worker = None
        self._auto_process = bool(auto_process)
        self._model_tile = 256
        self.image_cache = ImageCache(STORE.scratch,STORE.settings['ram_cache_mb'],STORE.settings['disk_cache_gb'])
        self.output = STORE.results
        self.output.mkdir(exist_ok=True)
        self._revision = 0
        self._pending = self._closing = self._updating = self._batch_active = False
        self._queued_batch = None
        self._profile_overrides = {}
        self._active_profile = None
        self._tool_context = 'general'
        self._cancelled = False
        self._base = self._base_key = self._result = self._result_request = self._original = None
        self._source = ''
        self._ui_ready = False
        self.model_info = ModelInfoCard(self)
        self._estimate = Estimate()
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.launch_latest)
        host = QWidget()
        self.setCentralWidget(host)
        root = QVBoxLayout(host)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName('toolbar')
        toolbar.setFixedHeight(56)
        top = QHBoxLayout(toolbar)
        top.setContentsMargins(18,8,18,8)
        brand = QLabel('PHOTO RESTORE')
        brand.setObjectName('brand')
        top.addWidget(brand)
        version = QLabel('ALPHA LITE  /  0.25')
        version.setObjectName('muted')
        top.addWidget(version)
        top.addSpacing(24)
        self.add_button = QPushButton('Открыть')
        self.add_button.setIcon(icon('folder'))
        self.add_button.clicked.connect(self.add_files)
        top.addWidget(self.add_button)
        top.addStretch()
        library_button = QPushButton('Модели и плагины')
        library_button.setIcon(icon('library'))
        library_button.clicked.connect(self.open_library)
        top.addWidget(library_button)
        storage_button = QToolButton()
        storage_button.setText('Настройки')
        storage_button.setToolTip('Видеокарта, память, хранение и обновления')
        storage_button.clicked.connect(self.open_storage)
        top.addWidget(storage_button)
        self.export_button = QPushButton('Экспорт PNG')
        self.export_button.setObjectName('primary')
        self.export_button.setIcon(icon('download','#ffffff'))
        self.export_button.clicked.connect(self.export_current)
        self.export_button.setEnabled(False)
        top.addWidget(self.export_button)
        self.export_menu = QToolButton()
        self.export_menu.setText('…')
        self.export_menu.setToolTip('Папка сохранения и экспорт очереди')
        self.export_menu.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.export_menu)
        menu.addAction('Выбрать папку результата…', self.choose_output)
        menu.addAction('Открыть папку результата', lambda: os.startfile(self.output))
        menu.addSeparator()
        menu.addAction('Экспортировать отмеченные файлы', self.export_batch)
        self.export_menu.setMenu(menu)
        top.addWidget(self.export_menu)
        root.addWidget(toolbar)
        body = QHBoxLayout()
        body.setSpacing(0)
        workspace = QWidget()
        work = QVBoxLayout(workspace)
        work.setContentsMargins(0,0,0,0)
        work.setSpacing(0)
        document_bar = QFrame()
        document_bar.setObjectName('documentBar')
        document_bar.setFixedHeight(42)
        doc = QHBoxLayout(document_bar)
        doc.setContentsMargins(18,4,14,4)
        self.document_name = QLabel('Нет открытого изображения')
        doc.addWidget(self.document_name,1)
        self.zoom_label = QLabel('Вписать')
        self.zoom_label.setObjectName('muted')
        doc.addWidget(self.zoom_label)
        fit = QToolButton()
        fit.setIcon(icon('fit'))
        fit.setToolTip('Вписать в окно · F')
        doc.addWidget(fit)
        actual = QPushButton('100%')
        actual.setObjectName('quiet')
        actual.setToolTip('Реальные пиксели результата · 1')
        doc.addWidget(actual)
        work.addWidget(document_bar)
        self.canvas = ImageCanvas()
        fit.clicked.connect(self.canvas.fit)
        actual.clicked.connect(self.canvas.actual_size)
        self.canvas.zoomChanged.connect(lambda zoom: self.zoom_label.setText(f'{zoom*100:.0f}%'))
        work.addWidget(self.canvas,1)
        hint = QLabel('  Удерживайте ЛКМ — оригинал   ·   Тяните — перемещение   ·   Колесо — масштаб')
        hint.setObjectName('canvasHint')
        hint.setFixedHeight(29)
        work.addWidget(hint)
        self.files = FileTable()
        self.files.currentItemChanged.connect(self.select_image)
        self.files.closeRequested.connect(self.close_file)
        self.files.hide()
        body.addWidget(workspace,1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(328)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setObjectName('sideScroll')
        self.sidebar = QWidget()
        self.sidebar.setObjectName('sidebar')
        panel = QVBoxLayout(self.sidebar)
        panel.setContentsMargins(18,18,18,18)
        panel.setSpacing(10)
        heading = QLabel('УЛУЧШЕНИЕ ИЗОБРАЖЕНИЯ')
        heading.setObjectName('sectionTitle')
        panel.addWidget(heading)
        self.models = QComboBox()
        self.models.setObjectName('modelSelector')
        self.models.setAccessibleName('Модель улучшения изображения')
        self.models.setToolTip('Выберите назначение модели. Ниже появятся её настройки.')
        self.models.currentIndexChanged.connect(self.choose_profile)
        self.models.activated.connect(lambda index:self.show_model_info())
        model_row = QHBoxLayout()
        model_row.addWidget(self.models,1)
        model_help = QToolButton()
        model_help.setText('i')
        model_help.setFixedWidth(28)
        model_help.setToolTip('О выбранной модели')
        model_help.clicked.connect(self.show_model_info)
        model_row.addWidget(model_help)
        panel.addLayout(model_row)
        self.install_button = QPushButton('Установить выбранную модель…')
        self.install_button.clicked.connect(self.install_selected)
        self.install_button.hide()
        panel.addWidget(self.install_button)
        self.model_note = QLabel()
        self.model_note.setWordWrap(True)
        self.model_note.setObjectName('muted')
        panel.addWidget(self.model_note)
        self.scale = OutputControls()
        self.scale.currentIndexChanged.connect(self.settings_changed)
        self.export_format = self.scale.format
        self.dpi = self.scale.dpi
        self.jpeg_quality = self.scale.jpeg_quality
        self.jpeg_settings = self.scale.jpeg_settings
        self.export_format.currentIndexChanged.connect(self.export_settings_changed)
        self.scale.vector_colors.valueChanged.connect(self.settings_changed)
        self.scale.vector_smoothness.valueChanged.connect(self.settings_changed)
        self.dpi.valueChanged.connect(self.refresh_file_info)
        self.jpeg_quality.valueChanged.connect(self.refresh_file_info)
        panel.addWidget(self.scale)
        self.effect=ThreeLevels('Сила улучшения',(60,80,100),100,
            ('Мягкое улучшение с большей долей исходника.','Сбалансированное улучшение.','Полный результат обработки.'))
        self.effect.valueChanged.connect(self.settings_changed);panel.addWidget(self.effect)
        self.detail_section = ToolSection('Резкость и смягчение')
        panel.addWidget(self.detail_section)
        self.sharpness, _ = self.slider(self.detail_section.body_layout,'Дополнительная резкость',5)
        self.smoothing, _ = self.slider(self.detail_section.body_layout,'Смягчение деталей',0)
        self.nature_repair=ThreeLevels('Очистка JPEG и шума',(0,20,40),0,
            ('Бережно: основная модель убирает сжатие без дополнительного сглаживания.',
             'Дополнительная очистка заметного шума и сжатия.',
             'Для сильно повреждённых файлов. Мелкие детали защищаются автоматически.'))
        self.nature_repair.valueChanged.connect(self.settings_changed);panel.addWidget(self.nature_repair)
        self.nature_section=ToolSection('Сцена')
        panel.addWidget(self.nature_section)
        scene_row=QHBoxLayout()
        self.nature_scene=QComboBox()
        for title,identifier in [('Фото и природа','mixed'),('Вода и облака','water'),('Архитектура','architecture'),('Интерьер','interior')]:
            self.nature_scene.addItem(title,identifier)
        self.nature_scene.currentIndexChanged.connect(self.scene_changed)
        scene_row.addWidget(self.nature_scene)
        self.nature_section.body_layout.addLayout(scene_row)
        self.nature_status=QLabel('Автоматическая проработка облаков, листвы и ряби воды. Программа усиливает найденную фактуру там, где основная модель её сгладила.')
        self.nature_status.setWordWrap(True);self.nature_status.setObjectName('muted')
        self.nature_section.body_layout.addWidget(self.nature_status)
        self.nature_separator = self.separator()
        panel.addWidget(self.nature_separator)
        self.faces = QCheckBox('Детализация лица')
        self.faces.toggled.connect(self.settings_changed)
        self.faces.toggled.connect(self.face_info)
        self.face_section = ToolSection('Детализация лица',self.faces)
        panel.addWidget(self.face_section)
        face_layout = self.face_section.body_layout
        self.strength, _ = self.slider(face_layout,'Сила восстановления лиц',60)
        self.strength.setEnabled(False)
        self.faces.toggled.connect(self.strength.setEnabled)
        face_note = QLabel('Умеренная сила помогает сохранить сходство.')
        face_note.setObjectName('muted')
        face_layout.addWidget(face_note)
        self.face_model = QComboBox()
        for title,identifier in [('Восстановление лица · CodeFormer','codeformer')]:
            entry = next(e for e in CATALOG if e['id'] == identifier)
            self.face_model.addItem(title,identifier)
            self.face_model.setItemData(self.face_model.count()-1,guide_text(MODELS/entry['file']),Qt.ToolTipRole)
        self.face_model.currentIndexChanged.connect(self.face_model_changed)
        face_layout.addWidget(self.face_model)
        self.face_model.hide()
        self.fidelity,self.fidelity_label = self.slider(face_layout,'Сохранение сходства',80)
        self.fidelity.setToolTip('CodeFormer: выше — ближе к исходнику; ниже — сильнее синтез деталей.')
        self.face_license = QLabel('CodeFormer · S-Lab: некоммерческое использование.')
        self.face_license.setObjectName('muted')
        self.face_license.setWordWrap(True)
        face_layout.addWidget(self.face_license)
        self.face_install = QPushButton('Установить модель лица…')
        self.face_install.clicked.connect(self.install_face_model)
        face_layout.addWidget(self.face_install)
        self.hair_section = ToolSection('Волосы, борода и усы')
        panel.addWidget(self.hair_section)
        hair_layout = self.hair_section.body_layout
        hair_note=QLabel('Лицо, шея, волосы и борода восстанавливаются согласованно. Повторного наложения прядей нет.')
        hair_note.setWordWrap(True);hair_note.setObjectName('muted');hair_layout.addWidget(hair_note)
        self.hair_model = QComboBox()
        for title,identifier in [('Детализация PBRify','pbrify-detail')]:
            entry = next(e for e in CATALOG if e['id'] == identifier)
            self.hair_model.addItem(title,identifier)
            self.hair_model.setItemData(self.hair_model.count()-1,guide_text(MODELS/entry['file']),Qt.ToolTipRole)
        self.hair_model.currentIndexChanged.connect(self.settings_changed)
        self.hair_model.activated.connect(lambda index:self.show_hair_info())
        hair_layout.addWidget(self.hair_model)
        self.hair_model.hide()
        self.hair_strength,_ = self.slider(hair_layout,'Детализация волос',65)
        self.faces.toggled.connect(self.update_face_controls)
        self.update_face_controls()
        self.portrait_separator = self.separator()
        panel.addWidget(self.portrait_separator)
        self.light_section = ToolSection('Свет лица')
        self.light_toggle = self.light_section.toggle
        self.light_group = self.light_section.body
        panel.addWidget(self.light_section)
        light_layout = self.light_section.body_layout
        self.light_faces = QCheckBox('Только область лица')
        self.light_faces.setChecked(True)
        self.light_faces.toggled.connect(self.settings_changed)
        light_layout.addWidget(self.light_faces)
        self.exposure,_ = self.slider(light_layout,'Экспозиция',0,-100,lambda value:f'{value/50:+.1f} EV')
        self.shadows,_ = self.slider(light_layout,'Тени',0,-100)
        self.highlights,_ = self.slider(light_layout,'Света',0,-100)
        self.temperature,_ = self.slider(light_layout,'Температура',0,-100)
        self.surface,_=self.slider(light_layout,'Сохранение бликов и отражений',75)
        self.surface.setToolTip('Сохраняет исходный рисунок освещения и цвет кожи, стекла и глянцевых поверхностей. Новые источники света не генерируются.')
        self.shadow_detail,_=self.slider(light_layout,'Детали в тенях',0)
        self.shadow_detail.setToolTip('Осторожно усиливает существующую фактуру тёмных объектов. Ровные тёмные участки и слабый шум не усиливаются.')
        light_reset = QPushButton('Сбросить свет')
        light_reset.clicked.connect(self.reset_light)
        light_layout.addWidget(light_reset)
        light_note = QLabel('Быстрая тоновая коррекция. При включённой области лица фон сохраняет свой свет.')
        light_note.setObjectName('muted')
        light_note.setWordWrap(True)
        light_layout.addWidget(light_note)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setObjectName('error')
        self.error_label.hide()
        panel.addWidget(self.error_label)
        panel.addStretch()
        scroll.setWidget(self.sidebar)
        body.addWidget(scroll)
        root.addLayout(body,1)
        root.addWidget(self.files)
        footer = QFrame()
        footer.setObjectName('footer')
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0,0,0,0)
        footer_layout.setSpacing(0)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        footer_layout.addWidget(self.progress)
        self.progress_reset_timer=QTimer(self)
        self.progress_reset_timer.setSingleShot(True)
        self.progress_reset_timer.timeout.connect(self.reset_idle_progress)
        line = QHBoxLayout()
        line.setContentsMargins(14,4,12,4)
        self.status_label = QLabel('Готов к работе · обработка на вашем компьютере')
        self.status_label.setObjectName('muted')
        line.addWidget(self.status_label,1)
        self.eta_label = QLabel('')
        self.eta_label.setObjectName('muted')
        line.addWidget(self.eta_label)
        self.stop = QToolButton()
        self.stop.setText('Отмена')
        self.stop.clicked.connect(self.cancel)
        self.stop.hide()
        line.addWidget(self.stop)
        footer_layout.addLayout(line)
        root.addWidget(footer)
        self.refresh_models()
        self.choose_profile(self.models.currentIndex())
        self._revision = 0
        self.debounce.stop()
        self._ui_ready = True
        self.cache_timer = QTimer(self)
        self.cache_timer.timeout.connect(self.maintain_cache)
        self.cache_timer.start(15000)
        QTimer.singleShot(1000,self.maintain_cache)
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(3600000)
        self.update_timer.timeout.connect(self.check_model_updates)
        self.update_timer.start()
        if auto_process and '--diagnostics' not in sys.argv:QTimer.singleShot(15000,self.check_model_updates)
        for shortcut,callback in [(QKeySequence.Open,self.add_files),(QKeySequence.Save,self.export_current),
                                  (QKeySequence('Ctrl+W'),self.close_current_file)]:
            action = QAction(self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def separator(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.HLine)
        frame.setObjectName('separator')
        return frame

    def slider(self,layout,title,value,minimum=0,formatter=None):
        controls = QWidget()
        controls.setObjectName('sliderControls')
        slider_layout = QVBoxLayout(controls)
        slider_layout.setContentsMargins(0,0,0,0)
        slider_layout.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(QLabel(title),1)
        formatter = formatter or (lambda number:f'{number:+d}%' if minimum < 0 else f'{number}%')
        label = QLabel(formatter(value))
        label.setObjectName('sliderValue')
        row.addWidget(label)
        slider_layout.addLayout(row)
        slider = AdjustmentSlider(Qt.Horizontal)
        slider.setRange(minimum,100)
        slider.setValue(value)
        slider.valueChanged.connect(lambda v: label.setText(formatter(v)))
        slider.valueChanged.connect(self.settings_changed)
        slider_layout.addWidget(slider)
        layout.addWidget(controls)
        slider.controls = controls
        return slider,label

    def refresh_models(self):
        self._updating = True
        selected = (self.models.currentData(Qt.UserRole+1) or {}).get('id')
        self.models.clear()
        def add_model(preset,path):
            self.models.addItem(preset['title'],str(path))
            index = self.models.count()-1
            self.models.setItemData(index,preset,Qt.UserRole+1)
            tooltip = preset['subtitle']+'\n\n'+guide_text(path)
            if preset.get('faces'):
                face_entry = next(e for e in CATALOG if e['id'] == preset.get('face_model','codeformer'))
                tooltip += f"\n\nВосстановление лиц: {face_entry['technical_name']}"

            self.models.setItemData(index,tooltip,Qt.ToolTipRole)
        for preset in PRESETS:
            resolved = resolve_profile(preset,self._profile_overrides.get(preset['id'],{}).get('quality',preset.get('quality',0)))
            if preset['id']=='graphics':
                add_model(preset,'graphics');continue
            entry = next(e for e in CATALOG if e['id'] == resolved['model'])
            add_model(preset,MODELS/entry['file'])
        represented = represented_models()
        for entry in CATALOG:
            if entry['kind'] == 'upscale' and entry['id'] not in represented:
                add_model(dict(id=entry['id'],title=entry['name'],subtitle='Локальная модель увеличения'),MODELS/entry['file'])
        known = {entry['file'] for entry in CATALOG}
        for path in sorted(MODELS.iterdir()):
            if path.name not in known and path.suffix in ('.pth','.safetensors'):
                add_model(dict(id='import:'+path.name,title=path.stem,subtitle='Импортированная локальная модель'),path)
        if selected:
            index = next((i for i in range(self.models.count())
                          if self.models.itemData(i,Qt.UserRole+1)['id'] == selected),0)
            self.models.setCurrentIndex(index)
        self._updating = False

    def select_profile(self,identifier,quality=None):
        index=next(i for i in range(self.models.count()) if self.models.itemData(i,Qt.UserRole+1)['id']==identifier)
        self.models.setCurrentIndex(index)

    def choose_profile(self,row):
        if self._updating or not 0 <= row < self.models.count():
            return
        selection = self.models.itemData(row,Qt.UserRole+1)
        identifier = selection['id']
        if self._active_profile is not None and self._active_profile != identifier:
            self._profile_overrides[self._active_profile] = self.profile_values()
        self._active_profile = identifier
        self._tool_context = selection.get('tools','general')
        overrides=self._profile_overrides.get(identifier,{})
        preset = {**resolve_profile(selection,overrides.get('quality',selection.get('quality',0))),**overrides}
        self._updating = True
        self.scale.set_graphics(self._tool_context=='graphics')
        entry=next((e for e in CATALOG if e['id']==preset.get('model')),None)
        if entry:
            path=MODELS/entry['file']
            self.models.setItemData(row,str(path))
            self.models.setItemData(row,selection['subtitle']+'\n\n'+guide_text(path),Qt.ToolTipRole)
        self.effect.setValue(preset.get('effect',85))
        self.sharpness.setValue(preset.get('sharpness',0))
        self.smoothing.setValue(preset.get('smoothing',0))
        self.faces.setChecked(preset.get('faces',False))
        self.strength.setValue(preset.get('face_strength',60))
        self.face_model.setCurrentIndex(self.face_model.findData(preset.get('face_model','codeformer')))
        self.fidelity.setValue(preset.get('face_fidelity',80))
        self.hair_strength.setValue(preset.get('hair_strength',65))
        self.hair_model.setCurrentIndex(self.hair_model.findData(preset.get('hair_model','pbrify-detail')))
        self.nature_repair.setValue(preset.get('nature_repair',0))
        self.nature_scene.setCurrentIndex(self.nature_scene.findData(preset.get('nature_scene','mixed')))
        self.light_faces.setChecked(preset.get('light_faces',self._tool_context=='portrait'))
        self.surface.setValue(preset.get('surface_protection',0))
        self.shadow_detail.setValue(preset.get('shadow_detail',0))
        for name in ('exposure','shadows','highlights','temperature'):
            getattr(self,name).setValue(preset.get(name,0))
        self.light_toggle.setChecked(preset.get('light_expanded',False))
        self.face_section.set_expanded(preset.get('face_expanded',self.faces.isChecked()))
        self.nature_section.set_expanded(preset.get('nature_expanded',True))
        self.hair_section.set_expanded(preset.get('hair_expanded',False))
        self._model_tile = preset.get('tile',256)
        self._updating = False
        self.nature_section.setVisible(self._tool_context == 'landscape')
        self.nature_separator.setVisible(self._tool_context == 'landscape')
        for widget in (self.face_section,self.hair_section,self.light_section,self.portrait_separator):
            widget.setVisible(self._tool_context == 'portrait' and widget in (self.face_section,self.hair_section,self.light_section,self.portrait_separator))
        self.light_section.setVisible(self._tool_context in ('portrait','landscape'))
        self.light_faces.setVisible(self._tool_context == 'portrait')
        self.light_section.toggle.setText('Свет кожи' if self._tool_context=='portrait' else 'Свет и отражения')
        self.update_face_controls()
        for widget in (self.effect,self.detail_section,self.nature_repair):widget.setVisible(self._tool_context!='graphics')
        ready = self._tool_context=='graphics' or Path(self.models.currentData()).is_file()
        self.install_button.setVisible(not ready)
        self.model_note.setText(selection['subtitle']+'\n'+('Готов к обработке · локально' if ready
            else 'Сначала установите модель в библиотеке.'))
        self.settings_changed()
        if self._ui_ready:
            self.show_model_info()

    def profile_values(self):
        return dict(surface_protection=self.surface.value(),shadow_detail=self.shadow_detail.value(),effect=self.effect.value(),sharpness=self.sharpness.value(),smoothing=self.smoothing.value(),
            faces=self.faces.isChecked(),face_strength=self.strength.value(),tile=self._model_tile,
            face_model=self.face_model.currentData(),face_fidelity=self.fidelity.value(),
            hair_strength=self.hair_strength.value(),hair_model=self.hair_model.currentData(),
            nature_scene=self.nature_scene.currentData(),nature_repair=self.nature_repair.value(),
            exposure=self.exposure.value(),shadows=self.shadows.value(),highlights=self.highlights.value(),
            temperature=self.temperature.value(),light_faces=self.light_faces.isChecked(),
            light_expanded=self.light_toggle.isChecked(),face_expanded=self.face_section.toggle.isChecked(),
            hair_expanded=self.hair_section.toggle.isChecked(),nature_expanded=self.nature_section.toggle.isChecked())

    def scoped_options(self):
        portrait = self._tool_context == 'portrait'
        return dict(faces=portrait and self.faces.isChecked(),hair_natural=portrait,
            **{name:getattr(self,name).value() if self._tool_context in ('portrait','landscape') else 0
               for name in ('exposure','shadows','highlights','temperature')})

    def show_model_info(self):
        path = self.models.currentData()
        if self._ui_ready and path:
            self.model_info.show_for(path,self.models,self.face_model.currentData() if self.scoped_options()['faces'] else False,
                display_title=self.models.currentText(),description=self.models.currentData(Qt.UserRole+1)['subtitle'])

    def face_info(self,enabled):
        if enabled and self._ui_ready and not self._updating:
            self.model_info.show_for(self.face_weight_path(),self.faces)

    def face_weight_path(self):
        return MODELS/('codeformer.pth' if self.face_model.currentData() == 'codeformer' else 'GFPGANv1.4.pth')

    def update_face_controls(self,*args):
        enabled = self.faces.isChecked()
        codeformer = self.face_model.currentData() == 'codeformer'
        self.face_model.setEnabled(enabled)
        self.fidelity.setEnabled(enabled and codeformer)
        self.fidelity.controls.setVisible(enabled and codeformer)
        self.face_license.setVisible(enabled and codeformer)
        self.face_install.setVisible(enabled and not self.face_weight_path().exists())

    def face_model_changed(self,*args):
        self.update_face_controls()
        self.settings_changed()
        if self._ui_ready and not self._updating:
            self.model_info.show_for(self.face_weight_path(),self.face_model)

    def install_face_model(self):
        dialog = self.open_library()
        identifier = self.face_model.currentData()
        dialog.catalog_list.setCurrentRow(next(i for i,e in enumerate(CATALOG) if e['id'] == identifier))

    def hair_weight_path(self):
        entry = next(e for e in CATALOG if e['id'] == self.hair_model.currentData())
        return MODELS/entry['file']

    def scene_changed(self,*args):
        if self._updating or not self._ui_ready:return
        if self.nature_scene.currentData()=='interior':
            self._updating=True;self.surface.setValue(85);self.shadow_detail.setValue(20)
            self.light_section.set_expanded(True);self._updating=False
        self.settings_changed()

    def show_hair_info(self):
        self.model_info.show_for(self.hair_weight_path(),self.hair_model)

    def reset_light(self):
        self._updating = True
        for slider in (self.exposure,self.shadows,self.highlights,self.temperature):
            slider.setValue(0)
        self._updating = False
        self.settings_changed()
        self.light_toggle.setChecked(False)

    def export_settings_changed(self,*args):
        jpeg = self.export_format.currentData() == 'JPEG'
        self.export_button.setText('Экспорт '+str(self.export_format.currentData()))
        self.jpeg_settings.setVisible(jpeg)
        self.scale.vector_settings.setVisible(self._tool_context=='graphics' and self.export_format.currentData()=='SVG')
        if not self._updating and self._tool_context=='graphics':self.settings_changed()
        self.refresh_file_info()

    def refresh_file_info(self,*args):
        if not self._ui_ready:
            return
        options = self.scoped_options()
        model_help=guide_text(self.models.currentData())
        self.files.set_settings(factor=self.scale.value,
            model=self.models.currentText(),
            model_help=model_help,effect=self.effect.value(),sharpness=self.sharpness.value(),
            faces=options['faces'],face_strength=self.strength.value(),face_help=guide_text(self.face_weight_path()),
            hair=options['hair_natural'],hair_strength=self.hair_strength.value(),hair_help=guide_text(self.hair_weight_path()),
            exposure=options['exposure'],shadows=options['shadows'],highlights=options['highlights'],
            temperature=options['temperature'],light_faces=self.light_faces.isChecked(),
            image_format=self.export_format.currentData(),dpi=self.dpi.value(),quality=self.jpeg_quality.value())

    def export_options(self):
        return dict(image_format=self.export_format.currentData(),dpi=self.dpi.value(),quality=self.jpeg_quality.value())

    def settings_changed(self,*args):
        if not self._updating:
            self.request_render()

    def effective_tile(self):
        from gpu_policy import tile_size
        return tile_size(self._model_tile,STORE.settings['gpu_mode'])

    def check_model_updates(self,force=False):
        from model_updates import due,check
        if self._closing or self.update_worker or self.worker or self.io_worker or self.cache_worker:
            return
        if self.library and self.library.worker and self.library.worker.isRunning():return
        if not force and not due():return
        if self.storage_dialog:self.storage_dialog.updates_status.setText('Проверка новых версий моделей…')
        if self.library and self.library.isVisible():self.library.status.setText('Проверка новых версий моделей…')
        self.update_worker = FileWorker(lambda worker:check(worker.progress.emit,worker.cancel))
        self.update_worker.completed.connect(self.model_updates_checked)
        self.update_worker.error.connect(lambda text:self.status_label.setText('Не удалось проверить обновления: '+text))
        self.update_worker.finished.connect(self.model_updates_finished)
        self.update_worker.start()

    def model_updates_checked(self,result):
        from model_updates import summary
        if result.get('new_count'):
            self.status_label.setText(f"Доступны новые релизы моделей: {result['new_count']}. Откройте настройки.")
        elif self.storage_dialog and self.storage_dialog.isVisible():
            self.status_label.setText(summary())
        if self.storage_dialog:self.storage_dialog.refresh_updates()
        if self.library and self.library.isVisible():self.library.status.setText(summary())

    def model_updates_finished(self):
        thread,self.update_worker = self.update_worker,None
        if thread:thread.deleteLater()
        if self._closing:QTimer.singleShot(0,self.close)

    def current_request(self):
        model = self.models.currentData()
        if not self._source or not model or (self._tool_context!='graphics' and not Path(model).is_file()):
            return None
        return RenderRequest(self._revision,self._source,model,self.scale.inference_factor,
            self.effective_tile(),face_strength=self.strength.value()/100,
            effect=self.effect.value()/100,sharpness=self.sharpness.value(),smoothing=self.smoothing.value(),
            face_model=self.face_model.currentData(),face_fidelity=self.fidelity.value()/100,
            hair_strength=self.hair_strength.value()/100,light_faces=self.light_faces.isChecked(),hair_model=self.hair_model.currentData(),
            nature_repair=self.nature_repair.value()/100,output_scale=self.scale.value,gpu_mode=STORE.settings['gpu_mode'],
            backend='graphics' if self._tool_context=='graphics' else 'studio',
            vector=self._tool_context=='graphics' and self.export_format.currentData()=='SVG',
            vector_colors=self.scale.vector_colors.value(),vector_smoothness=self.scale.vector_smoothness.value(),
            surface_protection=self.surface.value()/100,shadow_detail=self.shadow_detail.value(),
            automatic_detail=self._tool_context=='landscape',
            **self.scoped_options())

    def request_render(self,force=False):
        self._revision += 1
        self.export_button.setEnabled(False)
        self.refresh_file_info()
        if self._source and self._original is not None:
            self.scale.set_source_size(self._original.size)
        if not self._source or self._batch_active:
            return
        if self._auto_process or force:
            self.debounce.start(10 if force else 320)

    def launch_latest(self):
        if self._closing or self._batch_active:
            return
        request = self.current_request()
        if request is None:
            self.status_label.setText('Выберите установленную модель справа.')
            return
        if request.faces and not self.face_weight_path().exists():
            self.failure('Установите выбранную модель лица в библиотеке.')
            return
        if request.hair_natural and not self.hair_weight_path().exists():
            self.failure('Установите выбранную модель волос в библиотеке.')
            return
        if self.worker and self.worker.isRunning():
            self._pending = True
            if self.worker.request.key != request.key:
                self.worker.cancel.set()
            return
        self._pending = False
        self._cancelled = False
        self.error_label.hide()
        self._estimate = Estimate()
        self.progress.setValue(0)
        self.eta_label.setText('Оценка времени…')
        self.status_label.setText('Подготовка изображения…')
        self.stop.show()
        worker = RenderWorker(request,image_cache=self.image_cache)
        self.worker = worker
        worker.progress.connect(lambda text,value,w=worker: self.update_progress(text,value)
                                if self.worker is w and self._source == request.source and not w.cancel.is_set() else None)
        worker.result.connect(self.receive_result)
        worker.error.connect(lambda text,r=request: self.failure(text) if r.revision == self._revision else None)
        worker.finished.connect(lambda w=worker: self.render_finished(w))
        worker.start()

    def receive_result(self,payload):
        request = payload['request']
        current = self.current_request()
        if current is None or payload['key'] != current.key:
            return
        self._base,self._base_key = None,payload['key']
        if request.revision != self._revision:
            self._pending = True
            return
        self._result = payload['image']
        self._result_request = request
        self.files.set_result(request.source,self._result.size)
        self.canvas.set_images(self._original,self._result,request.export_factor)
        self.export_button.setEnabled(True)
        self.progress.setValue(100)
        self.progress_reset_timer.start(1400)
        self.status_label.setText('Готово · удерживайте левую кнопку мыши для сравнения')
        if request.light_active and request.light_faces and not self._result.info.get('portrait_regions'):
            self.status_label.setText('Лица для коррекции света не найдены · можно отключить «Только область лица»')
        elif (request.faces or request.hair_natural) and not self._result.info.get('portrait_stats',{}).get('faces'):
            self.status_label.setText('Лица не найдены · сохранён результат общего апскейла')
        self.eta_label.setText('')

    def failure(self,text):
        if 'out of memory' in text.lower():
            text = 'Недостаточно видеопамяти. Закройте другие программы, использующие видеокарту, или выберите экономный режим в настройках.'
        self.error_label.setText(text)
        self.error_label.show()
        self.status_label.setText('Не удалось завершить обработку')
        self.eta_label.setText('')

    def update_progress(self,text,value):
        self.progress.setValue(value)
        self.status_label.setText(text)
        self.eta_label.setText(self._estimate.update(value))

    def render_finished(self,thread=None):
        thread = thread or self.worker
        if self.worker is not thread:
            if thread:
                thread.deleteLater()
            return
        self.worker = None
        if not self._source:self.image_cache.retain_recent(0)
        if thread:
            thread.deleteLater()
        self.stop.hide()
        if self._closing:
            QTimer.singleShot(0,self.close)
        elif self._queued_batch:
            self.begin_batch()
        elif self._pending:
            self.debounce.start(0)
        elif self._cancelled:
            self.progress.setValue(0)
            self.status_label.setText('Обработка отменена')

    def reset_idle_progress(self):
        if self.worker is None and not self._closing:self.progress.setValue(0)

    def cancel(self):
        self.debounce.stop()
        self._pending = False
        self._cancelled = True
        if self._queued_batch:
            self.set_batch_ui(False)
        self._queued_batch = None
        self._revision += 1
        if self.worker:
            self.worker.cancel.set()
        self.status_label.setText('Отмена после текущей операции…')
        self.eta_label.setText('')

    def add_paths(self,paths):
        existing = set(self.files.paths())
        added = []
        for path in paths:
            path = str(Path(path).resolve())
            if path in existing or Path(path).suffix.lower() not in ('.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'):
                continue
            try:
                with Image.open(path) as opened:
                    thumb = ImageOps.exif_transpose(opened).convert('RGB')
                    size = thumb.size
                    thumb.thumbnail((100,64))
                item = self.files.add_file(path,size,thumb)
                existing.add(path)
                added.append(item)
            except Exception as error:
                self.status_label.setText(f'Не удалось открыть {Path(path).name}: {error}')
        if added:
            self.refresh_file_info()
            self.files.show()
            self.files.setCurrentItem(added[0])
        elif paths:
            target = str(Path(paths[0]).resolve())
            for index in range(self.files.topLevelItemCount()):
                if self.files.topLevelItem(index).data(0,Qt.UserRole) == target:
                    self.files.setCurrentItem(self.files.topLevelItem(index))
                    break

    def close_current_file(self):
        self.close_file(self.files.currentItem())

    def close_file(self,item):
        if item is None or self._batch_active:
            return
        row = self.files.indexOfTopLevelItem(item)
        if row < 0:
            return
        was_current = item is self.files.currentItem()
        closed_source=item.data(0,Qt.UserRole)
        if closed_source:self.image_cache.discard_source(closed_source)
        self.files.blockSignals(True)
        card = self.files.itemWidget(item,self.files.CLOSE)
        self.files.removeItemWidget(item,self.files.CLOSE)
        self.files.takeTopLevelItem(row)
        if card:
            card.deleteLater()
        if was_current:
            self.debounce.stop()
            self._pending = self._cancelled = False
            self._revision += 1
            if self.worker:
                self.worker.cancel.set()
            self._source = ''
            self._base = self._base_key = self._original = self._result = self._result_request = None
            self.export_button.setEnabled(False)
            self.canvas.clear()
            self.error_label.hide()
            self.progress.setValue(0)
            self.eta_label.clear()
            self.stop.hide()
            self.document_name.setText('Нет открытого изображения')
            self.document_name.setToolTip('')
            self.scale.set_source_size(None)
            self.status_label.setText('Файл закрыт · откройте изображение для обработки')
            if self.files.topLevelItemCount():
                self.files.setCurrentItem(self.files.topLevelItem(min(row,self.files.topLevelItemCount()-1)))
        self.files.blockSignals(False)
        self.files.update_height()
        self.files.update_checks()
        self.files.setVisible(self.files.topLevelItemCount() > 0)
        if was_current and self.files.currentItem() is not None:
            self.select_image(self.files.currentItem())

    def select_image(self,item,previous=None):
        if item is None:
            return
        path = item.data(0,Qt.UserRole)
        try:
            with Image.open(path) as opened:
                original = ImageOps.exif_transpose(opened).copy()
            self._source,self._original = path,original
            self.scale.set_source_size(original.size)
            self._result = self._base = self._base_key = self._result_request = None
            self.document_name.setText(Path(path).name)
            self.document_name.setToolTip(path)
            self.canvas.set_images(original,factor=self.scale.value,reset=True)
            self.request_render(force=self._auto_process)
        except Exception as error:
            self.failure(str(error))

    def add_files(self):
        from i18n import tr
        paths,_ = QFileDialog.getOpenFileNames(self,tr('Открыть изображения'),'',tr('Изображения (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)'))
        self.add_paths(paths)

    def open_library(self):
        if self.library is None:
            self.library = LibraryDialog(self)
            self.library.modelsChanged.connect(self.library_changed)
        self.library.show()
        self.library.raise_()
        return self.library

    def open_storage(self):
        if self.storage_dialog is None or not self.storage_dialog.isVisible():
            self.storage_dialog = StorageDialog(self,STORE)
        self.storage_dialog.show()
        self.storage_dialog.raise_()
        return self.storage_dialog

    def maintain_cache(self):
        if not self.isVisible() or self._closing or self.worker or self.io_worker or self.cache_worker or self.update_worker or self.debounce.isActive():
            return
        if self.storage_dialog and self.storage_dialog.worker:
            return
        if self.library and self.library.worker and self.library.worker.isRunning():
            return
        def action(worker):
            self.image_cache.maintain()
            for path in inactive_sessions(STORE.scratch):
                import shutil
                shutil.rmtree(path,ignore_errors=True)
            STORE.clean('cache',older_than=7*86400,keep=STORE.active_paths(),cancel=worker.cancel)
            if worker.cancel.is_set():
                return
            if memory_status()[1] < max(512*1024**2,memory_status()[0]//10):
                from core import release_models
                release_models()
        self.cache_worker = FileWorker(action)
        self.cache_worker.finished.connect(self.cache_finished)
        self.cache_worker.start()

    def cache_finished(self):
        thread = self.cache_worker
        self.cache_worker = None
        thread.deleteLater()
        if self._closing:
            QTimer.singleShot(0,self.close)

    def install_selected(self):
        dialog = self.open_library()
        path = self.models.currentData()
        if path:
            row = next((i for i,e in enumerate(CATALOG) if e['file'] == Path(path).name),None)
            if row is not None:
                dialog.catalog_list.setCurrentRow(row)

    def library_changed(self):
        if self._active_profile is not None:
            self._profile_overrides[self._active_profile] = self.profile_values()
        self.refresh_models()
        self.choose_profile(self.models.currentIndex())

    def choose_output(self):
        from i18n import tr
        directory = QFileDialog.getExistingDirectory(self,tr('Папка результата'),str(self.output))
        if directory:
            self.output = Path(directory)
            self.status_label.setText(f'Папка результата: {directory}')

    def export_current(self):
        if self._batch_active or self._result is None or self._result_request is None or not self.export_button.isEnabled():
            return
        if self.io_worker and self.io_worker.isRunning():
            return
        image,request,output = self._result,self._result_request,self.output
        options = self.export_options()
        self.io_worker = FileWorker(lambda worker: save_unique(image,output,request.source,request.export_factor,**options))
        self.io_worker.completed.connect(lambda path: self.status_label.setText(f'Сохранено: {path}'))
        self.io_worker.error.connect(self.failure)
        self.io_worker.finished.connect(self.io_finished)
        self.status_label.setText(f"Сохранение {options['image_format']} · {options['dpi']} DPI…")
        self.io_worker.start()

    def io_finished(self):
        thread = self.io_worker
        self.io_worker = None
        if thread:
            thread.deleteLater()
        if self._closing:
            QTimer.singleShot(0,self.close)

    def export_batch(self):
        request = self.current_request()
        if request is None or self._batch_active or (self.io_worker and self.io_worker.isRunning()):
            return
        paths = self.files.paths(checked_only=True)
        if not paths:
            self.status_label.setText('Отметьте файлы в нижней панели для пакетного экспорта.')
            return
        self.debounce.stop()
        self._pending = False
        self.set_batch_ui(True)
        self._queued_batch = (request,paths,self.output,self.export_options())
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
        else:
            self.begin_batch()

    def set_batch_ui(self,active):
        self._batch_active = active
        self.sidebar.setEnabled(not active)
        self.files.setEnabled(not active)
        self.add_button.setEnabled(not active)

    def begin_batch(self):
        request,paths,output,options = self._queued_batch
        self._queued_batch = None
        def action(worker):
            saved = []
            for i,path in enumerate(paths):
                check_cancel(worker.cancel)
                def report(text,value):
                    worker.progress.emit(f'Фото {i+1}/{len(paths)} · {text}',int((i+value/100)*100/len(paths)))
                final = render_image(replace(request,source=path),self.image_cache,report,worker.cancel,process_fn=process)['image']
                check_cancel(worker.cancel)
                saved.append(str(save_unique(final,output,path,request.export_factor,**options)))
            return saved
        self._estimate = Estimate()
        self.stop.show()
        self.worker = FileWorker(action)
        self.worker.progress.connect(self.update_progress)
        self.worker.completed.connect(self.batch_completed)
        self.worker.error.connect(self.failure)
        self.worker.finished.connect(lambda w=self.worker: self.batch_finished(w))
        self.worker.start()

    def batch_completed(self,saved):
        self.progress.setValue(100)
        self.status_label.setText(f'Сохранено изображений: {len(saved)}')
        self.progress_reset_timer.start(1400)

    def batch_finished(self,thread):
        self.set_batch_ui(False)
        self.eta_label.setText('')
        self.render_finished(thread)

    def show_result(self,source,path):
        with Image.open(source) as opened:
            original = ImageOps.exif_transpose(opened).copy()
        with Image.open(path) as opened:
            result = opened.copy()
        self.canvas.set_images(original,result,max(1,round(result.width/original.width)))

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self,event):
        if not self._batch_active:
            self.add_paths([url.toLocalFile() for url in event.mimeData().urls()])

    def closeEvent(self,event):
        self._closing=True
        self.progress_reset_timer.stop()
        self.model_info.hide()
        threads = [self.worker,self.io_worker,self.cache_worker,self.update_worker,self.library.worker if self.library else None,
                   self.storage_dialog.worker if self.storage_dialog else None]
        active = [thread for thread in threads if thread and thread.isRunning()]
        if active:
            self._closing = True
            self.debounce.stop()
            self._pending = False
            for thread in active:
                thread.cancel.set()
            self.status_label.setText('Завершение текущей операции…')
            QTimer.singleShot(250,self.close)
            event.ignore()
        else:
            self.debounce.stop()
            self.cache_timer.stop()
            self.update_timer.stop()
            self.image_cache.close()
            event.accept()

    def finish_close(self,timeout=30):
        """Drain every owned job before a non-interactive caller releases QApplication."""
        self.close()
        deadline=time.monotonic()+timeout
        while True:
            QApplication.processEvents()
            threads=[self.worker,self.io_worker,self.cache_worker,self.update_worker,self.library.worker if self.library else None,
                     self.storage_dialog.worker if self.storage_dialog else None]
            if not any(thread and thread.isRunning() for thread in threads):
                self.close()
                QApplication.processEvents()
                return
            if time.monotonic()>deadline:
                raise TimeoutError('Не удалось завершить фоновую задачу при закрытии окна.')
            time.sleep(.015)


def create_application():
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('PhotoRestore.Studio')
    app = QApplication(sys.argv)
    font_path = Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont('Segoe UI',10))
    app.setStyle('Fusion')
    app.setStyleSheet(THEME)
    app.setWindowIcon(QIcon(str(ROOT/'assets'/'brand'/'photo-restore.ico')))
    return app


def main():
    app = create_application()
    window = Studio()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    if '--studio-worker' in sys.argv:
        from studio_backend import worker
        sys.exit(worker(sys.argv[sys.argv.index('--studio-worker')+1]))
    elif '--startup-probe' in sys.argv:
        import json
        probe_app = create_application()
        probe_window = Studio(auto_process=False)
        probe_window.show()
        probe_app.processEvents()
        report = dict(seconds_to_window=time.perf_counter()-BOOT_STARTED,torch_loaded='torch' in sys.modules,
                      icon_loaded=not probe_app.windowIcon().isNull(),profiles=probe_window.models.count(),
                      models=str(STORE.models),cache=str(STORE.cache),scratch=str(STORE.scratch))
        probe_window.finish_close()
        from PySide6.QtCore import QCoreApplication,QEvent
        for widget in probe_app.topLevelWidgets():
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        probe_app.processEvents()
        report['shutdown_drained'] = True
        (DATA/'startup.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    elif '--diagnostics' in sys.argv:
        from diagnostics import run
        sys.exit(run())
    else:
        main()

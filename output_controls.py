"""Compact output sizing/export card with linked dimensions and scale presets."""
import math
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame,QVBoxLayout,QHBoxLayout,QLabel,QToolButton,QButtonGroup,
                              QSpinBox,QDoubleSpinBox,QAbstractSpinBox,QComboBox,QWidget)


class FactorSpin(QDoubleSpinBox):
    def textFromValue(self,value):
        text=self.locale().toString(value,'f',3)
        return text.rstrip('0').rstrip(self.locale().decimalPoint())


class OutputControls(QFrame):
    currentIndexChanged = Signal(int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('outputCard')
        self._factor = 4.0
        self._source_size = None
        layout = QVBoxLayout(self); layout.setContentsMargins(10,10,10,10); layout.setSpacing(9)
        heading = QHBoxLayout(); title = QLabel('Увеличение'); title.setObjectName('outputTitle')
        heading.addWidget(title); heading.addStretch()
        linked = QLabel('↔'); linked.setToolTip('Ширина и высота изменяются с сохранением пропорций')
        heading.addWidget(linked); layout.addLayout(heading)
        strip = QFrame(); strip.setObjectName('scaleStrip')
        row = QHBoxLayout(strip); row.setContentsMargins(3,3,3,3); row.setSpacing(2)
        self.group = QButtonGroup(self); self.buttons = {}
        for number in (1,2,4,6,8):
            button = QToolButton(); button.setObjectName('scalePreset'); button.setText(f'×{number}')
            button.setCheckable(True); button.setAccessibleName(f'Увеличение в {number} раз')
            button.clicked.connect(lambda checked=False,n=number:self.set_factor(n))
            self.group.addButton(button); row.addWidget(button,1); self.buttons[number] = button
        self.custom = QToolButton(); self.custom.setObjectName('scalePreset'); self.custom.setText('Свой')
        self.custom.setCheckable(True); self.group.addButton(self.custom); row.addWidget(self.custom,1)
        self.custom.clicked.connect(lambda:self.coefficient.setFocus())
        layout.addWidget(strip)
        self.coefficient = FactorSpin(); self.coefficient.setRange(1,8); self.coefficient.setDecimals(3)
        self.coefficient.setSingleStep(.1); self.coefficient.setSuffix(' ×'); self.coefficient.setValue(4)
        self.coefficient.setAccessibleName('Коэффициент увеличения'); self.coefficient.setKeyboardTracking(False)
        self.coefficient.valueChanged.connect(self.set_factor)
        self._field(layout,'Коэффициент',self.coefficient)
        label = QLabel('Размер изображения'); label.setObjectName('outputCaption'); layout.addWidget(label)
        sizes = QHBoxLayout(); sizes.setSpacing(6)
        self.width_pixels = QSpinBox(); self.height_pixels = QSpinBox()
        for name,spin in (('Ш',self.width_pixels),('В',self.height_pixels)):
            field = QFrame(); field.setObjectName('outputField'); row = QHBoxLayout(field)
            row.setContentsMargins(8,0,3,0); row.setSpacing(3)
            caption = QLabel(name); caption.setObjectName('outputCaption'); row.addWidget(caption)
            spin.setRange(1,200000); spin.setSuffix(' px'); spin.setKeyboardTracking(False)
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons); spin.setAlignment(Qt.AlignRight)
            spin.setEnabled(False); row.addWidget(spin,1); sizes.addWidget(field,1)
        self.width_pixels.setAccessibleName('Ширина результата'); self.height_pixels.setAccessibleName('Высота результата')
        self.width_pixels.valueChanged.connect(lambda value:self.dimension_changed(value,0))
        self.height_pixels.valueChanged.connect(lambda value:self.dimension_changed(value,1))
        layout.addLayout(sizes)
        self.source_note = QLabel('Откройте изображение'); self.source_note.setObjectName('outputCaption')
        layout.addWidget(self.source_note)
        self.dpi = QSpinBox(); self.dpi.setRange(15,600); self.dpi.setValue(300); self.dpi.setSuffix(' DPI')
        self.dpi.setAccessibleName('Плотность печати'); self.dpi.setKeyboardTracking(False)
        self.dpi.setToolTip('Плотность печати 15–600 DPI. Количество пикселей задают размеры выше.')
        self._field(layout,'Плотность печати',self.dpi)
        self.format = QComboBox(); self.format.addItem('PNG','PNG'); self.format.addItem('JPEG (.jpg)','JPEG')
        self.format.setAccessibleName('Формат экспорта'); self._field(layout,'Формат',self.format)
        self.jpeg_settings = QWidget(); jpeg_row = QHBoxLayout(self.jpeg_settings)
        jpeg_row.setContentsMargins(0,0,0,0); jpeg_row.addWidget(QLabel('Качество JPEG'),1)
        self.jpeg_quality = QSpinBox(); self.jpeg_quality.setRange(1,100); self.jpeg_quality.setValue(95)
        self.jpeg_quality.setSuffix(' %'); self.jpeg_quality.setKeyboardTracking(False)
        jpeg_row.addWidget(self.jpeg_quality); layout.addWidget(self.jpeg_settings); self.jpeg_settings.hide()
        self.vector_settings = QWidget(); vector_layout = QVBoxLayout(self.vector_settings)
        vector_layout.setContentsMargins(0,0,0,0)
        self.vector_colors = QSpinBox(); self.vector_colors.setRange(2,64); self.vector_colors.setValue(8)
        self.vector_colors.setKeyboardTracking(False)
        self.vector_colors.setToolTip('Меньше цветов — ровнее заливки. Больше — лучше сохраняются оттенки.')
        self._field(vector_layout,'Цветов в SVG',self.vector_colors)
        self.vector_smoothness = QSpinBox(); self.vector_smoothness.setRange(0,100); self.vector_smoothness.setValue(30)
        self.vector_smoothness.setSuffix(' %'); self.vector_smoothness.setKeyboardTracking(False)
        self.vector_smoothness.setToolTip('Повышение убирает мелкий мусор и упрощает контуры; тонкие детали могут исчезнуть.')
        self._field(vector_layout,'Чистота контуров',self.vector_smoothness)
        note=QLabel('SVG: ровные заливки и редактируемые кривые. Градиенты упрощаются; текст переводится в контуры.')
        note.setWordWrap(True); note.setObjectName('outputCaption'); vector_layout.addWidget(note)
        layout.addWidget(self.vector_settings); self.vector_settings.hide()
        self.buttons[4].setChecked(True)

    def set_graphics(self,enabled):
        index=self.format.findData('SVG')
        if enabled and index<0:self.format.addItem('SVG · вектор','SVG')
        elif not enabled and index>=0:
            if self.format.currentData()=='SVG':self.format.setCurrentIndex(0)
            self.format.removeItem(index)
        self.vector_settings.setVisible(enabled and self.format.currentData()=='SVG')

    def _field(self,layout,title,control):
        field = QFrame(); field.setObjectName('outputField'); row = QHBoxLayout(field)
        row.setContentsMargins(8,0,4,0); row.setSpacing(6)
        label = QLabel(title); label.setObjectName('outputCaption'); row.addWidget(label,1)
        if isinstance(control,QAbstractSpinBox):
            control.setButtonSymbols(QAbstractSpinBox.NoButtons); control.setAlignment(Qt.AlignRight)
        row.addWidget(control,1); layout.addWidget(field)

    @property
    def value(self):
        return self._factor

    @property
    def inference_factor(self):
        return min(8,max(1,math.ceil(self._factor-1e-9)))

    def currentText(self):
        return f'×{self._factor:g}'

    def setCurrentText(self,text):
        self.set_factor(float(text.lstrip('×xх ')))

    def set_factor(self,value):
        value = max(1.,min(8.,float(value)))
        changed = abs(value-self._factor)>1e-10
        self._factor = value
        self.coefficient.blockSignals(True); self.coefficient.setValue(value); self.coefficient.blockSignals(False)
        self.buttons.get(round(value),self.custom).setChecked(True) if abs(value-round(value))<1e-9 else self.custom.setChecked(True)
        self.refresh_dimensions()
        if changed:self.currentIndexChanged.emit(self.inference_factor)

    def set_source_size(self,size):
        self._source_size = size
        self.refresh_dimensions()

    def refresh_dimensions(self):
        for axis,spin in enumerate((self.width_pixels,self.height_pixels)):
            spin.blockSignals(True)
            spin.setEnabled(self._source_size is not None)
            spin.setRange(self._source_size[axis] if self._source_size else 1,
                          self._source_size[axis]*8 if self._source_size else 200000)
            spin.setValue(round(self._source_size[axis]*self._factor) if self._source_size else 1)
            spin.blockSignals(False)
        self.source_note.setText(f'Исходник: {self._source_size[0]} × {self._source_size[1]} px'
                                 if self._source_size else 'Откройте изображение')

    def dimension_changed(self,value,axis):
        if self._source_size:self.set_factor(value/self._source_size[axis])

"""Compact queue with the same processing settings used by the editor and batch export."""
from pathlib import Path
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QHeaderView, QCheckBox, QToolButton, QStyleOptionButton, QStyle
from viewer import icon


class SelectAllBox(QCheckBox):
    def nextCheckState(self):
        self.setCheckState(Qt.Unchecked if self.checkState() == Qt.Checked else Qt.Checked)

    def paintEvent(self,event):
        super().paintEvent(event)
        if self.checkState() == Qt.Unchecked:
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SE_CheckBoxIndicator,option,self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#f4f8ff'),1.5,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        x,y = rect.left(),rect.top()
        if self.checkState() == Qt.PartiallyChecked:
            painter.drawLine(x+3,y+7,x+10,y+7)
        else:
            painter.drawLine(x+3,y+7,x+6,y+10)
            painter.drawLine(x+6,y+10,x+11,y+4)


class FileTable(QTreeWidget):
    closeRequested = Signal(object)
    IMAGE, ORIGINAL, SCALE, OUTPUT, MODEL, EFFECT, SHARPNESS, FACES, HAIR, LIGHT, EXPORT, CLOSE = range(12)
    SIZE_ROLE = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('fileTable')
        self.setHeaderLabels(['', 'Исходник', 'Масштаб', 'Результат', 'Модель', 'Эффект',
                              'Резкость', 'Лица', 'Волосы', 'Свет', 'Экспорт', ''])
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setItemsExpandable(False)
        self.setUniformRowHeights(True)
        self.setIconSize(QSize(34,34))
        self.setSelectionMode(QTreeWidget.SingleSelection)
        self.setSelectionBehavior(QTreeWidget.SelectRows)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.StrongFocus)
        self.header().setStretchLastSection(False)
        self.header().setMinimumSectionSize(28)
        self.header().setFixedHeight(28)
        self.header().setSectionResizeMode(QHeaderView.Fixed)
        self.widths = [125,68,130,190,68,70,62,68,60,114,34]
        for column,width in enumerate(self.widths,1):
            self.setColumnWidth(column,width)
        self.select_all = SelectAllBox('Изображение',self.header().viewport())
        self.select_all.setObjectName('selectAllFiles')
        self.select_all.setTristate(True)
        self.select_all.setToolTip('Отмеченные файлы участвуют в пакетном экспорте.\nНастройки справа применяются ко всей очереди.')
        self.select_all.clicked.connect(self.check_all)
        self.header().geometriesChanged.connect(self.fit_columns)
        self.horizontalScrollBar().valueChanged.connect(self.position_header)
        self.itemChanged.connect(self.update_checks)
        tips = {
            self.ORIGINAL:'Размер исходного изображения с учётом его ориентации.',
            self.SCALE:'Выбранное увеличение от ×2 до ×8.',
            self.OUTPUT:'Размер после выбранного увеличения.',
            self.MODEL:'Модель общего апскейла. Настройки справа применяются ко всей очереди.',
            self.EFFECT:'Сила улучшения: 0% — обычное увеличение, 100% — полный AI-эффект.',
            self.SHARPNESS:'Дополнительная резкость после апскейла.',
            self.FACES:'Сила восстановления лиц. «Выкл.» — этап отключён.',
            self.HAIR:'Сила отдельной обработки волос. «Выкл.» — этап отключён.',
            self.LIGHT:'Экспозиция, тени, света и температура. Подробности — в подсказке строки.',
            self.EXPORT:'Формат и плотность печати. DPI не меняет количество пикселей.',
            self.CLOSE:'Закрыть файл без удаления исходника с диска.',
        }
        for column,tip in tips.items():
            self.headerItem().setToolTip(column,tip)
        self.update_height()

    def position_header(self,*args):
        self.select_all.setGeometry(self.header().sectionViewportPosition(0)+10,0,
                                    max(30,min(self.select_all.sizeHint().width(),self.header().sectionSize(0)-20)),
                                    self.header().height())

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.fit_columns()

    def fit_columns(self):
        width = max(250,self.viewport().width()-sum(self.widths))
        if self.columnWidth(0) != width:
            self.setColumnWidth(0,width)
        self.position_header()

    def update_height(self):
        self.setFixedHeight(29+42*max(1,min(3,self.topLevelItemCount()))+8)

    def paths(self,checked_only=False):
        return [self.topLevelItem(row).data(0,Qt.UserRole) for row in range(self.topLevelItemCount())
                if not checked_only or self.topLevelItem(row).checkState(0) == Qt.Checked]

    def add_file(self,path,size,thumb):
        item = QTreeWidgetItem([Path(path).name])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0,Qt.Checked)
        item.setData(0,Qt.UserRole,path)
        item.setData(0,self.SIZE_ROLE,size)
        item.setToolTip(0,path+'\nГалочка: включить в пакетный экспорт.')
        item.setIcon(0,QIcon(QPixmap.fromImage(ImageQt(thumb))))
        item.setSizeHint(0,QSize(250,42))
        item.setText(self.ORIGINAL,self.size_text(size))
        for column in (self.SCALE,self.EFFECT,self.SHARPNESS,self.FACES,self.HAIR,self.LIGHT):
            item.setTextAlignment(column,Qt.AlignCenter)
        self.addTopLevelItem(item)
        close = QToolButton()
        close.setObjectName('closeFile')
        close.setIcon(icon('close'))
        close.setFixedSize(28,42)
        close.setToolTip('Закрыть файл · Ctrl+W\nИсходник останется на диске.')
        close.setAccessibleName(f'Закрыть файл {Path(path).name}')
        close.clicked.connect(lambda checked=False,current=item:self.closeRequested.emit(current))
        self.setItemWidget(item,self.CLOSE,close)
        self.update_height()
        self.update_checks()
        return item

    @staticmethod
    def size_text(size):
        return f'{size[0]} × {size[1]} px'

    def set_settings(self,*,factor,model,model_help,effect,sharpness,faces,face_strength,face_help,
                     hair,hair_strength,hair_help,exposure,shadows,highlights,temperature,light_faces,
                     image_format,dpi,quality):
        light = any((exposure,shadows,highlights,temperature))
        light_help = (f'Экспозиция: {exposure/50:+.2f} EV\nТени: {shadows:+d}%\n'
                      f'Света: {highlights:+d}%\nТемпература: {temperature:+d}%\n'
                      + ('Только область лица' if light_faces else 'Всё изображение'))
        self.blockSignals(True)
        for row in range(self.topLevelItemCount()):
            item = self.topLevelItem(row)
            width,height = item.data(0,self.SIZE_ROLE)
            texts = {self.SCALE:f'×{factor:g}', self.OUTPUT:self.size_text((round(width*factor),round(height*factor))),
                     self.MODEL:model or 'Не выбрана', self.EFFECT:f'{effect}%', self.SHARPNESS:f'{sharpness}%',
                     self.FACES:f'{face_strength}%' if faces else 'Выкл.',
                     self.HAIR:f'{hair_strength}%' if hair else 'Выкл.', self.LIGHT:'Вкл.' if light else 'Выкл.',
                     self.EXPORT:f'{image_format} · {dpi} DPI'}
            for column,value in texts.items():
                item.setText(column,value)
            item.setToolTip(self.OUTPUT,'Целевой размер: '+texts[self.OUTPUT])
            item.setToolTip(self.MODEL,model_help)
            item.setToolTip(self.FACES,face_help if faces else 'Восстановление лиц отключено.')
            item.setToolTip(self.HAIR,hair_help if hair else 'Отдельная обработка волос отключена.')
            item.setToolTip(self.LIGHT,light_help if light else 'Коррекция света отключена.')
            item.setToolTip(self.EXPORT,texts[self.EXPORT]+(f'\nКачество JPEG: {quality}%' if image_format == 'JPEG' else ''))
        self.blockSignals(False)

    def set_result(self,path,size):
        for row in range(self.topLevelItemCount()):
            item = self.topLevelItem(row)
            if item.data(0,Qt.UserRole) == path:
                item.setText(self.OUTPUT,self.size_text(size))
                item.setToolTip(self.OUTPUT,'Размер обработанного изображения: '+self.size_text(size))
                break

    def check_all(self,*args):
        checked = self.select_all.checkState() == Qt.Checked
        self.blockSignals(True)
        for row in range(self.topLevelItemCount()):
            self.topLevelItem(row).setCheckState(0,Qt.Checked if checked else Qt.Unchecked)
        self.blockSignals(False)
        self.update_checks()

    def update_checks(self,item=None,column=0):
        if column != 0:
            return
        count = self.topLevelItemCount()
        checked = len(self.paths(checked_only=True))
        self.select_all.blockSignals(True)
        self.select_all.setCheckState(Qt.Checked if count and checked == count else
                                     Qt.PartiallyChecked if checked else Qt.Unchecked)
        self.select_all.blockSignals(False)

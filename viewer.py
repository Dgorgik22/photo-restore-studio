"""Single canvas with shared normalized navigation for all comparison modes."""
import math
from i18n import tr
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QIcon, QPainterPath
from PySide6.QtWidgets import QWidget, QToolButton, QMenu, QSlider


class AdjustmentSlider(QSlider):
    """Bright progress track and a hollow handle, with QSlider keyboard accessibility."""
    def paintEvent(self,event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        y = self.height()/2
        left,right = 6,self.width()-6
        value = (self.value()-self.minimum())/max(1,self.maximum()-self.minimum())
        x = left+(right-left)*value
        painter.setPen(QPen(QColor('#454545'),2,Qt.SolidLine,Qt.RoundCap))
        painter.drawLine(QPointF(left,y),QPointF(right,y))
        painter.setPen(QPen(QColor('#eeeeee' if self.isEnabled() else '#666666'),2,Qt.SolidLine,Qt.RoundCap))
        painter.drawLine(QPointF(left,y),QPointF(x,y))
        painter.setPen(QPen(QColor('#f3f3f3' if self.isEnabled() else '#777777'),2))
        painter.setBrush(QColor('#262626'))
        painter.drawEllipse(QPointF(x,y),5,5)

    def position_value(self,event):
        fraction = max(0,min(1,(event.position().x()-6)/max(1,self.width()-12)))
        self.setValue(round(self.minimum()+fraction*(self.maximum()-self.minimum())))

    def mousePressEvent(self,event):
        if event.button() == Qt.LeftButton:
            self.setFocus()
            self.setSliderDown(True)
            self.position_value(event)
            event.accept()

    def mouseMoveEvent(self,event):
        if self.isSliderDown():
            self.position_value(event)

    def mouseReleaseEvent(self,event):
        self.setSliderDown(False)
        event.accept()


def icon(name, color='#c5c5c5', size=20):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.4))
    if name in ('view', 'split'):
        painter.drawRoundedRect(QRectF(3, 4, 14, 12), 1.5, 1.5)
        painter.drawLine(10, 4, 10, 16)
    elif name == 'fit':
        for x,y,sx,sy in [(3,3,1,1),(17,3,-1,1),(3,17,1,-1),(17,17,-1,-1)]:
            painter.drawLine(x,y,x+4*sx,y)
            painter.drawLine(x,y,x,y+4*sy)
    elif name == 'folder':
        path = QPainterPath(QPointF(2, 6))
        for x,y in [(2,4),(8,4),(10,6),(18,6),(18,16),(2,16),(2,6)]:
            path.lineTo(x,y)
        painter.drawPath(path)
    elif name == 'download':
        painter.drawLine(10, 3, 10, 12)
        painter.drawLine(6, 8, 10, 12)
        painter.drawLine(10,12,14,8)
        painter.drawLine(3,14,3,17)
        painter.drawLine(3,17,17,17)
        painter.drawLine(17,17,17,14)
    elif name == 'library':
        for x in (3, 9, 15):
            painter.drawRoundedRect(QRectF(x,4,3,12),0.5,0.5)
    elif name == 'close':
        painter.drawLine(5,5,15,15)
        painter.drawLine(5,15,15,5)
    else:
        painter.drawLine(4,10,16,10)
        painter.drawLine(10,4,10,16)
    painter.end()
    return QIcon(pixmap)


class ImageCanvas(QWidget):
    zoomChanged = Signal(float)
    modeChanged = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.original = QImage()
        self.result = QImage()
        self.factor = 4
        self.center = QPointF(.5, .5)
        self.zoom = 1.0
        self.fit_mode = True
        self.mode = 'result'
        self.hold_original = False
        self.dragging = False
        self.last_mouse = QPointF()
        self.setMinimumSize(320, 250)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.view_button = QToolButton(self)
        self.view_button.setObjectName('canvasTool')
        self.view_button.setIcon(icon('view'))
        self.view_button.setToolTip('Виды просмотра')
        self.view_button.setAccessibleName('Виды просмотра')
        self.view_button.setFixedSize(34, 30)
        self.view_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.view_button)
        for text, mode in [('Результат', 'result'), ('Оригинал', 'original'), ('Рядом: оригинал / результат', 'split')]:
            action = menu.addAction(text)
            action.triggered.connect(lambda checked=False, value=mode: self.set_mode(value))
        self.view_button.setMenu(menu)
        self.setToolTip('ЛКМ: удерживать — оригинал, тянуть — перемещение. Колесо: масштаб. Двойной щелчок: вписать.')

    def clear(self):
        self.original = QImage()
        self.result = QImage()
        self.center = QPointF(.5,.5)
        self.zoom = 1.0
        self.fit_mode = True
        self.hold_original = self.dragging = False
        self.setCursor(Qt.OpenHandCursor)
        self.zoomChanged.emit(1.0)
        self.update()

    def world_size(self):
        if not self.result.isNull():
            return self.result.width(), self.result.height()
        return max(1, self.original.width()*self.factor), max(1, self.original.height()*self.factor)

    def panel_rects(self):
        if self.mode == 'split':
            half = self.width()/2
            return [QRectF(0,0,half,self.height()), QRectF(half,0,half,self.height())]
        return [QRectF(self.rect())]

    def scale_value(self):
        if self.fit_mode:
            w,h = self.world_size()
            panel = self.panel_rects()[0]
            return max(.0001, min((panel.width()-64)/w, (panel.height()-80)/h))
        return self.zoom

    def set_images(self, original=None, result=None, factor=None, reset=False):
        old_width = self.world_size()[0]
        if original is not None:
            self.original = QImage(ImageQt(original.convert('RGBA'))).copy()
        self.result = QImage(ImageQt(result.convert('RGBA'))).copy() if result is not None else QImage()
        if factor is not None:
            self.factor = factor
        if reset:
            self.center = QPointF(.5,.5)
            self.fit_mode = True
        elif not self.fit_mode:
            self.zoom *= old_width/self.world_size()[0]
        self.zoomChanged.emit(self.scale_value())
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.modeChanged.emit(mode)
        self.zoomChanged.emit(self.scale_value())
        self.update()

    def fit(self):
        self.fit_mode = True
        self.center = QPointF(.5,.5)
        self.zoomChanged.emit(self.scale_value())
        self.update()

    def actual_size(self):
        self.fit_mode = False
        self.zoom = 1.0
        self.zoomChanged.emit(self.zoom)
        self.update()

    def panel_at(self, pos):
        return next((p for p in self.panel_rects() if p.contains(pos)), self.panel_rects()[0])

    def normalized_at(self, pos):
        panel = self.panel_at(pos)
        w,h = self.world_size()
        scale = self.scale_value()
        return self.center + QPointF((pos.x()-panel.center().x())/(w*scale), (pos.y()-panel.center().y())/(h*scale))

    def zoom_at(self, position, multiplier):
        if self.original.isNull():
            return
        anchor = self.normalized_at(position)
        panel = self.panel_at(position)
        w,h = self.world_size()
        self.zoom = min(64, max(.002, self.scale_value()*multiplier))
        self.fit_mode = False
        self.center = anchor - QPointF((position.x()-panel.center().x())/(w*self.zoom),
                                      (position.y()-panel.center().y())/(h*self.zoom))
        self.zoomChanged.emit(self.zoom)
        self.update()

    def wheelEvent(self, event):
        steps = event.angleDelta().y()/120
        if not steps and event.pixelDelta().y():
            steps = event.pixelDelta().y()/60
        self.zoom_at(event.position(), 1.2**steps)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self.setFocus()
            self.dragging = True
            self.hold_original = event.button() == Qt.LeftButton
            self.last_mouse = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            delta = event.position()-self.last_mouse
            self.last_mouse = event.position()
            w,h = self.world_size()
            scale = self.scale_value()
            self.center -= QPointF(delta.x()/(w*scale), delta.y()/(h*scale))
            self.update()

    def mouseReleaseEvent(self, event):
        self.dragging = self.hold_original = False
        self.setCursor(Qt.OpenHandCursor)
        self.update()
        event.accept()

    def focusOutEvent(self, event):
        self.dragging = self.hold_original = False
        self.update()
        super().focusOutEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.dragging = self.hold_original = False
        self.fit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F:
            self.fit()
        elif event.key() == Qt.Key_1:
            self.actual_size()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        self.view_button.move(self.width()-48, 14)
        self.zoomChanged.emit(self.scale_value())
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#191919'))
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.original.isNull():
            painter.setPen(QColor('#dedede'))
            font = painter.font()
            font.setPointSize(17)
            painter.setFont(font)
            painter.drawText(self.rect().adjusted(24,-25,-24,-25), Qt.AlignCenter, tr('Перетащите изображение сюда'))
            font.setPointSize(10)
            painter.setFont(font)
            painter.setPen(QColor('#858585'))
            painter.drawText(self.rect().adjusted(24,35,-24,35), Qt.AlignCenter, tr('или нажмите «Открыть» · улучшение начнётся автоматически'))
            return
        w,h = self.world_size()
        scale = self.scale_value()
        panels = self.panel_rects()
        for index,panel in enumerate(panels):
            painter.save()
            painter.setClipRect(panel)
            original = self.hold_original or self.mode == 'original' or (self.mode == 'split' and index == 0)
            image = self.original if original or self.result.isNull() else self.result
            rect = QRectF(panel.center().x()-self.center.x()*w*scale,
                          panel.center().y()-self.center.y()*h*scale, w*scale, h*scale)
            # Checkerboard is clipped to the image bounds; the rest of the canvas stays neutral.
            painter.fillRect(rect, QColor('#303030'))
            if image.hasAlphaChannel():
                painter.save()
                painter.setClipRect(rect, Qt.IntersectClip)
                for y in range(0,self.height(),24):
                    for x in range(int(panel.left()),int(panel.right())+24,24):
                        if (x//24+y//24)%2:
                            painter.fillRect(x,y,24,24,QColor('#363636'))
                painter.restore()
            painter.drawImage(rect, image)
            painter.setPen(QColor('#101010'))
            painter.drawRect(rect)
            label = 'ОРИГИНАЛ' if original else ('РЕЗУЛЬТАТ' if not self.result.isNull() else 'ИСХОДНИК · ОБРАБОТКА')
            badge = QRectF(panel.left()+16, 16, 195 if 'ОБРАБОТКА' in label else 108, 26)
            painter.fillRect(badge, QColor(38,38,38,220))
            painter.setPen(QColor('#cccccc'))
            painter.drawText(badge, Qt.AlignCenter, tr(label))
            painter.restore()
        if self.mode == 'split':
            painter.setPen(QPen(QColor('#555555'),1))
            painter.drawLine(self.width()//2,0,self.width()//2,self.height())

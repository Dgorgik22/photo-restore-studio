"""Short, local model guides; no network calls or modal dialogs."""
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QToolButton
from core import CATALOG


GUIDES = {
    'realesrgan-photo': (
        'Фотооснова с автоматической проработкой деталей. В облаках работает локальная PBRify; в листве и воде восстанавливается сглаженная фактура исходника.',
        'Природа, вода, облака, архитектура и интерьеры. Повторяющиеся окна и прямые границы уточняются по исходнику. Для тёмных помещений выберите сцену «Интерьер».',
        'Детали обрабатываются автоматически по найденным областям. Чёткая фактура и ровные поверхности не усиливаются повторно. Очистка по умолчанию выключена; отсутствующие детали не гарантированно достоверны.'),
    'pbrify-detail': (
        'Портретная основа для ткани и волос. Лицо, глаза, нос и борода восстанавливаются единым выровненным проходом CodeFormer.',
        'Портреты с одеждой и волосами. Шея включена в восстановление; на крупном лице используются уже рассчитанные детали на сетке 1024 пикселя, без повторной загрузки модели. В пейзажах PBRify уточняет облака.',
        'Волосы обрабатываются автоматически; ползунок регулирует силу. Оттенки кожи и утраченная фактура поддерживаются исходником. Из очень маленького лица нельзя достоверно получить невидимые поры и черты.'),
    'codeformer': (
        'Восстановление лица с сохранением исходного освещения и настройкой сходства.',
        'Небольшие, размытые и сжатые портреты. Высокое сходство и умеренная сила помогают сохранить внешность.',
        'Может менять черты. Борода и усы восстанавливаются вместе с лицом; последующий проход волос их не перезаписывает. Лицензия S-Lab 1.0 ограничивает коммерческое применение.'),
}



def model_entry(path):
    return next((item for item in CATALOG if item['file'] == Path(path).name), None) if path else None


def model_guide(path):
    if str(path)=='graphics':
        return ('Графика и иллюстрации','Локальная обработка без дорисовки фотографической фактуры.',
                'Паттерны, плоская графика и иллюстрации. PNG/JPEG сохраняют оттенки; SVG строит цветные векторные кривые.',
                'SVG доступен только в этом режиме. Сокращение палитры упрощает градиенты; идеальные окружности и читаемость мелкого текста не гарантируются.')
    entry = model_entry(path)
    if not entry:
        return (Path(path).stem if path else 'Модель не выбрана',
                'Импортированная локальная модель.',
                'Назначение и сильные стороны уточните в описании её автора.',
                'Проверьте результат на небольшом изображении перед обработкой очереди.')
    return (entry['name'], *GUIDES[entry['id']])


def guide_text(path):
    title, benefit, use, note = model_guide(path)
    entry = model_entry(path)
    technical = f"\nМодель: {entry['technical_name']}" if entry else ''
    return f'{title}{technical}\n\nПреимущества: {benefit}\n\nЛучше для: {use}\n\n{note}'


class ModelInfoCard(QFrame):
    def __init__(self, parent):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName('modelInfoCard')
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(310)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14,12,14,14)
        layout.setSpacing(9)
        top = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName('modelInfoTitle')
        self.title.setWordWrap(True)
        top.addWidget(self.title,1)
        close = QToolButton()
        close.setText('×')
        close.setObjectName('quiet')
        close.setToolTip('Закрыть подсказку')
        close.clicked.connect(self.hide)
        top.addWidget(close,0,Qt.AlignTop)
        layout.addLayout(top)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.PlainText)
        layout.addWidget(self.body)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_for(self, path, anchor, faces=False, display_title=None, description=None):
        title, benefit, use, note = model_guide(path)
        self.title.setText(display_title or title)
        body = f'Преимущества\n{benefit}\n\nЛучше для\n{use}\n\n{note}'
        entry = model_entry(path)
        if entry:
            body = f"Модель: {entry['technical_name']}\n\n" + body
        if faces and Path(path).name not in ('GFPGANv1.4.pth','codeformer.pth'):
            name = 'CodeFormer' if faces == 'codeformer' else 'GFPGAN'
            body += f'\n\n{name}: включено восстановление лиц; умеренная сила помогает сохранить сходство.'
        if description:
            body = description+'\n\n'+body
        self.body.setText(body)
        self.layout().activate()
        self.setFixedHeight(max(180,self.layout().totalHeightForWidth(self.width())))
        screen = anchor.screen().availableGeometry()
        position = anchor.mapToGlobal(QPoint(-self.width()-12,0))
        x = max(screen.left(),min(position.x(),screen.right()-self.width()))
        y = max(screen.top(),min(position.y(),screen.bottom()-self.height()))
        self.move(x,y)
        self.show()
        self.timer.start(12000)

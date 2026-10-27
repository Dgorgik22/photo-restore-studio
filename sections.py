"""Fold optional tools without changing their parameter values."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QSizePolicy


class ToolSection(QWidget):
    def __init__(self,title,check=None,parent=None):
        super().__init__(parent)
        self.setObjectName('toolSection')
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setContentsMargins(0,0,0,0)
        self.toggle = QToolButton()
        self.toggle.setObjectName('sectionToggle')
        self.toggle.setCheckable(True)
        self.toggle.setArrowType(Qt.RightArrow)
        self.check = check
        if check is None:
            self.toggle.setText(title)
            self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            row.addWidget(self.toggle,0,Qt.AlignLeft)
            row.addStretch()
        else:
            row.addWidget(check,1)
            self.toggle.setFixedWidth(26)
            self.toggle.setToolTip('Свернуть или развернуть настройки')
            self.toggle.setAccessibleName(f'Настройки: {title}')
            row.addWidget(self.toggle)
            check.toggled.connect(self.set_active)
        layout.addLayout(row)
        self.body = QWidget()
        self.body.setObjectName('toolSectionBody')
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0,0,0,0)
        self.body_layout.setSpacing(8)
        layout.addWidget(self.body)
        self.body.hide()
        self.toggle.toggled.connect(self.set_expanded)
        if check is not None:
            self.set_active(check.isChecked())

    def set_expanded(self,expanded):
        expanded = bool(expanded) and (self.check is None or self.check.isChecked())
        self.toggle.setChecked(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body.setVisible(expanded)
        self.layout().invalidate()
        self.updateGeometry()

    def set_active(self,active):
        self.toggle.setEnabled(active)
        self.set_expanded(active)

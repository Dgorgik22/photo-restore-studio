"""Shared three-choice control with a single change notification."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QToolButton,QButtonGroup


class ThreeLevels(QWidget):
    valueChanged=Signal(int)
    LABELS=('Лёгкая','Средняя','Усиленная')

    def __init__(self,title,values,initial,tips=()):
        super().__init__()
        self.values=tuple(values);self._value=None
        self.setAccessibleName(title)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(7)
        layout.addWidget(QLabel(title))
        strip=QWidget();strip.setObjectName('levelStrip')
        row=QHBoxLayout(strip);row.setContentsMargins(2,2,2,2);row.setSpacing(2)
        self.group=QButtonGroup(self);self.group.setExclusive(True);self.buttons=[]
        for index,label in enumerate(self.LABELS):
            button=QToolButton();button.setText(label);button.setObjectName('levelPreset');button.setCheckable(True)
            button.setAccessibleName(title+': '+label)
            if tips:button.setToolTip(tips[index])
            self.group.addButton(button,index);row.addWidget(button,1);self.buttons.append(button)
        self.group.idClicked.connect(lambda index:self.setValue(self.values[index]))
        layout.addWidget(strip);self.setValue(initial)

    def value(self):return self._value

    def setValue(self,value):
        index=min(range(3),key=lambda i:abs(self.values[i]-value));new=self.values[index]
        self.buttons[index].setChecked(True)
        if new!=self._value:self._value=new;self.valueChanged.emit(new)

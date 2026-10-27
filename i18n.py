"""RUS/EN display translations; identifiers, paths and render settings stay unchanged."""
import json,re,string,sys
from pathlib import Path
from PySide6.QtCore import QObject,QEvent,Qt
from PySide6.QtWidgets import (QApplication,QWidget,QLabel,QAbstractButton,QComboBox,
    QAbstractSpinBox,QLineEdit,QTreeWidget,QListWidget,QMenu,QGroupBox)

_data=json.loads((Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets/i18n.json').read_text(encoding='utf-8'))
EN=_data['en'];RUS=_data.get('rus',{})
_language='ru'
_filter=None
_formatter=string.Formatter()
_reverse={value:key for key,value in EN.items() if value!=key}
_reverse.update({value:key for key,value in RUS.items() if value!=key})


def _parts(template):
    try:return list(_formatter.parse(template))
    except ValueError:return []


def _pattern(template):
    parts=_parts(template)
    if not any(field is not None for _,field,_,_ in parts):return None
    if sum(len(literal) for literal,_,_,_ in parts)<3:return None
    pieces=[];seen=set()
    for literal,field,_,_ in parts:
        pieces.append(re.escape(literal))
        if field is not None:
            if not field.isdigit():return None
            name='f'+field
            pieces.append('(?P='+name+')' if name in seen else '(?P<'+name+'>.*?)');seen.add(name)
    return re.compile('^'+''.join(pieces)+'$',re.S)


_patterns=[]
for source,english in EN.items():
    for variant in set((source,english,RUS.get(source,source))):
        pattern=_pattern(variant)
        if pattern:_patterns.append((len(variant),pattern,source))
_patterns.sort(key=lambda item:item[0],reverse=True)


def language():return _language


def tr(text,_depth=0):
    if not isinstance(text,str) or not text:return text
    source=_reverse.get(text,text)
    if source in EN or source in RUS:return EN.get(source,source) if _language=='en' else RUS.get(source,source)
    if _depth<4:
        for _,pattern,key in _patterns:
            match=pattern.fullmatch(text)
            if match:
                target=EN[key] if _language=='en' else RUS.get(key,key)
                return ''.join(literal+(tr(match.group('f'+field),_depth+1) if field is not None else '')
                               for literal,field,_,_ in _parts(target))
        if '\n' in text:return '\n'.join(tr(line,_depth+1) for line in text.split('\n'))
    return text


def _set(obj,getter,setter):
    value=getter();translated=tr(value)
    if value!=translated:setter(translated)


def translate_widget(widget):
    if not isinstance(widget,QWidget):return
    for getter,setter in ((widget.toolTip,widget.setToolTip),(widget.statusTip,widget.setStatusTip),
                          (widget.accessibleName,widget.setAccessibleName),(widget.windowTitle,widget.setWindowTitle)):
        _set(widget,getter,setter)
    if isinstance(widget,(QLabel,QAbstractButton)):_set(widget,widget.text,widget.setText)
    if isinstance(widget,(QMenu,QGroupBox)):_set(widget,widget.title,widget.setTitle)
    if isinstance(widget,QLineEdit):_set(widget,widget.placeholderText,widget.setPlaceholderText)
    if isinstance(widget,QAbstractSpinBox) and hasattr(widget,'suffix'):
        _set(widget,widget.suffix,widget.setSuffix);_set(widget,widget.prefix,widget.setPrefix)
    if isinstance(widget,QComboBox):
        blocked=widget.blockSignals(True)
        try:
            for i in range(widget.count()):
                text=widget.itemText(i);value=tr(text)
                if text!=value:widget.setItemText(i,value)
                tip=widget.itemData(i,Qt.ToolTipRole)
                if isinstance(tip,str) and tr(tip)!=tip:widget.setItemData(i,tr(tip),Qt.ToolTipRole)
        finally:widget.blockSignals(blocked)
    if isinstance(widget,QTreeWidget):
        items=[widget.headerItem()]+[widget.topLevelItem(i) for i in range(widget.topLevelItemCount())]
        for item in items:
            for col in range(widget.columnCount()):
                if item is not widget.headerItem() and col==0:continue
                for getter,setter in ((item.text,item.setText),(item.toolTip,item.setToolTip)):
                    text=getter(col);value=tr(text)
                    if value!=text:setter(col,value)
    if isinstance(widget,QListWidget):
        for i in range(widget.count()):
            item=widget.item(i)
            _set(item,item.text,item.setText);_set(item,item.toolTip,item.setToolTip)
    if isinstance(widget,QMenu):
        for action in widget.actions():_set(action,action.text,action.setText)


def apply(app=None):
    app=app or QApplication.instance()
    if not app:return
    for top in app.topLevelWidgets():
        translate_widget(top)
        for widget in top.findChildren(QWidget):translate_widget(widget);QWidget.update(widget)
        QWidget.update(top)


class TranslationFilter(QObject):
    def eventFilter(self,obj,event):
        if isinstance(obj,QWidget) and event.type() in (QEvent.Show,QEvent.Paint,QEvent.ToolTip,QEvent.LayoutRequest):
            translate_widget(obj)
            if isinstance(obj.parentWidget(),QTreeWidget):translate_widget(obj.parentWidget())
        return False


def set_language(value,store=None,persist=True):
    global _language
    if value not in ('ru','en'):raise ValueError('Unsupported language')
    if persist:
        if store is None:
            from storage import STORE
            store=STORE
        store.save(language=value)
    _language=value
    apply()


def install(app):
    global _filter,_language
    if _filter is not None:return
    from storage import STORE
    _language=STORE.settings.get('language','ru')
    _filter=TranslationFilter(app);app.installEventFilter(_filter)

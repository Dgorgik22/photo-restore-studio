THEME = '''
QWidget { background:#272727; color:#dfdfdf; font-size:12px; }
QMainWindow { background:#202020; }
#toolbar { background:#303030; border-bottom:1px solid #151515; }
#brand { font-size:14px; font-weight:700; letter-spacing:1px; background:transparent; }
#heading { font-size:19px; font-weight:600; }
#documentBar { background:#242424; border-bottom:1px solid #111; }
#sidebar { background:#2c2c2c; }
#sideScroll { border:0; border-left:1px solid #151515; }
#muted { color:#999; background:transparent; font-size:11px; }
#sectionTitle { font-size:11px; font-weight:600; color:#bfbfbf; letter-spacing:1px; }
#toolSection,#toolSectionBody,#sliderControls { background:transparent; }
#sectionToggle { background:transparent; border:0; padding:4px 2px; text-align:left; }
#sectionToggle:hover { background:#363636; }
QLabel { background:transparent; }
#outputCard { background:#222222; border:1px solid #343434; border-radius:5px; }
#outputTitle { color:#ededed; font-size:13px; font-weight:600; border:0; }
#outputCaption { color:#9da5ac; font-size:11px; border:0; }
#scaleStrip,#levelStrip { background:#191919; border:0; border-radius:4px; }
#levelPreset { background:transparent; border:0; border-radius:3px; color:#a1a7ad; padding:8px 3px; }
#levelPreset:hover { background:#303030; color:#fff; }
#levelPreset:checked { background:#414141; color:#fff; }
#scalePreset { background:transparent; border:0; border-radius:3px; color:#90979d; padding:6px 4px; }
#scalePreset:hover { background:#303030; color:#efefef; }
#scalePreset:checked { background:#414141; color:#ffffff; font-weight:600; }
#outputField { background:#191919; border:0; border-radius:3px; }
#outputField QSpinBox,#outputField QDoubleSpinBox,#outputField QComboBox { background:transparent; color:#dce9f3; border:0; padding:7px 2px; min-width:50px; }
#outputField QSpinBox:disabled { color:#666; }
#sliderValue { color:#eeeeee; font-size:11px; background:transparent; min-width:30px; }
QRadioButton { spacing:7px; }
QRadioButton::indicator { width:13px; height:13px; border:1px solid #929292; background:#252525; border-radius:7px; }
QRadioButton::indicator:checked { background:#c7dfef; border:3px solid #527c9a; }

QPushButton,QToolButton { background:#3b3b3b; border:1px solid #505050; border-radius:4px; padding:7px 12px; }
QPushButton:hover,QToolButton:hover { background:#484848; border-color:#6a6a6a; }
QPushButton:disabled { color:#737373; background:#333; border-color:#3e3e3e; }
#primary { background:#1473e6; color:white; border-color:#1473e6; font-weight:600; }
#primary:hover { background:#2684ef; }
#primary:disabled { background:#354254; color:#8d9bac; border-color:#354254; }
#quiet { border:0; background:transparent; padding:3px 6px; font-size:11px; }
#canvasTool { background:#303030; border:1px solid #505050; padding:4px; }
#canvasTool::menu-indicator { image:none; }
#canvasHint { color:#747474; background:#202020; font-size:10px; }
QListWidget { background:#252525; border:1px solid #404040; outline:0; }
#presets::item { padding:6px 9px; color:#bababa; border-left:3px solid transparent; }
#presets::item:hover { background:#353535; }
#presets::item:selected { background:#354453; border-left:3px solid #60a4ee; color:#fff; }
#fileTable { background:#242424; border:0; border-top:1px solid #151515; outline:0; }
#fileTable::item { border-bottom:1px solid #343434; padding:0 6px; }
#fileTable::item:hover { background:#303030; }
#fileTable::item:selected { background:#303d4a; color:#e4e9ee; }
#fileTable QHeaderView::section { background:#222; color:#999; border:0; border-bottom:1px solid #353535; padding:4px 6px; font-size:11px; }
#selectAllFiles { background:#222; color:#999; font-size:11px; }
#closeFile { background:transparent; border:0; padding:2px; }
#closeFile:hover { background:#505050; }
#modelInfoCard { background:#343434; border:1px solid #606060; border-radius:5px; }
#modelInfoCard QLabel { background:transparent; border:0; }
#modelInfoTitle { font-weight:600; color:#f1f1f1; }
QComboBox { background:#232323; border:1px solid #484848; border-radius:3px; padding:6px; min-height:18px; }
QSpinBox { background:#232323; border:1px solid #484848; border-radius:3px; padding:6px; min-height:18px; }
QSpinBox::up-button,QSpinBox::down-button { width:16px; background:#3b3b3b; border:0; }
QComboBox QAbstractItemView { background:#303030; selection-background-color:#345b87; }
QSlider { min-height:24px; max-height:24px; }
QSlider::groove:horizontal { height:3px; background:#181818; border-radius:1px; }
QSlider::sub-page:horizontal { background:#8a8a8a; margin:6px 0; }
QSlider::handle:horizontal { background:#d1d1d1; width:10px; margin:-4px 0; border-radius:5px; }
QSlider:disabled::handle:horizontal { background:#666; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:13px; height:13px; border:1px solid #777; background:#252525; border-radius:2px; }
QCheckBox::indicator:checked { background:#5598e5; border-color:#72b1fa; }
#separator { color:#414141; background:#414141; max-height:1px; border:0; }
#footer { background:#262626; }
QProgressBar { border:0; background:#242424; }
QProgressBar::chunk { background:#6193c7; }
#error { color:#e4a197; font-size:11px; }
QScrollBar:vertical { background:#252525; width:7px; margin:0; }
QScrollBar::handle:vertical { background:#555; min-height:25px; border-radius:3px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { background:#252525; height:7px; margin:0; }
QScrollBar::handle:horizontal { background:#555; min-width:25px; }
QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
QMenu { background:#333; border:1px solid #555; padding:4px; }
QMenu::item { padding:7px 18px; }
QMenu::item:selected { background:#3a608b; }
QToolTip { background:#414141; color:white; border:1px solid #666; padding:5px; }
'''

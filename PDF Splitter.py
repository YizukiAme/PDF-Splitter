import os, sys, webbrowser, ctypes
from PySide6 import QtCore, QtGui, QtWidgets
from pypdf import PdfReader, PdfWriter
from ctypes import wintypes

APP_TITLE = "PDF Splitter Pro"
DEFAULT_OUT = r"D:\UserData\Downloads" if os.path.isdir(r"D:\UserData\Downloads") else os.path.join(os.path.expanduser("~"), "Downloads")

# ---- helpers for light-theme contrast and button CSS ----
def set_dark_title_bar(window_handle: int):
    """
    Enable dark title bar for a given window on Windows 11 (and some Win10 builds).
    """
    if sys.platform != "win32":
        return  # Non‑Windows: do nothing

    try:
        # Load dwmapi.dll
        dwmapi = ctypes.WinDLL("dwmapi")
        
        # DWMWINDOWATTRIBUTE.DWMWA_USE_IMMERSIVE_DARK_MODE
        # Windows 11 SDK uses 20 (older Win10 SDKs used 19)
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        
        value = wintypes.BOOL(True)  # True to enable dark mode
        
        # Call DwmSetWindowAttribute
        # params: hwnd, attribute id, pointer to value, size of value
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(window_handle),
            wintypes.UINT(DWMWA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(value),
            ctypes.sizeof(value)
        )
    except Exception as e:
        # On unsupported systems (e.g., Win7 or early Win10), this may fail
        print(f"Failed to set dark title bar: {e}")

def _luminance(hexc):
    c = hexc.lstrip("#")
    r = int(c[0:2],16)/255.0
    g = int(c[2:4],16)/255.0
    b = int(c[4:6],16)/255.0
    def srgb(v):
        return v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4
    return 0.2126*srgb(r)+0.7152*srgb(g)+0.0722*srgb(b)

def ensure_contrast_on_light(accent: str, bg: str="#ffffff"):
    try:
        la = _luminance(accent); lb = _luminance(bg)
    except Exception:
        return accent
    if la > 0.7 and lb > 0.8:
        c = accent.lstrip("#")
        r = int(c[0:2],16); g = int(c[2:4],16); b = int(c[4:6],16)
        r = int(r*0.65); g = int(g*0.65); b = int(b*0.65)
        return f"#{r:02x}{g:02x}{b:02x}"
    return accent

def btn_css(accent):
    return (
        "QPushButton{background:%s; color:#ffffff; border:none; border-radius:12px; padding:10px 18px;}"
        "QPushButton:hover{opacity:0.96;}"
        "QPushButton:pressed{opacity:0.88;}"
    ) % accent

def win_system_accent_hex(default="#2f6bff"):
    try:
        color = ctypes.c_uint(); opaque = ctypes.c_bool()
        ctypes.windll.dwmapi.DwmGetColorizationColor(ctypes.byref(color), ctypes.byref(opaque))
        argb = color.value; r = (argb >> 16) & 0xFF; g = (argb >> 8) & 0xFF; b = argb & 0xFF
        return "#{:02x}{:02x}{:02x}".format(r,g,b)
    except Exception:
        return default

# ---------- parsing ----------

def _to_int(s):
    try: return int(s)
    except Exception: return None

def _norm_neg(i, total):
    if i is None: return None
    return total + 1 + i if i < 0 else i

def parse_ranges(tokens, total):
    """
    Parse range expressions like:
      - "3-5 8..9"
      - "odd" or "even"
      - "-5--3" etc., negative indices allowed and count from the end.
    Returns a list of merged [start, end] 1-based inclusive tuples.
    """
    low = [t.lower().strip() for t in tokens if t.strip()]
    if len(low) == 1 and low[0] in ("odd", "even"):
        return [(i, i) for i in range(1, total + 1) if (i % 2 == 1) == (low[0] == "odd")]
    ranges = []
    for t in low:
        if ".." in t: a, b = t.split("..", 1)
        elif "-" in t: a, b = t.split("-", 1)
        else: a = b = t
        a = a.strip(); b = b.strip()
        if a.lstrip("-").isdigit() and b.lstrip("-").isdigit():
            ia = _norm_neg(int(a), total); ib = _norm_neg(int(b), total)
            ia, ib = sorted([ia, ib])
            if ia < 1 or ib > total: raise ValueError(f"Range {t} is out of bounds 1..{total}")
            ranges.append((ia, ib))
        else:
            raise ValueError(f"Invalid range: {t}")
    ranges.sort()
    merged = []
    for st, ed in ranges:
        if not merged or st > merged[-1][1] + 1: merged.append([st, ed])
        else: merged[-1][1] = max(merged[-1][1], ed)
    return [(a, b) for a, b in merged]

def parse_cutpoints(tokens, total):
    """
    Parse a list of cutpoints (1-based) and return a sorted unique list.
    """
    pts = []
    for t in tokens:
        if not t.isdigit(): raise ValueError(f"Invalid cutpoint: {t}")
        v = int(t)
        if v <= 0 or v >= total: raise ValueError(f"Cutpoint {v} is out of bounds 1..{total-1}")
        pts.append(v)
    return sorted(set(pts))

def seg_from_cutpoints(cps, total):
    """
    Turn cutpoints into segments represented as (start, end) 1-based inclusive.
    """
    segs = []; prev = 1
    for p in cps: segs.append((prev, p)); prev = p + 1
    segs.append((prev, total)); return segs

def parse_smart(s, total):
    """
    Smart parser:
    - If two numbers are provided, treat them as two cutpoints and extract the between-range (exclusive).
    - If ranges like "a-b" or ".." or "odd/even" are present, parse as ranges.
    - Else treat input as a list of cutpoints.
    - Empty input -> full 1..total.
    """
    s = s.strip()
    if not s: return ("ranges", [(1, total)])
    toks = [t for t in s.replace(",", " ").replace(";", " ").split() if t]
    low = [t.lower() for t in toks]
    if all(t.lstrip("-").isdigit() for t in low) and len(low) == 2:
        a = _norm_neg(_to_int(low[0]), total); b = _norm_neg(_to_int(low[1]), total)
        a, b = sorted([a, b])
        if a == b: raise ValueError("The two cutpoints cannot be the same")
        if a + 1 > b: raise ValueError("No pages between the two cutpoints")
        return ("ranges", [(a + 1, b)])
    if any(("-" in t or ".." in t) for t in low) or (len(low) == 1 and low[0] in ("odd","even")):
        return ("ranges", parse_ranges(low, total))
    return ("cutpoints", parse_cutpoints(low, total))

def write_segments(pdf_path, segments, out_dir, naming, merge_single=False):
    """
    Write segments to disk as separate PDFs, or a single merged PDF if merge_single=True.
    """
    reader = PdfReader(pdf_path)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    saved = []
    if merge_single:
        writer = PdfWriter()
        for a, b in segments:
            for p in range(a - 1, b):
                writer.add_page(reader.pages[p])
        outp = os.path.join(out_dir, naming.format(base=base, mode="merge", idx=1, start=segments[0][0], end=segments[-1][1]))
        with open(outp, "wb") as f: writer.write(f)
        saved.append(outp); return saved
    for idx, (a, b) in enumerate(segments, 1):
        writer = PdfWriter()
        for p in range(a - 1, b):
            writer.add_page(reader.pages[p])
        outp = os.path.join(out_dir, naming.format(base=base, mode="range", idx=idx, start=a, end=b))
        with open(outp, "wb") as f: writer.write(f)
        saved.append(outp)
    return saved

# ---------- theming ----------

def build_qss(dark: bool, accent: str) -> str:
    BG = "#0f1115" if dark else "#f6f7f9"
    TEXT = "#e8ecf2" if dark else "#1c1f26"
    CTRL_BG = "#181c23" if dark else "#ffffff"
    return f"""
* {{ font-family: "Segoe UI", "Segoe UI Variable", "Arial"; }}
QWidget {{ background: {BG}; color: {TEXT}; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QLineEdit, QComboBox {{
  background: {CTRL_BG}; border: none; border-radius: 14px; padding: 12px 14px; color: {TEXT};
}}
QListWidget {{
  background: {CTRL_BG}; border: none; border-radius: 16px; padding: 10px; color: {TEXT};
}}
QPushButton {{
  background: {accent}; color: #ffffff; border: none; border-radius: 12px; padding: 10px 18px;
}}
QPushButton:disabled {{ background: rgba(127,127,127,0.35); }}
QProgressBar {{ background: {'#1a2230' if dark else '#e7edf5'}; border-radius: 9px; height: 16px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 9px; }}
QScrollBar:vertical, QScrollBar:horizontal {{ width:0px; height:0px; background: transparent; }}
Segmented, ToggleSwitch {{ background: transparent; }}
"""

# ---------- widgets ----------

class Card(QtWidgets.QFrame):
    def __init__(self, title=None):
        super().__init__()
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.radius = 18
        self.bg = QtGui.QColor("#ffffff")
        self.shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(28); self.shadow.setOffset(0, 10); self.shadow.setColor(QtGui.QColor(0,0,0,36))
        self.setGraphicsEffect(self.shadow)
        self.v = QtWidgets.QVBoxLayout(self); self.v.setContentsMargins(20,18,20,18); self.v.setSpacing(12)
        if title:
            lab = QtWidgets.QLabel(title); f = lab.font(); f.setPointSize(f.pointSize()+3); f.setWeight(QtGui.QFont.DemiBold); lab.setFont(f)
            self.v.addWidget(lab)

    def setCardColor(self, c): self.bg = QtGui.QColor(c); self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r = self.rect().adjusted(1,1,-1,-1)
        path = QtGui.QPainterPath(); path.addRoundedRect(r, self.radius, self.radius)
        p.fillPath(path, self.bg)

class ToggleSwitch(QtWidgets.QCheckBox):
    toggledVisual = QtCore.Signal(bool)
    def __init__(self, text="", parent=None, accent="#2f6bff"):
        super().__init__(text, parent)
        self._accent = accent
        self._anim = QtCore.QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=160)
        self._anim.valueChanged.connect(self.update)
        self.stateChanged.connect(self._on_state)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

    def setAccent(self, c): self._accent = c; self.update()

    def _on_state(self, _):
        self._anim.setDirection(QtCore.QAbstractAnimation.Forward if self.isChecked() else QtCore.QAbstractAnimation.Backward)
        self._anim.start(); self.toggledVisual.emit(self.isChecked())

    def sizeHint(self):
        base = super().sizeHint(); return QtCore.QSize(max(62, base.width()), max(32, base.height()))

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.setChecked(not self.isChecked()); e.accept()
        else:
            super().mouseReleaseEvent(e)

    def paintEvent(self, event):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.rect()
        sw, sh = 56, 30
        switch_rect = QtCore.QRect(rect.right()-sw, rect.center().y()-sh//2, sw, sh)
        text_rect = QtCore.QRect(rect.left(), rect.top(), rect.width()-sw-8, rect.height())
        progress = self._anim.currentValue() if self._anim.state()==QtCore.QAbstractAnimation.Running else (1.0 if self.isChecked() else 0.0)
        is_dark = self.palette().color(QtGui.QPalette.Window).value() < 128
        track_on = QtGui.QColor(self._accent)
        track_off = QtGui.QColor(35,41,50) if is_dark else QtGui.QColor(225,229,236)
        path = QtGui.QPainterPath(); path.addRoundedRect(QtCore.QRectF(switch_rect), sh/2, sh/2)
        bg = QtGui.QColor(track_off); bg.setAlpha(240 - int(160*progress)); p.fillPath(path, bg)
        active = QtGui.QColor(track_on); active.setAlpha(int(255*progress)); p.fillPath(path, active)
        x = switch_rect.left() + 3 + int(progress * (sw - sh))
        knob_rect = QtCore.QRect(x, switch_rect.top()+3, sh-6, sh-6)
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor("#ffffff")); p.drawEllipse(knob_rect)
        p.setPen(self.palette().color(QtGui.QPalette.Text)); p.drawText(text_rect.adjusted(0,0,-6,0), QtCore.Qt.AlignVCenter|QtCore.Qt.AlignLeft, self.text())

class Segmented(QtWidgets.QWidget):
    changed = QtCore.Signal(str)
    def __init__(self, items, accent="#2f6bff"):
        super().__init__()
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self._items = items; self._idx = 0; self._accent = accent
        self._rects = []
        self._pill = QtCore.QRect()
        self._pillPos = QtCore.QPoint(0,0)
        self._anim = QtCore.QPropertyAnimation(self, b"pillPos", duration=180, easingCurve=QtCore.QEasingCurve.OutCubic)

    def sizeHint(self): return QtCore.QSize(320, 46)

    def setAccent(self, c): self._accent = c; self.update()

    @QtCore.Property(QtCore.QPoint)
    def pillPos(self): return self._pillPos

    @pillPos.setter
    def pillPos(self, pt):
        self._pillPos = pt; self.update()

    def resizeEvent(self, e): self._layout_rects()

    def _layout_rects(self):
        fm = QtGui.QFontMetrics(self.font())
        pad_x = 18; h = 40; spacing = 6
        x = 6; y = (self.height()-h)//2
        rects = []
        for s in self._items:
            w = fm.horizontalAdvance(s) + pad_x*2
            rects.append(QtCore.QRect(x, y, w, h))
            x += w + spacing
        self._rects = rects
        if rects:
            self._pill = rects[self._idx].adjusted(-2,-2,2,2)
            self._pillPos = self._pill.topLeft()

    def paintEvent(self, e):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        if self._rects:
            left = self._rects[0].left()-4; right = self._rects[-1].right()+4
        else:
            left, right = 0, self.width()
        bg_rect = QtCore.QRect(left, (self.height()-44)//2, right-left, 44)
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(127,127,127,31)); p.drawRoundedRect(bg_rect, 22, 22)
        pr = QtCore.QRect(self._pillPos, self._pill.size())
        p.setBrush(QtGui.QColor(self._accent)); p.drawRoundedRect(pr, 20, 20)
        for i, r in enumerate(self._rects):
            p.setPen(QtGui.QColor("#ffffff") if i==self._idx else self.palette().color(QtGui.QPalette.Text))
            p.drawText(r, self._items[i], QtCore.Qt.AlignCenter)

    def mousePressEvent(self, e):
        pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
        for i, r in enumerate(self._rects):
            if r.contains(pos): self.setCurrent(i); break

    def currentText(self): return self._items[self._idx]

    def setCurrent(self, idx):
        if not self._rects: self._idx = idx; return
        self._idx = idx
        target = self._rects[idx].adjusted(-2,-2,2,2)
        self._anim.stop(); self._anim.setStartValue(self._pillPos); self._anim.setEndValue(target.topLeft()); self._anim.start()
        self._pill = target; self.changed.emit(self._items[idx]); self.update()

class DropList(QtWidgets.QListWidget):
    requestOpen = QtCore.Signal()
    def __init__(self, accent="#2f6bff"):
        super().__init__(); self.setAcceptDrops(True)
        self._drag = 0.0; self._anim = QtCore.QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=160); self._anim.valueChanged.connect(self._on_anim)
        self._accent = accent

    def setAccent(self, c): self._accent = c; self.viewport().update()

    def _on_anim(self, v): self._drag = v; self.viewport().update()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction(); self._anim.setDirection(QtCore.QAbstractAnimation.Forward); self._anim.start()

    def dragLeaveEvent(self, e):
        self._anim.setDirection(QtCore.QAbstractAnimation.Backward); self._anim.start()

    def dropEvent(self, e):
        self._anim.setDirection(QtCore.QAbstractAnimation.Backward); self._anim.start()
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".pdf") and os.path.isfile(p): self.addItem(p)

    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            inner = self.viewport().rect().adjusted(16,16,-16,-16)
            if inner.contains(ev.position().toPoint() if hasattr(ev, "position") else ev.pos()):
                self.requestOpen.emit(); ev.accept(); return
        super().mousePressEvent(ev)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self.count() > 0: return
        p = QtGui.QPainter(self.viewport()); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.viewport().rect().adjusted(16,16,-16,-16)
        pen = QtGui.QPen(QtGui.QColor(0,0,0,40) if self.palette().color(QtGui.QPalette.Window).value()>128 else QtGui.QColor(255,255,255,38))
        pen.setStyle(QtCore.Qt.DashLine); pen.setWidth(2)
        p.setPen(pen); p.setBrush(QtCore.Qt.NoBrush); p.drawRoundedRect(rect, 16, 16)
        center = rect.center()
        scale = 1.0 + 0.04*self._drag
        p.save(); p.translate(center); p.scale(scale, scale); p.translate(-center)
        file_rect = QtCore.QRectF(center.x()-20, center.y()-30, 40, 40)
        path = QtGui.QPainterPath(); path.addRoundedRect(file_rect, 8, 8)
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(240,243,248) if self.palette().color(QtGui.QPalette.Window).value()>128 else QtGui.QColor(255,255,255,210))
        p.drawPath(path)
        pen2 = QtGui.QPen(QtGui.QColor(self._accent)); pen2.setWidth(4); pen2.setCapStyle(QtCore.Qt.RoundCap); pen2.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(pen2)
        p.drawLine(center.x(), center.y()-18, center.x(), center.y()-2)
        p.drawLine(center.x(), center.y()-2, center.x()-7, center.y()-10)
        p.drawLine(center.x(), center.y()-2, center.x()+7, center.y()-10)
        p.restore()
        text = "Drop PDFs here (or click to choose)"
        fm = QtGui.QFontMetrics(self.font())
        tw = fm.horizontalAdvance(text)
        tx = center.x() - tw//2
        ty = center.y() + 18 + fm.ascent()
        p.setPen(self.palette().color(QtGui.QPalette.Mid))
        p.drawText(QtCore.QPoint(tx, ty), text)

class Toast(QtWidgets.QWidget):
    """Bottom-right stacked toasts, auto-dismiss, fade in/out, non-blocking."""
    def __init__(self, parent=None, margin=24):
        super().__init__(None)
        self._parent = parent
        self._margin = margin
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.NoDropShadowWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.v = QtWidgets.QVBoxLayout(self); self.v.setSpacing(10); self.v.setContentsMargins(12,12,12,12)
        self._items = []
        self.hide()
        self._reposition()

    def _screen_geo(self):
        if self._parent is not None:
            screen = self._parent.windowHandle().screen() if self._parent.windowHandle() else QtGui.QGuiApplication.primaryScreen()
        else:
            screen = QtGui.QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _reposition(self):
        g = self._screen_geo()
        width = 360
        height = sum(w.sizeHint().height()+10 for w in self._items) + 24
        if height < 80: height = 80
        x = g.right() - self._margin - width
        y = g.bottom() - self._margin - height
        self.setGeometry(x, y, width, height)

    def push(self, text, accent="#2f6bff", timeout_ms=1600):
        w = QtWidgets.QFrame(); w.setStyleSheet("QFrame{background: rgba(20,20,24,230); color: white; border-radius: 10px;} QLabel{background:transparent;}")
        l = QtWidgets.QHBoxLayout(w); l.setContentsMargins(12,8,12,8)
        dot = QtWidgets.QLabel(); dot.setFixedSize(10,10); dot.setStyleSheet(f"background:{accent}; border-radius:5px;")
        lab = QtWidgets.QLabel(text); lab.setWordWrap(True)
        l.addWidget(dot); l.addSpacing(8); l.addWidget(lab)
        self._items.append(w); self.v.addWidget(w, 0, QtCore.Qt.AlignRight)
        self._reposition(); self.show()
        eff = QtWidgets.QGraphicsOpacityEffect(w); w.setGraphicsEffect(eff); eff.setOpacity(0.0)
        a1 = QtCore.QPropertyAnimation(eff, b"opacity"); a1.setStartValue(0.0); a1.setEndValue(1.0); a1.setDuration(180)
        a1.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        QtCore.QTimer.singleShot(timeout_ms, lambda w=w: self._pop(w))

    def _pop(self, w):
        if w not in self._items: return
        eff = w.graphicsEffect()
        if eff is None:
            self._remove_item(w); return
        a = QtCore.QPropertyAnimation(eff, b"opacity"); a.setStartValue(1.0); a.setEndValue(0.0); a.setDuration(220)
        def after():
            self._remove_item(w)
        a.finished.connect(after); a.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

    def _remove_item(self, w):
        try:
            self._items.remove(w)
        except ValueError:
            pass
        w.setParent(None); w.deleteLater()
        if not self._items:
            self.hide()
        self._reposition()

def resource_path(relative_path):
    """Get the absolute path to a resource. Works in dev and PyInstaller."""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Robust path for development
        base_path = os.path.dirname(os.path.abspath(__file__))  # <-- dev path
    return os.path.join(base_path, relative_path)

# ---------- main window ----------

class Main(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QtGui.QIcon(resource_path("icon.ico")))
        self.resize(1320, 900)
        
        # Use a modern English font instead of DengXian
        f = QtGui.QFont("Segoe UI", 12); f.setHintingPreference(QtGui.QFont.PreferFullHinting); f.setStyleStrategy(QtGui.QFont.PreferAntialias)
        QtWidgets.QApplication.instance().setFont(f); self.setFont(f)

        self.dark = True
        self.accent = win_system_accent_hex("#2f6bff")
        self.setStyleSheet(build_qss(self.dark, self.accent))
        # Grab window handle and set initial title bar color
        self.window_handle = self.winId()
        set_dark_title_bar(self.window_handle)

        # Top card
        self.topCard = Card()
        bar = QtWidgets.QHBoxLayout(); bar.setContentsMargins(20,14,20,14)
        title = QtWidgets.QLabel(APP_TITLE); tf = title.font(); tf.setPointSize(tf.pointSize()+6); tf.setWeight(QtGui.QFont.Bold); title.setFont(tf)
        self.themeToggle = ToggleSwitch("Light", accent=self.accent); self.themeToggle.setChecked(False); self.themeToggle.toggledVisual.connect(self.onThemeToggle)
        bar.addWidget(title); bar.addStretch(1); bar.addWidget(QtWidgets.QLabel("Theme")); bar.addWidget(self.themeToggle)
        self.topCard.v.addLayout(bar)

        # Scroll content
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        content = QtWidgets.QWidget(); scroll.setWidget(content)
        grid = QtWidgets.QGridLayout(content); grid.setContentsMargins(16,16,16,16); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(12)

        # Files / rules
        self.cardMain = Card("Files / Rules")
        v = QtWidgets.QVBoxLayout(); v.setSpacing(12)
        hb = QtWidgets.QHBoxLayout(); self.btnAdd = QtWidgets.QPushButton("Add PDFs"); self.btnClear = QtWidgets.QPushButton("Clear")
        self.btnAdd.setMinimumHeight(40); self.btnClear.setMinimumHeight(40); hb.addWidget(self.btnAdd); hb.addWidget(self.btnClear); hb.addStretch(1)
        v.addLayout(hb)
        self.list = DropList(self.accent); self.list.setMinimumHeight(420); v.addWidget(self.list, 1)
        row2 = QtWidgets.QHBoxLayout()
        self.seg = Segmented(["smart","ranges","cutpoints"], accent=self.accent)
        self.rules = QtWidgets.QLineEdit(); self.rules.setPlaceholderText("2 4 | 3-5 8..9 | odd | 2 4 6")
        self.sample = QtWidgets.QPushButton("Sample")  # unified button style
        self.sample.setMinimumHeight(40)
        row2.addWidget(self.seg, 0); row2.addWidget(self.rules, 1); row2.addWidget(self.sample, 0)
        v.addLayout(row2)
        self.cardMain.v.addLayout(v)

        # Output settings
        self.cardOut = Card("Output Settings")
        form = QtWidgets.QFormLayout(); form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.outDir = QtWidgets.QLineEdit(DEFAULT_OUT)
        self.browse = QtWidgets.QPushButton("Browse"); self.browse.setMinimumHeight(40)
        rowOut = QtWidgets.QHBoxLayout(); rowOut.addWidget(self.outDir, 1); rowOut.addWidget(self.browse)
        self.naming = QtWidgets.QLineEdit("{base}_part{idx:02d}_p{start}-{end}.pdf")
        self.merge = ToggleSwitch("Merge all segments into a single PDF", accent=self.accent)
        self.openFolder = ToggleSwitch("Open output folder when finished", accent=self.accent)
        self.openNotebook = ToggleSwitch("Open NotebookLM when finished", accent=self.accent)
        form.addRow("Output folder", rowOut); form.addRow("Filename template", self.naming)
        self.cardOut.v.addLayout(form)
        toggles = QtWidgets.QVBoxLayout(); toggles.addWidget(self.merge); toggles.addWidget(self.openFolder); toggles.addWidget(self.openNotebook)
        self.cardOut.v.addLayout(toggles)

        grid.addWidget(self.cardMain, 0, 0, 1, 1)
        grid.addWidget(self.cardOut, 1, 0, 1, 1)

        # Action bar
        self.cardBottom = Card()
        bl = QtWidgets.QHBoxLayout(); bl.setContentsMargins(20,12,20,12)
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0,100); self.progress.setValue(0); self.progress.setTextVisible(False)
        self.go = QtWidgets.QPushButton("Start"); self.go.setMinimumHeight(42)
        bl.addWidget(self.progress, 1); bl.addWidget(self.go)
        self.cardBottom.v.addLayout(bl)
        grid.addWidget(self.cardBottom, 2, 0, 1, 1)

        # Root layout
        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central); root.setContentsMargins(16,16,16,16); root.setSpacing(12)
        root.addWidget(self.topCard); root.addWidget(scroll, 1)

        # Toast
        self.toast = Toast(self)

        # Signals
        self.btnAdd.clicked.connect(self.addFiles); self.btnClear.clicked.connect(self.list.clear)
        self.browse.clicked.connect(self.chooseDir); self.sample.clicked.connect(self.fillExample); self.go.clicked.connect(self.run)
        self.list.requestOpen.connect(self.addFiles)

        self._apply_card_bg()
        self._style_buttons()

    def _style_buttons(self):
        accent = ensure_contrast_on_light(self.accent, "#ffffff" if not self.dark else "#0f1115")
        css = btn_css(accent)
        for b in (self.btnAdd, self.btnClear, self.browse, self.go, self.sample):
            b.setStyleSheet(css)

    def _apply_card_bg(self):
        card_bg = "#14181e" if self.dark else "#ffffff"
        for c in (self.topCard, self.cardMain, self.cardOut, self.cardBottom):
            c.setCardColor(card_bg)

    def onThemeToggle(self, light_on: bool):
        self.dark = not light_on
        self.setStyleSheet(build_qss(self.dark, self.accent))
        self._apply_card_bg()
        for w in (self.themeToggle, self.merge, self.openFolder, self.openNotebook): w.setAccent(self.accent)
        self.seg.setAccent(self.accent); self.list.setAccent(self.accent)
        self._style_buttons()
        if self.dark:
            set_dark_title_bar(self.window_handle)
        else:
            # On some Windows versions passing False to disable may not work reliably.
            # For simplicity we only ensure dark mode looks correct.
            pass

    # ----- actions -----
    def addFiles(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Choose PDF files", "", "PDF (*.pdf)")
        for p in paths:
            if p and p.lower().endswith(".pdf"): self.list.addItem(p)

    def chooseDir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder", self.outDir.text())
        if d: self.outDir.setText(d)

    def fillExample(self):
        preset = {"smart":"2 4","ranges":"3-5 8..9","cutpoints":"2 4 6"}
        self.rules.setText(preset.get(self.seg.currentText(), "2 4"))

    def run(self):
        if self.list.count() == 0:
            self.toast.push("Add at least one PDF first", self.accent); return
        out = self.outDir.text().strip()
        if not out:
            self.toast.push("Output folder cannot be empty", self.accent); return
        os.makedirs(out, exist_ok=True)
        s = self.rules.text().strip()
        self.progress.setValue(0); step = 100 // max(1, self.list.count())
        for i in range(self.list.count()):
            path = self.list.item(i).text()
            try:
                total = len(PdfReader(path).pages)
                mode = self.seg.currentText()
                if mode=="smart":
                    kind, data = parse_smart(s, total)
                elif mode=="ranges":
                    tokens = [t for t in s.replace(",", " ").replace(";", " ").split() if t]
                    kind, data = "ranges", (parse_ranges(tokens, total) if tokens else [(1, total)])
                else:
                    tokens = [t for t in s.replace(",", " ").replace(";", " ").split() if t]
                    kind, data = "cutpoints", (parse_cutpoints(tokens, total) if tokens else [])
                segs = data if kind == "ranges" else seg_from_cutpoints(data, total)
                outs = write_segments(path, segs, out, "{base}_part{idx:02d}_p{start}-{end}.pdf", merge_single=self.merge.isChecked())
                self.toast.push(f"Done: {os.path.basename(path)} ({len(outs)} segments)", self.accent)
            except Exception as e:
                self.toast.push(f"Failed: {os.path.basename(path)} — {e}", self.accent)
            self.progress.setValue(min(100, self.progress.value() + step)); QtWidgets.QApplication.processEvents()

        if self.openFolder.isChecked(): QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(out))
        if self.openNotebook.isChecked():
            try: webbrowser.open("https://notebooklm.google.com/", new=2)
            except Exception: pass

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    w = Main(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

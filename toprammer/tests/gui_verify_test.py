"""Headless test: a failed verify highlights the differing bytes in the hex
view, and hovering one shows chip/buffer values in hex and binary.

usage: python tests/gui_verify_test.py <toprammer dir> [screenshot.png]"""
import os, sys, random, importlib.machinery, importlib.util
os.environ["QT_QPA_PLATFORM"] = "offscreen"
top = sys.argv[1]; shot = sys.argv[2] if len(sys.argv) > 2 else None
sys.path.insert(0, top)
loader = importlib.machinery.SourceFileLoader("tgui", os.path.join(top, "toprammer-gui"))
spec = importlib.util.spec_from_loader("tgui", loader); g = importlib.util.module_from_spec(spec)
sys.argv = ["toprammer-gui"]; loader.exec_module(g)
from PyQt6.QtWidgets import QApplication, QWidget, QToolTip
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtCore import QEvent, QPoint
from libtoprammer.chip import ChipDescription
app = QApplication.instance() or QApplication([])

class FakeConsole:
    def __init__(self): self.msgs = []
    def showMessage(self, m, bold=False): self.msgs.append(m)
    def setStatus(self, s): pass
class FakeMain(QWidget):
    def __init__(self):
        QWidget.__init__(self); self.currentChipDescription = None; self.console = FakeConsole()

mw = FakeMain()
tabs = g.BufferTabWidget(mw)
mw.currentChipDescription = ChipDescription.findOne("mh74s571")
tabs.setupBuffers(g.Chip.SUPPORT_EEPROMREAD)
eb = tabs.eepromBuffer
hexw = eb.browser.widget()

random.seed(1)
buf = bytes(random.randint(0, 15) for _ in range(512))
chip = bytearray(buf)
chip[0x003] ^= 0x01          # one bit
chip[0x011] ^= 0x0A          # two bits
chip[0x1FF] ^= 0x08
eb.loadImage(buf)

# 1. matching chip: no marks
assert tabs.verifyBuffers({"eeprom": buf})
assert hexw.mismatches == []

# 2. mismatch: three bytes marked, console names them, tab switched
assert not tabs.verifyBuffers({"eeprom": bytes(chip)})
assert hexw.mismatches == [0x003, 0x011, 0x1FF], hexw.mismatches
msg = mw.console.msgs[-1]
assert "3 bytes differ (0x3, 0x11, 0x1FF)" in msg, msg
assert tabs.currentWidget() is eb
print("console:", msg.strip())

# 3. tooltip over byte 0x11 (line 1, column 1) in the hex column, and over the ASCII column
class TipRecorder:
    text = ""
    @classmethod
    def showText(cls, pos, text, w=None): cls.text = text
    @classmethod
    def hideText(cls): cls.text = ""
g.QToolTip = TipRecorder     # the GUI module looks QToolTip up at call time
def tipAt(x, y):
    TipRecorder.text = ""
    ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(int(x), int(y)), hexw.mapToGlobal(QPoint(int(x), int(y))))
    hexw.event(ev)
    return TipRecorder.text
cw, ch = hexw.charWidth, hexw.charHeight
t = tipAt(cw * (13 + 3 * 1) + cw, 3 + ch * 1 + ch / 2)
assert "Address 0x11" in t and "Chip:</td><td>0x%02X" % chip[0x11] in t and "Buffer:</td><td>0x%02X" % buf[0x11] in t, t
assert "Differing bits: D1, D3" in t, t
t2 = tipAt(cw * (13 + 3 * 16 + 2 + 1) + cw / 2, 3 + ch * 1 + ch / 2)
assert "Address 0x11" in t2, t2
assert tipAt(cw * (13 + 3 * 2) + cw, 3 + ch / 2) == "", "tooltip on a matching byte"
print("tooltip over 0x11 OK (hex and ASCII column), none over a matching byte")

if shot:
    hexw.resize(hexw.width(), int(ch * 6))
    img = hexw.grab(); img.save(shot)
    from PyQt6.QtWidgets import QLabel
    lab = QLabel(); lab.setText(hexw.mismatchTooltip(0x11)); lab.setStyleSheet("background:#ffffe0;border:1px solid #888;padding:4px")
    lab.adjustSize(); lab.grab().save(shot.replace(".png", "_tip.png"))

# 4. editing the buffer to the chip value removes the mark
hexw._HexEditWidget__setCursor(0x003, False)
for c in "%02X" % chip[0x003]:
    hexw.charInput(c)
assert 0x003 not in hexw.mismatchSet and hexw.mismatches == [0x011, 0x1FF], hexw.mismatches
print("editing a marked byte to the chip value clears its mark")

# 5. a new verify that passes clears everything; loading a new buffer clears too
assert not tabs.verifyBuffers({"eeprom": bytes(chip)})
eb.loadImage(bytes(chip)); assert hexw.mismatches == []
assert tabs.verifyBuffers({"eeprom": bytes(chip)}) and hexw.mismatches == []
print("passing verify / new buffer clears the marks")
print("GUI VERIFY TESTS PASSED")

"""Headless test of the patched toprammer-gui fuse buffer (GAL mode)."""
import os, sys, types, importlib.machinery, importlib.util
os.environ["QT_QPA_PLATFORM"] = "offscreen"
top = sys.argv[1]; designs = sys.argv[2]
sys.path.insert(0, top)
loader = importlib.machinery.SourceFileLoader("tgui", os.path.join(top, "toprammer-gui"))
spec = importlib.util.spec_from_loader("tgui", loader); g = importlib.util.module_from_spec(spec)
sys.argv = ["toprammer-gui"]; loader.exec_module(g)
from PyQt6.QtWidgets import QApplication, QWidget
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
fb = tabs.fuseBuffer

def select(chipID):
    mw.currentChipDescription = ChipDescription.findOne(chipID)
    tabs.setupBuffers(g.Chip.SUPPORT_FUSEREAD | g.Chip.SUPPORT_FUSEWRITE)

for chipID, fn, csum in (("gal22v10", "test22v10.jed", "9D01"),
                         ("gal20v8", "test20v8.jed", "5070"),
                         ("gal16v8", "test16v8.jed", "431E")):
    select(chipID)
    raw = open(os.path.join(designs, fn), "rb").read()
    assert fb.setRawData(g.IO_binary().toBinary(raw)), "load failed"
    txt = fb.galView.toPlainText()
    assert fb.galView.isVisibleTo(fb) and not fb.bitsAreaScroll.isVisibleTo(fb)
    assert csum in txt.splitlines()[0], txt.splitlines()[0]
    data = fb.getRawData()
    # what the chip returns on read: same fuses, different header (PES note)
    sp = g.specForChipDescription(mw.currentChipDescription)
    fuses, _ = g.fusesFromImage(raw, sp)
    chipRead = g.jedecCreate(fuses, sp, pes=b"\x00\x02\x48\xA1\x00\x00\x00\x00")
    assert tabs.verifyBuffers({"fusebits": chipRead}), mw.console.msgs
    bad = list(fuses); bad[5] ^= 1
    assert not tabs.verifyBuffers({"fusebits": g.jedecCreate(bad, sp)})
    print("%-9s load OK, %4d lines shown, verify match OK, mismatch detected: %s" % (
        chipID, len(txt.splitlines()), mw.console.msgs[-1].strip()))
    # buffer re-loaded from a chip read (Read chip button path)
    tabs.loadBuffers({"fusebits": chipRead})
    assert fb.getRawData() == data

# wrong device file
select("gal16v8")
try:
    fb.setRawData(open(os.path.join(designs, "test22v10.jed"), "rb").read()); raise SystemExit("FAIL")
except g.TOPException as e:
    print("wrong-device file rejected:", e)

# non-GAL chip keeps the original per-bit checkbox view and 32-byte limit
select("atmega8dip28")
assert fb.setRawData(b"\xD9\xE1") and len(fb.checkboxes) == 16 and not fb.galView.isVisibleTo(fb)
assert fb.setRawData(b"x" * 40) is False
assert fb.compareImage(b"\xD9\xE1") is None
print("non-GAL chip: classic fuse checkbox view unchanged")
print("GUI TESTS PASSED")

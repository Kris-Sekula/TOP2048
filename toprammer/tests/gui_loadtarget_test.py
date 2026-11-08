"""Headless test: Load/Save buffer target when the chip info tab is active."""
import os, sys, importlib.machinery, importlib.util
os.environ["QT_QPA_PLATFORM"] = "offscreen"
top = sys.argv[1]; sys.path.insert(0, top)
loader = importlib.machinery.SourceFileLoader("tgui", os.path.join(top, "toprammer-gui"))
spec = importlib.util.spec_from_loader("tgui", loader); g = importlib.util.module_from_spec(spec)
sys.argv = ["toprammer-gui"]; loader.exec_module(g)
from PyQt6.QtWidgets import QApplication, QWidget
from libtoprammer.chip import ChipDescription
app = QApplication.instance() or QApplication([])
class MW(QWidget):
    def __init__(s): QWidget.__init__(s); s.currentChipDescription = None
mw = MW(); tabs = g.BufferTabWidget(mw)
for chipID in ("gal22v10", "gal16v8", "27c256", "atmega8dip28", "hm62256dip28"):
    desc = ChipDescription.findOne(chipID); mw.currentChipDescription = desc
    tabs.setupBuffers(desc.chipImplClass.getSupportFlags())
    tabs.setCurrentWidget(tabs.infoBuffer)              # GUI default
    buf = tabs.getDataBuffer()
    assert buf is not tabs.infoBuffer and tabs.currentWidget() is buf
    print("%-14s chip info active -> Load buffer goes to '%s' (tab switched)" % (chipID, buf.getName()))
    # an explicitly chosen data tab is respected
    last = tabs.widget(tabs.count() - 1); tabs.setCurrentWidget(last)
    assert tabs.getDataBuffer() is last
print("LOAD TARGET TESTS PASSED")

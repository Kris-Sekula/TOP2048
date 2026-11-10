"""Headless test of the toprammer-gui Autorun single-run / repeat behaviour."""
import os, sys, importlib.machinery, importlib.util
os.environ["QT_QPA_PLATFORM"] = "offscreen"
top = sys.argv[1]; sys.path.insert(0, top)
loader = importlib.machinery.SourceFileLoader("tgui", os.path.join(top, "toprammer-gui"))
spec = importlib.util.spec_from_loader("tgui", loader); g = importlib.util.module_from_spec(spec)
sys.argv = ["toprammer-gui"]; loader.exec_module(g)
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PyQt6.QtCore import Qt
from libtoprammer.chip import ChipDescription
app = QApplication.instance() or QApplication([])

prompts = []
def fakeInfo(*a, **k):
    prompts.append(a[2] if len(a) > 2 else "")
    return QMessageBox.StandardButton.Ok if len(prompts) == 1 else QMessageBox.StandardButton.Cancel
QMessageBox.information = staticmethod(fakeInfo)
QMessageBox.critical = staticmethod(lambda *a, **k: prompts.append("CRITICAL"))

class Console:
    def __init__(s): s.msgs = []
    def showMessage(s, m, bold=False): s.msgs.append(m.strip())

class MW(QMainWindow):
    def __init__(s):
        QMainWindow.__init__(s)
        s.currentChipDescription = ChipDescription.findOne("gal22v10")
        s.console = Console(); s.done = []
    def guiUpdateEnable(s): pass
    def _act(s, name):
        s.done.append(name)
        return True               # hardware op started OK; completion comes later
    def eraseChip(s): return s._act("erase")
    def writeChipFuses(s): return s._act("write")
    def verifySelectedMemories(s, **k):
        s.verifyArgs = k; return s._act("verify")
    def runTest(s): return s._act("test")
    def verifyChip(s): return True
    def readChip(s): return True
    def loadBuffer(s): return True
    def saveBuffer(s): return True
    def startUnitest(s): return True
    def selectChip(s): return True
    def eraseChip(s): return s._act("erase")
    def writeChipLockbits(s): return s._act("lock")

def drive(ar):
    "Emulate MainWindow: after each finished hardware op, continue autorun."
    for _ in range(50):
        if not ar.isRunning(): return
        ar.runNextAction()
    raise SystemExit("FAIL: autorun never finished")

flags = g.Chip.SUPPORT_ERASE | g.Chip.SUPPORT_FUSEREAD | g.Chip.SUPPORT_FUSEWRITE
mw = MW(); ar = g.AutorunWidget(mw); ar.setup(flags)
assert ar.repeatCheckBox is not None and ar.repeatCheckBox.checkState() == Qt.CheckState.Unchecked

# 1) default: single run, no prompts, ends back in the main window
ar.startRun(); drive(ar)
assert mw.done == ["erase", "write", "verify"], mw.done
assert prompts == [], prompts
assert not ar.isRunning() and mw.console.msgs[-1] == "Autorun finished."
print("single run :", mw.done, "-> no prompts, back to main window")

# 2) repeat ticked: original production behaviour (prompt, run, prompt again)
mw.done.clear(); ar.repeatCheckBox.setCheckState(Qt.CheckState.Checked)
ar.startRun(); drive(ar)
assert mw.done == ["erase", "write", "verify"], mw.done
assert len(prompts) == 2 and not ar.isRunning()
print("repeat mode:", mw.done, "-> prompted for next chip again (cancelled)")

# 3) a failing action still aborts with the error box
prompts.clear(); ar.repeatCheckBox.setCheckState(Qt.CheckState.Unchecked)
mw.writeChipFuses = lambda: False
mw.done.clear(); ar.startRun(); drive(ar)
assert prompts == ["CRITICAL"] and not ar.isRunning()
print("failure    : aborted with error message as before")

# 4) read-only chip with a unit-test (8755): test runs; verify is off by
#    default and, when ticked, really compares the EEPROM buffer
mw = MW(); mw.currentChipDescription = ChipDescription.findOne("i8755")
f8755 = mw.currentChipDescription.chipImplClass.getSupportFlags()
ar = g.AutorunWidget(mw); ar.setup(f8755)
assert ar.testCheckBox is not None and ar.testCheckBox.checkState() == Qt.CheckState.Checked
assert ar.verifyCheckBox.text() == "Verify chip against buffer"
assert ar.verifyCheckBox.checkState() == Qt.CheckState.Unchecked
prompts.clear(); ar.startRun(); drive(ar)
assert mw.done == ["test"], mw.done
ar.verifyCheckBox.setCheckState(Qt.CheckState.Checked)
mw.done.clear(); ar.startRun(); drive(ar)
assert mw.done == ["test", "verify"] and mw.verifyArgs["verifyEEPROM"] is True, (mw.done, mw.verifyArgs)
print("8755       :", mw.done, "-> unit-test in Autorun, verify compares the (E)EPROM buffer")

# 5) toolbars: "Run unit-test" sits right of "Verify all"; the right-hand
#    bar (write actions) is hidden when the chip has none
tt = g.TopToolBar(mw); rt = g.RightToolBar(mw)
tt.setup(f8755); rt.setup(f8755)
names = [a.text() for a in tt.actions() if a.text()]
assert names[names.index("Verify all") + 1] == "Run unit-test", names
assert not rt.actions() and not rt.isVisibleTo(mw)
fgal = ChipDescription.findOne("gal22v10").chipImplClass.getSupportFlags()
tt.setup(fgal); rt.setup(fgal)
assert "Run unit-test" not in [a.text() for a in tt.actions()]
assert [a.text() for a in rt.actions()] == ["Erase", "Write fuses"] and rt.isVisibleTo(mw)
print("toolbars   : unit-test right of Verify all; empty write bar hidden")
print("AUTORUN TESTS PASSED")

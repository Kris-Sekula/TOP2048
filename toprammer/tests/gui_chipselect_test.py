"""Headless test of the chip selection dialog (recently used list and
search) and of the wrapping chip-info labels.

usage: python tests/gui_chipselect_test.py <toprammer dir>"""
import os, sys, tempfile, importlib.machinery, importlib.util
os.environ["QT_QPA_PLATFORM"] = "offscreen"
top = sys.argv[1]; sys.path.insert(0, top)
loader = importlib.machinery.SourceFileLoader("tgui", os.path.join(top, "toprammer-gui"))
spec = importlib.util.spec_from_loader("tgui", loader); g = importlib.util.module_from_spec(spec)
sys.argv = ["toprammer-gui"]; loader.exec_module(g)
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtCore import QEvent
from libtoprammer.chip import ChipDescription
app = QApplication.instance() or QApplication([])

ini = os.path.join(tempfile.mkdtemp(), "gui.ini")	# never touch the real settings
g.guiSettings = lambda: QSettings(ini, QSettings.Format.IniFormat)

def chips(dlg): return [dlg.chipList.item(i).data(Qt.ItemDataRole.UserRole).chipID
                        for i in range(dlg.chipList.count())]

# no history: "Recently used" disabled, "All types" selected
dlg = g.ChipSelectDialog(None)
assert not dlg.recentRadio.isEnabled() and dlg.allRadio.isChecked()
nAll = dlg.chipList.count()
print("no history : 'Recently used (0)' disabled, %d chips listed" % nAll)

# history: newest first, de-duplicated, capped at 10
for c in ["gal16v8", "mh74s571", "i8755", "gal22v10", "gal16v8"]:
	g.addRecentChipID(c)
assert g.recentChipIDs() == ["gal16v8", "gal22v10", "i8755", "mh74s571"]
allIDs = [d.chipID for d in g.getRegisteredChips() if d.chipType != ChipDescription.TYPE_INTERNAL]
for c in allIDs[:15]:
	g.addRecentChipID(c)
assert len(g.recentChipIDs()) == 10 and g.recentChipIDs()[0] == allIDs[14]
open(ini, "w").close()
for c in ["gal16v8", "mh74s571", "i8755", "gal22v10", "gal16v8"]:
	g.addRecentChipID(c)
print("history    :", g.recentChipIDs(), "(newest first, no duplicates, max 10)")

dlg = g.ChipSelectDialog(None)
assert dlg.recentRadio.isChecked() and dlg.recentRadio.text() == "Recently used (4)"
assert chips(dlg) == ["gal16v8", "gal22v10", "i8755", "mh74s571"], chips(dlg)
assert dlg.getSelectedChip().chipID == "gal16v8"
print("recent list:", chips(dlg), "-> most recent preselected")

# search: partial, case-insensitive, matches description, ID or vendor;
# typing switches from the recent list to all types
dlg.searchEdit.setText("8755")
assert dlg.allRadio.isChecked() and chips(dlg) == ["i8755"], chips(dlg)
dlg.searchEdit.setText("gal")
assert set(chips(dlg)) >= {"gal16v8", "gal20v8", "gal22v10"} and all("gal" in c.lower() or "GAL" in
	dlg.chipList.item(i).text() for i, c in enumerate(chips(dlg)))
dlg.searchEdit.setText("lattice 22")
assert chips(dlg) == ["gal22v10"], chips(dlg)
dlg.searchEdit.setText("TESLA")
assert chips(dlg) == ["mh74s571"], chips(dlg)
dlg.searchEdit.setText("xyzzy")
assert chips(dlg) == [] and not dlg.okButton.isEnabled()
dlg.searchEdit.setText("")
assert dlg.chipList.count() == nAll and dlg.okButton.isEnabled()
print("search     : '8755', 'gal', 'lattice 22', 'TESLA' narrow correctly; no match disables Ok")

# arrow keys in the search box move through the list
dlg.searchEdit.setText("gal")
r0 = dlg.chipList.currentRow()
app.sendEvent(dlg.searchEdit, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
assert dlg.chipList.currentRow() == r0 + 1
print("keyboard   : Down in the search box moves the selection")

# long chip comment wraps instead of fixing the window's minimum width
class MW(QWidget):
	pass
mw = MW()
info = g.InfoBufferWidget(mw, "chip info")
d = ChipDescription.findOne("i8755")
info.setupDescription(d)
assert info.comment.wordWrap()
assert info.minimumSizeHint().width() < 400, info.minimumSizeHint().width()
info.resize(420, 300); info.show(); app.processEvents()
assert info.comment.height() > info.comment.fontMetrics().height() * 1.5
print("chip info  : comment wraps (minimum width %d px)" % info.minimumSizeHint().width())
print("CHIP SELECT TESTS PASSED")

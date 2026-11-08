# Windows launcher for toprammer-gui.
# Double-click to start the GUI without a console window (pythonw.exe).
# The real program is the extension-less "toprammer-gui" script next to
# this file (Unix convention: installed as a command, run via its shebang).
import os, runpy, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
script = os.path.join(here, "toprammer-gui")
sys.argv[0] = script
runpy.run_path(script, run_name="__main__")

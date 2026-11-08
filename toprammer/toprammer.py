# Windows launcher for the toprammer command line tool:
#     python toprammer.py -c gal16v8 -F design.jed -I bin
# (equivalent to "python toprammer ...")
import os, runpy, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
script = os.path.join(here, "toprammer")
sys.argv[0] = script
runpy.run_path(script, run_name="__main__")

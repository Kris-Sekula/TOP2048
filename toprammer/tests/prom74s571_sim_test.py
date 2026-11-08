"""Offline test of libtoprammer/chips/prom74s571.py against a pin-level
74S571 model driven through a fake TOP2049.
usage: python tests/prom74s571_sim_test.py <toprammer dir>"""
import sys, random
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from libtoprammer.chips.prom74s571 import *
from libtoprammer.chip import ChipDescription, AssignedChipOption
from libtoprammer.util import TOPException

class Layout:
    def __init__(s, top): s.top, s.ids = top, set()
    def setLayoutID(s, i): s.ids.add(i)
    def setLayoutMask(s, m):
        if m == 0: s.ids = set()
    def minVoltage(s): return 5

class Prom:
    "74S571: tri-state outputs, active-low /CE, needs VCC + GND."
    def __init__(s, data, flaky=False):
        s.mem, s.flaky, s.reads = data, flaky, 0
    def outputs(s, top, pins):
        if not (top.vcc.ids and top.gnd.ids) or pins[PIN_CE]:
            return None                                   # high impedance
        a = sum(pins[p] << i for i, p in enumerate(PIN_A))
        v = s.mem[a]
        if s.flaky and a == 0x123:        # bad contact: differs on every visit
            s.reads += 1
            if s.reads % 2: v ^= 1
        return v

class FakeTop:
    def __init__(s, prom):
        s.prom, s.out, s.en, s.buf = prom, 0, 0, b""
        s.vcc, s.vpp, s.gnd = Layout(s), Layout(s), Layout(s)
        s.vppVolt = 5; s.msgs = []
    def bind(s, chip):
        g = chip.getLayoutGenerator()
        s.z = {p: g.getZifPinForPackagePin(p) for p in range(1, 17)}
    def pins(s):
        return {p: (s.out >> (z - 1)) & 1 for p, z in s.z.items()}
    def getProgrammerType(s): return "TOP2049"
    def getForceLevel(s): return 0
    def getBufferRegSize(s): return 64
    def cmdFPGAWrite(s, addr, val):
        sh = 8 * (addr & 7)
        if 0x40 <= addr <= 0x45:
            s.en = (s.en & ~(0xFF << sh)) | (val << sh)
            for d in PIN_D + (PIN_VCC, PIN_GND):
                assert not (s.en >> (s.z[d] - 1)) & 1, "FPGA drives PROM pin %d" % d
        elif 0x60 <= addr <= 0x65:
            s.out = (s.out & ~(0xFF << sh)) | (val << sh)
    def cmdFPGARead(s, addr):
        sh = 8 * (addr & 7); v = (s.out >> sh) & 0xFF
        q = s.prom.outputs(s, s.pins())
        for i, p in enumerate(PIN_D):
            z = s.z[p]
            if (z - 1) // 8 == addr - 0x60:
                b = (z - 1) % 8
                bit = 1 if q is None else (q >> i) & 1        # floating reads 1
                v = (v & ~(1 << b)) | (bit << b)
        s.buf += bytes([v])
    def cmdReadBufferReg(s, n):
        d, s.buf = s.buf[:n], s.buf[n:]; assert len(d) == n; return d
    def cmdDelay(s, t): pass
    def hostDelay(s, t): pass
    def flushCommands(s, t=0): pass
    def cmdSetVCCVoltage(s, v): assert v <= 5.0, "VCC above 5 V"
    def cmdSetVPPVoltage(s, v): assert v <= 5.0, "VPP raised"; s.vppVolt = v
    def cmdEnableZifPullups(s, e): pass
    def printInfo(s, m): s.msgs.append(m); print("     ", m)
    def printWarning(s, m): s.msgs.append(m); print("      warn:", m)
    def printDebug(s, m): pass
    def progressMeterInit(s, *a): pass
    def progressMeter(s, *a): pass
    def progressMeterFinish(s, *a): pass

def run(data, opts=(), flaky=False):
    desc = ChipDescription.findOne("74s571")
    top = FakeTop(Prom(data, flaky))
    chip = desc.chipImplClass.createInstance(top, desc, opts); top.bind(chip)
    return chip.readEEPROM(), top

data = [random.randint(0, 15) for _ in range(512)]
img, top = run(data)
assert list(bytearray(img)) == data and len(img) == 512
print("random contents read back exactly (512 bytes, low nibble)")

img, top = run([0] * 512)
assert list(bytearray(img)) == [0] * 512 and "blank" in top.msgs[-1]
print("blank PROM reported as blank")

# A0/A2 swap: the image read with the option equals the image with
# address bits 0 and 2 exchanged
sw = lambda a: (a & ~5) | ((a & 1) << 2) | ((a >> 2) & 1)
img, top = run(data, (AssignedChipOption("swap_a0_a2", "1"),))
assert list(bytearray(img)) == [data[sw(a)] for a in range(512)]
print("swap_a0_a2 exchanges address bits 0 and 2")

try:
    run(data, flaky=True); raise SystemExit("FAIL: unstable read accepted")
except TOPException as e:
    print("unstable read rejected:", e)

desc = ChipDescription.findOne("mh74s571")
assert not desc.chipImplClass.chipSupportsAttr("writeEEPROM")
print("no write support exposed (read only)")
print("PROM TESTS PASSED")

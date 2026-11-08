"""Offline test of libtoprammer/chips/gal.py against pin-level GAL edit-mode
simulators (GAL16V8, GAL20V8, GAL22V10) driven through a fake TOP2049.

usage: python tests/gal_sim_test.py <toprammer dir>   (run from anywhere)
Each device is tested with a chip that samples SDIN on the rising edge and
one that samples on the falling edge (seen on real GAL16V8A parts)."""
import sys, random
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from libtoprammer.chips.gal import *
from libtoprammer.chip import ChipDescription, AssignedChipOption
from libtoprammer.util import TOPException


class Layout:
    def __init__(self, top): self.top, self.ids = top, set()
    def setLayoutID(self, i): self.ids.add(i); self.top.supplyChanged()
    def setLayoutMask(self, m):
        if m == 0: self.ids = set()
        self.top.supplyChanged()
    def minVoltage(self): return 5


class GalSim:
    """Edit-mode model of one GAL. Package-pin level."""
    def __init__(self, spec, pes, edge):
        self.s, self.pes, self.edge = spec, pes, edge
        self.fuses = [random.randint(0, 1) for _ in range(spec.nrFuses)]
        self.security = False
        self.shift, self.outRow, self.outPos = [], [0], 0
        self.lastSclk, self.lastStb, self.stbStart = 0, 1, 0
        self.log = []
        self.cfgmap = CFG_MAP_V10 if spec.family == "V10" else CFG_MAP_V8AB

    def rowValue(self, row, direct=False):
        s = self.s
        if s.family == "V10" and direct:
            if row == s.cfgRow: return [self.fuses[s.cfgBase + o] for o in self.cfgmap]
            raise AssertionError("RA-selected read of row %d" % row)
        if row < s.rows: return [self.fuses[s.rows * b + row] for b in range(s.rowBits)]
        if row == s.uesRow: return self.fuses[s.uesFuse:s.uesFuse + s.uesBits]
        if row == s.cfgRow: return [self.fuses[s.cfgBase + o] for o in self.cfgmap]
        if row == s.pesRow: return [(self.pes[i // 8] >> (i % 8)) & 1 for i in range(8 * len(self.pes))]
        raise AssertionError("read of unexpected row %d" % row)

    def program(self, row, data, top, dur, direct=False):
        s = self.s
        if s.family == "V10" and direct and row == s.cfgRow:
            assert len(data) == len(self.cfgmap), len(data)
            for i, o in enumerate(self.cfgmap): self.fuses[s.cfgBase + o] = data[i]
            return
        if s.family == "V10" and row < s.rows and direct:
            raise AssertionError("V10 array row %d selected on RA pins" % row)
        if top.vppVolt < 14.0: raise AssertionError("program at %.2fV" % top.vppVolt)
        if row == s.eraseRow:
            assert dur >= 0.04, dur
            self.fuses = [1] * s.nrFuses; self.security = False; self.log.append("erase"); return
        if row == s.securityRow:
            self.security = True; self.log.append("secure"); return
        if row < s.rows:
            assert len(data) == s.rowBits, (row, len(data))
            for b in range(s.rowBits): self.fuses[s.rows * b + row] = data[b]
        elif row == s.uesRow:
            assert len(data) == (s.rowBits if s.family == "V10" else s.uesBits), len(data)
            if s.family == "V10": assert data[s.uesBits:] == [1] * (s.rowBits - s.uesBits)
            self.fuses[s.uesFuse:s.uesFuse + s.uesBits] = data[:s.uesBits]
        elif row == s.cfgRow:
            assert len(data) == len(self.cfgmap), len(data)
            for i, o in enumerate(self.cfgmap): self.fuses[s.cfgBase + o] = data[i]
        else:
            raise AssertionError("program unexpected row %d" % row)

    def step(self, top, pins):
        s = self.s
        edit = top.vccOn and top.vppOn and top.vppVolt >= 11.0
        sclk, stb, pv, sdin = pins[s.sclk], pins[s.stb], pins[s.pv], pins[s.sdin]
        if not edit:
            self.lastSclk, self.lastStb = sclk, stb; return
        ra = sum(pins[p] << i for i, p in enumerate(s.ra))
        rise = sclk and not self.lastSclk
        fall = (not sclk) and self.lastSclk
        if s.family == "V8":
            if rise and not pv: self.outPos += 1
            if pv and ((rise and self.edge == "rise") or (fall and self.edge == "fall")):
                self.shift.append(sdin)
        else:   # V10: one shift register, clocked regardless of P/V
            if rise: self.outPos += 1
            if (rise and self.edge == "rise") or (fall and self.edge == "fall"):
                self.shift.append(sdin)
        if not stb and self.lastStb: self.stbStart = top.time
        prevStb = self.lastStb
        self.lastSclk, self.lastStb = sclk, stb
        if stb and not prevStb:
            dur = top.time - self.stbStart
            direct = s.family == "V8" or ra != 0
            if s.family == "V8":
                row, data = ra, self.shift
            else:
                if ra:      # config / erase rows are selected on RA pins
                    row, data = ra, self.shift
                else:
                    addr = self.shift[-6:]
                    row = sum(b << i for i, b in enumerate(addr))
                    data = self.shift[:-6]
            if pv:
                if s.family == "V8" and row in (s.eraseRow, s.securityRow): assert data == [1], data
                self.program(row, data, top, dur, direct)
            else:
                if top.vppVolt > 13.0: raise AssertionError("read at programming voltage")
                self.outRow = self.rowValue(row, direct and s.family == "V10")
                if self.security and row <= s.uesRow: self.outRow = [1] * len(self.outRow)
                self.outPos = 0
            self.shift = []
        self.lastSclk, self.lastStb = sclk, stb

    def sdout(self):
        return self.outRow[self.outPos] if self.outPos < len(self.outRow) else 0


class FakeTop:
    def __init__(self, sim):
        self.sim, self.out, self.en, self.buf = sim, 0, 0, b""
        self.vcc, self.vpp, self.gnd = Layout(self), Layout(self), Layout(self)
        self.vccOn = self.vppOn = False; self.vppVolt = 5; self.time = 0.0; self.writes = 0
    def bind(self, chip):
        self.gen = chip.getLayoutGenerator(); s = self.sim.s
        self.zif2pkg = {self.gen.getZifPinForPackagePin(p): p for p in range(1, s.pins + 1)}
        self.vppZif = self.gen.getZifPinForPackagePin(s.edit)
        self.sdoutZif = self.gen.getZifPinForPackagePin(s.sdout)
    def checkEdit(self):
        if self.vppOn and (self.en >> (self.vppZif - 1)) & 1:
            raise AssertionError("FPGA drives EDIT pin while VPP is on")
        for z, p in getattr(self, "zif2pkg", {}).items():
            if p in (self.sim.s.vcc, self.sim.s.gnd) and (self.en >> (z - 1)) & 1:
                raise AssertionError("FPGA drives supply pin %d" % p)
    def supplyChanged(self):
        self.vccOn = bool(self.vcc.ids) and bool(self.gnd.ids); self.vppOn = bool(self.vpp.ids)
        self.checkEdit(); self.tick()
    def pins(self):
        return {p: ((self.out >> (z - 1)) & 1 if (self.en >> (z - 1)) & 1 else 0)
                for z, p in self.zif2pkg.items()}
    def tick(self):
        if hasattr(self, "zif2pkg"): self.sim.step(self, self.pins())
    def getProgrammerType(self): return "TOP2049"
    def getForceLevel(self): return 0
    def getBufferRegSize(self): return 64
    def cmdFPGAWrite(self, addr, val):
        self.writes += 1; sh = 8 * (addr & 7)
        if 0x40 <= addr <= 0x45: self.en = (self.en & ~(0xFF << sh)) | (val << sh); self.checkEdit()
        elif 0x60 <= addr <= 0x65: self.out = (self.out & ~(0xFF << sh)) | (val << sh)
        self.time += 2e-6; self.tick()
    def cmdFPGARead(self, addr):
        sh = 8 * (addr & 7); v = (self.out >> sh) & 0xFF
        z = self.sdoutZif
        if (z - 1) // 8 == addr - 0x60:
            b = (z - 1) % 8; v = (v & ~(1 << b)) | (self.sim.sdout() << b)
        self.buf += bytes([v])
    def cmdReadBufferReg(self, n):
        d, self.buf = self.buf[:n], self.buf[n:]; assert len(d) == n; return d
    def cmdDelay(self, s): self.time += s
    def hostDelay(self, s): self.time += s
    def flushCommands(self, s=0): self.time += s
    def cmdSetVCCVoltage(self, v): pass
    def cmdSetVPPVoltage(self, v): self.vppVolt = v; self.tick()
    def cmdEnableZifPullups(self, e): pass
    def printInfo(self, m): print("     ", m)
    def printDebug(self, m): pass
    def printWarning(self, m): print("      warn:", m)
    def progressMeterInit(self, *a): pass
    def progressMeter(self, *a): pass
    def progressMeterFinish(self, *a): pass


def mkchip(chipID, sim, opts=()):
    desc = ChipDescription.findOne(chipID)
    top = FakeTop(sim)
    chip = desc.chipImplClass.createInstance(top, desc, opts)
    top.bind(chip)
    return chip, top


DEVICES = (
    ("gal16v8",  GAL16V8,  bytes([0x00, 0x03, 0x1A, 0xA1, 0, 0, 0, 0x30])),
    ("gal20v8",  GAL20V8,  bytes([0x00, 0x03, 0x3A, 0xA1, 0, 0, 0, 0x00])),
    ("gal22v10", GAL22V10, bytes([0x00, 0x03, 0x48, 0xA1, 0, 0, 0, 0, 0, 0])),
)

for chipID, spec, pes in DEVICES:
    for edge in ("rise", "fall"):
        print("== %s, chip samples SDIN on %s edge" % (spec.name, edge))
        sim = GalSim(spec, pes, edge)
        chip, top = mkchip(chipID, sim)
        assert chip.readSignature() == pes, "PES"
        want = [random.randint(0, 1) for _ in range(spec.nrFuses)]
        chip.writeFuse(jedecCreate(want, spec))
        assert sim.fuses == want, "chip contents differ from file"
        got, _ = jedecParse(chip.readFuse(), spec)
        assert got == want, "readback JEDEC differs"
        print("      ok (%d FPGA writes)" % top.writes)

print("== wrong chip in socket is rejected")
sim = GalSim(GAL22V10, DEVICES[2][2], "rise")
chip, top = mkchip("gal20v8", GalSim(GAL20V8, DEVICES[2][2][:8], "rise"))
try:
    chip.erase(); raise SystemExit("FAIL: 22V10 PES accepted as 20V8")
except TOPException as e:
    print("      ok:", e)

print("== wrong JEDEC size is rejected")
chip, top = mkchip("gal22v10", GalSim(GAL22V10, DEVICES[2][2], "rise"))
try:
    chip.writeFuse(jedecCreate([0] * GAL16V8.nrFuses, GAL16V8)); raise SystemExit("FAIL")
except TOPException as e:
    print("      ok:", e)

print("== 16V8 G1 sets security; 22V10 refuses security after a verified write")
sim = GalSim(GAL16V8, DEVICES[0][2], "fall"); chip, top = mkchip("gal16v8", sim)
chip.writeFuse(b"\x02*QF2194*F0*G1*L0000 1111*\x03"); assert sim.security
sim = GalSim(GAL22V10, DEVICES[2][2], "fall"); chip, top = mkchip("gal22v10", sim)
try:
    chip.writeFuse(b"\x02*QF5892*F0*G1*L0000 1111*\x03"); raise SystemExit("FAIL")
except TOPException as e:
    assert sim.fuses[:4] == [1, 1, 1, 1] and not sim.security
    print("      ok:", e)

print("ALL TESTS PASSED")

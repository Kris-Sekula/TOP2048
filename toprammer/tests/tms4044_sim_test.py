"""Offline test of libtoprammer/chips/tms4044.py (4K x 1 SRAM test) against a
pin-level SRAM model with injectable faults, driven through a fake TOP2049.

The model writes on the rising edge of /W while /S is low, fails the test if
the address changes while /W is low, and fails if the FPGA drives Q, VCC or
VSS.

usage: python tests/tms4044_sim_test.py <toprammer dir>"""
import sys, random
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from libtoprammer.chips.tms4044 import *
from libtoprammer.chip import ChipDescription, AssignedChipOption
from libtoprammer.util import TOPException


class Layout:
	def __init__(s, top): s.top, s.ids = top, set()
	def setLayoutID(s, i): s.ids.add(i)
	def setLayoutMask(s, m):
		if m == 0: s.ids = set()
	def minVoltage(s): return 5


class SRAM:
	"""faults: stuck {addr: v}, noRise {addr} (can't go 0->1), aliasBit n
	(address line An open, reads as 0), couple (aggressor, victim),
	leaky {addr} (loses a 1 after 0.5 s), absent (no chip: Q floats high)"""
	def __init__(s, **f):
		s.mem = [random.randint(0, 1) for _ in range(SIZE)]
		s.f = f
		s.lastW, s.addrAtWLow = 1, None
		s.time, s.written = 0.0, {}
		s.writes = 0
	def eff(s, a):
		if "aliasBit" in s.f: a &= ~(1 << s.f["aliasBit"])
		return a
	def cell(s, a):
		a = s.eff(a)
		if a in s.f.get("stuck", {}): return s.f["stuck"][a]
		if a in s.f.get("leaky", set()) and s.time - s.written.get(a, 0) > 0.5: return 0
		return s.mem[a]
	def step(s, top, pins):
		if not top.powered(): s.lastW = pins[PIN_W]; return
		a = sum(pins[p] << i for i, p in enumerate(PIN_A))
		w, sel = pins[PIN_W], not pins[PIN_S]
		if not w and s.lastW: s.addrAtWLow = a
		if not w and sel:
			assert a == s.addrAtWLow, "address changed while /W low"
		if w and not s.lastW and sel:			# rising edge: write
			s.writes += 1
			e, v = s.eff(a), pins[PIN_D]
			if e in s.f.get("noRise", set()) and v == 1 and s.mem[e] == 0: v = 0
			s.mem[e] = v; s.written[e] = s.time
			c = s.f.get("couple")
			if c and e == c[0] and v == 1: s.mem[c[1]] = 1
		s.lastW = w
	def q(s, top, pins):
		if "absent" in s.f: return 1
		if not top.powered() or pins[PIN_S] or not pins[PIN_W]:
			return random.randint(0, 1)			# high-Z
		return s.cell(sum(pins[p] << i for i, p in enumerate(PIN_A)))


class FakeTop:
	def __init__(s, ram):
		s.m, s.out, s.en, s.buf = ram, 0, 0, b""
		s.vcc, s.vpp, s.gnd = Layout(s), Layout(s), Layout(s)
		s.msgs = []; s.z = None; s.cmds = 0
	def powered(s): return bool(s.vcc.ids and s.gnd.ids)
	def bind(s, chip):
		g = chip.getLayoutGenerator()
		s.z = {p: g.getZifPinForPackagePin(p) for p in range(1, 19)}
	def pins(s): return {p: (s.out >> (z - 1)) & 1 for p, z in s.z.items()}
	def getProgrammerType(s): return "TOP2049"
	def getForceLevel(s): return 0
	def getBufferRegSize(s): return 64
	def cmdFPGAWrite(s, addr, val):
		s.cmds += 1
		sh = 8 * (addr & 7)
		if 0x40 <= addr <= 0x45:
			s.en = (s.en & ~(0xFF << sh)) | (val << sh)
			if s.z:
				for p in (PIN_Q, PIN_VCC, PIN_VSS):
					assert not (s.en >> (s.z[p] - 1)) & 1, "FPGA drives pin %d" % p
		elif 0x60 <= addr <= 0x65:
			s.out = (s.out & ~(0xFF << sh)) | (val << sh)
		if s.z: s.m.step(s, s.pins())
	def cmdFPGARead(s, addr):
		s.cmds += 1
		sh = 8 * (addr & 7); v = (s.out >> sh) & 0xFF
		z = s.z[PIN_Q]
		if (z - 1) // 8 == addr - 0x60:
			b = (z - 1) % 8
			v = (v & ~(1 << b)) | (s.m.q(s, s.pins()) << b)
		s.buf += bytes([v])
	def cmdReadBufferReg(s, n):
		d, s.buf = s.buf[:n], s.buf[n:]; assert len(d) == n; return d
	def cmdDelay(s, t): s.m.time += t
	def hostDelay(s, t): s.m.time += t
	def flushCommands(s, t=0): pass
	def cmdSetVCCVoltage(s, v): assert v <= 5.0
	def cmdSetVPPVoltage(s, v): pass
	def cmdEnableZifPullups(s, e): pass
	def printInfo(s, m): s.msgs.append(m); print("     ", m)
	def printWarning(s, m): s.msgs.append(m)
	def printDebug(s, m): pass
	def progressMeterInit(s, *a): pass
	def progressMeter(s, *a): pass
	def progressMeterFinish(s, *a): pass


def run(**faults):
	desc = ChipDescription.findOne("tms4044")
	top = FakeTop(SRAM(**faults))
	chip = desc.chipImplClass.createInstance(top, desc, ())
	top.bind(chip)
	chip.test()
	return top

top = run()
assert "passed" in top.msgs[-1]
print("good chip: passes (%d FPGA commands, %d writes)" % (top.cmds, top.m.writes))

for name, faults, expect in (
		("cell 0x123 stuck at 0",    dict(stuck={0x123: 0}),      ["1 of 4096", "0x123"]),
		("cell 0x456 can't go 0->1", dict(noRise={0x456}),        ["1 of 4096", "0x456"]),
		("A7 open (address fault)",  dict(aliasBit=7),            ["address line A7 (pin 16)"]),
		("0x100 write-1 sets 0x101", dict(couple=(0x100, 0x101)), ["0x101"]),
		("0x777 loses data (leaky)", dict(leaky={0x777}),         ["1 of 4096", "0x777", "checkerboard"]),
		("A0 open (address fault)",  dict(aliasBit=0),            ["address line A0 (pin 1)"]),
		("no chip in the socket",    dict(absent=True),           ["every cell fails", "No chip"])):
	try:
		run(**faults); raise SystemExit("FAIL: %s not detected" % name)
	except TOPException as e:
		msg = str(e)
		assert all(x in msg for x in expect), (name, msg)
		print("%-26s -> %s" % (name, msg.splitlines()[0].split(": ", 1)[-1]))

assert ChipDescription.findOne("tms4044").chipImplClass.chipSupportsAttr("test")
print("TMS4044 TESTS PASSED")

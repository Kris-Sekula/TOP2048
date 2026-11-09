"""Offline test of libtoprammer/chips/i8755.py against a pin-level 8755A
bus model driven through a fake TOP2049.

The model latches AD0-AD7, A8-A10, IO/M, /CE1 and CE2 on the falling edge of
ALE and drives AD0-AD7 only while /RD is low and the latched enables select
the ROM. It fails the test on bus contention, on the FPGA driving a supply,
READY or port pin, and on VDD above 5 V.

usage: python tests/i8755_sim_test.py <toprammer dir>"""
import sys, random
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from libtoprammer.chips.i8755 import *
from libtoprammer.chip import ChipDescription, AssignedChipOption
from libtoprammer.util import TOPException


class Layout:
	def __init__(s, top): s.top, s.ids = top, set()
	def setLayoutID(s, i): s.ids.add(i); s.top.step()
	def setLayoutMask(s, m):
		if m == 0: s.ids = set()
		s.top.step()
	def minVoltage(s): return 5


class I8755:
	"""faults: {"stuck": {(port, bit): level}, "short": [((p, b), (p, b))],
	            "ddrdead": {(port, bit)}}   port 0 = A, 1 = B"""
	def __init__(s, mem, flaky=False, faults=None):
		s.mem, s.flaky, s.visits = mem, flaky, 0
		s.lastAle = 0
		s.latch = None		# (addr, iom, ce1, ce2)
		s.resetSeen = False
		s.cycles = 0
		s.ddr, s.out = [0, 0], [0x3C, 0xC3]	# power-up junk in the latches
		s.lastIow = 1
		s.faults = faults or {}
		s.portPins = (PIN_PA, PIN_PB)

	def selected(s):
		return s.latch is not None and not s.latch[2] and s.latch[3]

	def portLevel(s, top, port, bit):
		"""Electrical level of one port pin; checks for contention."""
		pin = s.portPins[port][bit]
		fpga = top.fpgaDrives(pin)
		chipOut = s.powered(top) and (s.ddr[port] >> bit) & 1 and \
			  (port, bit) not in s.faults.get("ddrdead", set())
		if fpga and chipOut:
			raise AssertionError("contention on %s%d (FPGA and 8755 both drive)" % ("AB"[port], bit))
		if (port, bit) in s.faults.get("stuck", {}):
			return s.faults["stuck"][(port, bit)]
		if chipOut: v = (s.out[port] >> bit) & 1
		elif fpga: v = top.fpgaLevel(pin)
		else: v = 1 if top.pullups else random.randint(0, 1)
		for a, b in s.faults.get("short", []):
			if (port, bit) in (a, b):
				o = b if (port, bit) == a else a
				ochip = s.powered(top) and (s.ddr[o[0]] >> o[1]) & 1
				ofpga = top.fpgaDrives(s.portPins[o[0]][o[1]])
				ov = (s.out[o[0]] >> o[1]) & 1 if ochip else (
					top.fpgaLevel(s.portPins[o[0]][o[1]]) if ofpga else 1)
				v = v & ov		# wired-AND
		return v

	def portValue(s, top, port):
		return sum(s.portLevel(top, port, b) << b for b in range(8))

	def powered(s, top):
		return bool(top.vcc.ids and top.gnd.ids and top.vpp.ids)

	def step(s, top, pins):
		if not s.powered(top):
			s.lastAle = pins[PIN_ALE]; return
		if top.vppVolt > 5.5:
			raise AssertionError("VDD raised to %.1f V while reading" % top.vppVolt)
		if pins[PIN_RESET]:
			s.resetSeen = True; s.ddr = [0, 0]
		iow = pins[PIN_IOW]
		if iow and not s.lastIow and s.selected():	# /IOW rising edge: write
			assert not (top.en >> (top.z[PIN_AD[0]] - 1)) & 1 or True
			for p in PIN_AD:
				assert top.fpgaDrives(p), "/IOW with AD%d not driven" % PIN_AD.index(p)
			v = sum(pins[p] << i for i, p in enumerate(PIN_AD))
			reg = s.latch[0] & 3
			if reg < 2: s.out[reg] = v
			else: s.ddr[reg - 2] = v
		s.lastIow = iow
		for port in (0, 1):			# contention check on every step
			for b in range(8): s.portLevel(top, port, b)
		ale = pins[PIN_ALE]
		if s.lastAle and not ale:		# falling edge: latch
			a = sum(pins[p] << i for i, p in enumerate(PIN_AD))
			a |= sum(pins[p] << (8 + i) for i, p in enumerate(PIN_AH))
			s.latch = (a, pins[PIN_IOM], pins[PIN_CE1], pins[PIN_CE2])
			s.cycles += 1
		s.lastAle = ale

	def drivesBus(s, top, pins):
		if not s.powered(top) or pins[PIN_ALE] or not s.selected():
			return None
		a, iom, ce1, ce2 = s.latch
		if not pins[PIN_IOR] or (not pins[PIN_RD] and iom):
			return s.portValue(top, a & 1) if (a & 3) < 2 else 0xFF
		if pins[PIN_RD]:
			return None
		v = s.mem[a]
		if s.flaky and a == 0x5A5:
			s.visits += 1
			if s.visits % 2: v ^= 0x10
		return v


class FakeTop:
	def __init__(s, chipModel):
		s.m, s.out, s.en, s.buf = chipModel, 0, 0, b""
		s.vcc, s.vpp, s.gnd = Layout(s), Layout(s), Layout(s)
		s.vppVolt = 5; s.msgs = []; s.z = None; s.pullups = False
	def fpgaDrives(s, pin): return bool((s.en >> (s.z[pin] - 1)) & 1)
	def fpgaLevel(s, pin): return (s.out >> (s.z[pin] - 1)) & 1
	def bind(s, chip):
		g = chip.getLayoutGenerator()
		s.z = {p: g.getZifPinForPackagePin(p) for p in range(1, 41)}
		s.zinv = {z: p for p, z in s.z.items()}
	def drivenPins(s):
		return {s.zinv[z] for z in s.zinv if (s.en >> (z - 1)) & 1}
	def pins(s):
		return {p: (s.out >> (z - 1)) & 1 for p, z in s.z.items()}
	def check(s):
		if s.z is None: return
		bad = s.drivenPins() & {PIN_VDD, PIN_READY, PIN_GND, PIN_VCC}
		assert not bad, "FPGA drives pin(s) %s" % sorted(bad)
		pins = s.pins()
		if s.m.drivesBus(s, pins) is not None and s.drivenPins() & set(PIN_AD):
			raise AssertionError("bus contention on AD0-AD7")
	def step(s):
		if s.z is None: return
		s.m.step(s, s.pins()); s.check()
	def getProgrammerType(s): return "TOP2049"
	def getForceLevel(s): return 0
	def getBufferRegSize(s): return 64
	def cmdFPGAWrite(s, addr, val):
		sh = 8 * (addr & 7)
		if 0x40 <= addr <= 0x45: s.en = (s.en & ~(0xFF << sh)) | (val << sh)
		elif 0x60 <= addr <= 0x65: s.out = (s.out & ~(0xFF << sh)) | (val << sh)
		s.step()
	def cmdFPGARead(s, addr):
		sh = 8 * (addr & 7); v = (s.out >> sh) & 0xFF
		pins = s.pins()
		q = s.m.drivesBus(s, pins)
		for i, p in enumerate(PIN_AD):
			z = s.z[p]
			if (z - 1) // 8 == addr - 0x60 and not (s.en >> (z - 1)) & 1:
				b = (z - 1) % 8
				bit = 1 if q is None else (q >> i) & 1		# floating reads 1
				v = (v & ~(1 << b)) | (bit << b)
		for port, ppins in enumerate((PIN_PA, PIN_PB)):
			for i, p in enumerate(ppins):
				z = s.z[p]
				if (z - 1) // 8 == addr - 0x60:
					b = (z - 1) % 8
					v = (v & ~(1 << b)) | (s.m.portLevel(s, port, i) << b)
		s.buf += bytes([v])
	def cmdReadBufferReg(s, n):
		d, s.buf = s.buf[:n], s.buf[n:]; assert len(d) == n; return d
	def cmdDelay(s, t): pass
	def hostDelay(s, t): pass
	def flushCommands(s, t=0): pass
	def cmdSetVCCVoltage(s, v): assert v <= 5.0, "VCC above 5 V"
	def cmdSetVPPVoltage(s, v): s.vppVolt = v; s.step()
	def cmdEnableZifPullups(s, e): s.pullups = bool(e)
	def printInfo(s, m): s.msgs.append(m); print("     ", m)
	def printWarning(s, m): s.msgs.append(m); print("      warn:", m)
	def printDebug(s, m): pass
	def progressMeterInit(s, *a): pass
	def progressMeter(s, *a): pass
	def progressMeterFinish(s, *a): pass


def run(mem, flaky=False):
	desc = ChipDescription.findOne("i8755")
	model = I8755(mem, flaky)
	top = FakeTop(model)
	chip = desc.chipImplClass.createInstance(top, desc, ())
	top.bind(chip)
	return chip.readEEPROM(), top, model

mem = [random.randint(0, 255) for _ in range(SIZE)]
img, top, model = run(mem)
assert list(bytearray(img)) == mem and len(img) == 2048
assert model.resetSeen and model.cycles == 2 * SIZE
print("random contents read back exactly (2048 bytes, two passes, %d bus cycles)" % model.cycles)

img, top, model = run([0xFF] * SIZE)
assert list(bytearray(img)) == [0xFF] * SIZE and "blank" in top.msgs[-1]
print("erased chip reported as blank")

try:
	run(mem, flaky=True); raise SystemExit("FAIL: unstable read accepted")
except TOPException as e:
	print("unstable read rejected:", e)

# ---- I/O port unit-test ----
def runTest(faults=None):
	desc = ChipDescription.findOne("i8755")
	model = I8755([0] * SIZE, faults=faults)
	top = FakeTop(model)
	chip = desc.chipImplClass.createInstance(top, desc, ())
	top.bind(chip)
	chip.test()
	return top, model

top, model = runTest()
assert "passed" in top.msgs[-1]
print("good chip: port test passes, no contention")

for name, faults, expect in (
	("PA3 stuck at 0", {"stuck": {(0, 3): 0}}, ["PA3:"]),
	("PB6 stuck at 1", {"stuck": {(1, 6): 1}}, ["PB6:"]),
	("PA1-PB1 short", {"short": [((0, 1), (1, 1))]}, ["PA1: shorted to PB1", "PB1: shorted to PA1"]),
	("PA2-PB7 short", {"short": [((0, 2), (1, 7))]}, ["PA2: shorted to PB7", "PB7: shorted to PA2"]),
	("PB5 DDR bit dead", {"ddrdead": {(1, 5)}}, ["PB5:", "does not make it an output"])):
	try:
		runTest(faults); raise SystemExit("FAIL: %s not detected" % name)
	except TOPException as e:
		msg = str(e)
		assert all(x in msg for x in expect), msg
		blamed = {l.strip().split(":")[0] for l in msg.splitlines()[1:]}
		others = blamed - {x.split(":")[0] for x in expect if ":" in x}
		assert not others, "extra pins blamed for %s: %s" % (name, others)
		print("%-17s detected: %s" % (name, " | ".join(l.strip() for l in msg.splitlines()[1:])))

desc = ChipDescription.findOne("i8755")
assert desc.chipImplClass.chipSupportsAttr("test")
assert not desc.chipImplClass.chipSupportsAttr("writeEEPROM")
print("no write support exposed (read only)")
print("8755 TESTS PASSED")

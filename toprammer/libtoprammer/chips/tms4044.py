"""
#    TOP2049 Open Source programming suite
#
#    TI TMS4044 / TMS40L44, Intel 2147 and equivalents:
#    4096 x 1 static RAM, DIP18, 5 V.
#
#    Unit-test (-T): March C- (finds stuck-at, transition, address decoder
#    and most coupling faults), then a checkerboard and its inverse with a
#    short retention pause.
#
#    Uses the generic "unitest" FPGA configuration. Din and Dout are separate
#    pins, so the FPGA never has to share a pin with the chip: it drives the
#    address pins, D, /W and /S and only samples Q.
#
#    Pinout (TI TMS4044 data sheet):
#      1 A0   2 A1   3 A2   4 A3   5 A4   6 A5   7 Q    8 /W   9 VSS
#     10 /S  11 D   12 A11 13 A10 14 A9  15 A8  16 A7  17 A6  18 VCC
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
"""

from libtoprammer.chip import *
from libtoprammer.util import *


PIN_A	= (1, 2, 3, 4, 5, 6, 17, 16, 15, 14, 13, 12)	# A0..A11
PIN_Q	= 7	# data out (chip output, never driven)
PIN_W	= 8	# /W, write enable, active low
PIN_VSS	= 9
PIN_S	= 10	# /S, chip select, active low
PIN_D	= 11	# data in
PIN_VCC	= 18
SIZE	= 4096
DRIVEN	= PIN_A + (PIN_W, PIN_S, PIN_D)


class Chip_TMS4044(Chip):

	def __init__(self):
		Chip.__init__(self,
			      chipPackage = "DIP18",
			      chipPinVCC = PIN_VCC,
			      chipPinGND = PIN_VSS)

	def _opt(self, name, default):
		v = self.getChipOptionValue(name, None)
		return default if v is None else v

	def _zif(self, pin):
		return self.generator.getZifPinForPackagePin(pin)

	# ---- FPGA (unitest) pin access ----

	def _set(self, levels):
		new = self.outState
		for pin, val in levels.items():
			bit = 1 << (self._zif(pin) - 1)
			new = (new | bit) if val else (new & ~bit)
		changed = new ^ self.outState
		for i in range(6):
			if (changed >> (8 * i)) & 0xFF:
				self.top.cmdFPGAWrite(0x60 + i, (new >> (8 * i)) & 0xFF)
		self.outState = new

	def _addrLevels(self, addr):
		return { p: (addr >> i) & 1 for i, p in enumerate(PIN_A) }

	# ---- power ----

	def _powerOn(self):
		self.applyVPP(False)
		self.applyVCC(False)
		self.applyGND(False)
		self.top.cmdSetVCCVoltage(5)
		self.top.cmdEnableZifPullups(False)
		self.outState = 0
		for i in range(6):
			self.top.cmdFPGAWrite(0x60 + i, 0)
		self._set({ PIN_W: 1, PIN_S: 1, PIN_D: 0 })
		outEn = 0
		for p in DRIVEN:
			outEn |= 1 << (self._zif(p) - 1)
		for i in range(6):
			self.top.cmdFPGAWrite(0x40 + i, (outEn >> (8 * i)) & 0xFF)
		self.applyGND(True)
		self.applyVCC(True)
		self.top.hostDelay(0.05)
		self._set({ PIN_S: 0 })		# selected for the whole session
		zq = self._zif(PIN_Q)
		self.qReg = 0x60 + (zq - 1) // 8
		self.qBit = (zq - 1) % 8

	def _powerOff(self):
		self._set({ PIN_W: 1, PIN_S: 1 })
		self.applyVCC(False)
		self.applyGND(False)
		for i in range(6):
			self.top.cmdFPGAWrite(0x40 + i, 0)
		self.top.flushCommands()

	def shutdownChip(self):
		self.applyVCC(False)
		self.applyVPP(False)
		self.applyGND(False)
		self.top.cmdSetVCCVoltage(self.top.vcc.minVoltage())
		for i in range(6):
			self.top.cmdFPGAWrite(0x40 + i, 0)
		self.top.flushCommands()

	# ---- bus cycles ----

	def _write(self, addr, bit):
		lv = self._addrLevels(addr)
		lv[PIN_D] = bit
		self._set(lv)			# address + data stable, /W high
		self._set({ PIN_W: 0 })
		self._set({ PIN_W: 1 })		# data is taken on the rising edge

	def _queueRead(self, addr):
		self._set(self._addrLevels(addr))
		self.top.cmdFPGARead(self.qReg)

	# ---- operation stream with batched reads ----

	class _Runner(object):
		def __init__(self, chip, label, nrOps):
			self.chip, self.pending, self.fails = chip, [], {}
			self.batch = chip.top.getBufferRegSize()
			self.done, self.nrOps = 0, nrOps
			self.reads = 0
			chip.progressMeterInit(label, nrOps)

		def write(self, addr, bit):
			self.chip._write(addr, bit)
			self._step()

		def read(self, addr, expect, where):
			self.chip._queueRead(addr)
			self.pending.append((addr, expect, where))
			if len(self.pending) >= self.batch:
				self.flush()
			self._step()

		def _step(self):
			self.done += 1
			if (self.done & 0x3FF) == 0:
				self.chip.progressMeter(self.done)

		def flush(self):
			if not self.pending:
				return
			raw = self.chip.top.cmdReadBufferReg(len(self.pending))
			for (addr, expect, where), b in zip(self.pending, raw):
				got = (byte2int(b) >> self.chip.qBit) & 1
				self.reads += 1
				if got != expect:
					self.fails.setdefault(addr, []).append((where, expect, got))
			self.pending = []

		def finish(self):
			self.flush()
			self.chip.progressMeterFinish()
			return self.fails

	# ---- unit-test ----

	def _addressLines(self, run):
		"""For each address line An: cells 0 and 2^n must be independent.
		If An is open, stuck or shorted, both addresses hit the same cell."""
		for n in range(12):
			b = 1 << n
			tag = "A-line %d" % n
			run.write(0, 0); run.write(b, 1)
			run.read(0, 0, tag); run.read(b, 1, tag)
			run.write(0, 1); run.write(b, 0)
			run.read(0, 1, tag); run.read(b, 0, tag)

	def _marchC(self, run):
		N = SIZE
		up, down = range(N), range(N - 1, -1, -1)
		for a in up:	run.write(a, 0)				# M0 (w0)
		for a in up:	run.read(a, 0, "M1 r0"); run.write(a, 1)	# M1 up (r0,w1)
		for a in up:	run.read(a, 1, "M2 r1"); run.write(a, 0)	# M2 up (r1,w0)
		for a in down:	run.read(a, 0, "M3 r0"); run.write(a, 1)	# M3 down (r0,w1)
		for a in down:	run.read(a, 1, "M4 r1"); run.write(a, 0)	# M4 down (r1,w0)
		for a in up:	run.read(a, 0, "M5 r0")			# M5 (r0)

	@staticmethod
	def _checker(addr):
		# Assumes a 64 x 64 cell array (A0-A5 one way, A6-A11 the other).
		return ((addr & 0x3F) ^ (addr >> 6)) & 1

	def _checkerboard(self, run, invert, pause):
		for a in range(SIZE):
			run.write(a, self._checker(a) ^ invert)
		run.flush()
		self.top.flushCommands()
		self.top.hostDelay(pause)	# static cells must hold their data
		name = "checkerboard%s" % (" inverted" if invert else "")
		for a in range(SIZE):
			run.read(a, self._checker(a) ^ invert, name)

	def test(self):
		pause = float(self._opt("retention_pause", 1.0))
		nrOps = 12 * 8 + 10 * SIZE + 4 * SIZE
		self._powerOn()
		try:
			run = self._Runner(self, "Testing 4K x 1 SRAM", nrOps)
			self._addressLines(run)
			run.flush()
			badLines = sorted({ int(w[0].split()[1]) for f in run.fails.values()
					    for w in f if w[0].startswith("A-line") })
			run.fails = {}
			self._marchC(run)
			for invert in (0, 1):
				self._checkerboard(run, invert, pause)
			fails = run.finish()
		finally:
			self._powerOff()
		if not fails:
			self.printInfo("RAM test passed: all 4096 cells (March C- 10N, "
				       "checkerboard + inverse, %.1f s retention)" % pause)
			return
		self.throwError(self._describe(fails, run.reads, badLines))

	def _describe(self, fails, nrReads, badLines=()):
		nBad = len(fails)
		allGot = { got for f in fails.values() for (_, _, got) in f }
		nFailReads = sum(len(f) for f in fails.values())
		if nBad == SIZE and nFailReads * 2 >= nrReads and len(allGot) == 1:
			g = allGot.pop()
			return ("RAM test FAILED: every cell fails and Q always reads %d. "
				"No chip, chip inserted the wrong way, or Q stuck at %d." % (g, g))
		if badLines:
			lines = [ "A%d (pin %d)" % (n, PIN_A[n]) for n in badLines ]
			return ("RAM test FAILED: address line%s %s not working: addresses "
				"that differ only in %s reach the same cell (open, stuck or shorted "
				"line, or a bad socket contact). %d of 4096 cells then fail the "
				"March test." % ("s" if len(badLines) > 1 else "", ", ".join(lines),
				"that bit" if len(badLines) == 1 else "those bits", nBad))
		lines = []
		for addr in sorted(fails)[:12]:
			f = fails[addr]
			kinds = sorted({ "%s (expected %d, read %d)" % w for w in f })
			lines.append("  0x%03X (A11..A0 = %s): %s" %
				     (addr, format(addr, "012b"), "; ".join(kinds[:3])))
		more = "" if nBad <= 12 else "\n  ... and %d more" % (nBad - 12)
		hint = ""
		return "RAM test FAILED: %d of 4096 cells bad.\n%s%s%s" % (
			nBad, "\n".join(lines), more, hint)


_OPTIONS = (
	ChipOptionFloat("retention_pause", "Seconds to wait before reading back the "
			"checkerboard (default 1.0)", minVal=0.0, maxVal=60.0),
)

ChipDescription(
	Chip_TMS4044,
	bitfile = "unitest",
	chipID = "tms4044",
	runtimeID = (8, 1),
	chipType = ChipDescription.TYPE_SRAM,
	chipVendors = ("Texas Instruments", "Intel"),
	description = "TMS4044 / TMS40L44 / 2147 static RAM 4K x 1",
	packages = ( ("DIP18", ""), ),
	comment = "RAM test only (-T / Run unit-test): March C- plus checkerboard "
		  "and inverse with a retention pause.",
	chipOptions = _OPTIONS,
	maintainer = "Kris",
)

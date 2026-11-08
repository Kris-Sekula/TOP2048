"""
#    TOP2049 Open Source programming suite
#
#    74S571 / Tesla MH74S571 bipolar PROM, 512 x 4, DIP16 -- READ ONLY
#
#    Reads (dumps), and through the GUI verifies, 512x4 tri-state bipolar
#    PROMs at 5 V. Programming is NOT supported: blowing the fuses needs
#    VCC raised to ~10.5 V at several hundred mA and each data pin pulled
#    hard to 0 V (up to ~150 mA), which the TOP2049's drivers cannot do.
#
#    Uses the generic "unitest" FPGA configuration: the FPGA drives the
#    address and /CE pins, and only ever samples the data pins.
#
#    Image format: 512 bytes, one per address, the 4 data bits in the low
#    nibble (D0 = bit 0), high nibble 0 -- the usual format for 4-bit PROM
#    dumps (e.g. MAME). A blank PROM reads all 0.
#
#    Pinout (TI SN74S571 / Tesla MH74S571):
#      1 A6   2 A5   3 A4   4 A3   5 A0   6 A1   7 A2   8 GND
#      9 D3  10 D2  11 D1  12 D0  13 /CE 14 A8  15 A7  16 VCC
#    Option swap_a0_a2=1 exchanges A0 and A2 (some pinout transcriptions
#    list pins 5..7 as A2, A1, A0).
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
"""

from libtoprammer.chip import *
from libtoprammer.util import *


PIN_A = (5, 6, 7, 4, 3, 2, 1, 15, 14)	# A0..A8
PIN_D = (12, 11, 10, 9)			# D0..D3
PIN_CE = 13				# /CE, active low
PIN_VCC = 16
PIN_GND = 8
SIZE = 512


class Chip_PROM74S571(Chip):

	def __init__(self):
		Chip.__init__(self,
			      chipPackage = "DIP16",
			      chipPinVCC = PIN_VCC,
			      chipPinGND = PIN_GND)

	def _opt(self, name, default):
		v = self.getChipOptionValue(name, None)
		return default if v is None else v

	def _zif(self, pin):
		return self.generator.getZifPinForPackagePin(pin)

	def _addrPins(self):
		a = list(PIN_A)
		if self._opt("swap_a0_a2", False):
			a[0], a[2] = a[2], a[0]
		return a

	# ---- FPGA (unitest) pin access ----

	def _writeOutEn(self, mask):
		for i in range(6):
			self.top.cmdFPGAWrite(0x40 + i, (mask >> (8 * i)) & 0xFF)

	def _set(self, levels):
		old = self.outState
		for pin, val in levels.items():
			bit = 1 << (self._zif(pin) - 1)
			self.outState = (self.outState | bit) if val else (self.outState & ~bit)
		changed = old ^ self.outState
		for i in range(6):
			if (changed >> (8 * i)) & 0xFF:
				self.top.cmdFPGAWrite(0x60 + i, (self.outState >> (8 * i)) & 0xFF)

	# ---- power ----

	def _powerOn(self):
		self.applyVPP(False)
		self.top.cmdSetVPPVoltage(5)
		self.top.cmdSetVCCVoltage(5)
		self.top.cmdEnableZifPullups(bool(self._opt("pullups", False)))
		self.addrPins = self._addrPins()
		# The FPGA drives addresses and /CE only - never the data outputs.
		self.outState = 0
		outEn = 0
		for p in self.addrPins + [PIN_CE]:
			outEn |= 1 << (self._zif(p) - 1)
		for i in range(6):
			self.top.cmdFPGAWrite(0x60 + i, 0)
		self._set({ PIN_CE: 1 })			# outputs disabled while powering up
		self._writeOutEn(outEn)
		self.applyGND(True)
		self.applyVCC(True)
		self.top.hostDelay(0.05)
		self._set({ PIN_CE: 0 })			# enable outputs, keep enabled
		self.top.cmdDelay(0.0001)
		zd = [ self._zif(p) for p in PIN_D ]
		regs = sorted({ 0x60 + (z - 1) // 8 for z in zd })
		self.dataRegs = regs
		self.dataMap = [ (regs.index(0x60 + (z - 1) // 8), (z - 1) % 8) for z in zd ]

	def _powerOff(self):
		self._set({ PIN_CE: 1 })
		self.applyVCC(False)
		self.applyGND(False)
		self._writeOutEn(0)
		self.top.flushCommands()

	def shutdownChip(self):
		self.applyVCC(False)
		self.applyVPP(False)
		self.applyGND(False)
		self.top.cmdSetVCCVoltage(self.top.vcc.minVoltage())
		self.top.cmdSetVPPVoltage(self.top.vpp.minVoltage())
		self._writeOutEn(0)
		self.top.flushCommands()

	# ---- read ----

	def _readAll(self, label):
		nRegs = len(self.dataRegs)
		perChunk = self.top.getBufferRegSize() // nRegs
		image = []
		self.progressMeterInit(label, SIZE)
		addr = 0
		while addr < SIZE:
			n = min(perChunk, SIZE - addr)
			for a in range(addr, addr + n):
				self._set({ p: (a >> i) & 1 for i, p in enumerate(self.addrPins) })
				for r in self.dataRegs:
					self.top.cmdFPGARead(r)
			raw = self.top.cmdReadBufferReg(n * nRegs)
			for k in range(n):
				v = 0
				for bit, (ri, b) in enumerate(self.dataMap):
					v |= ((byte2int(raw[k * nRegs + ri]) >> b) & 1) << bit
				image.append(v)
			addr += n
			self.progressMeter(addr)
		self.progressMeterFinish()
		return image

	def readEEPROM(self):
		self._powerOn()
		try:
			first = self._readAll("Reading PROM")
			second = self._readAll("Re-reading PROM")
		finally:
			self._powerOff()
		diff = [ a for a in range(SIZE) if first[a] != second[a] ]
		if diff:
			self.throwError("Two reads differ at %d address(es), first 0x%03X "
				"(%X vs %X). Check the chip's seating and orientation." %
				(len(diff), diff[0], first[diff[0]], second[diff[0]]))
		used = sum(1 for v in first if v)
		ones = sum(bin(v).count("1") for v in first)
		if used == 0:
			self.printInfo("PROM is blank (all 512 locations read 0)")
		elif all(v == 0xF for v in first):
			self.printWarning("All locations read F - is a chip inserted? "
				"(a programmed PROM rarely reads all F)")
		else:
			self.printInfo("%d of 512 locations non-zero, %d of 2048 fuses blown, "
				"sum %04X" % (used, ones, sum(first) & 0xFFFF))
		return bytes(bytearray(first))


_OPTIONS = (
	ChipOptionBool("swap_a0_a2", "Exchange A0 and A2 (alternative pinout transcription)"),
	ChipOptionBool("pullups", "Enable the ZIF pull-ups (default off)"),
)
_COMMENT = ("READ ONLY. 512 bytes, data in the low nibble. Blank = all 0. "
	    "Programming needs ~10.5 V / high-current drivers the TOP2049 lacks.")

ChipDescription(
	Chip_PROM74S571,
	bitfile = "unitest",
	chipID = "mh74s571",
	runtimeID = (8, 1),
	chipType = ChipDescription.TYPE_EPROM,
	chipVendors = ("Tesla", "Texas Instruments", "National"),
	description = "MH74S571 / SN74S571 / DM74S571 bipolar PROM 512x4 (read only)",
	packages = ( ("DIP16", ""), ),
	comment = _COMMENT,
	chipOptions = _OPTIONS,
	maintainer = "Kris",
)

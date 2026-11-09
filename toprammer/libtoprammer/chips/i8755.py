"""
#    TOP2049 Open Source programming suite
#
#    Intel 8755 / 8755A (2K x 8 EPROM + 2 I/O ports) and 8355 (mask ROM
#    version), DIP40 -- READ ONLY
#
#    The chip is read the way an 8085 reads it, one bus cycle per byte:
#      1. drive A0-A7 on AD0-AD7, A8-A10, IO/M=0, /CE1=0, CE2=1, ALE high
#      2. ALE low: the chip latches the address and chip enables
#      3. release AD0-AD7, pull /RD low, sample AD0-AD7, /RD high
#    CLK is not needed for a read; it only releases READY (a wait-state
#    output). One CLK pulse per cycle is given anyway, as an 8085 would. Everything runs on the generic "unitest" FPGA
#    configuration: the host sets and samples the ZIF pins.
#
#    VDD (pin 5) must be at VCC level for reading. It is fed from the VPP
#    driver set to 5 V (the TOP2049 cannot program the 8755A anyway: that
#    needs VDD = 25 V, above the 21 V maximum of the VPP generator).
#
#    Image: 2048 bytes, address 0 first. A blank (erased) 8755A reads FF.
#
#    Pinout (Intel 8355/8755/8755A):
#      1 PROG,/CE1   2 CE2    3 CLK    4 RESET   5 VDD    6 READY
#      7 IO,/M       8 /IOR   9 /RD   10 /IOW   11 ALE   12-19 AD0-AD7
#     20 VSS     21-23 A8-A10      24-31 PA0-PA7   32-39 PB0-PB7  40 VCC
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
"""

from libtoprammer.chip import *
from libtoprammer.util import *


PIN_CE1		= 1	# also PROG; active low for reading
PIN_CE2		= 2
PIN_CLK		= 3
PIN_RESET	= 4
PIN_VDD		= 5	# from the VPP driver at 5 V
PIN_READY	= 6	# chip output, never driven
PIN_IOM		= 7
PIN_IOR		= 8
PIN_RD		= 9
PIN_IOW		= 10
PIN_ALE		= 11
PIN_AD		= tuple(range(12, 20))		# AD0..AD7
PIN_GND		= 20
PIN_AH		= (21, 22, 23)			# A8..A10
PIN_PA		= tuple(range(24, 32))		# chip I/O, never driven
PIN_PB		= tuple(range(32, 40))		# chip I/O, never driven
PIN_VCC		= 40
SIZE		= 2048

# Pins the FPGA drives (all others are left as inputs)
DRIVEN_ALWAYS = (PIN_CE1, PIN_CE2, PIN_CLK, PIN_RESET, PIN_IOM, PIN_IOR,
		 PIN_RD, PIN_IOW, PIN_ALE) + PIN_AH


class Chip_i8755(Chip):

	def __init__(self):
		Chip.__init__(self,
			      chipPackage = "DIP40",
			      chipPinVCC = PIN_VCC,
			      chipPinsVPP = (PIN_VDD,),
			      chipPinGND = PIN_GND)

	def _opt(self, name, default):
		v = self.getChipOptionValue(name, None)
		return default if v is None else v

	def _zif(self, pin):
		return self.generator.getZifPinForPackagePin(pin)

	# ---- FPGA (unitest) pin access ----

	def _writeRegs(self, base, new, old):
		changed = new ^ old
		for i in range(6):
			if (changed >> (8 * i)) & 0xFF:
				self.top.cmdFPGAWrite(base + i, (new >> (8 * i)) & 0xFF)

	def _set(self, levels):
		new = self.outState
		for pin, val in levels.items():
			bit = 1 << (self._zif(pin) - 1)
			new = (new | bit) if val else (new & ~bit)
		self._writeRegs(0x60, new, self.outState)
		self.outState = new

	def _drive(self, pins, enable):
		new = self.outEn
		for pin in pins:
			bit = 1 << (self._zif(pin) - 1)
			new = (new | bit) if enable else (new & ~bit)
		self._writeRegs(0x40, new, self.outEn)
		self.outEn = new

	# ---- power ----

	def _powerOn(self):
		self.applyVCC(False)
		self.applyVPP(False)
		self.applyGND(False)
		self.top.cmdSetVCCVoltage(5)
		self.top.cmdSetVPPVoltage(5)	# VDD = VCC for reading. Never more.
		self.top.cmdEnableZifPullups(bool(self._opt("pullups", False)))
		# Idle bus state: deselected, no strobes, RESET asserted
		self.outState = 0
		self.outEn = 0
		for i in range(6):
			self.top.cmdFPGAWrite(0x60 + i, 0)
			self.top.cmdFPGAWrite(0x40 + i, 0)
		self._set({ PIN_CE1: 1, PIN_CE2: 0, PIN_CLK: 0, PIN_RESET: 1,
			    PIN_IOM: 0, PIN_IOR: 1, PIN_RD: 1, PIN_IOW: 1,
			    PIN_ALE: 0 })
		self._drive(DRIVEN_ALWAYS, True)
		self.applyGND(True)
		self.applyVCC(True)
		self.applyVPP(True)		# VDD (pin 5) at 5 V
		self.top.hostDelay(0.05)
		self._set({ PIN_RESET: 0 })	# RESET makes both ports inputs
		self.top.cmdDelay(0.001)
		zd = [ self._zif(p) for p in PIN_AD ]
		regs = sorted({ 0x60 + (z - 1) // 8 for z in zd })
		self.dataRegs = regs
		self.dataMap = [ (regs.index(0x60 + (z - 1) // 8), (z - 1) % 8) for z in zd ]

	def _powerOff(self):
		self._drive(PIN_AD, False)
		self._set({ PIN_RD: 1, PIN_CE1: 1, PIN_CE2: 0, PIN_ALE: 0 })
		self.applyVPP(False)
		self.applyVCC(False)
		self.applyGND(False)
		self._drive(DRIVEN_ALWAYS, False)
		self.top.flushCommands()

	def shutdownChip(self):
		self.applyVCC(False)
		self.applyVPP(False)
		self.applyGND(False)
		self.top.cmdSetVCCVoltage(self.top.vcc.minVoltage())
		self.top.cmdSetVPPVoltage(self.top.vpp.minVoltage())
		for i in range(6):
			self.top.cmdFPGAWrite(0x40 + i, 0)
		self.top.flushCommands()

	# ---- read ----

	def _busRead(self, addr):
		"""Queue one 8085-style memory read cycle; the byte lands in the
		FPGA read buffer."""
		lv = { p: (addr >> i) & 1 for i, p in enumerate(PIN_AD) }
		lv.update({ p: (addr >> (8 + i)) & 1 for i, p in enumerate(PIN_AH) })
		lv.update({ PIN_IOM: 0, PIN_CE1: 0, PIN_CE2: 1, PIN_ALE: 1 })
		self._drive(PIN_AD, True)	# /RD is high: the chip isn't driving
		self._set(lv)
		self._set({ PIN_ALE: 0 })	# latch address + chip enables
		self._set({ PIN_CLK: 1 })	# one clock, like an 8085 bus cycle:
		self._set({ PIN_CLK: 0 })	# releases READY
		self._drive(PIN_AD, False)	# hand the bus to the chip
		self._set({ PIN_RD: 0 })
		for r in self.dataRegs:
			self.top.cmdFPGARead(r)
		self._set({ PIN_RD: 1 })

	def _readAll(self, label):
		nRegs = len(self.dataRegs)
		perChunk = self.top.getBufferRegSize() // nRegs
		image = []
		self.progressMeterInit(label, SIZE)
		addr = 0
		while addr < SIZE:
			n = min(perChunk, SIZE - addr)
			for a in range(addr, addr + n):
				self._busRead(a)
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
			first = self._readAll("Reading 8755")
			second = self._readAll("Re-reading 8755")
		finally:
			self._powerOff()
		diff = [ a for a in range(SIZE) if first[a] != second[a] ]
		if diff:
			self.throwError("Two reads differ at %d address(es), first 0x%03X "
				"(%02X vs %02X). Check the chip's seating and orientation." %
				(len(diff), diff[0], first[diff[0]], second[diff[0]]))
		if all(v == 0xFF for v in first):
			self.printInfo("All 2048 bytes read FF: blank (erased) 8755A, "
				"or no chip / chip not responding")
		elif all(v == 0x00 for v in first):
			self.printWarning("All bytes read 00 - check the chip is inserted "
				"the right way round (pin 1 at ZIF pin 5)")
		else:
			used = sum(1 for v in first if v != 0xFF)
			self.printInfo("%d of 2048 bytes programmed (not FF), sum %04X" %
				(used, sum(first) & 0xFFFF))
		return bytes(bytearray(first))


_OPTIONS = (
	ChipOptionBool("pullups", "Enable the ZIF pull-ups (default off)"),
)
_COMMENT = ("READ ONLY. 2048 bytes. Blank 8755A = all FF. Also reads the 8355 "
	    "mask ROM. Programming needs VDD = 25 V, above the TOP2049's 21 V.")

ChipDescription(
	Chip_i8755,
	bitfile = "unitest",
	chipID = "i8755",
	runtimeID = (8, 1),
	chipType = ChipDescription.TYPE_EPROM,
	chipVendors = ("Intel",),
	description = "8755 / 8755A / 8355 ROM+I/O, 2K x 8 (read only)",
	packages = ( ("DIP40", ""), ),
	comment = _COMMENT,
	chipOptions = _OPTIONS,
	maintainer = "Kris",
)

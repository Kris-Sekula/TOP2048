"""
#    TOP2049 Open Source programming suite
#
#    Lattice / National / ST GAL programming:
#        GAL16V8 (A/B/D)  DIP20
#        GAL20V8 (A/B)    DIP24
#        GAL22V10 (B/D)   DIP24
#
#    The GAL is driven in its serial "edit mode" by bit-banging the ZIF pins
#    through the generic "unitest" FPGA configuration, so no dedicated FPGA
#    bitstream is needed.
#
#    Fuse files: --read-fuse writes a JEDEC (.jed) file, --write-fuse accepts
#    a JEDEC file (GALasm, WinCUPL, ...) or a raw fuse bitmap
#    (fuse n = bit n%8 of byte n/8). Use "-I bin" / "-O bin".
#
#    Algorithm, row maps, PES decoding and config-bit order follow the
#    publicly documented GAL programming method (GALBLAST / ATFblast /
#    GALer / Afterburner).
#
#    Lessons from real hardware (TOP2049, GAL16V8A/D):
#      * SDIN must be stable across both SCLK edges (some parts sample on
#        the falling edge).
#      * Early GAL16V8A parts have an open-drain SDOUT -> ZIF pull-ups on.
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
"""

from libtoprammer.chip import *
from libtoprammer.util import *
import re


MANUFACTURERS = {
	0xA1: "Lattice",
	0x8F: "National",
	0x20: "ST Microelectronics",
}
NATIONAL = 0x8F

READ_VPP = 12.0		# edit-mode voltage for reading (all algorithms)
MAX_VPP = 16.5		# never exceed (GAL absolute max for EDIT)

# Order in which the 82 ACW bits of the V8 parts are shifted, as offsets
# from the config base fuse. JEDEC (16V8 base 2048, 20V8 base 2560):
#   +0..7 XOR, (UES), +72..79 AC1, +80..143 PTD, +144 SYN, +145 AC0
CFG_MAP_V8AB = (			# GAL16V8A/B/D, GAL20V8A/B
	0, 1, 2, 3,				# XOR(n) first four OLMCs
	145,					# AC0
	72, 73, 74, 75,				# AC1(n) first four
) + tuple(range(80, 144)) + (		# PTD 0..63
	76, 77, 78, 79,				# AC1(n) last four
	144,					# SYN
	4, 5, 6, 7,				# XOR(n) last four
)
CFG_MAP_V8 = tuple(range(80, 112)) + (	# original GAL16V8 / GAL20V8
	0, 1, 2, 3,
	145,
	72, 73, 74, 75, 76, 77, 78, 79,
	144,
	4, 5, 6, 7,
) + tuple(range(112, 144))
assert len(CFG_MAP_V8AB) == 82 and len(CFG_MAP_V8) == 82

# GAL22V10: 20 config bits (S0/S1 per OLMC), base 5808
CFG_MAP_V10 = (1, 0, 3, 2, 5, 4, 7, 6, 9, 8, 11, 10, 13, 12, 15, 14, 17, 16, 19, 18)


class GalSpec(object):
	"Geometry, pinout and protocol of one GAL type."
	def __init__(self, **kw):
		self.__dict__.update(kw)

GAL16V8 = GalSpec(
	name = "GAL16V8", family = "V8", package = "DIP20", pins = 20,
	vcc = 20, gnd = 10, edit = 2,
	ra = (18, 3, 4, 5, 6, 7),		# RAG0..RAG5
	sclk = 8, sdin = 9, stb = 11, sdout = 12, pv = 19,
	vil = (1, 13, 14, 15, 16, 17),
	nrFuses = 2194, rows = 32, rowBits = 64,
	uesRow = 32, uesFuse = 2056, uesBits = 64,
	cfgRow = 60, cfgBase = 2048,
	pesRow = 58, pesBytes = 8,
	eraseRow = 63, securityRow = 61,
	ids = { 0x00: "GAL16V8", 0x1A: "GAL16V8A/B/D" }, idsV8AB = (0x1A,),
	jedecTail = ((2048, 8), (2056, 64), (2120, 8), (2128, 64), (2192, 1), (2193, 1)),
	tailNames = ("XOR", "UES", "AC1", "PTD", "SYN", "AC0"),
)

GAL20V8 = GalSpec(
	name = "GAL20V8", family = "V8", package = "DIP24", pins = 24,
	vcc = 24, gnd = 12, edit = 2,
	ra = (21, 3, 4, 5, 8, 9),		# RAG0..RAG5
	sclk = 10, sdin = 11, stb = 13, sdout = 15, pv = 22,
	vil = (1, 6, 7, 14, 16, 17, 18, 19, 20, 23),
	nrFuses = 2706, rows = 40, rowBits = 64,
	uesRow = 40, uesFuse = 2568, uesBits = 64,
	cfgRow = 60, cfgBase = 2560,
	pesRow = 58, pesBytes = 8,
	eraseRow = 63, securityRow = 61,
	ids = { 0x20: "GAL20V8", 0x3A: "GAL20V8A/B" }, idsV8AB = (0x3A,),
	jedecTail = ((2560, 8), (2568, 64), (2632, 8), (2640, 64), (2704, 1), (2705, 1)),
	tailNames = ("XOR", "UES", "AC1", "PTD", "SYN", "AC0"),
)

GAL22V10 = GalSpec(
	name = "GAL22V10", family = "V10", package = "DIP24", pins = 24,
	vcc = 24, gnd = 12, edit = 2,
	ra = (4, 5, 6, 7, 8, 9),		# RAG0..RAG5
	sclk = 10, sdin = 11, stb = 13, sdout = 14, pv = 3,
	vil = (1, 15, 16, 17, 18, 19, 20, 21, 22, 23),
	nrFuses = 5892, rows = 44, rowBits = 132,
	uesRow = 44, uesFuse = 5828, uesBits = 64,
	cfgRow = 16, cfgBase = 5808,
	pesRow = 58, pesBytes = 10,
	eraseRow = 61, securityRow = None,
	ids = { 0x48: "GAL22V10", 0x49: "GAL22V10" }, idsV8AB = (),
	jedecTail = ((5808, 20), (5828, 64)),
	tailNames = ("S0/S1", "UES"),
)


# ---------------------------------------------------------------------------
# JEDEC helpers
# ---------------------------------------------------------------------------

def jedecParse(data, spec):
	"""Parse a JEDEC fuse file. Returns (fuses list of 0/1, securityFlag)."""
	nrFuses = spec.nrFuses
	text = data.decode("ascii", "replace")
	stx = text.find("\x02")
	if stx >= 0:
		text = text[stx + 1:]
	etx = text.find("\x03")
	if etx >= 0:
		text = text[:etx]
	fuses = None
	default = 0
	security = False
	declared = None
	m = re.search(r"\*\s*QF\s*(\d+)", text)
	if m and int(m.group(1)) != nrFuses:
		raise TOPException("JEDEC file is for a device with %d fuses, "
				   "%s has %d (wrong device selected?)" %
				   (int(m.group(1)), spec.name, nrFuses))
	for field in text.split("*")[1:] if "*" in text else []:
		field = field.strip()
		if not field:
			continue
		key = field[0]
		body = field[1:]
		if key == "Q" and body.startswith("F"):
			declared = int(re.sub(r"\s", "", body[1:]))
		elif key == "F":
			default = int(body.strip() or "0") & 1
		elif key == "G":
			security = (body.strip() or "0") != "0"
		elif key == "L":
			m = re.match(r"\s*(\d+)\s+([01\s]+)$", body, re.S)
			if not m:
				raise TOPException("JEDEC: bad L field: %r" % field[:40])
			if fuses is None:
				fuses = [default] * nrFuses
			addr = int(m.group(1))
			bits = re.sub(r"\s", "", m.group(2))
			if addr + len(bits) > nrFuses:
				raise TOPException("JEDEC: fuse %d out of range (%s has %d)" %
						   (addr + len(bits) - 1, spec.name, nrFuses))
			for i, b in enumerate(bits):
				fuses[addr + i] = 1 if b == "1" else 0
	if declared is not None and declared != nrFuses:
		raise TOPException("JEDEC file is for a device with %d fuses, "
				   "%s has %d (wrong device in the design?)" %
				   (declared, spec.name, nrFuses))
	if fuses is None:
		fuses = [default] * nrFuses
	return fuses, security

def jedecChecksum(fuses):
	s = 0
	for i in range(0, len(fuses), 8):
		byte = 0
		for j, b in enumerate(fuses[i:i + 8]):
			byte |= (b & 1) << j
		s += byte
	return s & 0xFFFF

def jedecCreate(fuses, spec, pes=None, security=False):
	lines = [ "\x02",
		  "TOP2049 toprammer %s readout*" % spec.name,
		  "QP%d*" % spec.pins, "QF%d*" % spec.nrFuses, "QV0*", "F0*",
		  "G1*" if security else "G0*" ]
	if pes is not None:
		lines.insert(2, "N PES %s*" % " ".join("%02X" % b for b in bytearray(pes)))
	arraySize = spec.rows * spec.rowBits
	for addr in range(0, arraySize, spec.rows):
		lines.append("L%05d %s*" % (addr, "".join(str(b) for b in fuses[addr:addr + spec.rows])))
	for addr, n in spec.jedecTail:
		lines.append("L%05d %s*" % (addr, "".join(str(b) for b in fuses[addr:addr + n])))
	lines.append("C%04X*" % jedecChecksum(fuses))
	body = "\r\n".join(lines) + "\r\n\x03"
	fileSum = sum(body.encode("ascii")) & 0xFFFF
	return (body + "%04X\r\n" % fileSum).encode("ascii")

def fuseMapText(fuses, spec, security=False):
	"""Human readable fuse map: address ranges and bit values, one product
	term per line, followed by the configuration / signature fields."""
	out = []
	ones = sum(fuses)
	out.append("%s   %d fuses, %d set to 1, JEDEC fuse checksum %04X%s" % (
		spec.name, spec.nrFuses, ones, jedecChecksum(fuses),
		",  SECURITY FUSE requested (G1)" if security else ""))
	out.append("")
	out.append("AND array: %d product terms x %d inputs  (1 = input not connected)" %
		   (spec.rowBits, spec.rows))
	w = len(str(spec.nrFuses - 1))
	for pt in range(spec.rowBits):
		a = pt * spec.rows
		bits = fuses[a:a + spec.rows]
		out.append("  %0*d-%0*d  PT%-3d %s" % (w, a, w, a + spec.rows - 1, pt,
			"".join(str(b) for b in bits)))
	out.append("")
	for (a, n), name in zip(spec.jedecTail, spec.tailNames):
		bits = fuses[a:a + n]
		line = "  %0*d-%0*d  %-5s %s" % (w, a, w, a + n - 1, name, "".join(str(b) for b in bits))
		if name == "UES":
			raw = bytes(bytearray(sum(bits[8 * i + j] << (7 - j) for j in range(8))
					      for i in range(n // 8)))
			txt = "".join(chr(c) if 32 <= c < 127 else "." for c in bytearray(raw))
			line += "   \"%s\"" % txt
		out.append(line)
	return "\n".join(out)

def specForChipDescription(desc):
	"GalSpec for a ChipDescription, or None if it is not a GAL handled here."
	cls = getattr(desc, "chipImplClass", None)
	return getattr(cls, "SPEC", None) if cls and issubclass(cls, Chip_GAL) else None

def fusesFromImage(image, spec):
	"JEDEC text or raw bitmap -> (fuses, security)"
	if b"*" in image and (b"L" in image or b"QF" in image):
		return jedecParse(image, spec)
	if len(image) * 8 < spec.nrFuses:
		raise TOPException("Fuse image too small: %d bytes, need %d "
				   "(or pass a JEDEC .jed file)" %
				   (len(image), (spec.nrFuses + 7) // 8))
	fuses = [ (byte2int(image[i // 8]) >> (i % 8)) & 1 for i in range(spec.nrFuses) ]
	return fuses, False


# ---------------------------------------------------------------------------
# Generic GAL chip
# ---------------------------------------------------------------------------

class Chip_GAL(Chip):
	SPEC = None

	def __init__(self):
		s = self.SPEC
		Chip.__init__(self,
			      chipPackage = s.package,
			      chipPinVCC = s.vcc,
			      chipPinsVPP = s.edit,
			      chipPinGND = s.gnd)
		self.spec = s
		self.pes = None

	# ---- low level pin access (unitest FPGA config) ----

	def _zif(self, pin):
		return self.generator.getZifPinForPackagePin(pin)

	def _pinsInit(self):
		s = self.spec
		self.outState = 0		# 48-bit shadow of FPGA output register
		self.outEn = 0
		for p in s.ra + s.vil + (s.sclk, s.sdin, s.stb, s.pv, s.edit):
			self.outEn |= 1 << (self._zif(p) - 1)
		z = self._zif(s.sdout)
		self.sdoutReg = 0x60 + (z - 1) // 8
		self.sdoutBit = (z - 1) % 8
		self._writeAllOut()
		self._writeOutEn()

	def _writeOutEn(self):
		for i in range(6):
			self.top.cmdFPGAWrite(0x40 + i, (self.outEn >> (8 * i)) & 0xFF)

	def _writeAllOut(self):
		for i in range(6):
			self.top.cmdFPGAWrite(0x60 + i, (self.outState >> (8 * i)) & 0xFF)

	def _set(self, levels):
		"levels: {packagePin: 0/1}. Only changed register bytes are written."
		old = self.outState
		for pin, val in levels.items():
			bit = 1 << (self._zif(pin) - 1)
			if val:
				self.outState |= bit
			else:
				self.outState &= ~bit
		changed = old ^ self.outState
		for i in range(6):
			if (changed >> (8 * i)) & 0xFF:
				self.top.cmdFPGAWrite(0x60 + i, (self.outState >> (8 * i)) & 0xFF)

	def _pin(self, pin, val):
		self._set({ pin: val })

	def _setRow(self, row):
		self._set({ p: (row >> i) & 1 for i, p in enumerate(self.spec.ra) })

	def _clkDelay(self):
		us = self._opt("clk_delay_us", 0)
		if us:
			self.top.cmdDelay(us / 1000000.0)

	def _sendBits(self, bits):
		"""Shift bits into SDIN (first element first). SDIN changes only
		while SCLK is low and is stable across both clock edges."""
		s = self.spec
		for b in bits:
			self._pin(s.sdin, b)		# SCLK is low here
			self._clkDelay()
			self._pin(s.sclk, 1)
			self._clkDelay()
			self._pin(s.sclk, 0)
			self._clkDelay()

	def _sendAddress(self, row):
		"V10: shift the 6-bit row address LSB first, then leave SDIN low."
		self._sendBits([ (row >> i) & 1 for i in range(6) ])
		self._pin(self.spec.sdin, 0)

	def _receiveBits(self, n):
		"Read n bits from SDOUT (sample, then clock)."
		s = self.spec
		bits = []
		while n > 0:
			chunk = min(n, self.top.getBufferRegSize())
			for i in range(chunk):
				self.top.cmdFPGARead(self.sdoutReg)
				self._pin(s.sclk, 1)
				self._clkDelay()
				self._pin(s.sclk, 0)
				self._clkDelay()
			data = self.top.cmdReadBufferReg(chunk)
			bits.extend((byte2int(data[i]) >> self.sdoutBit) & 1 for i in range(chunk))
			n -= chunk
		return bits

	def _strobe(self, seconds):
		self._pin(self.spec.stb, 0)
		self.top.cmdDelay(seconds)
		self._pin(self.spec.stb, 1)

	def _readStrobe(self):
		self._strobe(self._opt("read_strobe_us", 200) / 1000000.0)

	def _loadRowForRead(self, row):
		"Select a row and load it into the output shift register."
		if self.spec.family == "V8":
			self._setRow(row)
		else:
			self._setRow(0)
			self._sendAddress(row)
		self._readStrobe()

	# ---- edit mode on / off ----

	def _editModeOn(self, vpp):
		s = self.spec
		vpp = min(vpp, MAX_VPP)
		self.printDebug("Enter edit mode, EDIT = %.2f V" % vpp)
		self.applyVPP(False)
		self.top.cmdSetVCCVoltage(5)
		self.top.cmdSetVPPVoltage(5)
		# Early GAL16V8A parts have an open-drain SDOUT
		self.top.cmdEnableZifPullups(bool(self._opt("pullups", True)))
		self._pinsInit()
		lv = { p: 0 for p in s.vil }
		lv.update({ s.pv: 0, s.sdin: 1, s.sclk: 1, s.stb: 1, s.edit: 0 })
		self._set(lv)
		self._setRow(0x3F)
		self.applyGND(True)
		self.applyVCC(True)
		self.top.hostDelay(self._opt("vcc_settle_ms", 100) / 1000.0)
		self._pin(s.sclk, 0)
		# hand the EDIT pin over from the FPGA to the VPP driver
		self.outEn &= ~(1 << (self._zif(s.edit) - 1))
		self._writeOutEn()
		self.top.cmdSetVPPVoltage(vpp)
		self.applyVPP(True)
		self.top.hostDelay(self._opt("edit_settle_ms", 50) / 1000.0)

	def _editModeOff(self):
		s = self.spec
		self.printDebug("Leave edit mode")
		self._pin(s.pv, 0)
		self._setRow(0x3F)
		self._pin(s.sdin, 1)
		self.applyVPP(False)
		self.top.cmdSetVPPVoltage(5)
		self.top.hostDelay(0.02)
		self._pin(s.pv, 1)
		self.top.cmdDelay(0.002)
		self.applyVCC(False)
		self.applyGND(False)
		self.outEn = 0
		self._writeOutEn()
		self.top.flushCommands()

	def shutdownChip(self):
		self.printDebug("Shutdown chip")
		self.applyVCC(False)
		self.applyVPP(False)
		self.applyGND(False)
		self.top.cmdSetVCCVoltage(self.top.vcc.minVoltage())
		self.top.cmdSetVPPVoltage(self.top.vpp.minVoltage())
		for i in range(6):
			self.top.cmdFPGAWrite(0x40 + i, 0)
		self.top.flushCommands()

	# ---- options ----

	def _opt(self, name, default):
		ov = getattr(self, "_probeOverride", None)
		if ov and name in ov:
			return ov[name]
		v = self.getChipOptionValue(name, None)
		return default if v is None else v

	# ---- PES ----

	def _readPES(self):
		s = self.spec
		self._editModeOn(self._opt("read_vpp", READ_VPP))
		try:
			self._loadRowForRead(s.pesRow)
			bits = self._receiveBits(8 * s.pesBytes)
		finally:
			self._editModeOff()
		return bytes(bytearray(
			sum(bits[8 * i + j] << j for j in range(8)) for i in range(s.pesBytes)))

	def _decodePES(self, pes):
		"Returns dict with vpp (V), progtime (s), erasetime (s), cfgmap, text."
		s = self.spec
		p = [ byte2int(b) for b in pes ]
		pesTxt = " ".join("%02X" % b for b in p)
		if b"F16V8" in pes[::-1] or b"F20V8" in pes[::-1] or b"F22V" in pes[::-1]:
			self.throwError("PES %s identifies an Atmel ATF part. ATF16V8/20V8/22V10 "
				"use a different algorithm and are not supported." % pesTxt, always=True)
		if p[2] not in s.ids:
			others = [ g.name for g in (GAL16V8, GAL20V8, GAL22V10)
				   if p[2] in g.ids and g is not s ]
			self.throwError("PES %s does not look like a %s (id byte 0x%02X)%s. "
				"Is the chip inserted correctly?  Use --force to override." %
				(pesTxt, s.name, p[2],
				 (" - it looks like a %s" % others[0]) if others else ""))
		algo = p[1] & 0x0F
		if algo == 5:
			durations = (1, 2, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 200)
			erase = ((25 << ((p[4] >> 2) & 7)) // 2) / 1000.0
			idx = ((((p[5] << 8) | p[4]) >> 5) & 15)
			prog = (durations[idx] if idx < len(durations) else 100) / 1000.0
			vpp = (2 * ((p[5] >> 1) & 31) + 20) / 4.0
		elif s.family == "V8":
			erase = 0.100
			table = {	# algo: (VPP, program pulse)
				0: (15.75, 0.100),
				1: (15.75, 0.080),
				2: (16.50, 0.010),
				3: (15.00 if p[3] == NATIONAL else 14.50, 0.040),
				4: (14.00, 0.100),
			}
			if algo not in table:
				self.throwError("Unknown PES programming algorithm %d" % algo)
			vpp, prog = table.get(algo, (15.75, 0.080))
		else:
			erase = 0.050 if p[3] == NATIONAL else 0.100
			table = {
				0: (16.50, 0.010),
				1: (15.75, 0.100),
				2: (15.00 if p[3] == NATIONAL else 14.50, 0.040),
				3: (14.00, 0.100),
			}
			if algo not in table:
				self.throwError("Unknown PES programming algorithm %d" % algo)
			vpp, prog = table.get(algo, (15.75, 0.100))
		if s.family == "V8":
			cfgmap = CFG_MAP_V8AB if (p[2] in s.idsV8AB or self._opt("v8ab", False)) else CFG_MAP_V8
		else:
			cfgmap = CFG_MAP_V10
		info = {
			"vpp": float(self._opt("vpp", vpp)),
			"progtime": float(self._opt("prog_ms", prog * 1000)) / 1000.0,
			"erasetime": float(self._opt("erase_ms", erase * 1000)) / 1000.0,
			"cfgmap": cfgmap,
			"text": "%s, %s, algorithm %d" % (
				MANUFACTURERS.get(p[3], "manufacturer 0x%02X" % p[3]),
				s.ids.get(p[2], "unknown type"), algo),
		}
		self.printInfo("PES %s: %s -> program at %.2f V, %d ms pulses, erase %d ms" % (
			pesTxt, info["text"], min(info["vpp"], MAX_VPP),
			info["progtime"] * 1000, info["erasetime"] * 1000))
		return info

	def _getInfo(self):
		pes = self._readPES()
		if pes in (b"\x00" * len(pes), b"\xFF" * len(pes)):
			self.throwError("Cannot read the PES (all %02X). No chip, wrong orientation "
				"or bad contact? (try: -s pes.bin -C probe=1)" % byte2int(pes[0]))
		self.pes = pes
		return self._decodePES(pes)

	def readSignature(self):
		if self._opt("probe", False):
			return self._probe()
		return self._readPES()

	def _probe(self):
		"Try a range of read voltages / timings and print the PES for each."
		first = None
		pes = b""
		for vpp in (11.5, 12.0, 12.5, 13.0):
			for strobe_us, settle in ((200, 50), (2000, 200), (20000, 500)):
				for pull in (False, True):
					c = { "read_vpp": vpp, "read_strobe_us": strobe_us,
					      "edit_settle_ms": settle, "vcc_settle_ms": settle,
					      "pullups": pull }
					self._probeOverride = c
					try:
						pes = self._readPES()
					finally:
						self._probeOverride = None
					ok = byte2int(pes[2]) in self.spec.ids
					self.top.printInfo("probe EDIT %.1fV strobe %5dus settle %3dms "
						"pullups %-3s -> %s%s" % (
						vpp, strobe_us, settle, "on" if pull else "off",
						" ".join("%02X" % byte2int(b) for b in pes),
						"   <-- looks valid" if ok else ""))
					if ok and first is None:
						first = pes
		return first if first is not None else pes

	# ---- fuse map access ----

	def _readFuses(self, info):
		s = self.spec
		fuses = [0] * s.nrFuses
		cfgmap = info["cfgmap"]
		self._editModeOn(self._opt("read_vpp", READ_VPP))
		try:
			self.progressMeterInit("Reading %s fuses" % s.name, s.rows + 2)
			for row in range(s.rows):
				self.progressMeter(row)
				self._loadRowForRead(row)
				for b, v in enumerate(self._receiveBits(s.rowBits)):
					fuses[s.rows * b + row] = v
				if s.family == "V10":
					self.top.cmdDelay(0.001)
			self.progressMeter(s.rows)
			self._loadRowForRead(s.uesRow)
			for b, v in enumerate(self._receiveBits(s.uesBits)):
				fuses[s.uesFuse + b] = v
			self.progressMeter(s.rows + 1)
			if s.family == "V8":
				self._loadRowForRead(s.cfgRow)
			else:
				# V10: config row is selected on the RA pins directly
				self._setRow(s.cfgRow)
				self._strobe(max(0.001, self._opt("read_strobe_us", 200) / 1000000.0))
			for b, v in enumerate(self._receiveBits(len(cfgmap))):
				fuses[s.cfgBase + cfgmap[b]] = v
			self.progressMeterFinish()
		finally:
			self._editModeOff()
		return fuses

	def _writeFuses(self, info, fuses):
		s = self.spec
		cfgmap = info["cfgmap"]
		prog = info["progtime"]
		self._editModeOn(info["vpp"])
		try:
			self.progressMeterInit("Writing %s fuses" % s.name, s.rows + 2)
			if s.family == "V8":
				self._pin(s.pv, 1)
				for row in range(s.rows):
					self.progressMeter(row)
					self._setRow(row)
					self._sendBits([ fuses[s.rows * b + row] for b in range(s.rowBits) ])
					self._strobe(prog)
				self.progressMeter(s.rows)
				self._setRow(s.uesRow)
				self._sendBits(fuses[s.uesFuse : s.uesFuse + s.uesBits])
				self._strobe(prog)
				self.progressMeter(s.rows + 1)
				self._setRow(s.cfgRow)
				self._sendBits([ fuses[s.cfgBase + o] for o in cfgmap ])
				self._strobe(prog)
				self._pin(s.pv, 0)
			else:
				# V10: data bits first, then the 6-bit row address, then strobe
				self._setRow(0)
				for row in range(s.rows):
					self.progressMeter(row)
					self._sendBits([ fuses[s.rows * b + row] for b in range(s.rowBits) ])
					self._sendAddress(row)
					self._pin(s.pv, 1)
					self._strobe(prog)
					self._pin(s.pv, 0)
				self.progressMeter(s.rows)
				self._sendBits(fuses[s.uesFuse : s.uesFuse + s.uesBits] +
					       [1] * (s.rowBits - s.uesBits))
				self._sendAddress(s.uesRow)
				self._pin(s.pv, 1)
				self._strobe(prog)
				self._pin(s.pv, 0)
				self.progressMeter(s.rows + 1)
				self._setRow(s.cfgRow)
				self._sendBits([ fuses[s.cfgBase + o] for o in cfgmap ])
				self._pin(s.pv, 1)
				self._strobe(prog)
				self._pin(s.pv, 0)
			self.progressMeterFinish()
		finally:
			self._editModeOff()

	def _erase(self, info):
		s = self.spec
		self._editModeOn(info["vpp"])
		try:
			self._pin(s.pv, 1)
			self._setRow(s.eraseRow)
			if s.family == "V8":
				self._sendBits([1])
			self._strobe(info["erasetime"])
			self._pin(s.pv, 0)
		finally:
			self._editModeOff()

	def _secure(self, info):
		s = self.spec
		if s.securityRow is None:
			self.throwError("Setting the security fuse is not supported for %s; "
				"the chip was programmed and verified but is NOT secured." % s.name,
				always=True)
		self._editModeOn(info["vpp"])
		try:
			self._pin(s.pv, 1)
			self._setRow(s.securityRow)
			self._sendBits([1])
			self._strobe(info["progtime"])
			self._pin(s.pv, 0)
		finally:
			self._editModeOff()

	# ---- diagnostics ----

	def _region(self, f):
		s = self.spec
		array = s.rows * s.rowBits
		if f < array:
			return "array row %d bit %d" % (f % s.rows, f // s.rows)
		if s.uesFuse <= f < s.uesFuse + s.uesBits:
			return "UES bit %d" % (f - s.uesFuse)
		return "config fuse %d" % f

	def _fuseStats(self, label, fuses):
		s = self.spec
		array = s.rows * s.rowBits
		ones = sum(fuses)
		arr = sum(fuses[:array])
		ues = sum(fuses[s.uesFuse:s.uesFuse + s.uesBits])
		self.printInfo("%s: %d of %d fuses are 1 (array %d/%d, UES %d/%d, config %d/%d)" % (
			label, ones, s.nrFuses, arr, array, ues, s.uesBits,
			ones - arr - ues, s.nrFuses - array - s.uesBits))

	def _saveDebug(self, name, fuses):
		try:
			with open(name, "wb") as f:
				f.write(jedecCreate(fuses, self.spec, self.pes))
			self.printInfo("saved %s" % name)
		except OSError as e:
			self.printWarning("could not save %s: %s" % (name, e))

	# ---- toprammer API ----

	def erase(self):
		info = self._getInfo()
		self.printInfo("Erasing")
		self._erase(info)

	def readFuse(self):
		info = self._getInfo()
		fuses = self._readFuses(info)
		return jedecCreate(fuses, self.spec, self.pes)

	def writeFuse(self, image):
		s = self.spec
		fuses, security = fusesFromImage(image, s)
		if self._opt("secure", None) is not None:
			security = bool(self._opt("secure", False))
		info = self._getInfo()
		self._fuseStats("JEDEC file", fuses)
		if not self._opt("no_erase", False):
			self.printInfo("Erasing")
			self._erase(info)
			if self._opt("debug", False):
				after = self._readFuses(info)
				self._fuseStats("After erase", after)
				self._saveDebug("%s_after_erase.jed" % s.name.lower(), after)
		self._writeFuses(info, fuses)
		self.printInfo("Verifying")
		readBack = self._readFuses(info)
		bad = [ i for i in range(s.nrFuses) if readBack[i] != fuses[i] ]
		if bad:
			self._fuseStats("Read back", readBack)
			array = s.rows * s.rowBits
			w1r0 = sum(1 for i in bad if fuses[i] == 1)
			nUes = sum(1 for i in bad if s.uesFuse <= i < s.uesFuse + s.uesBits)
			nArr = sum(1 for i in bad if i < array)
			self.printInfo("Mismatches: %d wrote-1-read-0, %d wrote-0-read-1; "
				"array %d, UES %d, config %d" % (
				w1r0, len(bad) - w1r0, nArr, nUes, len(bad) - nArr - nUes))
			for i in bad[:12]:
				self.printInfo("   fuse %4d (%s): wrote %d read %d" % (
					i, self._region(i), fuses[i], readBack[i]))
			self._saveDebug("%s_verify_readback.jed" % s.name.lower(), readBack)
			self.throwError("Verify FAILED: %d fuse(s) differ" % len(bad))
		else:
			self.printInfo("Verify OK, fuse checksum %04X" % jedecChecksum(fuses))
		if security:
			self.printInfo("Setting the security fuse")
			self._secure(info)


class Chip_GAL16V8(Chip_GAL):
	SPEC = GAL16V8

class Chip_GAL20V8(Chip_GAL):
	SPEC = GAL20V8

class Chip_GAL22V10(Chip_GAL):
	SPEC = GAL22V10


_OPTIONS = (
	ChipOptionFloat("vpp", "Override programming EDIT voltage (V)", minVal=10.0, maxVal=MAX_VPP),
	ChipOptionFloat("read_vpp", "EDIT voltage for reading (V, default 12)", minVal=10.0, maxVal=13.0),
	ChipOptionInt("prog_ms", "Override program pulse width (ms)", minVal=1, maxVal=200),
	ChipOptionInt("erase_ms", "Override erase pulse width (ms)", minVal=10, maxVal=400),
	ChipOptionInt("clk_delay_us", "Extra delay per SCLK edge (us)", minVal=0, maxVal=250),
	ChipOptionInt("read_strobe_us", "Row-load /STR pulse for reading (us, default 200)", minVal=5, maxVal=100000),
	ChipOptionInt("edit_settle_ms", "Wait after raising EDIT (ms, default 50)", minVal=1, maxVal=2000),
	ChipOptionInt("vcc_settle_ms", "Wait after VCC on (ms, default 100)", minVal=1, maxVal=2000),
	ChipOptionBool("pullups", "Enable the ZIF pull-ups (default on; needed for early 16V8A)"),
	ChipOptionBool("probe", "With -s: try many read voltages/timings and print each PES"),
	ChipOptionBool("secure", "Set the security fuse after programming (not 22V10)"),
	ChipOptionBool("v8ab", "Force the 16V8A/20V8A config-row bit order"),
	ChipOptionBool("debug", "Read back and save the fuse map after erasing"),
	ChipOptionBool("no_erase", "Do not erase before programming"),
)

_COMMENT = "Fuse files are JEDEC: --read-fuse x.jed -O bin, --write-fuse x.jed -I bin"

ChipDescription(
	Chip_GAL16V8,
	bitfile = "unitest",
	chipID = "gal16v8",
	runtimeID = (8, 1),
	chipType = ChipDescription.TYPE_GAL,
	chipVendors = ("Lattice", "National", "ST"),
	description = "GAL16V8, GAL16V8A/B/D",
	packages = ( ("DIP20", ""), ),
	comment = _COMMENT,
	chipOptions = _OPTIONS,
	maintainer = "Kris",
)

ChipDescription(
	Chip_GAL20V8,
	bitfile = "unitest",
	chipID = "gal20v8",
	runtimeID = (8, 1),
	chipType = ChipDescription.TYPE_GAL,
	chipVendors = ("Lattice", "National", "ST"),
	description = "GAL20V8, GAL20V8A/B",
	packages = ( ("DIP24", ""), ),
	comment = _COMMENT,
	chipOptions = _OPTIONS,
	maintainer = "Kris",
)

ChipDescription(
	Chip_GAL22V10,
	bitfile = "unitest",
	chipID = "gal22v10",
	runtimeID = (8, 1),
	chipType = ChipDescription.TYPE_GAL,
	chipVendors = ("Lattice", "National", "ST"),
	description = "GAL22V10 (Lattice/National/ST, not Atmel ATF22V10)",
	packages = ( ("DIP24", ""), ),
	comment = _COMMENT + "; security fuse not supported",
	chipOptions = _OPTIONS,
	maintainer = "Kris",
)

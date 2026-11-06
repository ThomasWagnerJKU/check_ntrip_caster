"""Tests for the stream mode: RTCM3 content checks against a fake caster."""
import importlib.machinery
import importlib.util
import os
import socket
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(os.path.dirname(HERE), "check_ntrip_caster")

_loader = importlib.machinery.SourceFileLoader("check_ntrip_caster", PLUGIN)
_spec = importlib.util.spec_from_loader("check_ntrip_caster", _loader)
plugin = importlib.util.module_from_spec(_spec)
_loader.exec_module(plugin)

# JKU0 in Linz
LAT, LON, HEIGHT = 48.33597150, 14.32268850, 324.978


class Bits:
    """MSB-first bit writer for RTCM3 payloads."""

    def __init__(self):
        self.value = 0
        self.size = 0

    def add(self, value, count):
        self.value = (self.value << count) | (value & ((1 << count) - 1))
        self.size += count
        return self

    def payload(self):
        padding = -self.size % 8
        return (self.value << padding).to_bytes((self.size + padding) // 8, "big")


def frame(payload):
    head = bytes([0xD3, len(payload) >> 8, len(payload) & 0xFF]) + payload
    return head + plugin.crc24q(head).to_bytes(3, "big")


def gps_tow_ms(now=None):
    now = time.time() if now is None else now
    return int((now - plugin.GPS_EPOCH_UNIX + plugin.DEFAULT_LEAP_SECONDS) * 1000) % plugin.WEEK_MS


def msg_1005(x, y, z):
    bits = Bits().add(1005, 12).add(0, 12).add(0, 6).add(0b1100, 4)
    bits.add(round(x * 10000), 38).add(0, 2).add(round(y * 10000), 38).add(0, 2).add(round(z * 10000), 38)
    return frame(bits.payload())


def msm(message_type, prns, cnr, tow_ms=None, more=False):
    """MSM4 or MSM7 with one signal per satellite, every cell present and C/N0 cnr dBHz."""
    kind = message_type % 10
    epoch = gps_tow_ms() if tow_ms is None else tow_ms
    if message_type // 10 == 108:
        epoch = (int(time.time() * 1000) + plugin.GLONASS_OFFSET_MS) % plugin.DAY_MS
    bits = Bits().add(message_type, 12).add(0, 12).add(epoch, 30).add(1 if more else 0, 1)
    bits.add(0, 3).add(0, 7).add(0, 2).add(0, 2).add(0, 1).add(0, 3)
    mask = 0
    for prn in prns:
        mask |= 1 << (64 - prn)
    bits.add(mask, 64).add(1 << 31, 32).add((1 << len(prns)) - 1, len(prns))
    bits.add(0, len(prns) * plugin.MSM_SATELLITE_BITS[kind])
    before, width, resolution = plugin.MSM_CNR[kind]
    cells = len(prns)
    bits.add(0, cells * before)
    for _ in range(cells):
        bits.add(round(cnr / resolution), width)
    after = {4: 0, 7: 15}[kind]
    bits.add(0, cells * after)
    return frame(bits.payload())


class FakeCaster:
    """Answers one NTRIP request with ICY 200 OK and the given frames, then keeps the connection open."""

    def __init__(self, data):
        self.data = data
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        client, _ = self.server.accept()
        client.recv(4096)
        client.sendall(b"ICY 200 OK\r\n" + self.data)
        time.sleep(3)
        client.close()

    def close(self):
        self.server.close()


def run(data, *options):
    caster = FakeCaster(data)
    try:
        args = plugin.build_parser().parse_args(
            ["stream", "-H", "127.0.0.1", "-p", str(caster.port), "-m", "TEST", "-d", "0.5"] + list(options))
        args.warning = plugin.Range.parse("3")
        args.critical = plugin.Range.parse("10")
        return plugin.check_stream(args)
    finally:
        caster.close()


def jku0_stream(cnr=42.0, gps=range(1, 11), glonass=range(1, 7), offset=(0, 0, 0)):
    x, y, z = plugin.ecef(LAT, LON, HEIGHT)
    return (msg_1005(x + offset[0], y + offset[1], z + offset[2]) + msm(1077, list(gps), cnr)
            + msm(1087, list(glonass), cnr))


class ContentTests(unittest.TestCase):
    def test_decodes_position_satellites_and_cnr(self):
        content = plugin.StreamContent()
        for data in (jku0_stream(cnr=41.5),):
            index = 0
            while index < len(data):
                length = ((data[index + 1] & 3) << 8) | data[index + 2]
                payload = data[index + 3:index + 3 + length]
                content.add(plugin.bits(payload, 0, 12), payload)
                index += 6 + length
        self.assertLess(plugin.math.dist(content.position, plugin.ecef(LAT, LON, HEIGHT)), 0.001)
        self.assertEqual(content.satellites(), {"GPS": 10, "GLONASS": 6})
        self.assertAlmostEqual(content.mean_cnr(), 41.5)

    def test_msm4_cnr_resolution(self):
        content = plugin.StreamContent()
        data = msm(1074, [3, 5, 7], 37)
        payload = data[3:-3]
        content.add(1074, payload)
        self.assertEqual(content.satellites(), {"GPS": 3})
        self.assertEqual(content.mean_cnr(), 37)

    def test_split_epoch_counts_union_of_messages(self):
        content = plugin.StreamContent()
        tow = gps_tow_ms()
        for data in (msm(1077, [1, 2, 3], 40, tow, more=True), msm(1077, [3, 4], 40, tow)):
            content.add(1077, data[3:-3])
        self.assertEqual(content.satellites(), {"GPS": 4})

    def test_incomplete_newer_epoch_is_ignored(self):
        content = plugin.StreamContent()
        tow = gps_tow_ms()
        content.add(1077, msm(1077, range(1, 11), 40, tow - 1000)[3:-3])
        content.add(1077, msm(1077, [1, 2], 40, tow, more=True)[3:-3])
        self.assertEqual(content.satellites(), {"GPS": 10})

    def test_legacy_satellite_count(self):
        content = plugin.StreamContent()
        bits = Bits().add(1004, 12).add(0, 12).add(gps_tow_ms(), 30).add(0, 1).add(9, 5).add(0, 64)
        content.add(1004, bits.payload())
        self.assertEqual(content.satellites(), {"GPS": 9})
        self.assertIsNone(content.mean_cnr())

    def test_signed_coordinates(self):
        content = plugin.StreamContent()
        content.add(1005, msg_1005(-1234.5678, 2.0, -0.0001)[3:-3])
        for got, want in zip(content.position, (-1234.5678, 2.0, -0.0001)):
            self.assertAlmostEqual(got, want, places=4)


class StreamCheckTests(unittest.TestCase):
    def test_good_stream_is_ok(self):
        state, message, perf = run(jku0_stream(), "--require-messages", "1005,1077,1087",
                                   "--position", "%s,%s,%s" % (LAT, LON, HEIGHT),
                                   "--satellites-warning", "GPS=8,GLONASS=4", "--cnr-warning", "35")
        self.assertEqual(state, plugin.OK, message)
        self.assertIn("satellites GLONASS 6 GPS 10", message)
        self.assertIn("C/N0 42.0dBHz", message)
        self.assertTrue(any(p.startswith("position_error=0") for p in perf), perf)

    def test_without_options_only_reports(self):
        state, message, perf = run(jku0_stream(cnr=20, gps=[1]))
        self.assertEqual(state, plugin.OK, message)
        self.assertIn("satellites_gps=1;;;0", perf)

    def test_missing_message_is_critical(self):
        state, message, _ = run(jku0_stream(), "--require-messages", "1005,1230")
        self.assertEqual(state, plugin.CRITICAL)
        self.assertIn("message(s) 1230 missing", message)

    def test_moved_station_is_critical(self):
        state, message, _ = run(jku0_stream(offset=(0.3, 0, 0.4)), "--position", "%s,%s,%s" % (LAT, LON, HEIGHT))
        self.assertEqual(state, plugin.CRITICAL)
        self.assertIn("station position 0.500m away", message)

    def test_position_within_tolerance(self):
        state, message, _ = run(jku0_stream(offset=(0.3, 0, 0.4)), "--position", "%s,%s,%s" % (LAT, LON, HEIGHT),
                                "--position-tolerance", "0.6")
        self.assertEqual(state, plugin.OK, message)

    def test_no_position_message_is_warning(self):
        state, message, _ = run(msm(1077, list(range(1, 11)), 40), "--position", "%s,%s,%s" % (LAT, LON, HEIGHT))
        self.assertEqual(state, plugin.WARNING)
        self.assertIn("no station position", message)

    def test_satellite_thresholds(self):
        data = jku0_stream(glonass=[1, 2])
        state, message, _ = run(data, "--satellites-warning", "GLONASS=4")
        self.assertEqual(state, plugin.WARNING)
        self.assertIn("only 2 GLONASS satellite(s)", message)
        state, _, _ = run(data, "--satellites-warning", "GLONASS=4", "--satellites-critical", "glonass=3")
        self.assertEqual(state, plugin.CRITICAL)

    def test_missing_constellation_counts_as_zero(self):
        state, message, perf = run(jku0_stream(), "--satellites-critical", "Galileo=1")
        self.assertEqual(state, plugin.CRITICAL)
        self.assertIn("only 0 Galileo satellite(s)", message)
        self.assertIn("satellites_galileo=0;;1;0", perf)

    def test_cnr_thresholds(self):
        data = jku0_stream(cnr=33)
        self.assertEqual(run(data, "--cnr-warning", "35")[0], plugin.WARNING)
        self.assertEqual(run(data, "--cnr-warning", "35", "--cnr-critical", "34")[0], plugin.CRITICAL)
        self.assertEqual(run(data, "--cnr-warning", "30")[0], plugin.OK)

    def test_cnr_threshold_without_msm4_to_7_is_warning(self):
        bits = Bits().add(1004, 12).add(0, 12).add(gps_tow_ms(), 30).add(0, 1).add(9, 5).add(0, 64)
        state, message, _ = run(frame(bits.payload()), "--cnr-warning", "35")
        self.assertEqual(state, plugin.WARNING)
        self.assertIn("no C/N0", message)


class OptionTests(unittest.TestCase):
    def parse(self, *options):
        return plugin.build_parser().parse_args(["stream", "-H", "h", "-m", "M"] + list(options))

    def test_values(self):
        args = self.parse("--require-messages", "1005, 1077", "--position", "48.3,14.3,325",
                          "--satellites-warning", "gps=8,GLONASS=4")
        self.assertEqual(args.require_messages, [1005, 1077])
        self.assertEqual(args.position, (48.3, 14.3, 325.0))
        self.assertEqual(args.satellites_warning, {"GPS": 8, "GLONASS": 4})

    def test_invalid_values_exit_unknown(self):
        for options in (["--position", "48.3,14.3"], ["--satellites-warning", "Mars=3"],
                        ["--require-messages", "1005,x"]):
            with self.assertRaises(SystemExit) as raised, open(os.devnull, "w") as null:
                stderr, plugin.sys.stderr = plugin.sys.stderr, null
                try:
                    self.parse(*options)
                finally:
                    plugin.sys.stderr = stderr
            self.assertEqual(raised.exception.code, plugin.UNKNOWN, options)

import unittest
from unittest.mock import patch, MagicMock
from companion.metrics import MetricsCollector
from companion.qr_text import qr_payload


class FakeBattery:
    def __init__(self, percent, plugged, secsleft):
        self.percent = percent
        self.power_plugged = plugged
        self.secsleft = secsleft


class MetricsBatteryTests(unittest.TestCase):
    @patch("psutil.sensors_battery", return_value=None)
    def test_no_battery(self, _sb):
        bat = MetricsCollector.battery()
        self.assertFalse(bat["present"])
        self.assertIsNone(bat["percent"])

    @patch("psutil.sensors_battery", return_value=FakeBattery(15, False, 3600))
    def test_battery_low_not_plugged(self, _sb):
        bat = MetricsCollector.battery()
        self.assertTrue(bat["present"])
        self.assertEqual(bat["percent"], 15)
        self.assertFalse(bat["plugged"])
        self.assertEqual(bat["mins_left"], 60)

    @patch("psutil.sensors_battery", return_value=FakeBattery(88, True, 12345))
    def test_battery_charging(self, _sb):
        bat = MetricsCollector.battery()
        self.assertTrue(bat["present"])
        self.assertTrue(bat["plugged"])
        self.assertEqual(bat["percent"], 88)


class MetricsAlertsTests(unittest.TestCase):
    def _mk(self):
        return MetricsCollector()

    @patch("psutil.cpu_percent", return_value=97)
    @patch("psutil.virtual_memory")
    @patch("companion.metrics.MetricsCollector._system_disk_path", return_value="C:\\")
    @patch("psutil.disk_usage")
    @patch("companion.metrics.MetricsCollector.battery", return_value={"present": False, "percent": None, "plugged": None, "secsleft": None})
    def test_cpu_spike_alerts_critical(self, _b, disk, _sdp, mem, _cpu):
        md = MagicMock()
        md.percent = 40
        mem.return_value = md
        disk.return_value.percent = 20
        alerts = self._mk().alerts()
        kinds = [a["kind"] for a in alerts["alerts"]]
        self.assertIn("cpu", kinds)
        self.assertEqual(alerts["alerts"][0]["level"], "critical")

    @patch("psutil.cpu_percent", return_value=30)
    @patch("psutil.virtual_memory")
    @patch("companion.metrics.MetricsCollector._system_disk_path", return_value="C:\\")
    @patch("psutil.disk_usage")
    @patch("companion.metrics.MetricsCollector.battery", return_value={"present": False, "percent": None, "plugged": None, "secsleft": None})
    def test_no_alerts_when_healthy(self, _b, disk, _sdp, mem, _cpu):
        md = MagicMock()
        md.percent = 30
        mem.return_value = md
        disk.return_value.percent = 30
        alerts = self._mk().alerts()
        self.assertEqual(len(alerts["alerts"]), 0)


class QrPayloadTests(unittest.TestCase):
    def test_payload_format(self):
        payload = qr_payload("192.168.1.10", "12345678")
        self.assertEqual(payload, "PCCONN:1|host=192.168.1.10&code=12345678")


if __name__ == "__main__":
    unittest.main()

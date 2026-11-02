import os
import unittest
from datetime import date

from support import NOW, RepoCase, ca_intel, standard_transport


class PeriodParsing(unittest.TestCase):
    def test_default_is_seven_days(self):
        self.assertEqual(ca_intel.parse_period(""), 7)
        self.assertEqual(ca_intel.parse_period(None), 7)

    def test_accepted_forms(self):
        for text in ("3days", "3 days", "3d", "3", "3Day", " 3days "):
            self.assertEqual(ca_intel.parse_period(text), 3, text)

    def test_rejected_forms(self):
        for text in ("0", "121", "3w", "-1", "abc", "3days ago", "1.5d", "3 hours"):
            with self.assertRaises(ca_intel.PeriodError, msg=text):
                ca_intel.parse_period(text)

    def test_window_boundaries_are_exact_utc(self):
        w = ca_intel.make_window(3, ca_intel.parse_ts("2026-11-02T17:00:00.750Z"))
        self.assertEqual(w.as_dict(), {"days": 3, "start_utc": "2026-10-30T17:00:00Z", "end_utc": "2026-11-02T17:00:00Z"})

    def test_published_modified_and_kev_classification(self):
        w = ca_intel.make_window(3, ca_intel.parse_ts(NOW))
        self.assertEqual(ca_intel.window_reasons(w, "2026-11-01T00:00:00Z", "2026-11-01T01:00:00Z"), ["published"])
        self.assertEqual(ca_intel.window_reasons(w, "2020-01-01T00:00:00Z", "2026-11-01T01:00:00Z"), ["modified"])
        self.assertEqual(ca_intel.window_reasons(w, "2020-01-01T00:00:00Z", "2026-10-30T16:59:59Z"), [])
        self.assertEqual(ca_intel.window_reasons(w, None, "2026-11-01T12:30:00.000"), ["modified"])
        self.assertTrue(w.contains_date(date(2026, 10, 30)))
        self.assertTrue(w.contains_date(date(2026, 11, 2)))
        self.assertFalse(w.contains_date(date(2026, 10, 29)))


class StartWindow(RepoCase):
    def test_default_seven_days_recorded(self):
        out = self.start()
        self.assertEqual(out["window"], {"days": 7, "start_utc": "2026-10-26T17:00:00Z", "end_utc": NOW})
        run = self.state()["runs"][0]
        self.assertEqual(run["requested"], "")
        self.assertEqual(run["window"]["days"], 7)

    def test_explicit_three_days_and_nvd_query_params(self):
        transport = standard_transport()
        out = self.start("3days", transport=transport)
        self.assertEqual(out["window"]["start_utc"], "2026-10-30T17:00:00Z")
        nvd = [u for m, u, _ in transport.calls if u.startswith(ca_intel.INTEL_SOURCES["nvd"]["cves"]) and "lastMod" in u]
        self.assertEqual(len(nvd), 1)
        self.assertIn("lastModStartDate=2026-10-30T17%3A00%3A00.000%2B00%3A00", nvd[0])
        self.assertIn("lastModEndDate=2026-11-02T17%3A00%3A00.000%2B00%3A00", nvd[0])

    def test_invalid_period_rejected_without_creating_a_run(self):
        code, out = self.cli("start", "3weeks", transport=standard_transport())
        self.assertEqual(code, 2)
        self.assertEqual(out["status"], "invalid_period")
        self.assertFalse(os.path.exists(os.path.join(self.root, ".repo-kit", "contre-attaque", "state.json")))

    def test_consent_required_before_network(self):
        os.unlink(os.path.join(self.root, ".repo-kit", "contre-attaque", "config.json"))
        transport = standard_transport()
        code, out = self.cli("start", "3days", transport=transport)
        self.assertEqual(code, 3)
        self.assertEqual(out["status"], "consent_required")
        self.assertIn("transmits", out["providers"]["osv"])
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()

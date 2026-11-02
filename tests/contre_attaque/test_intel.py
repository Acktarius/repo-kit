import unittest

from support import FakeTransport, NOW, ca_intel, fixture

COMP = {"key": "library:npm:lodash:package-lock.json@4.17.20", "kind": "library", "ecosystem": "npm",
        "name": "lodash", "version": "4.17.20"}


def fetcher(transport):
    return ca_intel.Fetcher(transport, sleep=lambda _s: None)


class Osv(unittest.TestCase):
    def setUp(self):
        self.vulns = fixture("osv-vulns.json")

    def test_success_and_no_match_are_distinct_from_failure(self):
        t = FakeTransport(osv_index={("npm", "lodash", "4.17.20"): ["GHSA-29mw-wpgm-hmr9"]}, osv_vulns=self.vulns)
        res = ca_intel.collect_osv(fetcher(t), [COMP], {})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["matches"][COMP["key"]], ["GHSA-29mw-wpgm-hmr9"])

        res = ca_intel.collect_osv(fetcher(FakeTransport(osv_vulns=self.vulns)), [COMP], {})
        self.assertEqual(res["status"], "no_match")
        self.assertEqual(res["answered"], [COMP["key"]])

        res = ca_intel.collect_osv(fetcher(FakeTransport(fail={"osv"})), [COMP], {})
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["answered"], [])
        self.assertEqual(res["matches"], {})

    def test_failed_advisory_fetch_is_partial(self):
        t = FakeTransport(osv_index={("npm", "lodash", "4.17.20"): ["GHSA-29mw-wpgm-hmr9"]},
                          osv_vulns=self.vulns, fail={"osv-vuln"})
        res = ca_intel.collect_osv(fetcher(t), [COMP], {})
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["matches"][COMP["key"]], ["GHSA-29mw-wpgm-hmr9"])

    def test_cached_record_reused_only_when_modified_unchanged(self):
        t = FakeTransport(osv_index={("npm", "lodash", "4.17.20"): ["GHSA-29mw-wpgm-hmr9"]}, osv_vulns=self.vulns)
        rec = self.vulns["GHSA-29mw-wpgm-hmr9"]
        ca_intel.collect_osv(fetcher(t), [COMP], {rec["id"]: {"modified": rec["modified"], "record": rec}})
        self.assertFalse(any("/v1/vulns/" in u for _, u, _ in t.calls))
        ca_intel.collect_osv(fetcher(t), [COMP], {rec["id"]: {"modified": "2020-01-01T00:00:00Z", "record": rec}})
        self.assertTrue(any("/v1/vulns/" in u for _, u, _ in t.calls))

    def test_next_page_token_followed(self):
        calls = []

        def transport(method, url, body, headers):
            calls.append(url)
            if url.endswith("querybatch"):
                return 200, b'{"results":[{"vulns":[{"id":"GHSA-29mw-wpgm-hmr9","modified":"x"}],"next_page_token":"t1"}]}', ""
            if url.endswith("/v1/query"):
                return 200, b'{"vulns":[{"id":"GHSA-j8r2-6x86-q33q","modified":"y"}]}', ""
            return 200, b'{"id":"' + url.rsplit("/", 1)[1].encode() + b'"}', ""

        res = ca_intel.collect_osv(fetcher(transport), [COMP], {})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["matches"][COMP["key"]], ["GHSA-29mw-wpgm-hmr9", "GHSA-j8r2-6x86-q33q"])
        self.assertIn(ca_intel.INTEL_SOURCES["osv"]["query"], calls)

    def test_local_match_for_imported_records(self):
        rec = self.vulns["GHSA-29mw-wpgm-hmr9"]
        self.assertTrue(ca_intel.osv_record_affects(rec, COMP))
        self.assertFalse(ca_intel.osv_record_affects(rec, {**COMP, "version": "4.17.21"}))
        self.assertIsNone(ca_intel.osv_record_affects(rec, {**COMP, "version": "4.17.21-beta"}))


class Nvd(unittest.TestCase):
    def window(self, days=3):
        return ca_intel.make_window(days, ca_intel.parse_ts(NOW))

    def test_pagination(self):
        items = [dict(fixture("nvd-items.json")[1], id=f"CVE-2026-90{i:02d}") for i in range(5)]
        t = FakeTransport(nvd_items=items, nvd_page_size=2)
        res = ca_intel.collect_nvd(fetcher(t), self.window())
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["pages"], 3)
        self.assertEqual(len(res["items"]), 5)

    def test_failed_and_partial(self):
        self.assertEqual(ca_intel.collect_nvd(fetcher(FakeTransport(fail={"nvd"})), self.window())["status"], "failed")
        items = [dict(fixture("nvd-items.json")[1], id=f"CVE-2026-90{i:02d}") for i in range(5)]
        t = FakeTransport(nvd_items=items, nvd_page_size=2, fail={"nvd-page2"})
        res = ca_intel.collect_nvd(fetcher(t), self.window())
        self.assertEqual(res["status"], "partial")
        self.assertEqual(len(res["items"]), 2)

    def test_successful_empty_window_is_no_match(self):
        res = ca_intel.collect_nvd(fetcher(FakeTransport(nvd_items=[])), self.window())
        self.assertEqual(res["status"], "no_match")

    def test_cpe_relation_and_prefix_versions(self):
        cve = fixture("nvd-items.json")[0]
        py = {"cpe": [("python", "python")]}
        self.assertTrue(ca_intel.nvd_cpe_relation(cve, {**py, "version": "3.11.4"}))
        self.assertFalse(ca_intel.nvd_cpe_relation(cve, {**py, "version": "3.11.9"}))
        self.assertFalse(ca_intel.nvd_cpe_relation(cve, {**py, "version": "3.12"}))
        self.assertIsNone(ca_intel.nvd_cpe_relation(cve, {**py, "version": "3.11"}))
        self.assertIsNone(ca_intel.nvd_cpe_relation(cve, {**py, "version": None}))
        self.assertFalse(ca_intel.nvd_cpe_relation(cve, {"cpe": [("nodejs", "node.js")], "version": "20.1.0"}))
        self.assertEqual(ca_intel.nvd_severity(cve), "high")


class Kev(unittest.TestCase):
    def test_success_and_failure(self):
        res = ca_intel.collect_kev(fetcher(FakeTransport()))
        self.assertEqual(res["status"], "success")
        self.assertIn("CVE-2021-44228", res["entries"])
        self.assertEqual(ca_intel.collect_kev(fetcher(FakeTransport(fail={"kev"})))["status"], "failed")


class Aliases(unittest.TestCase):
    def test_alias_groups_prefer_cve(self):
        canon = ca_intel.alias_groups({
            "GHSA-j8r2-6x86-q33q": ["CVE-2023-32681"],
            "PYSEC-2023-74": ["CVE-2023-32681", "GHSA-j8r2-6x86-q33q"],
            "GHSA-29mw-wpgm-hmr9": ["CVE-2020-28500"],
        })
        self.assertEqual(canon["PYSEC-2023-74"], "CVE-2023-32681")
        self.assertEqual(canon["GHSA-j8r2-6x86-q33q"], "CVE-2023-32681")
        self.assertEqual(canon["GHSA-29mw-wpgm-hmr9"], "CVE-2020-28500")


class Network(unittest.TestCase):
    def test_destination_policy(self):
        for url in ("http://api.osv.dev/v1", "https://user:pw@example.com/", "https://example.com:8443/",
                    "https://127.0.0.1/", "https://169.254.169.254/latest", "https://[::1]/", "https://10.0.0.1/"):
            with self.assertRaises(ValueError, msg=url):
                ca_intel.validate_url(url)
        status, _, err = ca_intel.live_transport("GET", "https://127.0.0.1/", None, {})
        self.assertEqual(status, 0)
        self.assertIn("destination policy", err)

    def test_size_limit_retry_and_redaction(self):
        attempts = []

        def big(method, url, body, headers):
            attempts.append(1)
            if len(attempts) == 1:
                return 429, b"", "HTTP 429"
            return 200, b"x" * (ca_intel.MAX_RESPONSE_BYTES + 1), ""

        f = fetcher(big)
        status, data, meta = f.request("vendor", "GET", "https://example.com/a?api_key=SECRET&id=1",
                                       headers={"apiKey": "SECRET"})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(status, 0)
        self.assertIn("exceeds", meta["error"])
        self.assertNotIn("SECRET", repr(f.log))
        self.assertIn("id=1", meta["url"])


if __name__ == "__main__":
    unittest.main()

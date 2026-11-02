import contextlib
import glob
import io
import json
import multiprocessing
import os
import subprocess
import unittest

from support import NOW, RepoCase, standard_transport

import contre_attaque

CTX = multiprocessing.get_context("fork")


def _quiet_main(argv, transport=None):
    with contextlib.redirect_stdout(io.StringIO()):
        return contre_attaque.main(argv, transport=transport, sleep=lambda _s: None)


def _decide_worker(root, run_id, cid, q):
    q.put(_quiet_main(["--root", root, "--now", NOW, "decide", "--run", run_id, "--candidate", cid,
                       "--status", "affected", "--confidence", "medium", "--rationale", "concurrent",
                       "--evidence", "package-lock.json"]))


def _start_worker(root, q):
    q.put(_quiet_main(["--root", root, "--now", NOW, "start", "3days"], transport=standard_transport()))


def _run_all(target, arglists):
    q = CTX.Queue()
    procs = [CTX.Process(target=target, args=(*a, q)) for a in arglists]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
    return sorted(q.get(timeout=5) for _ in procs)


class Concurrency(RepoCase):
    def test_concurrent_decisions_are_all_recorded(self):
        out = self.start("3days")
        cids = [i["candidate_id"] for i in out["worklist"]]
        self.assertGreaterEqual(len(cids), 3)
        codes = _run_all(_decide_worker, [(self.root, out["run_id"], c) for c in cids])
        self.assertEqual(codes, [0] * len(cids))
        state = self.state()
        self.assertEqual({c for c in cids if state["assessments"][c]["applicability"] == "affected"}, set(cids))
        self.assertEqual(sorted(state["runs"][-1]["assessment"]["decided"]), sorted(cids))

    def test_overlapping_starts_keep_both_runs_and_one_queue(self):
        codes = _run_all(_start_worker, [(self.root,), (self.root,)])
        self.assertEqual(codes, [0, 0])
        state = self.state()
        self.assertEqual(len(state["runs"]), 2)
        ids = [q["candidate_id"] for q in state["queue"]]
        self.assertEqual(len(ids), len(set(ids)), "queue has no duplicates")
        self.assertEqual(set(ids), set(state["candidates"]))

    def test_no_temp_files_left_behind(self):
        out = self.start("3days")
        cid = self.item(out, "lodash")["candidate_id"]
        self.decide(out["run_id"], cid, "affected", "--evidence", "package-lock.json")
        self.cli("finish", "--run", out["run_id"])
        leftovers = glob.glob(os.path.join(self.root, "**", "*.tmp.*"), recursive=True)
        self.assertEqual(leftovers, [])


class Recovery(RepoCase):
    def test_interrupted_run_is_detected_and_queue_and_checkpoints_survive(self):
        out = self.start("3days")
        before = self.state()
        dead = subprocess.Popen(["true"])
        dead.wait()
        path = os.path.join(self.root, ".repo-kit", "contre-attaque", "state.json")
        before["runs"][-1]["pid"] = dead.pid
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(before, fh)
        out2 = self.start("3days", transport=standard_transport(fail={"osv", "nvd", "kev"}),
                          now="2026-11-02T18:00:00Z")
        self.assertEqual(out2["recovered_interrupted_runs"], [out["run_id"]])
        after = self.state()
        self.assertEqual(after["runs"][0]["outcome"], "interrupted")
        self.assertEqual({q["candidate_id"] for q in after["queue"]}, {q["candidate_id"] for q in before["queue"]})
        self.assertEqual(after["checkpoints"], before["checkpoints"])
        code, err = self.cli("finish", "--run", out["run_id"])
        self.assertEqual(code, 2)
        self.assertIn("interrupted", err["error"])

    def test_stale_run_from_another_host_is_interrupted_after_24h(self):
        out = self.start("3days")
        state = self.state()
        state["runs"][-1]["host"] = "elsewhere"
        with open(os.path.join(self.root, ".repo-kit", "contre-attaque", "state.json"), "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        self.assertEqual(self.start("3days", now="2026-11-02T20:00:00Z")["recovered_interrupted_runs"], [])
        self.assertEqual(self.start("3days", now="2026-11-03T18:00:00Z")["recovered_interrupted_runs"],
                         [out["run_id"]])

    def test_corrupt_or_duplicate_key_state_fails_closed(self):
        path = os.path.join(self.root, ".repo-kit", "contre-attaque", "state.json")
        self.start("3days")
        for body in ("{", '{"schema_version": 1, "schema_version": 1}', '{"schema_version": 99}'):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
            code, err = self.cli("status")
            self.assertEqual(code, 1, body)
            self.assertEqual(err["status"], "error")
            code, _ = self.cli("start", "3days", transport=standard_transport())
            self.assertEqual(code, 1)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), body, "corrupt state is never overwritten")


if __name__ == "__main__":
    unittest.main()

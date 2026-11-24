#!/usr/bin/env python3
"""Turn one Gitleaks JSON report into a secret-minimized handoff.

Supported input is the built-in JSON report from Gitleaks v8.30.1, commit
83d9cd684c87d95d656c1458ef04895a7f1cbd8e. report/json.go writes a JSON array
of finding objects with encoding/json. This program does not run Gitleaks.

The report path and the handoff path are the caller's explicit selections.
Paths named inside the report are not opened. Caller-supplied metadata is
stored as a claim: it is not an approval and it is not a verified version.
An empty array does not show that a scan completed.

These file checks are not a sandbox against a malicious same-user process
or a hostile replacement of an ancestor directory.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_IO = 3
EXIT_MALFORMED = 4
EXIT_UNSUPPORTED = 5
EXIT_LIMIT = 6

MAX_INPUT_BYTES = 1_048_576
MAX_RECORDS = 200
MAX_COPIED_STRING = 256
MAX_OUTPUT_BYTES = 73_728
MAX_DEPTH = 32
MAX_LINE = 1_000_000
MAX_KEY_LENGTH = 64
MAX_NUMBER_LENGTH = 64

FORMAT_VERSION = "v8.30.1"
FORMAT_REVISION = "83d9cd684c87d95d656c1458ef04895a7f1cbd8e"
FORMAT_SOURCE = "https://github.com/gitleaks/gitleaks/blob/v8.30.1/report/json.go"
ADAPTER_ID = "gitleaks-json-handoff"
SUMMARY = "Unreviewed secrets-detection lead. No secret value is included."
SCANNER_OUTCOMES = frozenset(
    {"completed", "error", "timeout", "unsupported", "truncated", "skipped", "unknown"}
)
_CHECK_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,31}$")
_RETAINED = frozenset({"RuleID", "File", "StartLine", "EndLine"})


class HandoffError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _Dropped:
    """A retained field that must not be copied."""


_DROPPED = _Dropped()


def evidence_path_error(path: object) -> str | None:
    """Lexical repository-relative path check. Does not open or resolve.

    Keep this in step with hermes_vps_common.evidence_path_error and
    ca_state.evidence_path_error.
    """
    if not isinstance(path, str):
        return "must be a string"
    if path == "" or path.strip() == "":
        return "empty or whitespace-only"
    if any(unicodedata.category(ch) == "Cc" for ch in path):
        return "contains a control character"
    if "\\" in path:
        return "contains a backslash"
    if path.startswith("/"):
        return "is absolute"
    if "://" in path or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", path):
        return "is a URI or drive-qualified path"
    parts = path.split("/")
    if any(part == "" for part in parts):
        return "has an empty component"
    for part in parts:
        if part in (".", ".."):
            return f"contains a {part!r} component"
    return None


class _Parser:
    def __init__(self, text: str) -> None:
        self.s = text
        self.n = len(text)
        self.i = 0
        self.depth = 0

    def report(self) -> list[dict[str, object]]:
        self._skip()
        if self.i >= self.n:
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        if self.s[self.i] != "[":
            self._value(keep=False)
            self._skip()
            if self.i != self.n:
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
            raise HandoffError(EXIT_UNSUPPORTED, "unsupported format")
        findings = self._array(findings=True)
        self._skip()
        if self.i != self.n:
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        return findings

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise HandoffError(EXIT_MALFORMED, "excessive nesting")

    def _leave(self) -> None:
        self.depth -= 1

    def _skip(self) -> None:
        s = self.s
        n = self.n
        i = self.i
        while i < n and s[i] in " \t\r\n":
            i += 1
        self.i = i

    def _peek(self, ch: str) -> bool:
        return self.i < self.n and self.s[self.i] == ch

    def _array(self, findings: bool) -> list[dict[str, object]]:
        self._enter()
        if not self._peek("["):
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        self.i += 1
        items: list[dict[str, object]] = []
        self._skip()
        if self._peek("]"):
            self.i += 1
            self._leave()
            return items
        while True:
            if findings:
                if len(items) >= MAX_RECORDS:
                    raise HandoffError(EXIT_LIMIT, "limit exceeded: records")
                items.append(self._finding())
            else:
                self._value(keep=False)
            self._skip()
            if self._peek("]"):
                self.i += 1
                self._leave()
                return items
            if not self._peek(","):
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
            self.i += 1
            self._skip()

    def _finding(self) -> dict[str, object]:
        self._skip()
        if not self._peek("{"):
            raise HandoffError(EXIT_MALFORMED, "malformed record")
        value = self._object(retain=True)
        if not isinstance(value, dict):
            raise HandoffError(EXIT_MALFORMED, "malformed record")
        return value

    def _object(self, retain: bool) -> dict[str, object] | None:
        self._enter()
        if not self._peek("{"):
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        self.i += 1
        seen: set[str] = set()
        kept: dict[str, object] = {}
        self._skip()
        if self._peek("}"):
            self.i += 1
            self._leave()
            return kept if retain else None
        while True:
            key = self._string(keep=True, limit=MAX_KEY_LENGTH, controls_fail=True)
            if not isinstance(key, str):
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
            if key in seen:
                raise HandoffError(EXIT_MALFORMED, "duplicate JSON key")
            seen.add(key)
            self._skip()
            if not self._peek(":"):
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
            self.i += 1
            keep_value = retain and key in _RETAINED
            value = self._value(keep=keep_value)
            if keep_value:
                kept[key] = value
            self._skip()
            if self._peek("}"):
                self.i += 1
                self._leave()
                return kept if retain else None
            if not self._peek(","):
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
            self.i += 1
            self._skip()

    def _value(self, keep: bool) -> object:
        self._skip()
        if self.i >= self.n:
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        ch = self.s[self.i]
        if ch == '"':
            return self._string(keep=keep, limit=MAX_COPIED_STRING, controls_fail=False)
        if ch == "{":
            self._object(retain=False)
            return None
        if ch == "[":
            self._array(findings=False)
            return None
        if ch == "t":
            self._literal("true")
            return None
        if ch == "f":
            self._literal("false")
            return None
        if ch == "n":
            self._literal("null")
            return None
        if ch == "-" or ch.isdigit():
            return self._number(keep=keep)
        raise HandoffError(EXIT_MALFORMED, "malformed JSON")

    def _literal(self, word: str) -> None:
        if not self.s.startswith(word, self.i):
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        self.i += len(word)

    def _number(self, keep: bool) -> object:
        start = self.i
        s = self.s
        if self._peek("-"):
            self.i += 1
        if self.i >= self.n or not s[self.i].isdigit():
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        if s[self.i] == "0":
            self.i += 1
            if self.i < self.n and s[self.i].isdigit():
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        else:
            while self.i < self.n and s[self.i].isdigit():
                self.i += 1
        integer = True
        if self.i < self.n and s[self.i] == ".":
            integer = False
            self.i += 1
            if self.i >= self.n or not s[self.i].isdigit():
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
            while self.i < self.n and s[self.i].isdigit():
                self.i += 1
        if self.i < self.n and s[self.i] in "eE":
            integer = False
            self.i += 1
            if self.i < self.n and s[self.i] in "+-":
                self.i += 1
            if self.i >= self.n or not s[self.i].isdigit():
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
            while self.i < self.n and s[self.i].isdigit():
                self.i += 1
        if self.i - start > MAX_NUMBER_LENGTH:
            raise HandoffError(EXIT_LIMIT, "limit exceeded: value")
        if not keep or not integer or s[start] == "-":
            return None if not keep else _DROPPED
        value = int(s[start:self.i])
        if value < 1 or value > MAX_LINE:
            return _DROPPED
        return value

    def _string(self, keep: bool, limit: int, controls_fail: bool) -> object:
        if not self._peek('"'):
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        self.i += 1
        chars: list[str] = []
        length = 0
        while self.i < self.n:
            ch = self.s[self.i]
            if ch == '"':
                self.i += 1
                if not keep:
                    return None
                text = "".join(chars)
                if any(unicodedata.category(item) == "Cc" for item in text):
                    if controls_fail:
                        raise HandoffError(EXIT_MALFORMED, "malformed JSON")
                    return _DROPPED
                return text
            if ch == "\\":
                decoded = self._escape()
            else:
                if unicodedata.category(ch) == "Cc":
                    raise HandoffError(EXIT_MALFORMED, "malformed JSON")
                decoded = ch
                self.i += 1
            length += len(decoded)
            if keep and length > limit:
                raise HandoffError(EXIT_LIMIT, "limit exceeded: copied string")
            if keep:
                chars.append(decoded)
        raise HandoffError(EXIT_MALFORMED, "malformed JSON")

    def _escape(self) -> str:
        self.i += 1
        if self.i >= self.n:
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        ch = self.s[self.i]
        self.i += 1
        simple = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
        if ch in simple:
            return simple[ch]
        if ch != "u":
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        return self._u_escape()

    def _u_escape(self) -> str:
        code = self._hex4()
        if 0xD800 <= code <= 0xDBFF:
            if not self.s.startswith("\\u", self.i):
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
            self.i += 2
            low = self._hex4()
            if not 0xDC00 <= low <= 0xDFFF:
                raise HandoffError(EXIT_MALFORMED, "malformed JSON")
            code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
        elif 0xDC00 <= code <= 0xDFFF:
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        return chr(code)

    def _hex4(self) -> int:
        chunk = self.s[self.i:self.i + 4]
        if len(chunk) != 4 or any(ch not in "0123456789abcdefABCDEF" for ch in chunk):
            raise HandoffError(EXIT_MALFORMED, "malformed JSON")
        self.i += 4
        return int(chunk, 16)


def _claim(value: str) -> str:
    if value == "" or any(unicodedata.category(ch) == "Cc" for ch in value):
        raise HandoffError(EXIT_USAGE, "invalid arguments")
    if len(value) > MAX_COPIED_STRING:
        raise HandoffError(EXIT_USAGE, "invalid arguments")
    return value


def _check_id(value: str) -> str:
    if _claim(value) != value or not _CHECK_ID.fullmatch(value):
        raise HandoffError(EXIT_USAGE, "invalid arguments")
    if value.startswith("SG-") or value.startswith("WC-"):
        raise HandoffError(EXIT_USAGE, "invalid arguments")
    return value


def _read_input(path: str) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise HandoffError(EXIT_IO, "input is a symlink") from None
        raise HandoffError(EXIT_IO, "input could not be read") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise HandoffError(EXIT_IO, "input is not a regular file")
        chunks: list[bytes] = []
        total = 0
        cap = MAX_INPUT_BYTES + 1
        while total < cap:
            chunk = os.read(fd, min(65536, cap - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > MAX_INPUT_BYTES:
            raise HandoffError(EXIT_LIMIT, "limit exceeded: input bytes")
        return b"".join(chunks), info
    finally:
        os.close(fd)


def _write_output(path: str, payload: bytes, source: os.stat_result, source_path: str) -> None:
    if os.path.abspath(path) == os.path.abspath(source_path):
        raise HandoffError(EXIT_IO, "input and output alias")
    parent = os.path.dirname(path) or "."
    try:
        parent_info = os.stat(parent)
    except OSError:
        raise HandoffError(EXIT_IO, "output parent directory is missing") from None
    if not stat.S_ISDIR(parent_info.st_mode):
        raise HandoffError(EXIT_IO, "output parent directory is missing")
    try:
        existing = os.lstat(path)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if existing.st_dev == source.st_dev and existing.st_ino == source.st_ino:
            raise HandoffError(EXIT_IO, "input and output alias")
        raise HandoffError(EXIT_IO, "output already exists")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise HandoffError(EXIT_IO, "output already exists") from None
        raise HandoffError(EXIT_IO, "output could not be created") from None
    committed = False
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise HandoffError(EXIT_IO, "output could not be created")
            view = view[written:]
        os.fsync(fd)
        committed = True
    finally:
        os.close(fd)
        if not committed:
            try:
                os.unlink(path)
            except OSError:
                pass


def _location(value: object) -> tuple[dict[str, str], bool]:
    if not isinstance(value, str) or evidence_path_error(value) is not None:
        return {"status": "unavailable", "reason": "location-unavailable"}, True
    return {"status": "untrusted", "path": value}, False


def _rule(value: object) -> tuple[str | None, str, bool]:
    if not isinstance(value, str) or value == "" or value.strip() == "":
        return None, "unavailable", True
    return value, "present", False


def _line_range(record: dict[str, object]) -> tuple[dict[str, int] | None, bool]:
    has_start = "StartLine" in record
    has_end = "EndLine" in record
    if not has_start and not has_end:
        return None, False
    start = record.get("StartLine")
    end = record.get("EndLine")
    if isinstance(start, int) and isinstance(end, int) and end >= start:
        return {"startLine": start, "endLine": end}, False
    return None, True


def _leads(records: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, int]]:
    leads: list[dict[str, object]] = []
    omitted_rules = 0
    omitted_locations = 0
    omitted_lines = 0
    for index, record in enumerate(records, start=1):
        rule_id, rule_status, rule_omitted = _rule(record.get("RuleID"))
        if "RuleID" not in record:
            rule_id, rule_status, rule_omitted = None, "unavailable", True
        location, location_omitted = _location(record.get("File") if "File" in record else None)
        if "File" not in record:
            location, location_omitted = {"status": "unavailable", "reason": "location-unavailable"}, True
        line_range, line_omitted = _line_range(record)
        omitted_rules += int(rule_omitted)
        omitted_locations += int(location_omitted)
        omitted_lines += int(line_omitted)
        lead: dict[str, object] = {
            "leadId": f"L-{index:03d}",
            "ruleId": rule_id,
            "ruleIdStatus": rule_status,
            "location": location,
            "summary": SUMMARY,
        }
        if line_range is not None:
            lead["lineRange"] = line_range
        leads.append(lead)
    counts = {
        "records": len(records),
        "leads": len(leads),
        "locationsOmitted": omitted_locations,
        "lineRangesOmitted": omitted_lines,
        "ruleIdsOmitted": omitted_rules,
    }
    return leads, counts


def build_handoff(raw: bytes, claims: dict[str, str]) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise HandoffError(EXIT_MALFORMED, "invalid UTF-8") from None
    if text.startswith("\ufeff"):
        raise HandoffError(EXIT_MALFORMED, "malformed JSON")
    records = _Parser(text).report()
    leads, counts = _leads(records)
    document = {
        "schemaVersion": 1,
        "adapter": ADAPTER_ID,
        "format": {
            "id": "gitleaks-json-array",
            "version": FORMAT_VERSION,
            "revision": FORMAT_REVISION,
            "source": FORMAT_SOURCE,
        },
        "input": {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byteCount": len(raw),
        },
        "callerSupplied": {
            "origin": "caller-supplied",
            "approved": False,
            "verified": False,
            "checkId": claims["checkId"],
            "sourceRevision": claims["sourceRevision"],
            "workingTree": claims["workingTree"],
            "toolVersion": claims["toolVersion"],
            "rulesIdentity": claims["rulesIdentity"],
            "reportProvenance": claims["reportProvenance"],
            "scannerOutcome": claims["scannerOutcome"],
        },
        "parsingOutcome": "empty" if not records else "normalized",
        "declaredScannerOutcome": claims["scannerOutcome"],
        "counts": counts,
        "limits": {
            "maxInputBytes": MAX_INPUT_BYTES,
            "maxRecords": MAX_RECORDS,
            "maxCopiedString": MAX_COPIED_STRING,
            "maxOutputBytes": MAX_OUTPUT_BYTES,
        },
        "limitations": [
            "Allowlisting removes known sensitive finding fields. Filenames and rule identifiers can still be sensitive.",
            "This handoff is not proven free of secrets for arbitrary hostile input.",
            "Locations are untrusted and were not opened or resolved.",
            "An empty report does not show that a scan completed.",
            "Caller-supplied metadata is not an approval or a verified version.",
            "No WC-* mapping, severity, entrySink, or reviewed status is assigned.",
            "File checks do not sandbox a malicious same-user process or a replaced ancestor directory.",
        ],
        "leads": leads,
    }
    encoded = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise HandoffError(EXIT_LIMIT, "limit exceeded: output")
    return encoded


def normalize(input_path: str, output_path: str, claims: dict[str, str]) -> None:
    raw, info = _read_input(input_path)
    payload = build_handoff(raw, claims)
    _write_output(output_path, payload, info, input_path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitleaks_handoff.py", add_help=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--check-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--working-tree", required=True)
    parser.add_argument("--tool-version", required=True)
    parser.add_argument("--rules-identity", required=True)
    parser.add_argument("--report-provenance", required=True)
    parser.add_argument("--scanner-outcome", required=True)

    def reject(message: str) -> None:
        print("gitleaks-handoff: invalid arguments", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)

    parser.error = reject  # type: ignore[method-assign]
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        outcome = args.scanner_outcome
        if outcome not in SCANNER_OUTCOMES:
            raise HandoffError(EXIT_USAGE, "invalid arguments")
        claims = {
            "checkId": _check_id(args.check_id),
            "sourceRevision": _claim(args.source_revision),
            "workingTree": _claim(args.working_tree),
            "toolVersion": _claim(args.tool_version),
            "rulesIdentity": _claim(args.rules_identity),
            "reportProvenance": _claim(args.report_provenance),
            "scannerOutcome": outcome,
        }
        normalize(args.input, args.output, claims)
        return EXIT_OK
    except HandoffError as exc:
        print(f"gitleaks-handoff: {exc.message}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())

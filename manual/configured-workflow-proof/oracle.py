"""Explicit local business oracle; never launches agents or submits Workflow reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CASES = [
    ("local-base", {"subtotal": "499.99", "weight_grams": 1000, "zone": "local"}, 200,
     {"shipping": "15.00", "total": "514.99", "currency": "RUB"}),
    ("local-threshold-below", {"subtotal": "999.99", "weight_grams": 1, "zone": "local"}, 200,
     {"shipping": "15.00", "total": "1014.99", "currency": "RUB"}),
    ("local-free", {"subtotal": "1000.00", "weight_grams": 1000, "zone": "local"}, 200,
     {"shipping": "0.00", "total": "1000.00", "currency": "RUB"}),
    ("free-keeps-weight", {"subtotal": "1000.00", "weight_grams": 1001, "zone": "local"}, 200,
     {"shipping": "5.00", "total": "1005.00", "currency": "RUB"}),
    ("weight-block-exact", {"subtotal": "0.00", "weight_grams": 2000, "zone": "local"}, 200,
     {"shipping": "20.00", "total": "20.00", "currency": "RUB"}),
    ("weight-block-ceil", {"subtotal": "0.00", "weight_grams": 2001, "zone": "local"}, 200,
     {"shipping": "25.00", "total": "25.00", "currency": "RUB"}),
    ("remote-never-free", {"subtotal": "1000.00", "weight_grams": 1000, "zone": "remote"}, 200,
     {"shipping": "25.00", "total": "1025.00", "currency": "RUB"}),
    ("maximum-weight", {"subtotal": "1000.00", "weight_grams": 20000, "zone": "remote"}, 200,
     {"shipping": "120.00", "total": "1120.00", "currency": "RUB"}),
    ("unknown-zone", {"subtotal": "1.00", "weight_grams": 1, "zone": "moon"}, 400, None),
    ("negative-money", {"subtotal": "-0.01", "weight_grams": 1, "zone": "local"}, 400, None),
    ("excess-precision", {"subtotal": "1.001", "weight_grams": 1, "zone": "local"}, 400, None),
    ("numeric-money", {"subtotal": 1, "weight_grams": 1, "zone": "local"}, 400, None),
    ("zero-weight", {"subtotal": "1.00", "weight_grams": 0, "zone": "local"}, 400, None),
    ("excess-weight", {"subtotal": "1.00", "weight_grams": 20001, "zone": "local"}, 400, None),
    ("fractional-weight", {"subtotal": "1.00", "weight_grams": 1.5, "zone": "local"}, 400, None),
    ("boolean-weight", {"subtotal": "1.00", "weight_grams": True, "zone": "local"}, 400, None),
    ("missing-fields", {}, 400, None),
    ("unknown-field", {"subtotal": "1.00", "weight_grams": 1, "zone": "local", "override": 0}, 400, None),
]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Deployed proof workload in PDLC1, loopback only")
    parser.add_argument("--candidate-sha", required=True, help="Exact independently verified source commit")
    parser.add_argument("--output", required=True, type=Path, help="New report file in the operator evidence directory")
    args = parser.parse_args()
    url = urllib.parse.urlsplit(args.base_url)
    if (url.scheme not in {"http", "https"} or url.hostname not in {"localhost", "127.0.0.1"}
            or url.username is not None or url.password is not None or url.query or url.fragment
            or url.path not in {"", "/"}):
        parser.error("base-url must be a loopback workload origin without credentials, path or query")
    if not re.fullmatch(r"[0-9a-f]{40}", args.candidate_sha):
        parser.error("candidate-sha must be the full lowercase Git SHA")
    if args.output.exists():
        parser.error("output already exists; retain the original report")
    args.base_url = args.base_url.rstrip("/")
    return args


def main() -> int:
    args = arguments()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    results = []
    cases = [("health", None, 200, {"status": "ok"}), *CASES]
    for name, payload, status, expected in cases:
        request_bytes = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(args.base_url + ("/health" if payload is None else "/quote"),
                                         data=request_bytes, headers={"Content-Type": "application/json"})
        result = {"case": name, "expected_status": status, "passed": False}
        try:
            try:
                response = opener.open(request, timeout=5)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                result["actual_status"] = response.code
                raw = response.read(16385)
            if len(raw) > 16384:
                result["error"] = "response exceeds 16 KiB"
            else:
                result["response_sha256"] = hashlib.sha256(raw).hexdigest()
                value = json.loads(raw)
                matches = expected is None or value == expected
                if name == "health":
                    matches = isinstance(value, dict) and value.get("status") == "ok"
                result["passed"] = response.code == status and matches
        except (OSError, ValueError):
            result["error"] = "HTTP or JSON read failed"
        results.append(result)
    report = {"schema": "workflow-manual-business-oracle/v1", "scope": "PDLC1",
              "candidate_sha": args.candidate_sha, "origin": args.base_url,
              "recorded_at": datetime.now(timezone.utc).isoformat(), "results": results,
              "passed": all(item["passed"] for item in results),
              "proves": "Business HTTP behavior only; execution and deployment provenance need separate evidence"}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    passed = sum(item["passed"] for item in results)
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {passed}/{len(results)} business cases")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

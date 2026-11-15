#!/usr/bin/env python3
"""Immutable XPI 1.6.1 historical reference under shallow CI checkouts.

The historical MP02B commit (24e4ac3) is reachable via GitHub but is not
necessarily in a source-only checkout of a stacked PR. Its reference snapshot
was verified against GitHub blob 77c390a8...; the baseline seal is identical
whether that commit is locally present or not. Never fetch or rewrite history.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path

HISTORICAL_COMMIT = "24e4ac3056a63b2185a7825b43e893cb1f0ba749"
HISTORICAL_GIT_BLOB = "77c390a8c00a90db5a7ee2e5c364efbe968789c2"
HISTORICAL_SNAPSHOT_SHA256 = "03f98f395df9e8a0b48070d4b1865837dc4c7574f75d0055d978d08aac64fd63"
HISTORICAL_PATH = "docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json"
FIELDS = ("reference", "originalXpiSha256", "referenceSnapshotBeforeMp01Sha256")


def exact_snapshot(document):
    if not isinstance(document, dict) or any(key not in document for key in FIELDS):
        raise AssertionError("HISTORICAL_XPI_MISSING_REFERENCE_FIELDS")
    snapshot = {key: document[key] for key in FIELDS}
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if hashlib.sha256(raw).hexdigest() != HISTORICAL_SNAPSHOT_SHA256:
        raise AssertionError("HISTORICAL_XPI_PINNED_SNAPSHOT_DRIFT")
    return snapshot


def historical_reference(document, *, root):
    """Verify pinned historical data offline; optionally cross-check original Git blob.

    Do not mistake a source-only checkout's missing historical commit for a
    changed XPI. Missing history is normal; malformed or present-but-drifted
    historical content is NOT. The fixed SHA-256 seal is always required.
    """
    actual = exact_snapshot(document)
    repo = Path(root)
    probe = subprocess.run(["git", "cat-file", "-e", HISTORICAL_COMMIT + "^{commit}"],
                           cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=30, check=False)
    if probe.returncode != 0:
        return "XGO_XPI_HISTORICAL_SHA256_SEAL_PASS_LOCAL_COMMIT_ABSENT"
    result = subprocess.run(["git", "show", HISTORICAL_COMMIT + ":" + HISTORICAL_PATH],
                            cwd=repo, capture_output=True, timeout=35, check=False)
    if result.returncode:
        raise AssertionError("HISTORICAL_XPI_GIT_MANIFEST_MISSING_WITH_COMMIT_PRESENT")
    data = result.stdout
    actual_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual_blob != HISTORICAL_GIT_BLOB:
        raise AssertionError("HISTORICAL_XPI_GIT_BLOB_DRIFT")
    original = json.loads(data)
    if {key: original.get(key) for key in FIELDS} != actual:
        raise AssertionError("HISTORICAL_XPI_GIT_REFERENCE_DRIFT")
    return "XGO_XPI_HISTORICAL_GIT_BLOB_AND_SHA256_SEAL_PASS"

#!/usr/bin/env python3
"""XGO CI05: targeted source testing and exact-SHA periodic full qualification.

Routine change checks never dispatch a heavy workflow. Only the main-branch
router dispatches the retained workflows. A gate checkpoint is recorded only
when every mandatory hosted job succeeded at the current exact main SHA.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
INITIAL_ACCOUNTING_SHA = "cbebbb03a9a36266977e6cd5e7403900857a94a3"
DEFAULT_INTERVAL = 5
GATE_TAG_PREFIX = "xgo-full-gate/"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# This anchor is an accounting baseline only. It is NOT a full-gate receipt.
# The first CI-policy change is high-risk and forces a fresh full gate on main.
WORKFLOWS = {
    "android.yml": {
        "hotfix-fast", "validate", "emulator-compatibility"
    },
    "modern-ci.yml": {
        "modern-fast", "validate (ubuntu-latest)", "validate (windows-latest)",
        "native-linux-arm64", "native-windows-arm64"
    },
    "media-parity.yml": {
        "MP00 playable HLS DASH server and evidence",
        "MP00 existing Android media JVM regressions",
        "MP00 existing Go and Firefox Node suites"
    },
    "devtool-xgo-engine.yml": {"source", "engine"},
}

EXTENSION_TESTS = [
    "app/XDM.Android/browser-extension/tests/test_detector.js",
    "app/XDM.Android/browser-extension/tests/test_handoff.js",
    "app/XDM.Android/browser-extension/tests/test_secure_handoff.js",
    "app/XDM.Android/browser-extension/tests/test_background.js",
    "app/XDM.Android/browser-extension/tests/test_fab.js",
    "app/XDM.Android/browser-extension/tests/test_phase43a_bridge.js",
    "app/XDM.Android/browser-extension/tests/test_release_gate.js",
    "app/XDM.Android/browser-extension/tests/test_mp02_discovery.js",
    "app/XDM.Android/browser-extension/tests/test_mp02b_site_mode.js",
    "app/XDM.Android/browser-extension/tests/test_mp02c_playback.js",
    "app/XDM.Android/browser-extension/tests/test_mp02c_observer.js",
]
EXTENSION_PYTHON = [
    "scripts/test_xgo_mp02b_source_contract.py",
    "scripts/test_xgo_mp02c_source_contract.py",
    "scripts/test_xgo_mp02c_staleness_audit.py",
    "scripts/test_xgo_mp01_hf05_xpi_guard.py",
    "scripts/test_xgo_mp01_hf06_capture_contract.py",
    "scripts/test_xgo_mp02a_source_contract.py",
    "app/XDM.Android/tools/validate-xar10-browser-capture-evidence.py",
    "app/XDM/eng/validate-xfe01-single-firefox-extension.py",
]
ANDROID_SOURCE_TESTS = [
    "scripts/test_xgo_mp01_hf07_emulator_contract.py",
    "scripts/test_xgo_xp02b_browser_emulator_ci.py",
]
MODERN_SOURCE_TESTS = [
    "app/XDM/eng/validate-xfe01-single-firefox-extension.py",
    "app/XDM/eng/rem18-release-matrix-audit.py",
]
MP03_PYTHON = [
    "scripts/test_xgo_mp03_source_contract.py",
    "scripts/test_xgo_mp03_staleness_contract.py",
    "scripts/test_xgo_mp03_android_e2e_contract.py",
    "scripts/test_xgo_mp03_android_staleness.py",
]
POLICY_TESTS = [
    "scripts/ci/test_xgo_ci_policy.py",
    "scripts/test_xgo_mp01_hf04_ci_tiers.py",
]

# A full gate is mandatory on main after these source changes; a fast PR check
# is never permission to release/publish or to omit ARM64 physical acceptance.
RISK_PREFIXES = (
    ".github/workflows/", "scripts/ci/", ".devtool.toml",
    "app/XDM.Android/app/build.gradle.kts", "app/XDM.Android/gradle/",
    "app/XDM.Android/browser-extension/src/main/extension/xdm-firefox/handoff.js",
    "app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/BrowserCaptureEnvelopeManager.kt",
    "app/XDM.Android/browser-integration/src/main/kotlin/",
    "app/XDM.Android/app/src/main/AndroidManifest.xml",
    "app/XDM.Android/app/src/main/jniLibs/", "tools/xgo/build_android_",
    "scripts/run_physical_arm64_instrumentation.sh",
    "app/XDM/packaging/", "app/XDM/eng/publish-",
    "build-release-apk.sh", "engine/runtime/",
)
RISK_TERMS = ("security", "signature", "signing", "release", "keystore", "migration", "crypto", "trust", "credential")


def git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd or ROOT, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise RuntimeError("XGO_CI_GIT_REFUSED: " + " ".join(args) + ": " + proc.stderr.strip()[:200])
    return proc.stdout.strip()


def paths_between(base: str, head: str, *, cwd: Path | None = None) -> list[str]:
    if not SHA_RE.fullmatch(base) or not SHA_RE.fullmatch(head):
        raise ValueError("XGO_CI_REFUSED: complete 40-character Git SHAs required")
    return sorted(set(filter(None, git("diff", "--name-only", "--no-renames",
                                       "--diff-filter=ACDMRTUXB", base, head,
                                       cwd=cwd).splitlines())))


def is_risk(path: str) -> bool:
    p = path.lower()
    return any(p.startswith(x.lower()) for x in RISK_PREFIXES) or (
        any(term in p for term in RISK_TERMS) and
        p.startswith(("app/", "engine/", "scripts/", "tools/"))
    )


def classify(paths: list[str]) -> dict:
    groups: set[str] = set()
    unknown = False
    for path in paths:
        if path.startswith(("app/XDM.Android/browser-extension/",)):
            groups.add("extension")
        elif path.startswith(("app/XDM.Android/",)):
            groups.add("android")
        elif path.startswith(("app/XDM/", "app/XDM.Modern/")):
            groups.add("modern")
        elif path.startswith(("engine/", "tools/xgo/")) or path == "go.work":
            groups.add("go")
        elif path.startswith("tests/media-parity/"):
            groups.add("media")
        elif path.startswith((".github/workflows/", "scripts/ci/")):
            groups.update(("ci", "extension", "android", "modern", "go", "media"))
        elif path.startswith("scripts/"):
            groups.add("ci")
        elif path.startswith(("docs/", "README", ".gitignore")):
            groups.add("docs")
        else:
            unknown = True
    if unknown:
        groups.update(("ci", "extension", "android", "modern", "go", "media"))
    tests = set(POLICY_TESTS)
    if groups & {"extension", "media", "ci"}:
        tests.update(EXTENSION_TESTS)
        tests.update(EXTENSION_PYTHON)
    if groups & {"go", "android", "ci"}:
        tests.update(MP03_PYTHON)
    if groups & {"android", "ci"}:
        tests.update(ANDROID_SOURCE_TESTS)
        tests.add("app/XDM.Android/tools/validate-xar10-browser-capture-evidence.py")
    if groups & {"modern", "ci"}:
        tests.update(MODERN_SOURCE_TESTS)
    return {
        "groups": sorted(groups) if groups else ["docs"],
        "tests": sorted(tests),
        "needs_android_compile": any(p.startswith(("app/XDM.Android/app/src/", "app/XDM.Android/browser-integration/src/",
                                                      "app/XDM.Android/app/build.gradle", "app/XDM.Android/gradle/")) for p in paths),
        "needs_go": "go" in groups,
        "ci_sensitive": "ci" in groups,
        "high_risk": any(is_risk(p) for p in paths),
        "changed_files": len(paths),
    }


def run_targeted(base: str, head: str, *, cwd: Path | None = None) -> dict:
    root = cwd or ROOT
    planned = classify(paths_between(base, head, cwd=root))
    print("XGO_CI_TARGETED_PLAN=" + json.dumps(planned, sort_keys=True), flush=True)
    for name in planned["tests"]:
        if not (root / name).is_file():
            raise RuntimeError("XGO_CI_MISSING_REQUIRED_TEST: " + name)
        cmd = (["node", name] if name.endswith(".js") else [sys.executable, "-B", name])
        print("XGO_CI_TARGETED_TEST=" + name, flush=True)
        subprocess.run(cmd, cwd=root, check=True)
    if planned["needs_go"]:
        subprocess.run(["go", "test", "./..."], cwd=root / "engine", check=True)
    print("XGO_CI_TARGETED_PASS: exact source targeted checks", flush=True)
    return planned


def first_parent(head: str, *, cwd: Path | None = None) -> list[str]:
    if not SHA_RE.fullmatch(head):
        raise ValueError("XGO_CI_REFUSED: full head SHA required")
    return git("rev-list", "--first-parent", head, cwd=cwd).splitlines()


def most_recent_gate(head: str, *, cwd: Path | None = None) -> tuple[str, str]:
    chain = first_parent(head, cwd=cwd)
    eligible = set(chain)
    tags = git("tag", "--list", GATE_TAG_PREFIX + "*", cwd=cwd).splitlines()
    by_commit: dict[str, str] = {}
    for tag in tags:
        if not re.fullmatch(r"xgo-full-gate/[0-9]+", tag):
            continue
        commit = git("rev-parse", f"refs/tags/{tag}^{{commit}}", cwd=cwd)
        if commit in eligible:
            by_commit[commit] = tag
    for sha in chain:
        if sha in by_commit:
            return sha, by_commit[sha]
    if INITIAL_ACCOUNTING_SHA not in eligible:
        raise RuntimeError("XGO_CI_REFUSED: accounting baseline not on first-parent main history")
    return INITIAL_ACCOUNTING_SHA, "accounting-only-not-qualified"


def gate_plan(head: str, interval: int = DEFAULT_INTERVAL, *, cwd: Path | None = None, force: bool = False) -> dict:
    if not 1 <= interval <= 25:
        raise ValueError("XGO_CI_REFUSED: full gate interval must be 1..25")
    history = first_parent(head, cwd=cwd)
    baseline, baseline_tag = most_recent_gate(head, cwd=cwd)
    units = history.index(baseline)
    high_risk = [p for p in paths_between(baseline, head, cwd=cwd) if is_risk(p)]
    reasons = (["manual"] if force else []) + (["cadence"] if units >= interval else []) + (["high-risk"] if high_risk else [])
    return {"due": bool(reasons), "head": head, "interval": interval,
            "integrations_since_gate": units, "baseline": baseline,
            "baseline_tag": baseline_tag, "reason": reasons, "high_risk_paths": high_risk,
            "gate_qualified": baseline_tag != "accounting-only-not-qualified"}


def api(method: str, path: str, payload: dict | None = None) -> dict:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not token or repo != "Mikeyphw/xdm-xgo":
        raise RuntimeError("XGO_CI_REFUSED: dedicated repository token/context required")
    url = "https://api.github.com/repos/" + repo + "/" + path.lstrip("/")
    request = Request(url, method=method,
                      data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Authorization": "Bearer " + token,
                               "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28",
                               "User-Agent": "xgo-ci05-gate"})
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except (HTTPError, URLError) as err:
        raise RuntimeError("XGO_CI_API_REFUSED: " + method + " " + path +
                           "; HTTP/network error (details intentionally withheld)") from err


def ensure_main(head: str) -> None:
    if os.getenv("GITHUB_REF") != "refs/heads/main":
        raise RuntimeError("XGO_CI_REFUSED: router restricted to main")
    b = api("GET", "branches/main")
    if b["commit"]["sha"] != head:
        raise RuntimeError("XGO_CI_REFUSED: main advanced; gate not certified")


def runs_for(file: str, head: str) -> list[dict]:
    # Only recent runs at the current exact SHA are relevant. In large repos
    # historical workflow runs may exceed one page; never reject solely for that.
    results = []
    for page in range(1, 6):
        result = api("GET", "actions/workflows/" + file +
                     "/runs?branch=main&event=workflow_dispatch&per_page=100&page=" + str(page))
        batch = result.get("workflow_runs", [])
        results.extend(r for r in batch if r.get("head_sha") == head and r.get("event") == "workflow_dispatch")
        if len(batch) < 100:
            return results
    raise RuntimeError("XGO_CI_REFUSED: workflow run pagination exceeded safe bound for " + file)


def verify_run(file: str, run: dict, head: str) -> None:
    if run.get("head_sha") != head or run.get("status") != "completed" or run.get("conclusion") != "success":
        raise RuntimeError("XGO_CI_REFUSED: unsuccessful workflow " + file)
    jobs = api("GET", "actions/runs/" + str(run["id"]) + "/jobs?filter=latest&per_page=100")
    if jobs.get("total_count", 0) > 100:
        raise RuntimeError("XGO_CI_REFUSED: job listing truncated for " + file)
    names: dict[str, list[dict]] = {}
    for job in jobs.get("jobs", []):
        names.setdefault(job.get("name", ""), []).append(job)
    missing = WORKFLOWS[file] - names.keys()
    if missing:
        raise RuntimeError("XGO_CI_REFUSED: missing mandatory " + file + " jobs: " + repr(sorted(missing)))
    for name in WORKFLOWS[file]:
        matched = names[name]
        if len(matched) != 1 or matched[0].get("conclusion") != "success" or matched[0].get("status") != "completed" or matched[0].get("head_sha", head) != head:
            raise RuntimeError("XGO_CI_REFUSED: mandatory job failed or ambiguous: " + file + ":" + name)
    print("XGO_FULL_GATE_WORKFLOW_PASS=" + file + ":" + str(run["id"]), flush=True)


def authenticate_last_gate(plan: dict) -> None:
    """Reject forged/repointed checkpoint tags: the named router run must be green."""
    tag = plan["baseline_tag"]
    if tag == "accounting-only-not-qualified":
        return
    run_id = tag.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[0-9]+", run_id):
        raise RuntimeError("XGO_CI_REFUSED: checkpoint is not a router-run tag")
    run = api("GET", "actions/runs/" + run_id)
    if (run.get("head_sha") != plan["baseline"] or
            run.get("status") != "completed" or run.get("conclusion") != "success" or
            run.get("head_branch") != "main" or
            not str(run.get("path", "")).endswith("/.github/workflows/xgo-full-gate-router.yml") and
            str(run.get("path", "")) != ".github/workflows/xgo-full-gate-router.yml"):
        raise RuntimeError("XGO_CI_REFUSED: checkpoint tag has no qualified router run")
    jobs = api("GET", "actions/runs/" + run_id + "/jobs?per_page=100")
    names = {j.get("name"): j for j in jobs.get("jobs", [])}
    for expected in ("Calculate five-integration checkpoint and security overrides",
                     "Four full workflows / 13 mandatory jobs on exact main SHA"):
        j = names.get(expected)
        if not j or j.get("conclusion") != "success" or j.get("status") != "completed":
            raise RuntimeError("XGO_CI_REFUSED: checkpoint router jobs are not all green")
    print("XGO_CI_CHECKPOINT_AUTHENTICATED=" + tag, flush=True)


def gate_dispatch(head: str, interval: int, *, force: bool) -> None:
    plan = gate_plan(head, interval, force=force)
    print("XGO_CI_GATE_PLAN=" + json.dumps(plan, sort_keys=True), flush=True)
    authenticate_last_gate(plan)
    if not plan["due"]:
        print("XGO_CI_GATE_NOT_DUE: no full workflow dispatched", flush=True)
        return
    ensure_main(head)
    previous = {name: {r["id"] for r in runs_for(name, head)} for name in WORKFLOWS}
    for name in WORKFLOWS:
        api("POST", "actions/workflows/" + name + "/dispatches", {"ref": "main"})
        print("XGO_FULL_GATE_DISPATCHED=" + name, flush=True)
    waiting = set(WORKFLOWS)
    deadline = time.monotonic() + 105 * 60
    while waiting and time.monotonic() < deadline:
        ensure_main(head)
        for name in sorted(waiting):
            matches = [r for r in runs_for(name, head) if r["id"] not in previous[name]]
            if not matches:
                continue
            run = max(matches, key=lambda r: r["id"])
            if run.get("status") == "completed":
                verify_run(name, run, head)
                waiting.remove(name)
        if waiting:
            time.sleep(20)
    if waiting:
        raise RuntimeError("XGO_CI_REFUSED: gate timed out: " + repr(sorted(waiting)))
    ensure_main(head)
    run_id = os.getenv("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[0-9]+", run_id):
        raise RuntimeError("XGO_CI_REFUSED: no GitHub router run ID")
    tag = GATE_TAG_PREFIX + run_id
    api("POST", "git/refs", {"ref": "refs/tags/" + tag, "sha": head})
    print("XGO_FULL_GATE_13_JOBS_VERIFIED_AND_TAGGED=" + tag + ":" + head, flush=True)


def write_output(path: str | None, fields: dict[str, str]) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            for k, v in fields.items():
                stream.write(k + "=" + v + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    cmd = parser.add_subparsers(dest="command", required=True)
    for name in ("classify", "run-targeted"):
        p = cmd.add_parser(name)
        p.add_argument("--base", required=True)
        p.add_argument("--head", required=True)
        if name == "classify":
            p.add_argument("--github-output")
    for name in ("gate-plan", "gate-dispatch"):
        p = cmd.add_parser(name)
        p.add_argument("--head", required=True)
        p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
        p.add_argument("--force", action="store_true")
        if name == "gate-plan":
            p.add_argument("--github-output")
    args = parser.parse_args()
    if args.command == "classify":
        plan = classify(paths_between(args.base, args.head))
        print("XGO_CI_TARGETED_PLAN=" + json.dumps(plan, sort_keys=True))
        write_output(args.github_output, {
            "base_sha": args.base, "head_sha": args.head,
            "needs_android_compile": str(plan["needs_android_compile"]).lower(),
            "needs_go": str(plan["needs_go"]).lower(),
        })
    elif args.command == "run-targeted":
        run_targeted(args.base, args.head)
    elif args.command == "gate-plan":
        plan = gate_plan(args.head, args.interval, force=args.force)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            authenticate_last_gate(plan)
        print("XGO_CI_GATE_PLAN=" + json.dumps(plan, sort_keys=True))
        write_output(args.github_output, {"due": str(plan["due"]).lower(),
                                         "integrations_since_gate": str(plan["integrations_since_gate"])})
    else:
        gate_dispatch(args.head, args.interval, force=args.force)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

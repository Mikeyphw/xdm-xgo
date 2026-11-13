# MP12 P01 — evidence-bound production-readiness baseline

This starts **MP12 production qualification, release and desktop parity** after MP11 P04. It is **not a release candidate or release authorization**. It adds source-policy guards, a read-only exact-commit GitHub audit, negative tests, and fail-closed gate statuses. It does not change production media behavior.

## Observed historical evidence (not transferable to a different SHA)

- At `cd4a1a851d3858bb6a2a0b664d54e46f1665d1ed`, `XDM MP00 Media Parity Baseline` [run 43428873102](https://github.com/Mikeyphw/xdm-xgo/actions/runs/43428873102) completed successfully. The API36/x86_64 Compose job opened KVM, started five tests, finished five tests, and emitted `MP11_P04_API36_FIVE_REAL_COMPOSE_TESTS_PASS_NOT_PHYSICAL_ARM64`.
- Exact-head XGO Targeted CI [43368720109](https://github.com/Mikeyphw/xdm-xgo/actions/runs/43368720109) and MP08B3 real-media **source/Linux** [43368720102](https://github.com/Mikeyphw/xdm-xgo/actions/runs/43368720102) passed. The MP08B3 full Android opt-in gate was not implied by its ordinary source/Linux success.
- These are historical receipts. When MP12 P01 creates a new commit, it must obtain new exact-head checks. Old receipts **must not** be promoted to new-HEAD acceptance.

## Fixed MP12 release checklist

`targeted_source`, `mp08b3_linux_media`, `mp11_p04_compose_api36`, `x86_full_native_api36`, `physical_arm64_media`, `signed_android_provenance`, `go_canary_rollback`, `desktop_protocol_parity`, `licensed_1dm_differential`, `perf_chaos_reproducibility`, `user_visible_limitations`.

Only the first four can be supported by the current GitHub run/job evidence adapter, and only for the **same exact SHA** with matching job and execution receipts. Others stay `not_qualified` until dedicated, auditable evidence adapters exist. This avoids false completion from inherited source tests, skipped jobs, emulator compilation, or release artifacts created for another ABI.

## Commands (no local Gradle)

```sh
python3 -B scripts/test_mp12_qualification.py
python3 -B scripts/mp12_qualification.py --source-only
python3 -B scripts/mp12_qualification.py --live --output "$TMPDIR/xgo-mp12-p01-readiness.json"
# Expected to refuse: actual production release gates remain unmet.
python3 -B scripts/mp12_qualification.py --release-gate
```

`--live` uses `gh` to inspect PR #28, current branch/head, actual GitHub workflow runs, their named jobs and the five-case P04 execution marker. It saves only closed-set statuses, IDs and SHA; raw logs never enter the report. `--release-gate` returns a nonzero status while production evidence is unavailable. An offline source-contract pass is not an API36 pass.

## Roadmap after P01

Implement qualified cross-arch release provenance and reproducibility, an explicit unified-Go canary and tested rollback, signed Android release gates, desktop protocol parity and real portable fixtures, then physical ARM64, licensed black-box differential and soak/chaos evidence. Protect the MP08 publish/readback invariant and never infer ARM64 from x86. Do not auto-merge, tag, publish, force push or change user data.

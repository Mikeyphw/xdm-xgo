# MP12 P03 — legacy-first Go canary, durable crash recovery and rollback

This is a **pre-release, opt-in, host-side control protocol**, not authorization to replace the existing Android/desktop downloader. It adds `engine/runtime/canary` with a private durable JSON state and optional `runtime.MP12CanaryHandlers` for the existing `Config.Handlers` mechanism. No Android app or desktop host registers the handlers by default. The Go engine may run **read-only shadow diagnostics only** when an independently trusted host passes a fresh explicit opt-in. The primary engine selection remains `legacy` in every phase.

## Durable transition contract

`legacy -> prepared -> shadow -> rollback_pending -> rolled_back`, with each transition fenced by a single-writer exclusive-create lock, revision CAS, a canonical SHA-256 sealed (non-authenticated) receipt, private directory/file permissions, file sync, atomic rename and parent-directory sync. A second process cannot commit a stale generation. A long-lived stale controller also re-reads the durable receipt before reporting its decision and refuses to re-enable shadow after an external rollback. `Open` auto-rolls an unfinished `prepared`, `shadow`, or `rollback_pending` session back to legacy **before** returning a controller. A stale lock, temporary file, corrupt record, mismatched source SHA or unsafe permission refuses startup, leaving the invoking host responsible for retaining legacy and requesting manual investigation. The seal detects accidental corruption and canonicalization changes; it is not a keyed signature or evidence against a malicious writer with filesystem access.

The optional host command accepts `inspect`, `prepare`, `start_read_only_shadow`, or `rollback`. `prepare` and `start_read_only_shadow` require the handler's **trusted host opt-in argument**, not merely a JSON field from the caller. Host command payloads are bounded, extra JSON fields are rejected, and emitted decisions contain only a fixed set of non-secret values. Rollback is never permission-gated by an opt-in. There is **no production promote action**, no transfer writer switch, no download-state mutation and no physical ARM64 or release-signature claim.

## Tests

`go test -count=1 ./runtime/canary ./runtime` and `go vet ./runtime/canary ./runtime` from `engine/` exercise real restart/rollback journaling, two-writer concurrency, injected failures, corrupted records, source mismatch, exclusive locks, private file mode and the real Engine command/event protocol. `scripts/test_mp12_p03_canary_contract.py` adds 10 offline structural/mutation tests. It is called from the already-registered MP12 P01 source gate, avoiding changes to legacy pinned CI workflow files. The targeted CI policy independently discovers `engine/` changes and runs native Go tests.

## Qualification boundaries

This P03 source and host-primitive implementation does not mean a canary is running in the Android application. Connecting it to a trusted app host, validating actual read-only shadow outputs against legacy, stress-testing process-death handling on API36 and a physical ARM64 device, and providing release signing/rollback receipts remain separate acceptance steps. In particular, **no automatic Kotlin-to-Go cutover** or rollback of user files is performed by this overlay. PR #28 remains draft until later qualification.

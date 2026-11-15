# MP09 — Consolidated final scope and qualification boundary

Source-pinned continuation of PR #28 (Mikeyphw/xdm-xgo). Existing MP03–MP08
source, Kotlin HLS fallback, and inherited regression contracts are preserved.

## Implemented in this overlay

- Fresh, Android-broker-authorized DASH manifest graph + native representation
  binding: never translate hashed MP03 IDs by guessing.
- One single-period, unprotected, dynamic DASH MPD with **separate explicit
  video and audio**. Unsupported/multiple periods, DRM, mismatched origins,
  ambiguous representation IDs or changed selections fail closed.
- Explicit user-controlled recovery of a crashed HLS/DASH session: the
  owner reauthorizes, the source binding must match, the Android journal is
  re-read, all fragment SHA-256 proofs are reverified, and restored sequence
  high-water marks retain gap detection. No stored signed URLs/cookies or
  automatic download-complete flag.
- Dedicated session journal stores only source SHA-256 fingerprint, generation,
  protocol, start time, user limits and allowed source properties. Native DASH
  representation IDs are deliberately never stored in this descriptor.
- Partial and orphaned fragments survive startup reconciliation for review;
  a fresh start refuses unbound parts. Explicit discard is idempotent across
  crash-after-tombstone interruptions.
- Stop & Save still requires MP08 staged FFmpeg, FFprobe and byte-verified
  MediaStore publication. If post-publication cleanup fails, publication is
  not rolled back or falsified; cleanup remains a separate review item.
- Native Devtool-v2 Python ZIP launcher; original `gh pr checks --watch`
  stdout/stderr is streamed (not replaced by parsed JSON). Pin to one PR HEAD,
  clean worktree and one non-force push only.

## LIVE01–LIVE14 test coverage and gating

- LIVE01–02: DASH exact native IDs + protection, origin, period and role
  mismatches; Go unit tests.
- LIVE03–05: HLS/DASH restored high-water and gap/generation rejection;
  Go unit tests.
- LIVE06–11: long virtual lifetime, no implicit completion, audio required,
  user-initiated cancellation and source end; deterministic Go tests.
- LIVE12–14: source fingerprint privacy and drift, DASH revision boundaries;
  Go runtime tests.

These are **offline deterministic tests**, not physical 12-minute sessions.
Mandatory hosted checks after apply: XGO Targeted CI (full Go suite and
Kotlin compile) and XGO MP08B3 Real Media Acceptance on the exact PR head.

Still awaiting real-device evidence: >=12 minute HLS/DASH uninterrupted and
reconnecting runs, process force-stop/restart with newly authorized capture,
API36 emulator MediaStore/notification actions, physical ARM64 kernel/network
and fragmented media FFprobe duration/sync measurements. An Android `dataSync`
foreground service may be time-limited by the OS; interruption is always
reported as recovery-required, not successful output.

Unsupported by design: DRM bypass, guessed embedded audio, multi-period DASH
live, silent process reauthorization, unattended restart, synthetic test-only
proof as a substitute for a real Android recording.

## DASH hardening folded audit

- Preflight now reuses the **exact one** authorized root MPD response from
  `ResolveManifestGraph` for both the MP03 revision and raw DASH ID parsing.
  Another root fetch would create a time-of-check/time-of-use split.
- Recovery source identity excludes only known short-lived signing keys as
  defined by `engine/media/resource.go`; arbitrary query fields remain bound.
  An expired browser session must still be explicitly reauthorized, and all
  stored fragments must be reverified. Token-rotating CDN paths that change
  logical resource identity may still be unresumable and require review.
- Bundled Go `-race`, mock-port exact-snapshot tests, 16 Kotlin picker
  selection cases and session helper compile can now run with `--deep-self-test`.
  CI on the actual source tree and device acceptance remain separately required.

## Process-death recovery audit — folded publication fencing

- The app-private `session-v1.json` record now has an atomic `phase` of
  `recording`, `publishing`, or `published`. It contains no raw network URL,
  cookie, header, or representation ID. Only the first phase permits
  explicitly reauthorized resume; terminal/publish-pending recovery is
  inspection/cleanup-only and is never considered a second playable output.
- Before invoking MP08 finalization, Go requests an acknowledged durable
  `publishing` transition. After MP08 validates the published output, it
  requests `published` before cleanup. A missing/mismatched acknowledgment
  blocks unsafe progression; publishing-state recovery is never replayed.
- Reattaching verified fragments now ends in Go's recoverable state until a
  healthy manifest poll independently proves network recovery. The HLS/DASH
  high-water marks preserve gap detection. Offline duration alone is not
  proof that missing fragments can be recovered from a sliding window.
- Explicit UI review differentiates a recoverable stopped capture, an
  interrupted publication, already published output with pending cleanup,
  and fragments without a verified session journal. Resume buttons are absent
  in unsafe states. Corrupt receipts are preserved and failed closed.
- LIVE17/18: independent Go `-race` tests reject unexpected terminal phases,
  forged phase acknowledgments and invalid transition requests. The Kotlin
  phase helper executes 36 transition and six resume checks on the JVM.

No device-level forced process death or resumed real 12-minute recording has
been qualified here. These safety improvements and the source-level tests do
not constitute physical or API36 acceptance evidence.

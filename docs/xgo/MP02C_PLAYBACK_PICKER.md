# MP02C — Playback detection and picker fidelity

Parent: `Mikeyphw/xdm-xgo` PR #11, SHA `24e4ac3056a63b2185a7825b43e893cb1f0ba749`. New stacked draft PR (not automatically merged).

## Implemented

- MIME-authorized opaque HLS/DASH responses remain discoverable even without URL suffixes. Bounded page body parsing rejects JSON and requires actual manifest structure; forged untrusted body/MIME never upgrades a response without privileged manifest MIME.
- Explicit playback evidence for `blob:` sources is a **tentative**, frame-isolated correlation to one very recent privileged stream manifest. If zero or multiple manifests match, the observer refuses to claim the underlying source; it never sends a `blob:` URL.
- HLS variants and DASH representations stay grouped under logical manifest identity; segment observations cannot exhaust the privileged cache; aliases are bounded. Per-request evidence age cannot be refreshed by a page hint.
- 1DM+ is an external custom-scheme intent, not an encrypted-v2 channel. Refuse signed URLs and authenticated Cookie/Authorization requests rather than stripping tokens and silently breaking downloads or leaking secrets. Direct non-sensitive media can use 1DM+.
- Popup, FAB, and (most importantly) background share exactly-once protection for a candidate/target/exact-request. Reject changed tabs/candidates after asynchronous paired envelope building. Navigation and site-mode changes clear cached sends.
- `webRequest` header authority is URL+frame+tab scoped across redirected response events; a mismatch strips final sent-header authority. This does **not** claim to verify Android executor per-hop redirects (future security gate).
- Redacted UI candidate data, MP01 encrypted-v2 envelope, historical XPI provenance and original CI05 tiering are preserved. Updated active source digests in both tables; immutable historical reference unchanged.

## Evidence boundaries

`test_mp02c_playback.js`, `test_mp02c_observer.js` and `test_xgo_mp02c_source_contract.py` are executable targeted checks. They must be run on actual generated source before Devtool apply, again after local apply, and in exact-SHA hosted targeted CI before manual merge. Full Firefox UI, native APK install, physical ARM64 and licensed 1DM+ end-to-end are still **not measured**. Full recursive manifests, authorized segments and authoritative quality/audio/subtitle selection belong to MP03.

No local Gradle/.NET. CI05 heavyweight gate every five main first-parent integration commits or immediately for high-risk changes, with manual releases; no repeated full workflows per overlay. Keep Kotlin native HLS fallback until proven durable Go fragment storage (MP05).

## Continuing rule (MP03–MP12)

Always audit stale tests/contracts before editing, and update genuinely superseded expectations in the same overlay, with executable positive/negative coverage and intact XAR10/XFE01/XPI history. See `handoff/08_ADDITIONAL_RULE_STALE_TESTS.md`.

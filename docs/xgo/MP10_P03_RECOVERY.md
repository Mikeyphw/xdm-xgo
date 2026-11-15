# MP10 P03 — source-bound process-restart recovery and fault injection

## Scope

This phase **extends**, and does not replace, MP09's `resume_interrupted`
user-reviewed recovery. A restarted process is never allowed to recover from an
old cached token, skip the sealed source fingerprint, or mark a file as playable.
P01 expiry detection and P02 two-track reauthorization remain in the same
consolidated 19-path overlay.

The existing Go recovery reader first verifies the encrypted Android capture
handoff, the app-private session journal phase `recording`, the stable source
binding, and every fragment through MP05 readback. P03 adds two matching
recovery inventory fences around the actual `mp09Rehydrate` step:

1. Before rehydration, read the sealed journal again and acquire the entire
   capture-owned video/audio inventory. Require no orphan fragments, no
   cross-role duplicate IDs, strict paths owned by the capture hash, supported
   protocol, stable generation, nonempty media for both tracks, and independent
   `VerifyCommitted` evidence for every inventoried file.
2. Rehydrate the existing single Go live session; neither `DownloadReady` nor
   `Published` may be set by recovery.
3. Re-read the session journal and the full independently verified inventory.
   Require the canonical, length-framed SHA-256 inventory fingerprint to match
   the first fence exactly. On any error, return a sanitized refusal and leave
   durable fragments intact for review. No auto-cleanup or silent generation
   advancement occurs.

This is a **process-restart integrity gate**, not token rotation, a second
network downloader, cross-origin authorization, or automatic resume from a
published/partially published session.

## Offline failure-injection suite

Go `engine/runtime/mp10_recovery_p03_test.go` includes **REC01–REC12** plus
REC13–REC19, covering healthy disk readback, orphan parts, missing video,
missing audio, corrupted bytes, stale generation, duplicate fragment identity,
role confusion, timeline/byte-range/encryption identity drift, source binding mismatch,
publication-phase crash, and a journal race across recovery barriers. Additional
negatives reject symlink/path escape, truncated/oversized journal input, a
missing real readback verifier, changed byte-ranges, changed encryption identity,
and canonical full-identity fingerprint changes. Real temporary files and SHA-256 reads are used.

Python `scripts/test_xgo_mp10_p03_contract.py` checks that both pre- and
post-fences exist in the real resume handler, and uses targeted negative source
mutations to reject missing security conditions.

## Gates deliberately deferred

- Termux `go test ./media ./runtime` and inherited Python contracts must pass
  on a temporary exact-source worktree before applying this overlay.
- GitHub exact-HEAD Android Kotlin compilation and source CI must pass once
  pushed. Do **not** run Gradle locally in Termux.
- API36 foreground/instrumentation, real 12-minute HLS/DASH, physical ARM64,
  network expiry and publication equivalence tests remain **not qualified**.
- PR #28 remains open, draft and unmerged. No signed release or auto-merge.

The recovery fence cannot and does not authenticate a compromised app process;
Android's app-private checksum is not a MAC. It protects against ordinary
stale/partial/corrupt disk state and races within the documented model.

## Audit HF01 — strict identity and transport cooldown

The recovery inventory now compares the *complete known fragment identity*,
including optional byte range and encryption identifier, across both fences.
A valid range is included in the canonical digest; changing, adding or deleting
it refuses recovery, as does changing an encryption key/IV identity. REC17–REC19
cover these mutations on top of the real-file readback tests.

For P01, once a fragment fetch yields expired authorization or bounded
`Retry-After`, its tracker makes no further transport calls in the current
poll. This prevents unnecessary repeated requests to an already-expired token.
The status remains recoverable, never DownloadReady/Published. Real app-level
refresh and physical recovery qualification are still deferred.

## Audit HF02 — P02 session-wide durability proof

Before any reauthorization preview, P02 compares every previously observed
LiveSession media fragment against the independently readback-verified store
inventory for each track. FileFragmentStore.CommittedRecords() filters corrupt
items, so accepting only a valid overlap was unsafe: a corrupt committed item
could silently vanish. HF02 requires complete session inventory coverage,
strict role/generation/hash/artifact identity, no duplicates across tracks,
and exact total bytes before attempting a URL rebind. The original corrupt
readback regression remains unchanged; an additional negative poisons a
non-overlapping, same-length audio fragment. Any failure preserves all stored
files and refuses the entire reauthorization. No Android/physical qualification
is implied by this fix.

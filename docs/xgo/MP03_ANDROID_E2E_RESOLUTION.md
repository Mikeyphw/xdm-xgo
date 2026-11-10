# MP03 — Android end-to-end authorized manifest inspection

Parent is PR #14 `8471707c742ef991747ece24b7e03f9c8ccd921d`.
MP03 extends the Go ManifestGraphV1 resolver with an actual Android read-only
fetch port and app review UI. No download is launched by manifest inspection.

## Transport path

1. **User** taps *Inspect Go manifest* on a captured HLS/DASH item in MediaInbox.
2. AndroidMediaUiClient issues `android.media.resolve_manifest` via the existing
   single AndroidEngineService, not a second Go engine.
3. The Go handler resolves the capture's exact URL from the current authoritative
   capture/envelope state and invokes `ResolveManifestGraph` using `ManifestFetch`.
4. For each requested root/child playlist, the correlated platform request reaches
   the existing Kotlin frame pump, which schedules network IO off-pump.
5. `AndroidAuthorizedManifestFetcher` checks `MediaRequestHandoffStore.forCapture`,
   exact root, fresh expiry, bounded depth/bytes (in Go), same-origin children and
   redirects, Android cleartext/private-network policy, and scoped header allowlist.
6. The bounded response returns as base64 in the correlated platform reply.
7. Go parses actual complete HLS/DASH manifest bodies and returns a **volatile**
   `ManifestGraphV1` frame. Android rejects mismatched graph schemas and displays
   qualities, languages, periods, protection status; never raw signed URLs.

This path is read-only. The existing Kotlin HLS download fallback remains active.
The MP04/MP05 track-output and durable-fragment gates are not bypassed.

## Security policy / known intentional restrictions

* Only existing, non-expired encrypted capture handoffs authorize network reads;
  Go-supplied URLs and booleans are never sufficient authorization.
* Cross-origin manifests and cross-origin redirects are denied by default; a
  separate future consent/session-scoped approval would be needed for such CDN
  graphs, with **no** implicit credential replay.
* Only same-origin approved request headers are replayed; no page-supplied
  headers, token diagnostics, browser navigation URLs or persistent graph storage.
* Private destination networks and cleartext credentials require the existing
  Android handoff approvals and Android network-security-config rules.
* HTTPS hostname verification is delegated to Android's platform TLS; DNS
  rebinding requires additional pinned-connection verification before enabling
  privileged private-network source traversal in production.
* Network requests have explicit timeouts, redirect limits, body limits and
  matched JNI request IDs. Go commands time out; a canceled UI never creates a
  download or durable artifact.
* DRM remains diagnostic-only; `download_ready=false` is an invariant.

## Acceptance boundaries

Staged Python stale/security contracts run before Devtool. Hosted targeted CI
must exercise `go test ./...` and Android Kotlin compilation at exact PR head.
Neither hosted emulators nor unit tests alone qualify real ARM64 browser sessions,
licensed 1DM+ comparisons, or production Go durable fragment storage.

MP04–MP12 roadmap is preserved separately and unchanged.

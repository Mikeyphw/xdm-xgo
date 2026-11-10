# MP03 — Authoritative manifest graph (Go + Kotlin schema v1)

**Parent:** PR #14 (MP02C), `8471707c742ef991747ece24b7e03f9c8ccd921d`. **Stack:** PR #10 -> PR #11 -> PR #14 -> this new draft PR. No automatic merges.

## Implemented in this overlay

* `engine/media/manifest_resolver.go` is a bounded recursive HLS resolver and DASH graph adapter over the existing production Go parsers (`ParseHLSPlaylist`, `ParseDASHManifest`). The transport is injected as `ManifestFetcher`; the resolver neither creates an HTTP client nor silently carries browser credentials to another origin.
* A versioned `ManifestGraphV1` reports exact observed HLS variant/rendition groups, DASH adaptation periods and representations, codecs, bandwidth, resolution, language and manifest protection hints. `DownloadReady=false` at this stage.
* Opaque/extensionless manifests are accepted only after a valid manifest-body signature, bounded full-body fetch, and allowed response MIME. Unrelated API JSON is rejected, as are oversized manifests, cycles, unmatched redirect hops, non-allowlisted origins, expired signed responses, XML entities and unsupported content kinds.
* `ManifestGraphV1Contract.kt` is a strict Android DTO decoder for ephemeral Go-owned graph frames. It does not persist or log signed transport URLs.
* 23 deterministic Go assertions grouped as HLS01–HLS07, DASH01–DASH06 and RES01–RES10; Python source/privacy/stale-contract tests; targeted CI policy route requiring these and `go test ./...`. Kotlin application changes cause targeted Android compile in Actions; no Gradle/.NET/Go locally in Termux.

## Important runtime boundary

The resolver is a **read-only Go API** and the Kotlin decoder is a **schema contract**, not an already-wired JNI request flow. A separate integration must connect Android's *approved* browser capture broker to the `ManifestFetcher` port and deliver the result over the Go platform channel before any UI may claim authoritative, fully resolved choices. This change therefore cannot qualify the final MP03 Android end-to-end exit criterion or the MP04 required-output plan by itself. Do not replace the currently working Kotlin HLS downloader. Do not infer durable fragment storage, decryption support, a muxed output or real licensed 1DM+ results from these tests.

## Risk, review and follow-on

* Security/privacy: no raw manifest, signed URL or Cookie/Authorization values in diagnostics or logs. Input graph exists only in the trusted engine-to-app transport and must not be passed via plaintext deep links.
* Future MP03 runtime integration: implement a bounded Android-authorized fetch adapter with root capture ownership, per-hop redirect validation, exact request evidence and token-refresh broker; bridge the result to the Kotlin `ManifestGraphV1Contract` and media UI, then collect device evidence.
* MP04: track selection and required audio/subtitle output validation.
* MP05: durable fragment storage and crash recovery; retain native Kotlin HLS fallback until physical parity is proven.
* MP06–MP12 remain specified in the unchanged canonical roadmap bundled in the launchable ZIP.

## Evidence boundaries

Source and synthetic Go fixture tests are not device/release qualification. Staging Python tests run before application. GitHub targeted Go and Android compilation must succeed at the exact new PR head. CI05 full gate triggers upon qualifying main integration and any high-risk path; its five-first-parent cadence is unmodified. Physical ARM64 and licensed 1DM+ remain `not_run` until measured.

# MP01 HF02 — secure CI contract closure and ARM64 downloader resilience

Source: `Mikeyphw/xdm-xgo`, PR #10, commit `7112f8c6f13f05de82ce7f4f625de027385ccf16`.

## Closed by this patch

1. `validate-1dm-media-locator-xpi-v3.py`: migrate **obsolete** assertions that required plaintext media metadata, raw headers and crypto absence in browser navigation. Require app-paired encrypted-v2 RSA-OAEP/AES-GCM with ciphertext-only deep links, preserve size/duration/poster and authenticated request evidence *inside* the encrypted payload, enforce v3 capture rejection, and link actual WebCrypto round-trip tests.
2. `BugHuntPhase5BrowserExtensionContractTest.kt`: keep the underlying webRequest proposed/final header evidence checks; reject serialization of replay headers and candidate JSON into URL query parameters. Demand encryption and app pairing.
3. `rem18-release-matrix-audit.py`: replace an obsolete required C# `capture v3` acceptance marker with explicit checks that desktop rejects browser captures and explains Android-only pairing. Keep existing release/platform/signing checks.
4. `setup-windows-arm64-cgo.ps1`: retry transient GitHub 504 download failures using both the canonical release-asset URL and the official GitHub Release API asset **551256614**; verify the same declared byte size **185605459** and unchanged SHA-256 **7fe35f60407473c420ac72b25137f54385b0affd2c42efd507c0062fc626ab56** on every attempt before extraction/execution. Stop if all six attempts fail.

## Explicitly preserved

- MP01 Android Keystore private-key ownership, RSA-OAEP/AES-GCM encryption, IV uniqueness and ciphertext-only import journaling.
- No raw Cookie/Authorization, request headers, signed media URLs or candidate batch in URI query parameters.
- Unpaired Firefox releases may only use public Add v1. Plaintext capture v3 remains rejected by Android and Desktop.
- MP00 media fixtures, 1DM oracle and Go/Node/Android regression suites.
- Native ARM64 release-toolchain version, SHA-256 pin, compiler-target validation and Windows runtime tests.

## Qualification limits

This delivery builds a source-pinned Devtool overlay on the user's clean Termux checkout. Local offline transformation, source-pin and package tests are separate from repository-hosted Android and Modern CI. A temporary outage across both GitHub download URLs can still block Windows ARM64; there is **no** checksum bypass or unpinned mirror. Do not merge PR #10 until all required checks pass, and qualify the app-paired XPI on an actual Android device before claiming full production media parity.

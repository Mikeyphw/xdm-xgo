# MP12 P05 — Firefox native messaging → Go desktop protocol parity (shadow only)

This phase adds a deliberately **read-only** boundary between the existing .NET Native Messaging v2 capture parser and the Go v1 desktop runtime. Both protocols have real, distinct versions: Firefox/Native Messaging `2.0` uses a four-byte little-endian message length; Go command envelopes use `protocol.major=1` and typed `cmd_`/`op_` identities. No application-specific capture command is silently translated into a Go download.

## What is actually verified

* The five canonical, recorded .NET browser test fixtures are copied **byte-for-byte** to `engine/runtime/desktopparity/testdata`. A source-only auditor compares them to the originals and enforces immutable Git blobs for .NET parsing/framing/native-host code and Go wire/desktop projection code.
* `engine/runtime/desktopparity/parity.go` strictly checks framed lengths, nested duplicate JSON keys, source/host session equality, native protocol version, capture/batch cardinality, HTTP(S) URL shape and disallowed incognito. Its bounded evidence contains only a request correlation ID, item count and a SHA-256 fingerprint; no cookies, URLs, headers, POST body, destination or credentials.
* `SnapshotCommand` is only callable with explicit trusted-host opt-in and a session-authenticated in-memory inspection receipt. It emits **only** `desktop.ui.snapshot` in Go wire v1. Production cutover and command execution remain false.
* The integration test invokes the real Go v1 `DecodeCommand`, the actual Go `runtime.Engine` in desktop mode, and checks the desktop UI projection and completion events. Synthetic source tests never claim to have exercised Firefox or a .NET host process.

## Execute after application

```sh
python3 -B scripts/test_mp12_p05_desktop_parity.py
python3 -B scripts/mp12_p05_desktop_parity.py source-only --repo .
(cd engine && go test -count=1 ./runtime/desktopparity ./runtime)
# On supported Linux/amd64 with CGO (also mandatory in hosted XGO Targeted CI):
(cd engine && go test -race -count=1 ./runtime/desktopparity)
# On Android/arm64 Termux, run only the normal tests/vet locally;
# the ZIP explicitly defers the race gate to Linux hosted CI.
```

All checks run offline. The Python audit is part of the already-registered P01 targeted CI entry point; Go's existing classified targeted source job executes engine Go tests because the overlay adds files under `engine/`. No local Gradle, Android installation, release signing or native-host replacement is required.

## What this does **not** prove

This does **not** run the actual .NET/XDM native host, deliver a real Firefox extension event, execute HTTP downloads, preserve POST/cookie authority, verify desktop native binaries, exercise Windows/macOS/Linux graphical UI, or authorize a Go production desktop cutover. The independent desktop host implementation and real OS-browser acceptance remain P05 follow-ups. P06 physical ARM64, signed-release proof, licensed differential, x86 runtime and chaos/performance gates remain distinct.

### HF02: gofmt-compatible real-runtime source proof

P05's source-only audit no longer treats harmless space differences in Go calls as a changed contract. It requires concrete decoder, submission, read-only kind, projection and completion guards and no-execution/no-cutover checks, with independent positive and adversarial tests against the actual bundled integration source. This is not proof of .NET host or production browser acceptance; Go integration tests remain mandatory in the staged repo and hosted CI.

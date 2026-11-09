# MP00 — XDM media parity baseline (fixtures + reference oracle)

**Baseline:** `Mikeyphw/xdm-xgo` at `de52f1eec4f0e3652c646310fba66e5ad627dbbf`.
This stage adds **test-only infrastructure**; it does **not** modify production
capture/deep-link, Go fragment durability, native HLS, or FFmpeg live behavior.
The 140-case matrix is an acceptance target, not a claim of 140 passing tests.

## Local qualification (Linux, with Python 3.10+, libx264-capable FFmpeg and FFprobe)

```sh
bash tests/media-parity/ci.sh
python3 tests/media-parity/generate_fixtures.py --out /tmp/xdm-mp00-fixtures
python3 tests/media-parity/fixture_server.py --fixtures /tmp/xdm-mp00-fixtures --port 8765
```

Open `http://127.0.0.1:8765/vod/hls/master.m3u8`,
`/vod/dash/static.mpd` or `/vod/progressive.mp4`.
Other paths include `/live/hls/playlist.m3u8?tick=4`,
`/live/dash/stream.mpd?tick=4`, `/auth/refresh`,
`/auth/segment.ts?token=mp00-token-v2`, `/range/progressive.mp4`,
`/status/404once`, `/status/429once`, `/redirect/cross-origin`,
`/stall`, `/abort` and `/metrics`. The HLS/DASH streams are generated
with real decodable audio/video bytes and include separate English/Spanish
HLS audio, TS and fMP4, subtitles and DASH multi-adaptation segments.

The generator verifies FFmpeg by a caller-provided exact version-prefix pin
(`MP00_FFMPEG_VERSION` / `--expected-version`) and optionally an **exact binary
SHA-256** (`MP00_FFMPEG_SHA256` / `--expected-binary-sha256`). A generated
`fixture_manifest.json` records the binary SHA, tool versions and SHA-256 for
each output. CI pins runner series and FFmpeg version family `6.1.1`; the
actual executable hash is captured as provenance, not claimed portable
across operating systems. A future release gate must supply an exact trusted
binary hash when the distribution path is fixed.

For manually verifying a final XDM output:

```sh
python3 tests/media-parity/verify_output.py /path/to/output.mp4 --min-duration 5 --output /tmp/output-receipt.json
```

The verifier checks demanded audio and video streams, duration/skew, entire
decode, output SHA-256, and decoded frame fingerprints. A successful HLS/DASH
fixture remux in this suite is **FFmpeg + server validation**, not a claim
that the XDM app itself downloaded, recovered or merged these streams.

## Licensed 1DM reference — strict black-box, ARM64 only

The supplied `1DM+_18.2.apk` was used for a **prior static audit**. It is **not
in this repository or overlay** and must never be checked into public CI.
The reference signer was **not** validated; this project must not install or
replace an existing 1DM app automatically. Use only the legitimate installed
app on an owner-controlled licensed ARM64 device. Verify installed package
signing and version through Android Package Manager / `apksigner`, including
comparison to a known trusted vendor certificate; a parseable signature alone
is insufficient. Do not access private app data, intercept protected TLS,
circumvent DRM/licensing or automate without the device owner's approval.

From the host (after the fixture server is running and the user consents):

```sh
adb -s <approved-arm64-device> reverse tcp:8765 tcp:8765
adb -s <approved-arm64-device> shell getprop ro.product.cpu.abi
# Open http://127.0.0.1:8765/vod/hls/master.m3u8 via a browser and use
# 1DM's supported public UI/chooser. No private app storage is read.
```

Record observable REF01–REF10 outcomes in `reference_1dm.json`: statuses
`measured`, `failed`, `unsupported`, `not_run`; `measured`/`failed` require
an observed timestamp and non-secret evidence (quality labels, offered
tracks, UI screenshots scrubbed of tokens, public exported output probe,
request **metadata**). Run `reference_oracle.py` to reject inferred passes or
unintended secret fields. Do not write URLs, cookie/token values, header
contents, private paths or the APK itself into receipts or CI artifacts.
All REF cases intentionally remain `not_run` in this stage.

## Test coverage / CI truthfulness

- `media-server-integration`: runs generated MP4/HLS/DASH and HTTP behavior tests.
- `media-static-and-unit`: runs existing Go `engine/media` and the seven
  `browser-extension/tests/test_*.js` files; **old tests still expect the
  unsafe v3 URI and do not certify SEC01**. MP01 will fix that behavior.
- `media-kotlin-unit`: runs existing Android JVM `:media:test` and
  `:transfer-native:testDebugUnitTest` on hosted Gradle.
- Physical ARM64 and licensed 1DM comparisons: **not_run**, never silently
  replaced by x86 emulator or JS/JVM success.
- Hosted x86_64: XP03B provides an opt-in native/UI smoke lane, but MP00
  does not claim it is a complete media-download integration lane.

`acceptance.py` reports **140 `not_run` cases by default**, even when the MP00
harness itself passes. Only add explicit per-case receipts after the
corresponding scenario runs. `suite_inventory.json` documents which older
suites run and what they *do not* prove. No 1DM APK, unredacted request,
source URL with tokens, media credentials, or private cookies are uploaded.

## Security and isolation

The fixture server binds only loopback; use `adb reverse` for Android.
Request logs record normalized route paths, header names excluding sensitive
ones, query **key names**, and whether auth/cookie existed, never values or
raw targets. `/metrics` is test-only and may still reveal request behavior;
never expose the server externally. `scoped_http.py` is a **fixture-client
reference**, not a patch to XDM network code. The existing production
cross-origin credential leak risk A01/A10 is still open pending MP01/MP10.

## Next implementation gate

MP01: replace sensitive `xdmdownload://capture?v=3` payloads with a paired
short-lived encrypted/app-owned token flow and negative browser/Android tests,
without regressing current capture discovery. Keep the existing Kotlin HLS
executor enabled until a genuinely durable Go/Android store passes MP05.

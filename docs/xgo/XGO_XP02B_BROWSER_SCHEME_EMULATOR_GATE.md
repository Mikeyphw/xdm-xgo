# XP02B — Real API36 browser-scheme intake instrumentation (native-free)

## Scope

XP02 qualified 35 real Room persistence tests in 7 classes on an API36 x86_64
emulator. XP02B adds a **second, independent** instrumented lane for the
**production** `XdmBrowserDeepLinkParser` in `:browser-integration`.

This is not a cloned parser or a synthetic demonstration handler: test methods
call the same library parser compiled into XDM Android. Android `Intent` and
`Uri` transport is exercised on the emulator before parser admission. The
library has no native ARM64 engine, FFmpeg, aria2, app startup, network
operations or packaged release dependency.

## Coverage

Ten AndroidJUnit4 tests require release/debug variant separation, real VIEW
intent URI round trips, v2 encrypted capture without plaintext media URLs,
v3 sender-bound candidate sessions, and rejection of duplicate parameters,
unsafe nested URLs, unsupported hosts, oversized links, authority credentials,
ports and fragments.

`:persistence:connectedDebugAndroidTest` still runs first and retains its
unchanged seven-class XML receipt; the emulator then executes
`:browser-integration:connectedDebugAndroidTest`. Both must pass. The XP02B
verifier requires exactly ten named methods, no unexpected classes or methods,
no errors, failures or skips, consistent JUnit suite counts and XML digests.
It writes `EMULATOR_X86_64_BROWSER_INTAKE_PASS` with explicit
`native_arm64_executed=false` and `app_composition_executed=false`.

The new artifact is `xdm-emulator-browser-intake-test-results`. The previous
`xdm-emulator-persistence-test-results` is retained intact. The existing
physical ARM64 test, manual translation diagnostic and signed-release gates
remain unmodified. No local Gradle is required: compilation and instrumentation
run solely on GitHub Actions.

## Next boundary

Full Compose UI journeys, exported *production app* intent routing, secure
storage and direct-v3 dispatch still require an explicitly isolated native-free
app variant and are **not** proven by this library gate. XP02B is the first
incremental extension, not an app-level release/physical ARM64 acceptance claim.

## Acceptance

Merge only after the hosted Android `validate` source regressions pass, the
API36 emulator reports `XGO_XP02_JUNIT_PASS` and `XGO_XP02B_JUNIT_PASS` with
all ten XP02B methods, and both uploaded receipts are present.

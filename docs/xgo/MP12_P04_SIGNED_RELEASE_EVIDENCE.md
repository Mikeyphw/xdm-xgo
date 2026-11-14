# MP12 P04 — Independent signing and release provenance

P04 adds a **read-only, fail-closed post-build audit**, with a six-file source
contract for the historical XAR16 publishing/signing flow. It does **not**
perform signing, request a release, grant secrets, tag, merge, install on a
physical device, or authorize a Go production canary.

## Previously undiscovered XAR16 publication checksum defect

The former `generate-xar16-publication-bundle.sh` used `find "$OUT_DIR"`
while redirecting the checksum into that same directory. POSIX shell creates
`SHA256SUMS` or `SHA512SUMS` *before* launching `find`; therefore those output
files could appear in their own inventories. MP12 P04 changes only the release
publication **generator**, not `.github/workflows/android.yml` or the sealed
`signed-release:` job. A deterministic `checksum-write` mode requires exactly
six known evidence inputs and creates only SHA256SUMS and SHA512SUMS, excluding
self-hashes. Existing output, symlinks and unexpected inventory are refused;
partial outputs after power loss are not silently overwritten.

## Three independent evidence boundaries

1. `source-only` checks six immutable source pins, the tag-only signed release
   job and fixed publication generator. Runs automatically in the existing
   MP12 P01 targeted-CI Python suite. This is **not signing**.
2. `verify` requires an XAR16 publication **directory**, the exact Git checkout
   HEAD, same-run evidence, checksum inventory (both SHA-256/SHA-512), and the
   actual APK, AAB and APKS bytes. The source-built ARM64 ELF libraries must
   have 16 KiB PT_LOAD alignment; foreign ABIs, stale/forged run IDs, missing
   evidence, and changed bytes cause refusal.
3. Independent Android SDK `apksigner` verifies APK and **every** APKSet split
   against an externally supplied SHA-256 signer-certificate pin. Java
   `jarsigner -verify -strict` and `keytool -printcert -jarfile` verify the AAB
   separately. No secret/keystore is passed to this script. `apksigner`,
   `jarsigner` and `keytool` must exist when real release evidence is checked.

Example, **only when a genuine signed XAR16 build and its inputs exist**:

```sh
python3 -B scripts/mp12_p04_signed_release.py verify \
  --repo . --expected-head "$(git rev-parse HEAD)" \
  --run-id 'XAR16_RUN_ID' \
  --publication-dir 'app/XDM.Android/build/release/publication/xar16-XAR16_RUN_ID' \
  --apk /actual/source-built/app-release.apk \
  --aab /actual/source-built/app-release.aab \
  --apks /actual/source-built/app-release.apks \
  --signer-sha256 '<trusted release certificate SHA-256>'
```

The fixture suite runs offline with *mocked* signing tools; it never passes off
synthetic signatures as a real signed release. The independent auditor reports
`release_qualified: false` and `physical_arm64_qualified: false` even after
actual signed-artifact verification, because Go cutover, physical device and
store publication qualifications are distinct. XGO MP12 P01's 11 release
readiness gates are unchanged. The historical signed-release workflow is not
triggered by this overlay; an `android-v*` tag is required by design.

## Commands

```sh
python3 -B scripts/test_mp12_p04_signed_release.py
python3 -B scripts/mp12_p04_signed_release.py source-only --repo .
python3 -B scripts/test_mp12_qualification.py
```

The new tests exercise genuine ZIP bytes and mutation refusals, plus exclusive
checksum creation, restart-safe refusal on partial receipts, signed APK/AAB
certificates and APKSet set-level checks. No Gradle builds run in Termux.

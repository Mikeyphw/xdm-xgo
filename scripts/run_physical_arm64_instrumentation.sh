#!/usr/bin/env bash
# Physical-device-only Android/ARM64 instrumentation gate for a user-owned device.
# Pass a single ADB serial, the debug APK, and the matching instrumentation APK.
# Does not root, wipe, or change any device security settings.
set -euo pipefail
if (( $# != 3 )); then
  printf 'Usage: bash %s <ADB_SERIAL> <app-debug.apk> <app-debug-androidTest.apk>\n' "$0" >&2
  exit 2
fi
serial=$1
app=$2
testapk=$3
for tool in adb unzip grep awk mktemp sha256sum tee tr; do
  command -v "$tool" >/dev/null || { echo "XGO_ADB_TOOL_MISSING:$tool" >&2; exit 2; }
done
[[ -f "$app" && -s "$app" && -f "$testapk" && -s "$testapk" ]] || { echo 'XGO_ADB_APKS_MISSING' >&2; exit 2; }
unzip -Z1 "$app" | grep -Fx 'lib/arm64-v8a/libxdmcore.so' >/dev/null || { echo 'XGO_ADB_ARM64_JNI_MISSING' >&2; exit 2; }
# When using the published paired artifact, refuse modified or mismatched APKs.
if [[ -f "$(dirname "$app")/SHA256SUMS" ]]; then
  [[ "$(dirname "$app")" == "$(dirname "$testapk")" ]] || { echo 'XGO_ADB_PAIR_DIRECTORY_MISMATCH' >&2; exit 2; }
  (cd "$(dirname "$app")" && sha256sum -c SHA256SUMS) || { echo 'XGO_ADB_APK_PAIR_SHA256_MISMATCH' >&2; exit 2; }
fi
[[ "$(adb -s "$serial" get-state)" == device ]] || { echo 'XGO_ADB_NOT_ONLINE' >&2; exit 2; }
prop() { adb -s "$serial" shell getprop "$1" | tr -d '\r'; }
abi=$(prop ro.product.cpu.abilist)
qemu=$(prop ro.kernel.qemu)
primary=$(prop ro.product.cpu.abi)
sdk=$(prop ro.build.version.sdk)
[[ ",$abi," == *,arm64-v8a,* && "$primary" == arm64-v8a ]] || { echo "XGO_ADB_NATIVE_ARM64_REQUIRED: $abi" >&2; exit 2; }
[[ "$qemu" != 1 ]] || { echo 'XGO_ADB_EMULATOR_REFUSED' >&2; exit 2; }
[[ "$sdk" =~ ^[0-9]+$ ]] || { echo "XGO_ADB_SDK_INVALID:$sdk" >&2; exit 2; }
[[ "$sdk" -ge 26 ]] || { echo "XGO_ADB_SDK_UNSUPPORTED:$sdk" >&2; exit 2; }
page_size=$(adb -s "$serial" shell getconf PAGESIZE | tr -d '\r' || true)
printf 'XGO_ADB_DEVICE_PREFLIGHT_PASS: primary=%s sdk=%s page_size=%s\n' "$primary" "$sdk" "${page_size:-unknown}"
# Installing only the two user-supplied APKs; no data reset or uninstall.
adb -s "$serial" install -r -t "$app"
adb -s "$serial" install -r -t "$testapk"
runner='com.mikeyphw.xdm.android.debug.test/androidx.test.runner.AndroidJUnitRunner'
adb -s "$serial" shell pm list instrumentation | grep -Fq "$runner" || { echo "XGO_ADB_RUNNER_NOT_FOUND:$runner" >&2; exit 2; }
outdir="${XGO_ADB_EVIDENCE_DIR:-$PWD/xdm-arm64-device-evidence}"
mkdir -p "$outdir"
result="$outdir/instrumentation.txt"
set +e
adb -s "$serial" shell am instrument -w -r "$runner" 2>&1 | tee "$result"
status=${PIPESTATUS[0]}
set -e
if (( status != 0 )); then
  echo "XGO_ADB_INSTRUMENTATION_ADB_FAILED:exit=$status" >&2
  exit "$status"
fi
if grep -Eqi '(FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed|Error in |shortMsg=)' "$result"; then
  echo 'XGO_ADB_INSTRUMENTATION_FAILED' >&2
  exit 1
fi
if ! grep -Eq 'INSTRUMENTATION_CODE: -1' "$result"; then
  echo 'XGO_ADB_INSTRUMENTATION_RESULT_MISSING' >&2
  exit 1
fi
if ! grep -Eq 'OK \([1-9][0-9]* tests?\)' "$result"; then
  echo 'XGO_ADB_POSITIVE_TEST_COUNT_MISSING' >&2
  exit 1
fi
{
  printf 'status=REAL_ARM64_DEVICE_INSTRUMENTATION_PASS\n'
  printf 'abi=%s\nsdk=%s\npage_size=%s\n' "$abi" "$sdk" "${page_size:-unknown}"
  printf 'adb_serial=%s\n' "$serial"
  sha256sum "$app" "$testapk"
} > "$outdir/receipt.txt"
echo "XGO_REAL_ARM64_DEVICE_INSTRUMENTATION_PASS: $outdir"

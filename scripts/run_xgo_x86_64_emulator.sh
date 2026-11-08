#!/usr/bin/env bash
# x86_64 APK runtime acceptance: builds Android/amd64 Go JNI and executes it on API36.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_OS:-}" == Linux && "${XGO_X86_TEST_EXPLICIT_OPT_IN:-}" == yes ]] || { echo XGO_X86_HOST_REFUSED >&2; exit 2; }
[[ "$(uname -m)" == x86_64 ]] || { echo XGO_X86_CI_HOST_ARCH_REFUSED >&2; exit 2; }
[[ "$(git -C "$root" rev-parse HEAD)" == "${GITHUB_SHA:?}" ]] || { echo XGO_X86_HEAD_REFUSED >&2; exit 2; }
serial=emulator-5554
[[ "$(adb -s "$serial" get-state)" == device ]] || { echo XGO_X86_EMULATOR_OFFLINE >&2; exit 2; }
prop() { adb -s "$serial" shell getprop "$1" | tr -d '\r'; }
[[ "$(prop ro.kernel.qemu)" == 1 && "$(prop ro.product.cpu.abi)" == x86_64 && "$(prop ro.build.version.sdk)" == 36 ]] || { echo XGO_X86_WRONG_EMULATOR >&2; exit 2; }
[[ -r /dev/kvm && -w /dev/kvm ]] || { echo XGO_X86_KVM_REFUSED >&2; exit 2; }
cd "$root/app/XDM.Android"
gradle --no-daemon --console=plain -Dorg.gradle.parallel=false :app:assembleDebug :app:assembleDebugAndroidTest
apk=app/build/outputs/apk/debug/app-debug.apk
testapk=app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
[[ -s "$apk" && -s "$testapk" ]] || { echo XGO_X86_APK_OUTPUT_MISSING >&2; exit 2; }
receipt="${RUNNER_TEMP:?}/xdm-x86_64-apk/receipt.json"
python3 -B "$root/scripts/verify_xgo_x86_apk.py" --apk "$apk" --core app/src/main/jniLibs/x86_64/libxdmcore.so --receipt "$receipt"
adb -s "$serial" install -r "$apk"
adb -s "$serial" install -r "$testapk"
# A real UI process launch (native runtime may be initialized lazily).
adb -s "$serial" shell am start -W -n com.mikeyphw.xdm.android.debug/com.mikeyphw.xdm.android.MainActivity
sleep 5
pid="$(adb -s "$serial" shell pidof com.mikeyphw.xdm.android.debug | tr -d '\r' || true)"
[[ -n "$pid" ]] || { adb -s "$serial" logcat -d -t 300 '*:E' >&2; echo XGO_X86_APP_START_FAILED >&2; exit 2; }
# Invoke a genuine JNI entry point; loading an APK alone is insufficient.
set +e
output="$(adb -s "$serial" shell am instrument -w -r -e class com.mikeyphw.xdm.android.XgoX86JniSmokeTest com.mikeyphw.xdm.android.debug.test/androidx.test.runner.AndroidJUnitRunner 2>&1)"
status=$?
set -e
printf '%s\n' "$output"
if (( status != 0 )) || ! grep -Eq 'OK \(1 test\)' <<<"$output"; then
  adb -s "$serial" logcat -d -t 250 '*:E' >&2 || true
  echo XGO_X86_JNI_INSTRUMENTATION_FAILED >&2; exit 2
fi
python3 -B - "$receipt" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);d=json.loads(p.read_text())
d.update(status='EMULATOR_X86_64_APP_JNI_PASS',jni_instrumentation_tests=1,app_process_launched=True,
         optional_arm64_only_media_backends_qualified=False)
p.write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
PY
mkdir -p "${RUNNER_TEMP:?}/xdm-x86_64-apk"
cp "$apk" "${RUNNER_TEMP:?}/xdm-x86_64-apk/xdm-android-x86_64-debug.apk"
printenv GITHUB_SHA >/dev/null
printf 'XGO_X86_EMULATOR_APP_JNI_PASS: genuine x86_64 APK installed, launched and JNI called\n'

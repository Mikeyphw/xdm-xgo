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
evidence_dir="${RUNNER_TEMP:?}/xdm-x86_64-apk"
mkdir -p "$evidence_dir"
printf '%s\n' "$output" > "$evidence_dir/jni-instrumentation.txt"
if (( status != 0 )) || ! grep -Eq 'OK \(1 test\)' <<<"$output"; then
  adb -s "$serial" logcat -d -t 250 '*:E' >&2 || true
  echo XGO_X86_JNI_INSTRUMENTATION_FAILED >&2; exit 2
fi
# XP03B: launch real Compose UI and exported review routing tests in the manual-only x86 lane.
run_ui_suite() {
  local label="$1" selector="$2" transcript rc
  set +e
  transcript="$(adb -s "$serial" shell am instrument -w -r -e class "$selector"     com.mikeyphw.xdm.android.debug.test/androidx.test.runner.AndroidJUnitRunner 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "$transcript" | tee "$evidence_dir/${label}-instrumentation.txt"
  if (( rc != 0 )); then
    adb -s "$serial" logcat -d -t 250 '*:E' >&2 || true
    echo "XGO_XP03B_${label}_COMMAND_FAILED" >&2
    exit 2
  fi
}
run_ui_suite compose 'com.mikeyphw.xdm.android.AppSmokeTest'
run_ui_suite routing 'com.mikeyphw.xdm.android.ExternalControlSecurityInstrumentedTest#exportedAutomationResolvesOnlyToReviewGate'
python3 -B "$root/scripts/verify_xgo_x86_ui_runs.py"   --jni "$evidence_dir/jni-instrumentation.txt"   --compose "$evidence_dir/compose-instrumentation.txt"   --routing "$evidence_dir/routing-instrumentation.txt"   --receipt "$receipt"
mkdir -p "${RUNNER_TEMP:?}/xdm-x86_64-apk"
cp "$apk" "${RUNNER_TEMP:?}/xdm-x86_64-apk/xdm-android-x86_64-debug.apk"
printenv GITHUB_SHA >/dev/null
printf 'XGO_XP03B_EMULATOR_JNI_AND_UI_PASS: 1 JNI, 4 Compose, 1 exported-route tests passed\n'

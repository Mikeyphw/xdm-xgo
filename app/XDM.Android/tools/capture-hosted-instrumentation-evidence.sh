#!/usr/bin/env bash
# HF13: hosted-only, bounded instrumentation crash evidence; NEVER turns failure into success.
set -euo pipefail
mode="${1:?missing mode}"
status="${2:?missing child exit code}"
serial="${3:?missing emulator serial}"
case "$mode" in (--device|--signed-release) ;; (*) echo XDM_HF13_MODE_REFUSED >&2; exit 2;; esac
[[ "$status" =~ ^[0-9]+$ ]] || { echo XDM_HF13_EXIT_CODE_REFUSED >&2; exit 2; }
[[ "$status" -le 255 ]] || { echo XDM_HF13_EXIT_CODE_REFUSED >&2; exit 2; }
[[ "${GITHUB_ACTIONS:-}" == true && "${RUNNER_OS:-}" == Linux && -n "${RUNNER_TEMP:-}" ]] || { echo XDM_HF13_HOST_ONLY >&2; exit 2; }
[[ "$serial" == emulator-5554 ]] || { echo XDM_HF13_SERIAL_REFUSED >&2; exit 2; }
[[ "$(uname -m)" == x86_64 ]] || { echo XDM_HF13_ARCH_REFUSED >&2; exit 2; }
dir="$RUNNER_TEMP/xdm-instrumentation-evidence"
mkdir -p "$dir"
chmod 0700 "$dir"
# Redact secrets even when an unexpected AndroidRuntime message includes an URL.
redact() {
  python3 -c '
import re,sys
s=sys.stdin.read()
s=re.sub(r"(?i)((?:authorization\s*[:=]\s*)?bearer\s+)[^\s\r\n]+",r"\1[REDACTED]",s)
s=re.sub(r"(?i)([?&](?:token|access_token|auth|key|api_key|secret)=)[^&\s\r\n]+",r"\1[REDACTED]",s)
s=re.sub(r"(?i)(\b(?:password|secret|access_token|api_key)\s*[:=]\s*)[^\s,;}]+",r"\1[REDACTED]",s)
sys.stdout.write(s)
'
}
receipt="$dir/HF13_RESULT.txt"
{
  printf 'HF13_SCHEMA=1\n'
  printf 'HF13_MODE=%s\n' "$mode"
  printf 'HF13_TEST_EXIT=%s\n' "$status"
  printf 'HF13_REAL_DEVICE=false\n'
  printf 'HF13_RELEASE_ACCEPTANCE=false\n'
  if (( status == 0 )); then
    printf 'HF13_RESULT=TEST_COMMAND_SUCCEEDED\n'
  else
    printf 'HF13_RESULT=INSTRUMENTATION_FAILED_FAIL_CLOSED\n'
  fi
} > "$receipt"
# Never upload unfiltered whole-device logcat. Bound output to recent failure lines.
if (( status != 0 )); then
  { adb -s "$serial" logcat -d -b crash -v threadtime 2>&1 || :; } | tail -n 280 | redact > "$dir/android-crash-buffer.txt" || :
  { adb -s "$serial" logcat -d -b main -v threadtime -s AndroidRuntime:E TestRunner:E Instrumentation:E libc:F DEBUG:F art:E 2>&1 || :; } | tail -n 380 | redact > "$dir/android-runtime-errors.txt" || :
  { adb -s "$serial" shell pm list instrumentation 2>&1 || :; } | head -n 40 | redact > "$dir/instrumentation-packages.txt" || :
  # Read-only screenshot is evidence of a booted emulator, NOT proof of tests.
  adb -s "$serial" exec-out screencap -p > "$dir/emulator-on-failure.png" 2>/dev/null || rm -f "$dir/emulator-on-failure.png"
  # Expose a bounded crash trace in public CI output without printing full logcat.
  echo 'XDM_HF13_INSTRUMENTATION_FAILED: see hosted crash-evidence artifact' >&2
  echo '=== AndroidRuntime crash excerpt (bounded) ===' >&2
  tail -n 100 "$dir/android-runtime-errors.txt" >&2 || :
  echo '=== Native/Android crash buffer excerpt (bounded) ===' >&2
  tail -n 80 "$dir/android-crash-buffer.txt" >&2 || :
else
  echo 'XDM_HF13_INSTRUMENTATION_COMMAND_PASS: results are still subject to the release gate' >&2
fi
# Return success to EXIT-trap caller, which always exits with original code.
exit 0

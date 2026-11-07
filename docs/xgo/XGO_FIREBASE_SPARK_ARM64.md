# XGO: Firebase Test Lab Spark native ARM64 acceptance (HF14)

This is a **manual, one-physical-device** Android instrumentation job. It runs on the Firebase **Spark** plan's documented five physical-device test runs per day. It does **not** automatically run on commits or PRs, and it cannot guarantee unused quota or inspect a project's payment plan without additional permissions. Do not run it against a Blaze/billable project. Firebase Test Lab is being discontinued on September 30, 2027.

## Configure once (outside the source tree)

1. Create or select a Firebase project and verify it is on the **Spark (no-cost)** plan in the Firebase console. Do not enable billing/Blaze. Enable the relevant Test Lab/Cloud Testing APIs and permissions for the project; this requires project owner/admin access.
2. Configure GitHub OIDC-to-Google **Workload Identity Federation** restricted to the exact GitHub repository `Mikeyphw/xdm-xgo`. Grant the chosen service account the minimum Test Lab run permission and required test-artifact storage permissions. Follow [google-github-actions/auth](https://github.com/google-github-actions/auth#workload-identity-federation-through-a-service-account) and [Firebase Test Lab CLI docs](https://firebase.google.com/docs/test-lab/android/command-line).
3. In **GitHub repository Settings → Secrets and variables → Actions → Variables**, set: `XGO_FIREBASE_PROJECT_ID`, `XGO_FIREBASE_WIF_PROVIDER` (full `projects/NUMBER/locations/global/workloadIdentityPools/POOL/providers/PROVIDER` path), and `XGO_FIREBASE_SERVICE_ACCOUNT` (`ACCOUNT@PROJECT.iam.gserviceaccount.com`). No private key, project ID, or Google token belongs in this repository.
4. Get an exact eligible physical model ID using `gcloud firebase test android models list`, and check `gcloud firebase test android models describe MODEL_ID --format=json`: the model must be `PHYSICAL`, support `arm64-v8a`, and list the Android OS version (prefer `36` if available). Models and OS availability can change; the workflow **refuses** unsupported combinations. Android 16 is not guaranteed on a physical Spark device.
5. In GitHub **Actions → XDM Android CI → Run workflow**, select the intended branch, set `firebase_spark=true`, provide `model_id` and `version_id` (default `36`), and deliberately tick `confirm_spark` after verifying the free Spark plan. One workflow dispatch consumes at most **one device execution**; retrying consumes more quota. Never dispatch this workflow on every PR.

## What is / isn't proven

- The workflow builds the actual ARM64 Go JNI debug app and the real Android instrumentation APKs with hosted Gradle/NDK. It refuses APKs with missing `lib/arm64-v8a/libxdmcore.so` or a non-AArch64 ELF.
- The `gcloud` invocation targets exactly one validated **physical ARM64** test device. Its nonzero exit status propagates, and a receipt records APK SHA256 checksums, selected device and the Test Lab summary. This is **real instrumentation**, not a source-only check.
- The existing x86-64 emulator in `.github/workflows/android.yml` still has an independently confirmed Android native-translation crash (`internal/cpu.getMIDR`). This new lane **does not make that job pass** and does not silently disable it. The existing release/signing/KVM gates are unchanged.
- A real physical-device run establishes native ARM64 behavior; it does not automatically prove 16 KiB physical page-size testing. Select a supported 16 KiB target explicitly if one is present in the Test Lab catalog. The Android ELF build still checks 16 KiB segment alignment.
- Firebase Test Lab Spark provides up to **5 physical** and **10 virtual** runs/day per project. Usage or device availability may block runs. The workflow does not verify the project's billing status itself; the manual confirmation is mandatory.

## References

- Firebase usage/quota/pricing: https://firebase.google.com/docs/test-lab/usage-quotas-pricing
- Firebase instrumentation via gcloud: https://firebase.google.com/docs/test-lab/android/command-line
- Catalog: https://firebase.google.com/docs/test-lab/android/available-testing-devices
- Google authentication: https://github.com/google-github-actions/auth

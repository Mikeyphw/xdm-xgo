# MP01 HF03 — Secure Phase13 validator and Kotlin contract migration

Source-pinned to PR #10 head `12c464136e8ef4d1bf8fb91f766e8b6db71f4013` (tree `0f457a7a182924f745fa26fbc54b393e91648889`).

The Android CI `Static release contracts` gate failed at `validate-remediation-phase13-final-gate.py` with “direct-v3 media capture builder is missing”. This historical assertion still demanded the now-forbidden plaintext v3 URL/headers-in-navigation model. The adjacent `RemediationPhase13FinalGateContractTest.kt` also required a plaintext v3 query serializer and would have failed in the subsequent Gradle test phase.

This hotfix changes exactly those two existing files and adds this report. It requires public-only Add v1, rejection of unpaired credential-bearing captures, app-paired RSA-OAEP + AES-GCM v2 capture with fresh IV and bounded encrypted envelope, no plaintext URL/headers/candidates in navigation, and existing Node behavioral tests proving successful decrypt, no secret disclosure and no cross-request header promotion. It preserves the legacy bridge rejection coverage without re-enabling legacy capture v3.

The installer uses a clean source checkout, exact PR head, two Git blob pins, atomic Devtool overlay and automatic commit, corrected Zsh-safe fetch refspec, static validator and optional local Node checks, then non-force push to existing feature branch. No local Gradle. GitHub CI and physical Android validation remain separate and must be checked after push.

GitHub connector direct write returned HTTP 403 Resource not accessible by integration, so this deliverable must be run in the user's authenticated Termux/gh environment.

#!/usr/bin/env python3
"""Focused behavioral regressions for XAR01 build/runtime provenance hardening."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ff = load("xdm_xar01_ffmpeg_installer", "tools/install-ffmpeg-runtime.py")
aria = load("xdm_xar01_aria_installer", "tools/install-aria2-runtime.py")
bundle = load("xdm_xar01_bundletool", "tools/ensure-bundletool.py")


class Xar01BuildProvenanceTest(unittest.TestCase):
    def test_wrong_ndk_revision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ndk = Path(raw)
            (ndk / "source.properties").write_text("Pkg.Revision = 28.2.13676358\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                ff.ndk_provenance(ndk, "29.0.14206865")

    def test_exact_ndk_revision_is_attested(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ndk = Path(raw)
            source = ndk / "source.properties"
            source.write_text("Pkg.Desc = Android NDK\nPkg.Revision = 29.0.14206865\n", encoding="utf-8")
            evidence = ff.ndk_provenance(ndk, "29.0.14206865")
            self.assertEqual("29.0.14206865", evidence["revision"])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), evidence["sourcePropertiesSha256"])

    def test_tool_fingerprint_changes_when_compiler_bytes_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tool = Path(raw) / "clang"
            tool.write_text("#!/bin/sh\necho clang-xar01-v1\n", encoding="utf-8")
            tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
            first = ff.tool_fingerprint(tool)
            tool.write_text("#!/bin/sh\necho clang-xar01-v2\n", encoding="utf-8")
            tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
            second = ff.tool_fingerprint(tool)
            self.assertNotEqual(first["sha256"], second["sha256"])
            self.assertNotEqual(first["version"], second["version"])

    def test_modified_extracted_source_tree_is_not_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "source.tar.gz"
            payload = b"pinned source bytes\n"
            with tarfile.open(archive, "w:gz") as tf:
                info = tarfile.TarInfo("source-1/configure")
                info.size = len(payload)
                info.mode = 0o755
                tf.addfile(info, io.BytesIO(payload))
            extracted = root / "tree"
            ff.safe_extract(archive, extracted)
            self.assertTrue(ff.archive_tree_matches(archive, extracted))
            (extracted / "source-1/configure").write_bytes(b"tampered\n")
            self.assertFalse(ff.archive_tree_matches(archive, extracted))

    def test_aria_cache_identity_is_bound_to_trusted_digest(self) -> None:
        manifest = {
            "component": "aria2c",
            "version": "1.37.0",
            "releaseTag": "v1.37.0",
            "officialUrl": "https://example.invalid/aria2c-arm64-v8a",
            "archiveName": "aria2c-arm64-v8a",
        }
        with tempfile.TemporaryDirectory() as raw:
            cache = Path(raw)
            a = aria.cached_download_path(manifest, cache, "a" * 64)
            b = aria.cached_download_path(manifest, cache, "b" * 64)
            self.assertNotEqual(a, b)

    def test_aria_cached_payload_must_match_explicit_trusted_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            payload = Path(raw) / "aria2c"
            payload.write_bytes(b"x")
            manifest = {"minimumBinaryBytes": 1, "officialUrl": "https://example.invalid/aria2c", "archiveName": "aria2c"}
            actual = hashlib.sha256(b"x").hexdigest()
            self.assertTrue(aria.cached_payload_usable(payload, manifest, actual))
            self.assertFalse(aria.cached_payload_usable(payload, manifest, "0" * 64))

    def test_bundletool_pin_is_content_addressed(self) -> None:
        self.assertEqual("1.18.3", bundle.VERSION)
        self.assertRegex(bundle.SHA256, r"^[0-9a-f]{64}$")
        with tempfile.TemporaryDirectory() as raw:
            bad = Path(raw) / "bundletool.jar"
            bad.write_bytes(b"not the pinned jar")
            with self.assertRaises(SystemExit):
                bundle.verify(bad)


# HF02 regression: S01-11 event-driven Android CI, without path-filter fiction.
# Historical release signing, toolchain and source-pinning checks stay unchanged.
from xar01_ci_trigger_policy import audit_android_triggers


class Xar01ExplicitAndroidTriggersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT.parent.parent / '.github/workflows/android.yml').read_text(encoding='utf-8')

    def test_real_workflow_accepts_tag_only_and_manual_default_off(self):
        self.assertEqual(audit_android_triggers(self.workflow), [])

    def test_old_path_filter_assumptions_not_required(self):
        self.assertNotIn("- '.devtool.toml'", self.workflow)
        self.assertNotIn("- 'build-release-apk.sh'", self.workflow)
        self.assertEqual(audit_android_triggers(self.workflow), [])

    def test_unsafe_trigger_and_signing_mutations_refuse(self):
        cases = {
            'push-main': ("    tags: ['android-v*']", "    branches: [main]"),
            'push-all-tags': ("    tags: ['android-v*']", "    tags: ['*']"),
            'push-all-branches': ("    tags: ['android-v*']", "    branches: ['*']"),
            'push-no-restriction': ("    tags: ['android-v*']", "    tags: []"),
            'automatic-pr': ("  workflow_dispatch:\n", "  pull_request:\n  workflow_dispatch:\n"),
            'schedule': ("  workflow_dispatch:\n", "  schedule:\n  workflow_dispatch:\n"),
            'duplicate-manual': ("  workflow_dispatch:\n", "  workflow_dispatch:\n  workflow_dispatch:\n"),
            'signed-on-branch': ("if: startsWith(github.ref, 'refs/tags/android-v')", "if: startsWith(github.ref, 'refs/heads/main')"),
            'signed-always': ("if: startsWith(github.ref, 'refs/tags/android-v')", "if: true # startsWith(github.ref, 'refs/tags/android-v')"),
            'signed-auto-dispatch': ("&& inputs.signed_release))", "&& true))"),
            'signed-allow-failure': ('  signed-release:\n', '  signed-release:\n    continue-on-error: true\n'),
            'signed-skip-provenance': ('      XDM_XAR16_FULL_RELEASE_GATE: "1"', '      XDM_XAR16_FULL_RELEASE_GATE: "0"'),
            'strip-signer': ('      XDM_RELEASE_SIGNER_SHA256:', '      XDM_RELEASE_SIGNER_SHA257:'),
            'drop-artifact': ('name: xdm-android-physical-arm64-apk-pair', 'name: fake-apk-pair'),
            'skip-preflight': ('  validate:\n    needs: hotfix-fast', '  validate:\n    needs: nope'),
        }
        for label, (old, new) in cases.items():
            with self.subTest(label=label):
                self.assertIn(old, self.workflow)
                mutated = self.workflow.replace(old, new, 1)
                self.assertTrue(audit_android_triggers(mutated), label)

    def test_each_explicit_input_cannot_enable_itself(self):
        for name in ('signed_release', 'arm64_translation_diagnostic', 'x86_64_native_test'):
            block = self.workflow.split('      '+name+':\n', 1)[1]
            import re
            end = re.split(r'(?m)^      [a-z0-9_]+:\s*$', block, maxsplit=1)[0]
            self.assertIn('default: false', end)
            with self.subTest(name=name):
                self.assertTrue(audit_android_triggers(self.workflow.replace(
                    '      '+name+':\n'+end,
                    '      '+name+':\n'+end.replace('default: false', 'default: true'), 1)))

    def test_direct_path_filters_are_not_a_signed_release_substitute(self):
        injected = self.workflow.replace("    tags: ['android-v*']", "    paths: ['.devtool.toml']", 1)
        self.assertTrue(audit_android_triggers(injected))

    def test_duplicate_on_mapping_refuses(self):
        self.assertTrue(audit_android_triggers(self.workflow + '\non:\n  push:\n    tags: [\'android-v*\']\n'))

if __name__ == "__main__":
    unittest.main(verbosity=2)

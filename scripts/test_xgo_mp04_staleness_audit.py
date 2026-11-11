#!/usr/bin/env python3
"""MP04 immutable parent/stale test contract audit (XPI, HLS, and CI05)."""
from pathlib import Path
import hashlib,os,re,subprocess,unittest
ROOT=Path(__file__).resolve().parents[1]
REAL=Path(os.environ.get('XGO_MP04_REAL_REPO',ROOT))
PARENT='aa098d6ee5403b3e734c88f8736ae551604e56c1'

def committed(path):return subprocess.check_output(['git','show',f'{PARENT}:{path}'],cwd=REAL)
def contract(path):return (ROOT/path).read_bytes()
def validate_ci05_contract(code, workflow):
    # These are executable workflow/policy anchors, not arbitrary user-visible
    # names, capitalization, or prose. Each must be present in the real stage.
    guards = (
        ('mp03_registry', 'tests.update(MP03_PYTHON)', code),
        ('mp04_registry', 'tests.update(MP04_PYTHON)', code),
        ('full_go_test', 'subprocess.run(["go", "test", "./..."]', code),
        ('android_classifier', '"needs_android_compile": any(', code),
        ('source_job', 'targeted-source:', workflow),
        ('setup_go', '- uses: actions/setup-go@v6', workflow),
        ('conditional_go', "if: needs.scope.outputs.needs_go == 'true'", workflow),
        ('go_toolchain', 'go-version-file: engine/go.mod', workflow),
        ('targeted_runner', 'python3 -B scripts/ci/xgo_ci_policy.py run-targeted', workflow),
        ('go_scope', '--base "$BASE_SHA" --head "$HEAD_SHA"', workflow),
        ('head_sha', 'test "$HEAD_SHA" = "$EXPECTED_SHA"', workflow),
        ('head_checkout', 'test "$(git rev-parse HEAD)" = "$HEAD_SHA"', workflow),
        ('android_job', 'targeted-android:', workflow),
        ('android_compile', ':app:compileDebugKotlin', workflow),
        ('android_qualification', 'test "$ANDROID" = success', workflow),
        ('source_qualification', 'test "$SOURCE" = success', workflow),
    )
    for name, anchor, body in guards:
        if anchor not in body:
            raise AssertionError('MP04_CI05_STALE_OR_BYPASSED: '+name)
    # Ensure the Go setup condition and mandatory run are in the source job,
    # not a dead/commented sibling job. Disallow silent job omissions.
    src=workflow.split('  targeted-source:',1)[-1].split('  targeted-android:',1)[0]
    if not all(x in src for x in ('- uses: actions/setup-go@v6',
                "if: needs.scope.outputs.needs_go == 'true'",
                'python3 -B scripts/ci/xgo_ci_policy.py run-targeted')):
        raise AssertionError('MP04_CI05_STALE_OR_BYPASSED: scoped_go_job')
    return True

def ci05_fixtures():
    return (contract('scripts/ci/xgo_ci_policy.py').decode(),
            contract('.github/workflows/xgo-targeted.yml').decode())

class Staleness(unittest.TestCase):
    def test_parent_exists_in_actual_repository(self):
        self.assertEqual(subprocess.check_output(['git','rev-parse',PARENT],cwd=REAL,text=True).strip(),PARENT)
    def test_original_xpi_and_hls_parsers_not_modified(self):
        for path in ('docs/xgo/XGO_XPI_V161_REFERENCE_DIGESTS.json',
             'engine/media/manifest_resolver.go','engine/media/selection.go',
             'app/XDM.Android/media/src/main/kotlin/com/mikeyphw/xdm/android/media/MediaDownloadPlanner.kt'):
            self.assertEqual(contract(path),committed(path),path)
    def test_mp05_hls_mutation_requires_actual_durable_sink(self):
        current=contract('engine/media/hls_execution.go').decode()
        original=committed('engine/media/hls_execution.go').decode()
        self.assertIn('artifact := artifactRefForFragment(entry.Identity)',original)
        self.assertNotIn('artifact := artifactRefForFragment(entry.Identity)',current)
        for evidence in ('BindDurableStore(store DurableFragmentSink)',
                         'e.store.WriteAndCommitFragment(ctx,',
                         'e.store.VerifyCommitted(',
                         'e.ledger.Commit(receipt)', 'durable_store_required'):
            self.assertIn(evidence,current)
        self.assertIn('executeSegment(',current)

    def test_no_stale_fixture_inheritance(self):
        for path in ('engine/media/selection_test.go','engine/media/manifest_resolver_test.go'):
            text=committed(path).decode()
            self.assertIn('func Test',text)
        new=contract('engine/media/manifest_selection_test.go').decode()
        for name in ('SEL01','SEL02','SEL03','SEL04','SEL05','SEL06','SEL07','SEL08','MUX01'):
            self.assertIn(name,new)
        self.assertGreaterEqual(len(re.findall(r'^func TestMP04',new,re.M)),10)
    def test_targeted_ci05_not_bypassed(self):
        # Source-level checks: no literal job-label dependency ("Go" is not a
        # stable workflow contract). The actual setup, SHA and compilation
        # wiring must remain active, or a targeted job can silently disappear.
        validate_ci05_contract(
            contract('scripts/ci/xgo_ci_policy.py').decode(),
            contract('.github/workflows/xgo-targeted.yml').decode(),
        )
    def test_ci05_negative_missing_go_setup(self):
        code, workflow = ci05_fixtures()
        with self.assertRaisesRegex(AssertionError, 'setup_go'):
            validate_ci05_contract(code, workflow.replace('actions/setup-go@v6','actions/setup-node@v5'))
    def test_ci05_negative_unconditional_go_setup(self):
        code, workflow = ci05_fixtures()
        with self.assertRaisesRegex(AssertionError, 'conditional_go'):
            validate_ci05_contract(code, workflow.replace("needs.scope.outputs.needs_go == 'true'", "always()"))
    def test_ci05_negative_removed_go_execution(self):
        code, workflow = ci05_fixtures()
        with self.assertRaisesRegex(AssertionError, 'full_go_test'):
            validate_ci05_contract(code.replace('subprocess.run(["go", "test", "./..."]', 'pass # disabled Go tests'), workflow)
    def test_ci05_negative_removed_mp04_tests(self):
        code, workflow = ci05_fixtures()
        with self.assertRaisesRegex(AssertionError, 'mp04_registry'):
            validate_ci05_contract(code.replace('tests.update(MP04_PYTHON)', '# removed MP04 tests'), workflow)
    def test_ci05_negative_removed_android_compile(self):
        code, workflow = ci05_fixtures()
        with self.assertRaisesRegex(AssertionError, 'android_compile'):
            validate_ci05_contract(code, workflow.replace(':app:compileDebugKotlin', ':app:tasks'))
    def test_ci05_negative_removed_head_sha_guard(self):
        code, workflow = ci05_fixtures()
        with self.assertRaisesRegex(AssertionError, 'head_sha'):
            validate_ci05_contract(code, workflow.replace('test "$HEAD_SHA" = "$EXPECTED_SHA"', 'echo unpinned'))
    def test_ci05_negative_removed_qualification(self):
        code, workflow = ci05_fixtures()
        with self.assertRaisesRegex(AssertionError, 'android_qualification'):
            validate_ci05_contract(code, workflow.replace('test "$ANDROID" = success', 'echo skipped'))
    def test_transport_secret_boundary(self):
        core=contract('engine/media/manifest_selection.go').decode()
        self.assertNotIn('log.Printf(',core)
        self.assertNotIn('fmt.Printf(',core)
        kt=contract('app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/ManifestSelectionV1Contract.kt').decode()
        self.assertNotIn('transportUrl',kt)
        self.assertNotIn('println(',kt)
if __name__=='__main__':unittest.main(verbosity=2)

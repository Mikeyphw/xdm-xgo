#!/usr/bin/env python3
"""MP12 P03 source contracts and mutation tests; no Android/Gradle or real data."""
from __future__ import annotations
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'controller': 'engine/runtime/canary/controller.go',
    'controller_tests': 'engine/runtime/canary/controller_test.go',
    'handler': 'engine/runtime/mp12_canary_handlers.go',
    'handler_tests': 'engine/runtime/mp12_canary_handlers_test.go',
}

class Refused(Exception):
    pass


def require(condition: bool, code: str):
    if not condition:
        raise Refused('MP12_P03_REFUSED_' + code)


def audit(root: Path) -> dict:
    data = {}
    for name, path in FILES.items():
        file = root / path
        require(file.is_file() and not file.is_symlink(), 'SOURCE_MISSING_' + name)
        data[name] = file.read_text(encoding='utf-8')
    controller, tests = data['controller'], data['controller_tests']
    handler, handlers_test = data['handler'], data['handler_tests']
    require(controller.count('Primary: "legacy"') == 3 and
            'ProductionCutoverAuthorized: false' in controller and
            'Primary: "legacy"' in controller and
            'Primary: "go"' not in controller,
            'LEGACY_PRIMARY_NOT_IMMUTABLE')
    require('O_EXCL' in controller and 'os.Rename(' in controller and
            'out.Sync()' in controller and 'dir.Sync()' in controller and
            'STALE_REVISION' in controller and 'SINGLE_OWNER_BUSY' in controller,
            'DURABLE_SINGLE_WRITER_OR_FSYNC_LOST')
    require('PhaseRollbackPending' in controller and 'PhaseRolledBack' in controller and
            'recovery_restart' in controller and 'rollbackLocked' in controller and
            'INTERRUPTED_TRANSACTION_MANUAL_REVIEW' in controller,
            'RESTART_RECOVERY_FENCE_LOST')
    require('JOURNAL_NONCANONICAL_OR_DUPLICATE' in controller and
            'JOURNAL_INTEGRITY_OR_SOURCE' in controller and
            'PRIVATE_DIR_PERMISSIONS' in controller and
            'JOURNAL_FILE_UNSAFE' in controller,
            'PRIVATE_JOURNAL_INTEGRITY_LOST')
    require('EXPLICIT_OPT_IN_REQUIRED' in controller and
            'PRODUCTION_CUTOVER_NOT_AUTHORIZED' in controller and
            'NewMP12' not in controller,
            'NO_CUTOVER_BOUNDARY_LOST')
    require('DisallowUnknownFields()' in handler and
            'trustedHostOptIn' in handler and handler.count('trustedHostOptIn') == 3 and
            'len(env.Payload) > 1024' in handler and
            'MP12CanaryHandlers' in handler and
            'runtime.canary.decision' in handler and
            'case "rollback"' in handler and
            'command.Envelope' in handler and
            'event.Operational' in handler,
            'HOST_WIRE_BOUNDARY_LOST')
    require(re.search(r'func Test\w+\(', tests) is not None and
            tests.count('func Test') >= 14 and
            'TestConcurrentPrepareOnlyOneSucceeds' in tests and
            'TestRollbackFaultAfterPendingRecovers' in tests and
            'TestCrashAfterShadowAutoRollback' in tests and
            'TestCorruptSealAndDuplicateJSONRefused' in tests,
            'CANARY_GO_NEGATIVE_MATRIX_LOST')
    require('TestMP12CanaryRealEngineCommandProtocol' in handlers_test and
            'TestMP12CanaryHostOptInNotGrantedFromPayload' in handlers_test and
            'runtime.canary.decision' in handlers_test and
            'command.failed' in handlers_test,
            'REAL_RUNTIME_HANDLER_TEST_MISSING')
    return {'files_checked': len(FILES), 'production_cutover_authorized': False,
            'primary': 'legacy', 'requires_real_runtime': True}


class CanaryContracts(unittest.TestCase):
    def test_source_controls(self):
        result = audit(ROOT)
        self.assertEqual(result['files_checked'], 4)
        self.assertEqual(result['primary'], 'legacy')
        self.assertFalse(result['production_cutover_authorized'])

    def fixture(self):
        td = tempfile.TemporaryDirectory(prefix='mp12-p03-negative-')
        self.addCleanup(td.cleanup)
        temp = Path(td.name)
        for file in FILES.values():
            target = temp / file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / file).read_bytes())
        return temp

    def mutation(self, file: str, source: str, target: str, code: str):
        root = self.fixture()
        p = root / FILES[file]
        original = p.read_text()
        self.assertIn(source, original)
        p.write_text(original.replace(source, target, 1))
        with self.assertRaisesRegex(Refused, code):
            audit(root)

    def test_primary_mutation_refused(self):
        self.mutation('controller', 'Primary: "legacy"', 'Primary: "go"', 'LEGACY_PRIMARY')

    def test_writer_fsync_mutation_refused(self):
        self.mutation('controller', 'dir.Sync()', 'nil', 'DURABLE_SINGLE_WRITER')

    def test_rollback_fence_mutation_refused(self):
        self.mutation('controller', 'recovery_restart', 'unverified_restart', 'RESTART_RECOVERY')

    def test_journal_seal_guard_mutation_refused(self):
        self.mutation('controller', 'JOURNAL_INTEGRITY_OR_SOURCE', 'UNSAFE_SKIP', 'PRIVATE_JOURNAL')

    def test_untrusted_host_mutation_refused(self):
        self.mutation('handler', 'trustedHostOptIn', 'ignoreHostOptIn', 'HOST_WIRE')

    def test_missing_concurrent_negative_refused(self):
        self.mutation('controller_tests', 'TestConcurrentPrepareOnlyOneSucceeds',
                      'DisabledNegative', 'CANARY_GO_NEGATIVE')

    def test_missing_runtime_command_negative_refused(self):
        self.mutation('handler_tests', 'TestMP12CanaryHostOptInNotGrantedFromPayload',
                      'DisabledNegative', 'REAL_RUNTIME_HANDLER')

    def test_missing_file_refused(self):
        root = self.fixture()
        (root / FILES['handler']).unlink()
        with self.assertRaisesRegex(Refused, 'SOURCE_MISSING_handler'):
            audit(root)

    def test_symlink_source_refused(self):
        root = self.fixture()
        target = root / FILES['handler']
        target.unlink()
        target.symlink_to(root / FILES['controller'])
        with self.assertRaisesRegex(Refused, 'SOURCE_MISSING_handler'):
            audit(root)

if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""MP09 capture-scoped cleanup contract and negative mutation checks.

This is a source-security contract, not an Android device deletion proof.
"""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
ENGINE=Path('app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine')


def check(store:str, policy:str)->None:
    for marker in ('private var startupHealthy:',
                   'action !in setOf("discard_capture", "reconcile")',
                   'startupHealthy = runCatching { reconcile()',
                   'if (!AndroidMP09SessionPhaseGate.mayDiscard(phase))',
                   'AndroidMP09CleanupPlan.ownedJournalKeys(',
                   'AndroidMP09CleanupPlan.deleteOwnedFiles(',
                   'keys.forEach { rows.remove(it) }',
                   'atomicFile(journal, rows.toString().toByteArray(Charsets.UTF_8))',
                   'syncDirectory(parts)',
                   'AndroidMP09CleanupPlan.ownedFiles(',
                   'cleanup_unsafe_owned_path',
                   'cleanup_scope", "capture_owned_only"',
                   'if (phase == "published" && terminal == "published_clean")',
                   'sessionSeal(priorSession)',
                   'sessionJournalRows()'):
        if marker not in store:raise AssertionError('missing cleanup gate '+marker)
    fragment=store.split('    private fun discardCapture(')[1].split('    private fun reconcile(')[0]
    for bad in ('rec.optString("artifact_ref")', 'if (!checkReceipt(rec))',
                'File(root,name)', 'rows.optJSONObject(key) ?: return refused("cleanup_corrupt")'):
        if bad in fragment:raise AssertionError('unsafe cleanup receipt dependency '+bad)
    for marker in ('ownedJournalKeys(', 'ownedPartNames(', 'deleteOwnedFiles(', 'ownedFiles(', 'captureDigest',
                   'fragmentId', 'ownedFileSuffix', 'MAX_OWNED_ENTRIES',
                   'require(selected.all', 'require(owned.all'):
        if marker not in policy:raise AssertionError('missing owner-scope validation '+marker)
    if 'deleteRecursively(' in fragment or 'walkTopDown(' in fragment:
        raise AssertionError('unbounded recursive deletion forbidden')


class CleanupContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store=(ROOT/ENGINE/'AndroidLiveDurableFragmentStore.kt').read_text()
        cls.policy=(ROOT/ENGINE/'AndroidMP09CleanupPlan.kt').read_text()
    def test_real_source(self):check(self.store,self.policy)
    def test_negative_mutations(self):
        substitutions=[
            ('AndroidMP09CleanupPlan.deleteOwnedFiles(', 'listOf(', 'store'),
            ('AndroidMP09CleanupPlan.ownedJournalKeys(', 'listOf(', 'store'),
            ('if (!AndroidMP09SessionPhaseGate.mayDiscard(phase))', 'if (false)', 'store'),
            ('syncDirectory(parts)', '/* missing fsync */', 'store'),
            ('AndroidMP09CleanupPlan.ownedFiles(', 'false', 'store'),
            ('capture_owned_only', 'all_files', 'store'),
            ('fragmentId', 'disabledIdCheck', 'policy'),
            ('ownedFileSuffix', 'disabledPattern', 'policy'),
        ]
        for old,new,where in substitutions:
            with self.subTest(old=old):
                data=self.store if where=='store' else self.policy
                self.assertIn(old,data)
                altered=data.replace(old,new)
                with self.assertRaises(AssertionError):
                    check(altered if where=='store' else self.store,
                          altered if where=='policy' else self.policy)


if __name__=='__main__':unittest.main(verbosity=2)

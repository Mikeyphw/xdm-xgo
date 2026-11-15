#!/usr/bin/env python3
"""MP11 P03 source contract: fail-closed publication and media-library UX.
This does not substitute for hosted Android Kotlin compilation or API36 testing.
"""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
E='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/engine/'
UI='app/XDM.Android/app/src/main/kotlin/com/mikeyphw/xdm/android/ui/library/MediaLibraryScreen.kt'

def check(policy:str,index:str,screen:str)->None:
    required={
      'policy':('phase in setOf("published", "published_clean")','status == "published_verified"',
                '&& visible && verifiedBytes &&','!uri.contains("..")','content.matches(uri)'),
      'index':('session_status','AndroidLiveDurableFragmentStore','verifyMediaStore',
                'MP11LiveLibraryPolicy.completed','verifyMediaStore(app, uri, bytes, digestValue)','finalPhase != phase','seenPublications.add(pub)',
                'seenUris.add(uri)','safeDirectory','safeFile','currentCoroutineContext().ensureActive()',
                'stillVerified','mediaStoreUri','MediaStore.AUTHORITY','!Files.isSymbolicLink',
                'phase == "publishing"','phase == "recording" && owned.isEmpty()','cleanupPending'),
      'screen':('MP11LiveLibraryIndex.scan','MP11LiveLibraryIndex.stillVerified',
                'Verified live recordings','Live recordings requiring review',
                'onLiveMediaAction(recording, false)','shareMediaFile(context, item.mediaStoreUri',
                'openMediaFile(context, item.mediaStoreUri', 'Review in Media',
                'File verification required','selectedLiveDetails'),
    }
    for scope,src in {'policy':policy,'index':index,'screen':screen}.items():
      for phrase in required[scope]:
        if phrase not in src:raise AssertionError(scope+' missing '+phrase)
    for phrase in ('MediaRequestHandoffStore','rememberCapture(', 'setDataAndType(Uri.parse(capture.sourceUrl',
                   'isCompleted = true','DownloadState.Completed'):
      if phrase in index:raise AssertionError('unverified source or completion promotion: '+phrase)
    if 'if (visibleItems.isEmpty() && visibleLive.isEmpty())' not in screen:
      raise AssertionError('false empty library when live items exist')

class P03Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy=(ROOT/(E+'MP11LiveLibraryPolicy.kt')).read_text()
        cls.index=(ROOT/(E+'MP11LiveLibraryIndex.kt')).read_text()
        cls.screen=(ROOT/UI).read_text()
    def test_contract(self):check(self.policy,self.index,self.screen)
    def test_negative_mutations(self):
        for kind,needle in [('policy','&& visible && verifiedBytes &&'),('policy','published_clean'),
                            ('index','verifyMediaStore(app, uri, bytes, digestValue)'),('index','finalPhase != phase'),
                            ('index','seenPublications.add(pub)'),('index','session_status'),
                            ('screen','MP11LiveLibraryIndex.stillVerified'),
                            ('screen','if (visibleItems.isEmpty() && visibleLive.isEmpty())')]:
            with self.subTest(kind=kind,needle=needle):
                values=dict(policy=self.policy,index=self.index,screen=self.screen)
                self.assertIn(needle,values[kind]);values[kind]=values[kind].replace(needle,'MUTATED',1)
                with self.assertRaises(AssertionError):check(**values)

if __name__=='__main__':unittest.main(verbosity=2)

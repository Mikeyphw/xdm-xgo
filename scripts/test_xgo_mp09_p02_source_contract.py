#!/usr/bin/env python3
"""Focused source-only MP09 P02 contract checks; real Go tests run in hosted CI."""
from pathlib import Path
import re

root=Path(__file__).resolve().parents[1]
source=(root/'engine/media/live_poll.go').read_text()
tests=(root/'engine/media/live_poll_test.go').read_text()
compact=re.sub(r"\s+", "", source)
legacy=(root/'engine/media/live_session.go').read_text()
for token in ('func NewLivePollEngine(', 'func (e *LivePollEngine) Poll(',
              'NewHLSExecutor(', 'NewDASHExecutor(', 'BindDurableStore(e.store)',
              'ObserveCommitted(now,e.store,rec)', 'HLSFetchManifest', 'DASHFetchManifest',
              'SourceEnded', 'DownloadReady:false', 'Published:false',
              'ErrLivePollIncomplete', 'e.session.MarkGap(now)', 'e.session.NetworkFailure(now)',
              'MaxManifestBytes', 'MaxFragmentsPerPoll'):
    if token not in source and token not in compact:
        raise AssertionError('MP09_P02_SOURCE_REFUSED missing '+token)
for bad in ('http.Get(', 'http.Client{', 'Authorization:', 'Cookie:',
            'time.After(10*time.Minute)', 'time.After(2*time.Hour)',
            'DownloadReady:true', 'Published:true', 'os.WriteFile('):
    if bad in source:
        raise AssertionError('MP09_P02_SOURCE_REFUSED unsafe '+bad)
if 'func (s *LiveSession) StopAndSave' not in legacy or 'DownloadReady: false' not in legacy:
    raise AssertionError('MP09_P02_PARENT_LIFECYCLE_DRIFT')
names=re.findall(r'^func (TestMP09P02\w+)\(',tests,re.M)
if len(names)<8 or len(names)!=len(set(names)):
    raise AssertionError('MP09_P02_INSUFFICIENT_GO_TEST_COVERAGE '+str(names))
assert 'func TestMP09P02DASHRealDurableExplicitSelection' in tests
assert 'func TestMP09P02HLSRealDurableSlidingWindowAndReplay' in tests
assert (root/'docs/xgo/MP09_P02_LIVE_POLLING.md').exists()
print('XGO_MP09_P02_SOURCE_CONTRACT_PASS tests='+str(len(names)))

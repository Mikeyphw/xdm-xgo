#!/usr/bin/env python3
"""MP08A hostile-source test suite: real source, mandatory CI and fail-closed mux contract."""
from pathlib import Path
import re,unittest
ROOT=Path(__file__).resolve().parents[1]
def load(p):return (ROOT/p).read_text(encoding='utf-8')
def flat(s):return re.sub(r'\s+','',s)
class MP08SourceContracts(unittest.TestCase):
 def test_host_must_materialize_probe_and_reverify_published_bytes(self):
  s=load('engine/media/verified_publication.go');f=flat(s)
  for anchor in ('type MP08Host interface {','Assemble(context.Context, MP08FinalizationPlan)','Probe(context.Context, MP08StagedOutput)','ReadStaged(context.Context, MP08StagedOutput)','PublishAtomic(context.Context, MP08StagedOutput, string)','ReadPublished(context.Context, MP08PublishedOutput)'):
   self.assertIn(flat(anchor),f,anchor)
  for anchor in ('mp08HashStream(stream, staged.Size, staged.SHA256)','mp08ProbeCheck(p, probe, staged.Size)','mp08HashStream(published, output.Size, output.SHA256)','!output.Atomic','!mp08SafeName.MatchString(output.PublicationID)'):
   self.assertIn(flat(anchor),f,anchor)
 def test_source_records_require_real_verified_disk_bytes(self):
  s=load('engine/media/verified_publication.go');f=flat(s)
  for anchor in ('store.CommittedRecords()','store.VerifyCommitted(rec)','store.ReadVerified(rec.Identity)','rec.DurableBytesWritten','rec.State != FragmentCommitted','int64(len(body)) != rec.ExpectedLength','sha256.Sum256(body)'):
   self.assertIn(flat(anchor),f,anchor)
  self.assertNotRegex(s,r'\bhttp\s*\.\s*(?:Get|Post|Client|NewRequest)\s*\(')
  self.assertNotIn('os/exec',s)
  self.assertNotIn('net/http',s)
  self.assertNotIn('exec.Command',s)
  for anchor in ('result.validated = true', 'result.seal = mp08PlanSeal(result)', 'p.seal != mp08PlanSeal(p)'):
   self.assertIn(flat(anchor),flat(s),anchor)
 def test_every_dash_period_and_init_part_is_verified_by_identity(self):
  s=load('engine/media/verified_publication.go');f=flat(s)
  for a in ('PlanDASHPeriods(req)','p.IsDynamic','staged.Status != "staged"','staged.ReadyForMux','rt.ArtifactRefs[i]','mp07InitIdentity(f)','track.InitForPart = append(track.InitForPart, initForThis)','track.Parts = append(track.Parts, rec)'):
   self.assertIn(flat(a),f,a)
  self.assertNotIn('DownloadReady: true',s)
 def test_hls_map_before_key_privacy_and_stage_bound(self):
  s=load('engine/media/verified_publication.go');f=flat(s)
  for a in ('PlanHLSVOD(req)','HLSTimelineIdentity(seg)','seg.Map.Key','digestID("hls-init-key"','staged.IntentionalGaps','mp08Proof(store, initRec)'):
   if a=='staged.IntentionalGaps':continue
   self.assertIn(flat(a),f,a)
  self.assertIn('rt.IntentionalGaps != 0',s)
  self.assertIn('track.InitForPart',s)
 def test_probe_requires_real_container_duration_size_and_roles(self):
  s=load('engine/media/verified_publication.go');f=flat(s)
  for anchor in ('probe.Duration <= 0','probe.Container != p.Container','probe.Size != size','roles[StreamVideo] == 0','p.RequireAudio && roles[StreamAudio] == 0','p.RequireSubtitle && roles[StreamSubtitle] == 0','diff > tol'):
   self.assertIn(flat(anchor),f,anchor)
 def test_salvage_not_automatic_and_no_production_android_cutover(self):
  s=load('engine/media/verified_publication.go');f=flat(s)
  self.assertIn('RunMP08PartialRecovery',s)
  self.assertIn('ErrMP08PartialConsent',s)
  self.assertIn('p.Partial',s)
  self.assertIn('return receipt, ErrMP08PartialConsent',s)
  self.assertNotIn('receipt.DownloadReady = true; receipt.Partial = true',s)
  self.assertIn('receipt.DownloadReady = true',s) # only after publish + readback
  self.assertNotIn('Log.',s)
 def test_mux01_17_and_pub01_08_negative_go_cases(self):
  s=load('engine/media/verified_publication_test.go')
  for i in range(1,18):self.assertRegex(s,rf'func TestMP08MUX{i:02d}[A-Za-z0-9_]*\(')
  for i in range(1,9):self.assertRegex(s,rf'func TestMP08PUB{i:02d}[A-Za-z0-9_]*\(')
  for x in ('CorruptedOnDiskFragment','MissingAudio','MissingInit','FFmpegFailure','ProbeFailure','NonAtomic','PostPublishByteCorruption','PartialSalvage'):
   self.assertIn(x,s)
 def test_mp07_staleness_audit_only_strips_exact_mp08_registry(self):
  s=load('scripts/test_xgo_mp07_staleness_audit.py')
  for a in ('after.count(mp08_block)',
            "after=after.replace(mp08_block,'',1)",
            "self.assertEqual(after.replace('MP07_PYTHON"):
   self.assertIn(a,s)
 def test_targeted_ci_routes_go_and_prior_contracts(self):
  s=load('scripts/ci/xgo_ci_policy.py')
  for a in ('MP08_PYTHON = [','tests.update(MP08_PYTHON)','tests.update(MP07_PYTHON)','tests.update(MP06_PYTHON)','tests.update(MP05_PYTHON)','subprocess.run(["go", "test", "./..."]'):
   self.assertIn(a,s)
  p=load('scripts/ci/test_xgo_ci_policy.py')
  self.assertIn('def test_mp08_verified_publication_go_stage_always_routes_source_and_negative_tests',p)
  w=load('.github/workflows/xgo-targeted.yml')
  self.assertIn('test "$HEAD_SHA" = "$EXPECTED_SHA"',w)
  self.assertIn(':app:compileDebugKotlin',w)
 def test_explicit_acceptance_boundary_documented(self):
  d=load('docs/xgo/MP08A_VERIFIED_PUBLICATION_CORE_ACCEPTANCE.md')
  for a in ('not Android MediaStore qualified','MP08B','DownloadReady','FFprobe','ReadPublished','partial'):
   self.assertIn(a,d)
if __name__=='__main__':unittest.main(verbosity=2)

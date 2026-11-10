package media

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type mp08FakeHost struct {
	stage, published                                                                 []byte
	failMux, failProbe, failPublish, failStageRead, failPublishedRead                bool
	notAtomic, missingAudio, wrongDuration, wrongContainer, wrongSize, swappedDigest bool
	assemble, probe, publish                                                         int
}

func mp08Hash(b []byte) string { h := sha256.Sum256(b); return "sha256:" + hex.EncodeToString(h[:]) }
func mp08Host() *mp08FakeHost {
	b := bytes.Repeat([]byte("Z"), 4096)
	return &mp08FakeHost{stage: b, published: append([]byte(nil), b...)}
}
func (h *mp08FakeHost) Assemble(_ context.Context, _ MP08FinalizationPlan) (MP08StagedOutput, error) {
	h.assemble++
	if h.failMux {
		return MP08StagedOutput{}, errors.New("ffmpeg failed")
	}
	return MP08StagedOutput{HostToken: "stage_one", Size: int64(len(h.stage)), SHA256: mp08Hash(h.stage)}, nil
}
func (h *mp08FakeHost) Probe(_ context.Context, s MP08StagedOutput) (FFProbeReport, error) {
	h.probe++
	if h.failProbe {
		return FFProbeReport{}, errors.New("ffprobe failed")
	}
	p := FFProbeReport{Size: s.Size, Container: "mp4", Duration: 8 * time.Second,
		Streams: []FFProbeStream{{Kind: StreamVideo}, {Kind: StreamAudio}}}
	if h.missingAudio {
		p.Streams = p.Streams[:1]
	}
	if h.wrongDuration {
		p.Duration = 2 * time.Second
	}
	if h.wrongContainer {
		p.Container = "mkv"
	}
	if h.wrongSize {
		p.Size--
	}
	return p, nil
}
func (h *mp08FakeHost) ReadStaged(_ context.Context, _ MP08StagedOutput) (io.ReadCloser, error) {
	if h.failStageRead {
		return nil, errors.New("stage inaccessible")
	}
	return io.NopCloser(bytes.NewReader(h.stage)), nil
}
func (h *mp08FakeHost) PublishAtomic(_ context.Context, s MP08StagedOutput, _ string) (MP08PublishedOutput, error) {
	h.publish++
	if h.failPublish {
		return MP08PublishedOutput{}, errors.New("ENOSPC")
	}
	digest := s.SHA256
	if h.swappedDigest {
		digest = mp08Hash([]byte("swapped"))
	}
	return MP08PublishedOutput{URI: "content://xdm/media/one", PublicationID: "published_one", Size: s.Size, SHA256: digest, Atomic: !h.notAtomic}, nil
}
func (h *mp08FakeHost) ReadPublished(_ context.Context, _ MP08PublishedOutput) (io.ReadCloser, error) {
	if h.failPublishedRead {
		return nil, errors.New("after-crash")
	}
	return io.NopCloser(bytes.NewReader(h.published)), nil
}
func mp08DASHFixture(t *testing.T) (MP08FinalizationPlan, *FileFragmentStore, *FileFragmentStore) {
	t.Helper()
	r, f := mp07Fixture()
	v, a := mp07Stores(t)
	stage, err := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if err != nil {
		t.Fatal(err)
	}
	p, err := MP08DASHPlan(r, stage, v, a, nil, "media_one", "mp4")
	if err != nil {
		t.Fatal(err)
	}
	return p, v, a
}
func mp08Run(t *testing.T, p MP08FinalizationPlan, h *mp08FakeHost) (MP08FinalizationReceipt, error) {
	t.Helper()
	return RunMP08VerifiedPublication(context.Background(), p, h)
}
func mp08ExpectBlocked(t *testing.T, p MP08FinalizationPlan, h *mp08FakeHost, expected error) {
	t.Helper()
	receipt, err := mp08Run(t, p, h)
	if !errors.Is(err, expected) || receipt.DownloadReady || receipt.Status == "completed" {
		t.Fatalf("must fail closed err=%v receipt=%+v", err, receipt)
	}
}
func TestMP08MUX01ExactTwoPeriodDASHReady(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	if len(p.Tracks) != 4 || p.ExpectedDurationMS != 8000 || p.Tracks[2].PeriodID != "scene" {
		t.Fatalf("incorrect ordered plan %+v", p)
	}
}
func TestMP08MUX02FFprobeRequiredAudioVideoAndCompletePublish(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	receipt, err := mp08Run(t, p, h)
	if err != nil || !receipt.DownloadReady || receipt.Status != "completed" || h.assemble != 1 || h.probe != 1 || h.publish != 1 {
		t.Fatalf("not verified %+v err=%v", receipt, err)
	}
}
func TestMP08MUX03StagedReceiptCannotSelfCertify(t *testing.T) {
	r, f := mp07Fixture()
	v, a := mp07Stores(t)
	stage, _ := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	stage.DownloadReady = true
	if _, e := MP08DASHPlan(r, stage, v, a, nil, "media_one", "mp4"); !errors.Is(e, ErrMP08InvalidStage) {
		t.Fatal(e)
	}
}
func TestMP08MUX04SwappedPartReceiptRejected(t *testing.T) {
	r, f := mp07Fixture()
	v, a := mp07Stores(t)
	stage, _ := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	stage.Tracks[0].ArtifactRefs[0], stage.Tracks[1].ArtifactRefs[0] = stage.Tracks[1].ArtifactRefs[0], stage.Tracks[0].ArtifactRefs[0]
	if _, e := MP08DASHPlan(r, stage, v, a, nil, "media_one", "mp4"); !errors.Is(e, ErrMP08MissingProof) {
		t.Fatal(e)
	}
}
func TestMP08MUX05MissingAudioTrackFails(t *testing.T) {
	r, f := mp07Fixture()
	v, a := mp07Stores(t)
	stage, _ := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	stage.Tracks = stage.Tracks[:len(stage.Tracks)-1]
	if _, e := MP08DASHPlan(r, stage, v, a, nil, "media_one", "mp4"); !errors.Is(e, ErrMP08InvalidStage) {
		t.Fatal(e)
	}
}
func TestMP08MUX06CorruptedOnDiskFragmentBlockedBeforeMux(t *testing.T) {
	p, v, _ := mp08DASHFixture(t)
	rec := p.Tracks[0].Parts[0]
	path, _ := v.ReadVerified(rec.Identity)
	if len(path) == 0 {
		t.Fatal("empty fixture")
	}
	target := filepath.Join(v.root, rec.LocalArtifactRef)
	if err := os.WriteFile(target, []byte("tampered"), 0600); err != nil {
		t.Fatal(err)
	}
	h := mp08Host()
	mp08ExpectBlocked(t, p, h, ErrMP08MissingProof)
	if h.assemble != 0 {
		t.Fatal("FFmpeg ran before revalidation")
	}
}
func TestMP08MUX07NoAutomaticDynamicPublication(t *testing.T) {
	r, f := mp07Fixture()
	v, a := mp07Stores(t)
	r.MPDBody = strings.Replace(r.MPDBody, `type="static" mediaPresentationDuration="PT8S"`, `type="dynamic" minimumUpdatePeriod="PT2S"`, 1)
	r.DynamicPollBound = 1
	stage, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = MP08DASHPlan(r, stage, v, a, nil, "media_one", "mp4"); !errors.Is(e, ErrMP08InvalidStage) {
		t.Fatal("live published", e)
	}
}
func TestMP08MUX08MissingInitFragmentRejected(t *testing.T) {
	p, v, _ := mp08DASHFixture(t)
	if p.Tracks[0].Init == nil {
		t.Fatal("no init fixture")
	}
	target := filepath.Join(v.root, p.Tracks[0].Init.LocalArtifactRef)
	if err := os.Remove(target); err != nil {
		t.Fatal(err)
	}
	h := mp08Host()
	mp08ExpectBlocked(t, p, h, ErrMP08MissingProof)
}
func TestMP08MUX09UntrustedDestinationAndContainerRejected(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	p.DestinationKey = "../escape"
	mp08ExpectBlocked(t, p, mp08Host(), ErrMP08InvalidStage)
	p.DestinationKey = "media_one"
	p.Container = "exe"
	mp08ExpectBlocked(t, p, mp08Host(), ErrMP08InvalidStage)
}
func TestMP08MUX10ProbeSilentVideoFailsClosed(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.missingAudio = true
	mp08ExpectBlocked(t, p, h, ErrMP08Probe)
	if h.publish != 0 {
		t.Fatal("published missing audio")
	}
}
func TestMP08MUX11AVDurationAndContainerMismatch(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.wrongDuration = true
	mp08ExpectBlocked(t, p, h, ErrMP08Probe)
	h = mp08Host()
	h.wrongContainer = true
	mp08ExpectBlocked(t, p, h, ErrMP08Probe)
}
func TestMP08MUX12NoUnverifiedOrphanTranscript(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.failStageRead = true
	mp08ExpectBlocked(t, p, h, ErrMP08Publication)
	if h.probe != 0 || h.publish != 0 {
		t.Fatal("probe/publish after missing staged bytes")
	}
}
func TestMP08PUB01FFmpegFailureNeverPublishes(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.failMux = true
	mp08ExpectBlocked(t, p, h, ErrMP08Publication)
	if h.publish != 0 {
		t.Fatal("published failure")
	}
}
func TestMP08PUB02ProbeFailureNeverPublishes(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.failProbe = true
	mp08ExpectBlocked(t, p, h, ErrMP08Probe)
	if h.publish != 0 {
		t.Fatal("published unprobed")
	}
}
func TestMP08PUB03ENOSPCFailClosed(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.failPublish = true
	mp08ExpectBlocked(t, p, h, ErrMP08Publication)
}
func TestMP08PUB04NonAtomicPublishRejected(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.notAtomic = true
	mp08ExpectBlocked(t, p, h, ErrMP08Publication)
}
func TestMP08PUB05PostPublishByteCorruptionRejected(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.published[0] = 'X'
	mp08ExpectBlocked(t, p, h, ErrMP08Publication)
}
func TestMP08PUB06SwappedPublishHashRejected(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.swappedDigest = true
	mp08ExpectBlocked(t, p, h, ErrMP08Publication)
}
func TestMP08PUB07CrashBeforeReadbackDoesNotClaimComplete(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	h := mp08Host()
	h.failPublishedRead = true
	mp08ExpectBlocked(t, p, h, ErrMP08Publication)
}
func TestMP08PUB08PartialSalvageRequiresSeparateUserAction(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	p.Partial = true
	h := mp08Host()
	receipt, err := RunMP08PartialRecovery(context.Background(), p, h, false)
	if !errors.Is(err, ErrMP08PartialConsent) || receipt.DownloadReady || h.publish != 0 {
		t.Fatal("unauthorized salvage")
	}
	receipt, err = RunMP08PartialRecovery(context.Background(), p, h, true)
	if !errors.Is(err, ErrMP08PartialConsent) || receipt.DownloadReady || h.publish != 0 {
		t.Fatal("unqualified salvage")
	}
}
func mp08HLSFixture(t *testing.T) (MP08FinalizationPlan, *FileFragmentStore) {
	t.Helper()
	req := HLSVODRequest{
		MasterURL:         "https://cdn.example/vod/master.m3u8",
		MasterBody:        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nvideo.m3u8\n",
		VideoURI:          "https://cdn.example/vod/video.m3u8",
		VideoBody:         "#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-MEDIA-SEQUENCE:1\n#EXTINF:8,\nv1.ts\n#EXT-X-ENDLIST\n",
		AttemptGeneration: 1,
	}
	store, err := NewFileFragmentStore(filepath.Join(t.TempDir(), "hls"), 8<<20)
	if err != nil {
		t.Fatal(err)
	}
	list, err := ParseHLSPlaylist(req.VideoURI, req.VideoBody)
	if err != nil {
		t.Fatal(err)
	}
	identity, err := HLSTimelineIdentity(list.Segments[0])
	if err != nil {
		t.Fatal(err)
	}
	record, err := store.WriteAndCommitFragment(context.Background(), FragmentRecord{Identity: identity, Role: "media", AttemptGeneration: 1}, []byte("hls-fragment"))
	if err != nil {
		t.Fatal(err)
	}
	stage := HLSVODSessionReceipt{SchemaVersion: HLSVODSchemaV1, Status: "staged", ReadyForMux: true,
		Tracks: []HLSVODTrackReceipt{{Role: "video", Status: "staged", NonGapExpected: 1, DurableCount: 1, ArtifactRefs: []string{record.LocalArtifactRef}}}}
	p, err := MP08HLSPlan(req, stage, store, nil, "hls_one", "mp4")
	if err != nil {
		t.Fatal(err)
	}
	return p, store
}
func TestMP08MUX13HLSVerifiedTrackReattached(t *testing.T) {
	p, _ := mp08HLSFixture(t)
	if p.Source != "hls_vod" || len(p.Tracks) != 1 || p.RequireAudio || p.ExpectedDurationMS != 8000 {
		t.Fatal("bad HLS handoff", p)
	}
	h := mp08Host()
	_, err := RunMP08VerifiedPublication(context.Background(), p, h)
	if err != nil {
		t.Fatal(err)
	}
}
func TestMP08MUX14HLSStaleOrReplacedPartNeverPromoted(t *testing.T) {
	p, store := mp08HLSFixture(t)
	rec := p.Tracks[0].Parts[0]
	target := filepath.Join(store.root, rec.LocalArtifactRef)
	if err := os.WriteFile(target, []byte("different bytes"), 0600); err != nil {
		t.Fatal(err)
	}
	h := mp08Host()
	mp08ExpectBlocked(t, p, h, ErrMP08MissingProof)
}
func TestMP08MUX15MissingInitForPartNeverPublished(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	if p.Tracks[0].Init == nil {
		t.Fatal("fixture missing init")
	}
	p.Tracks[0].InitForPart[0] = nil
	// Simulate an internal buggy constructor resealing this broken graph:
	// the independent init-per-part validation must still reject it.
	p.seal = mp08PlanSeal(p)
	h := mp08Host()
	mp08ExpectBlocked(t, p, h, ErrMP08MissingProof)
	if h.assemble != 0 {
		t.Fatal("host executed before full init validation")
	}
}
func TestMP08MUX16ForgedUnsealedGraphRejected(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	p.seal = ""
	h := mp08Host()
	mp08ExpectBlocked(t, p, h, ErrMP08InvalidStage)
	if h.assemble != 0 {
		t.Fatal("host ran on unsealed plan")
	}
}
func TestMP08MUX17MutatedGraphAfterApprovalRejected(t *testing.T) {
	p, _, _ := mp08DASHFixture(t)
	p.Tracks[0].Role = "audio"
	h := mp08Host()
	mp08ExpectBlocked(t, p, h, ErrMP08InvalidStage)
	if h.assemble != 0 {
		t.Fatal("host ran on mutated plan")
	}
}

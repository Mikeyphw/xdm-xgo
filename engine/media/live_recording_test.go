package media

import (
	"context"
	"errors"
	"io"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

type mp09Feed struct {
	manifests []string
	next      int
	segments  map[string][]byte
	fail      bool
}

func (f *mp09Feed) FetchHLS(_ context.Context, r HLSFetchRequest) (HLSFetchResponse, error) {
	if f.fail {
		return HLSFetchResponse{}, errors.New("offline")
	}
	if r.Kind == HLSFetchManifest {
		n := f.next
		if n >= len(f.manifests) {
			n = len(f.manifests) - 1
		}
		f.next++
		if n < 0 {
			return HLSFetchResponse{}, errors.New("empty")
		}
		return HLSFetchResponse{Bytes: []byte(f.manifests[n])}, nil
	}
	b, ok := f.segments[r.URI]
	if !ok {
		return HLSFetchResponse{}, errors.New("missing segment")
	}
	return HLSFetchResponse{Bytes: append([]byte(nil), b...)}, nil
}
func mp09Fixture(t *testing.T) (*MP09Recording, *FileFragmentStore, *FileFragmentStore, time.Time, *mp09Feed, *mp09Feed) {
	t.Helper()
	now := time.Date(2026, 11, 11, 12, 0, 0, 0, time.UTC)
	session, e := NewLiveSession("live_test", 1, now, LiveSessionPolicy{IdleTimeout: time.Minute, PollTimeout: 5 * time.Second, SourceDVRCapable: true})
	if e != nil {
		t.Fatal(e)
	}
	playlist := func(path string) string {
		return "#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:1\n#EXTINF:2,\n" + path + "1.ts\n#EXTINF:2,\n" + path + "2.ts\n"
	}
	v := &mp09Feed{manifests: []string{playlist("v")}, segments: map[string][]byte{"https://media.example/v1.ts": []byte(strings.Repeat("video1", 200)), "https://media.example/v2.ts": []byte(strings.Repeat("video2", 200))}}
	a := &mp09Feed{manifests: []string{playlist("a")}, segments: map[string][]byte{"https://media.example/a1.ts": []byte(strings.Repeat("audio1", 200)), "https://media.example/a2.ts": []byte(strings.Repeat("audio2", 200))}}
	vs, e := NewFileFragmentStore(filepath.Join(t.TempDir(), "video"), 8<<20)
	if e != nil {
		t.Fatal(e)
	}
	as, e := NewFileFragmentStore(filepath.Join(t.TempDir(), "audio"), 8<<20)
	if e != nil {
		t.Fatal(e)
	}
	ve, e := NewLivePollEngine(session, vs, v, nil, LivePollSpec{Protocol: FragmentProtocolHLS, ManifestURL: "https://media.example/stream-v.m3u8"})
	if e != nil {
		t.Fatal(e)
	}
	ae, e := NewLivePollEngine(session, as, a, nil, LivePollSpec{Protocol: FragmentProtocolHLS, ManifestURL: "https://media.example/stream-a.m3u8"})
	if e != nil {
		t.Fatal(e)
	}
	rr, e := NewMP09Recording(session, true, MP09TrackBinding{"video", ve, vs}, MP09TrackBinding{"audio", ae, as})
	if e != nil {
		t.Fatal(e)
	}
	return rr, vs, as, now, v, a
}
func TestMP09ConsolidatedMultiTrackRealDurable(t *testing.T) {
	r, v, a, now, _, _ := mp09Fixture(t)
	s, e := r.PollDue(context.Background(), now)
	if e != nil {
		t.Fatal(e)
	}
	if s.TrackCount != 2 || s.DurableFragments != 4 || s.DownloadReady || s.Published || len(v.CommittedRecords()) != 2 || len(a.CommittedRecords()) != 2 {
		t.Fatalf("not durable %+v", s)
	}
	s, e = r.PollDue(context.Background(), now.Add(time.Second))
	if e != nil {
		t.Fatal(e)
	}
	if s.DurableFragments != 4 {
		t.Fatal("double count", s)
	}
	if _, e = r.Stop(now.Add(3 * time.Second)); e != nil {
		t.Fatal(e)
	}
	plan, e := mp09LiveMP08Plan(r.tracks, true, "live_target", 4*time.Second)
	if e != nil || plan.Source != "hls_live" || !plan.validated || len(plan.Tracks) != 2 || len(plan.Tracks[0].Parts) != 2 {
		t.Fatalf("bad sealed plan %+v %v", plan, e)
	}
	if _, e := r.PollDue(context.Background(), now.Add(4*time.Second)); !errors.Is(e, ErrLiveSessionState) {
		t.Fatal("poll after stop", e)
	}
}
func TestMP09ConsolidatedNoImplicitTimeoutAndRecovery(t *testing.T) {
	r, _, _, now, v, a := mp09Fixture(t)
	_, e := r.PollDue(context.Background(), now)
	if e != nil {
		t.Fatal(e)
	}
	v.fail = true
	a.fail = true
	_, e = r.PollDue(context.Background(), now.Add(13*time.Hour))
	if e == nil {
		t.Fatal("network outage should be recoverable, not completion")
	}
	s, _ := r.session.Snapshot()
	if s.State != LiveSessionRecoverable || s.DownloadReady || s.UserBoundReached {
		t.Fatal(s)
	}
	v.fail = false
	a.fail = false
	_, e = r.PollDue(context.Background(), now.Add(13*time.Hour+time.Minute))
	if e != nil {
		t.Fatal(e)
	}
	s, _ = r.session.Snapshot()
	if s.State != LiveSessionCapturing || s.DurableFragments != 4 {
		t.Fatal(s)
	}
}
func TestMP09ConsolidatedPauseResumeAndNoDVR(t *testing.T) {
	r, _, _, now, _, _ := mp09Fixture(t)
	if e := r.Pause(now); e != nil {
		t.Fatal(e)
	}
	s, e := r.PollDue(context.Background(), now.Add(12*time.Hour))
	if e != nil || s.State != LiveSessionPaused {
		t.Fatal(s, e)
	}
	if e := r.Resume(now.Add(12 * time.Hour)); e != nil {
		t.Fatal(e)
	}
	if _, e := r.PollDue(context.Background(), now.Add(12*time.Hour)); e != nil {
		t.Fatal(e)
	}
	snapshot, _ := r.session.Snapshot()
	if snapshot.UserBoundReached || snapshot.DownloadReady {
		t.Fatal(snapshot)
	}
}
func TestMP09ConsolidatedStopRequiresVerifiedMedia(t *testing.T) {
	r, _, _, now, _, _ := mp09Fixture(t)
	if _, e := r.Stop(now); !errors.Is(e, ErrLiveSessionNoMedia) {
		t.Fatal(e)
	}
	if _, e := r.Finalize(context.Background(), "bad", time.Second, nil); !errors.Is(e, ErrMP09NotReady) {
		t.Fatal(e)
	}
}
func TestMP09ConsolidatedFailClosedMissingAudioOrGap(t *testing.T) {
	r, v, a, now, _, _ := mp09Fixture(t)
	if _, e := r.PollDue(context.Background(), now); e != nil {
		t.Fatal(e)
	}
	if e := r.session.MarkGap(now); e != nil {
		t.Fatal(e)
	}
	if _, e := r.Stop(now.Add(time.Second)); e != nil {
		t.Fatal(e)
	}
	if _, e := mp09LiveMP08Plan(r.tracks, true, "target", 4*time.Second); e != nil {
		t.Fatal("planning independent of session gap", e)
	}
	if _, e := r.Finalize(context.Background(), "target", 4*time.Second, mp09RejectHost{}); !errors.Is(e, ErrMP09Partial) {
		t.Fatal(e)
	}
	_ = v
	_ = a
}

// Host is deliberately non-publishing; any attempted finalization must fail
// closed rather than fabricating a DownloadReady receipt.
type mp09RejectHost struct{}

func (mp09RejectHost) Assemble(context.Context, MP08FinalizationPlan) (MP08StagedOutput, error) {
	return MP08StagedOutput{}, ErrMP08Publication
}
func (mp09RejectHost) Probe(context.Context, MP08StagedOutput) (FFProbeReport, error) {
	return FFProbeReport{}, ErrMP08Probe
}
func (mp09RejectHost) ReadStaged(context.Context, MP08StagedOutput) (io.ReadCloser, error) {
	return nil, ErrMP08Publication
}
func (mp09RejectHost) PublishAtomic(context.Context, MP08StagedOutput, string) (MP08PublishedOutput, error) {
	return MP08PublishedOutput{}, ErrMP08Publication
}
func (mp09RejectHost) ReadPublished(context.Context, MP08PublishedOutput) (io.ReadCloser, error) {
	return nil, ErrMP08Publication
}
func TestMP09ConsolidatedNeverClaimsReadyBeforeHost(t *testing.T) {
	r, _, _, now, _, _ := mp09Fixture(t)
	_, e := r.PollDue(context.Background(), now)
	if e != nil {
		t.Fatal(e)
	}
	_, e = r.Stop(now.Add(4 * time.Second))
	if e != nil {
		t.Fatal(e)
	}
	got, e := r.Finalize(context.Background(), "target", 4*time.Second, mp09RejectHost{})
	if e == nil || got.DownloadReady || got.Status == "completed" {
		t.Fatal(got, e)
	}
}
func TestMP09ConsolidatedSafeReceiptSchema(t *testing.T) {
	r, _, _, now, _, _ := mp09Fixture(t)
	s, e := r.PollDue(context.Background(), now)
	if e != nil {
		t.Fatal(e)
	}
	fields := reflect.TypeOf(s)
	for i := 0; i < fields.NumField(); i++ {
		name := strings.ToLower(fields.Field(i).Name)
		for _, bad := range []string{"url", "cookie", "token", "header", "credential", "path", "hash"} {
			if strings.Contains(name, bad) {
				t.Fatal(name)
			}
		}
	}
	if s.DownloadReady || s.Published {
		t.Fatal(s)
	}
}
func TestMP09ConsolidatedStrictSequenceSort(t *testing.T) {
	if !mp09Earlier("hls:1:9", "hls:1:10") || mp09Earlier("hls:1:11", "hls:1:10") {
		t.Fatal("bad numeric sort")
	}
	a := []FragmentRecord{{Identity: FragmentIdentity{TimelineKey: "hls:0:9"}}, {Identity: FragmentIdentity{TimelineKey: "hls:0:11"}}}
	if !errors.Is(mp09Continuous(a), ErrMP09Partial) {
		t.Fatal("gap accepted")
	}
}

// A mux, probe, or MediaStore failure must never strand recorded fragments.
// The user can explicitly retry Stop & Save or discard after reviewing failure.
type mp09DiscardProbe struct {
	fail  bool
	calls int
}

func (p *mp09DiscardProbe) DiscardAndVerify(_ context.Context, records []FragmentRecord) error {
	p.calls++
	if len(records) != 4 || p.fail {
		return ErrMP09Cleanup
	}
	return nil
}
func TestMP09ConsolidatedFailedSaveRetryAndExplicitDiscard(t *testing.T) {
	r, _, _, now, _, _ := mp09Fixture(t)
	if _, e := r.PollDue(context.Background(), now); e != nil {
		t.Fatal(e)
	}
	if _, e := r.Stop(now.Add(4 * time.Second)); e != nil {
		t.Fatal(e)
	}
	if _, e := r.Finalize(context.Background(), "target", 4*time.Second, mp09RejectHost{}); !errors.Is(e, ErrMP08Publication) {
		t.Fatalf("expected unverified host rejection: %v", e)
	}
	if _, e := r.Stop(now.Add(5 * time.Second)); e != nil {
		t.Fatalf("stop retry blocked: %v", e)
	}
	cleaner := &mp09DiscardProbe{fail: true}
	if _, e := r.Cancel(context.Background(), now.Add(6*time.Second), cleaner); !errors.Is(e, ErrMP09Cleanup) {
		t.Fatalf("failed cleanup should remain pending: %v", e)
	}
	cleaner.fail = false
	out, e := r.Cancel(context.Background(), now.Add(7*time.Second), cleaner)
	if e != nil || out.DownloadReady || out.Published || cleaner.calls != 2 {
		t.Fatalf("explicit cleanup retry failed: %+v %v calls=%d", out, e, cleaner.calls)
	}
	if _, e := r.Stop(now.Add(8 * time.Second)); !errors.Is(e, ErrLiveSessionState) {
		t.Fatalf("discarded media reopened: %v", e)
	}
}
func TestMP09ConsolidatedEndedSourcesStillRequireUserSave(t *testing.T) {
	r, _, _, now, video, audio := mp09Fixture(t)
	video.manifests[0] += "#EXT-X-ENDLIST\n"
	audio.manifests[0] += "#EXT-X-ENDLIST\n"
	status, e := r.PollDue(context.Background(), now)
	if e != nil || !status.AllTracksEnded || status.DownloadReady || status.Published {
		t.Fatalf("ended source must await explicit save: %+v %v", status, e)
	}
}

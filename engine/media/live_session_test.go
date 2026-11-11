package media

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

type mp09StubStore struct{ verifyErr error }

func (s mp09StubStore) VerifyCommitted(FragmentRecord) error { return s.verifyErr }

// The session never calls WriteAndCommitFragment. Only MP05 may write bytes.
func (s mp09StubStore) WriteAndCommitFragment(_ context.Context, _ FragmentRecord, _ []byte) (FragmentRecord, error) {
	return FragmentRecord{}, errors.New("not implemented")
}

func mp09Start(t *testing.T, p LiveSessionPolicy) (*LiveSession, time.Time) {
	t.Helper()
	now := time.Date(2026, 11, 11, 0, 0, 0, 0, time.UTC)
	s, err := NewLiveSession("mp09_test", 1, now, p)
	if err != nil {
		t.Fatal(err)
	}
	return s, now
}
func mp09Record(t *testing.T, gen int64, key string) FragmentRecord {
	t.Helper()
	id := FragmentIdentity{Protocol: FragmentProtocolHLS, TimelineKey: key, ResourceID: "opaque-resource"}
	name, err := FragmentID(id)
	if err != nil {
		t.Fatal(err)
	}
	return FragmentRecord{ID: name, Identity: id, Role: "video", State: FragmentCommitted, ExpectedLength: 512,
		Hash: "sha256:" + strings.Repeat("a", 64), AttemptGeneration: gen, LocalArtifactRef: "parts/" + name + ".part", DurableBytesWritten: true}
}
func mp09Add(t *testing.T, s *LiveSession, now time.Time, key string) {
	t.Helper()
	if err := s.ObserveCommitted(now, mp09StubStore{}, mp09Record(t, 1, key)); err != nil {
		t.Fatal(err)
	}
}

func TestMP09NoImplicitWallClockTimeout(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{IdleTimeout: 5 * time.Second, PollTimeout: 2 * time.Second})
	for _, delta := range []time.Duration{11 * time.Minute, 12 * time.Minute, 2 * time.Hour, 13 * time.Hour} {
		state, err := s.Tick(now.Add(delta))
		if err != nil {
			t.Fatal(err)
		}
		if state.State != LiveSessionRecoverable || state.DownloadReady || state.UserBoundReached {
			t.Fatalf("implicit bound: %+v", state)
		}
	}
}
func TestMP09UserDurationOnly(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{UserMaxDuration: 11 * time.Minute})
	r, _ := s.Tick(now.Add(10 * time.Minute))
	if r.State != LiveSessionCapturing {
		t.Fatal(r)
	}
	r, _ = s.Tick(now.Add(11 * time.Minute))
	if r.State != LiveSessionStopPending || !r.UserBoundReached || r.DownloadReady {
		t.Fatal(r)
	}
}
func TestMP09UserBytesOnly(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{UserMaxDurableBytes: 1024})
	mp09Add(t, s, now.Add(time.Second), "seg-1")
	mp09Add(t, s, now.Add(2*time.Second), "seg-2")
	r, _ := s.Snapshot()
	if r.DurableFragments != 2 || r.DurableBytes != 1024 || r.State != LiveSessionStopPending || !r.UserBoundReached {
		t.Fatal(r)
	}
}
func TestMP09DurableStoreMandatory(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	rec := mp09Record(t, 1, "seg-1")
	if !errors.Is(s.ObserveCommitted(now, nil, rec), ErrLiveSessionDurability) {
		t.Fatal("nil store accepted")
	}
	if !errors.Is(s.ObserveCommitted(now, mp09StubStore{verifyErr: errors.New("bad bytes")}, rec), ErrLiveSessionDurability) {
		t.Fatal("bad readback accepted")
	}
	r, _ := s.Snapshot()
	if r.DurableBytes != 0 {
		t.Fatal(r)
	}
}
func TestMP09RejectsStaleGenerationAndBadHash(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	rec := mp09Record(t, 2, "seg-1")
	if !errors.Is(s.ObserveCommitted(now, mp09StubStore{}, rec), ErrLiveSessionGeneration) {
		t.Fatal("stale accepted")
	}
	rec = mp09Record(t, 1, "seg-1")
	rec.Hash = "sha256:" + strings.Repeat("Z", 64)
	if !errors.Is(s.ObserveCommitted(now, mp09StubStore{}, rec), ErrLiveSessionDurability) {
		t.Fatal("bad hash accepted")
	}
	rec = mp09Record(t, 1, "seg-1")
	rec.ID = "wrong"
	if !errors.Is(s.ObserveCommitted(now, mp09StubStore{}, rec), ErrLiveSessionDurability) {
		t.Fatal("identity mismatch accepted")
	}
}
func TestMP09ReplayIdempotentAndConflictFailClosed(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	rec := mp09Record(t, 1, "seg-1")
	if err := s.ObserveCommitted(now, mp09StubStore{}, rec); err != nil {
		t.Fatal(err)
	}
	if err := s.ObserveCommitted(now, mp09StubStore{}, rec); err != nil {
		t.Fatal(err)
	}
	bad := rec
	bad.ExpectedLength++
	if !errors.Is(s.ObserveCommitted(now, mp09StubStore{}, bad), ErrLiveSessionConflict) {
		t.Fatal("conflicting replay accepted")
	}
	r, _ := s.Snapshot()
	if r.DurableFragments != 1 || r.DurableBytes != 512 {
		t.Fatal(r)
	}
}
func TestMP09StopAndSaveDoesNotClaimPublication(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	if _, err := s.StopAndSave(now); !errors.Is(err, ErrLiveSessionNoMedia) {
		t.Fatal("empty stop accepted")
	}
	mp09Add(t, s, now.Add(time.Second), "seg-1")
	r, err := s.StopAndSave(now.Add(2 * time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if r.State != LiveSessionStopPending || !r.MuxVerificationRequired || r.DownloadReady || r.Published {
		t.Fatal(r)
	}
	if err := s.ObserveCommitted(now.Add(3*time.Second), mp09StubStore{}, mp09Record(t, 1, "seg-2")); !errors.Is(err, ErrLiveSessionState) {
		t.Fatal("continued after stop")
	}
}
func TestMP09ExplicitGapRequiresPartialReview(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	mp09Add(t, s, now.Add(time.Second), "seg-1")
	if err := s.MarkGap(now.Add(2 * time.Second)); err != nil {
		t.Fatal(err)
	}
	r, err := s.StopAndSave(now.Add(3 * time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if !r.HasGaps || !r.PartialReviewRequired || r.DownloadReady {
		t.Fatal(r)
	}
}
func TestMP09PauseRequiresDVR(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	if !errors.Is(s.Pause(now), ErrLiveSessionNoDVR) {
		t.Fatal("non-DVR pause accepted")
	}
}
func TestMP09DVRPauseResume(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{SourceDVRCapable: true, IdleTimeout: time.Second})
	if err := s.Pause(now.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	r, _ := s.Tick(now.Add(2 * time.Hour))
	if r.State != LiveSessionPaused {
		t.Fatal(r)
	}
	if err := s.Resume(now.Add(2 * time.Hour)); err != nil {
		t.Fatal(err)
	}
	r, _ = s.Tick(now.Add(2*time.Hour + time.Millisecond))
	if r.State != LiveSessionCapturing {
		t.Fatal(r)
	}
}
func TestMP09NetworkFailureRecoverable(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	if err := s.NetworkFailure(now.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
	r, _ := s.Snapshot()
	if r.State != LiveSessionRecoverable || r.DownloadReady {
		t.Fatal(r)
	}
	if err := s.Resume(now.Add(10 * time.Minute)); err != nil {
		t.Fatal(err)
	}
	if err := s.NetworkFailure(now.Add(12 * time.Minute)); err != nil {
		t.Fatal(err)
	}
	mp09Add(t, s, now.Add(13*time.Minute), "seg-1")
	r, _ = s.Snapshot()
	if r.State != LiveSessionCapturing {
		t.Fatal(r)
	}
}
func TestMP09CancelRequiresActualCleanup(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	mp09Add(t, s, now.Add(time.Second), "seg-1")
	r, err := s.CancelAndDiscard(now.Add(2 * time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if r.State != LiveSessionCancelPending || !r.CleanupRequired || r.DownloadReady || r.Published {
		t.Fatal(r)
	}
	if _, err := s.StopAndSave(now.Add(3 * time.Second)); !errors.Is(err, ErrLiveSessionState) {
		t.Fatal("cancel bypass")
	}
}
func TestMP09ClockAndValidation(t *testing.T) {
	now := time.Now()
	for _, id := range []string{"", "bad/id", strings.Repeat("a", 97)} {
		if _, err := NewLiveSession(id, 1, now, LiveSessionPolicy{}); !errors.Is(err, ErrLiveSessionInvalid) {
			t.Fatalf("bad id %q", id)
		}
	}
	if _, err := NewLiveSession("valid", 0, now, LiveSessionPolicy{}); !errors.Is(err, ErrLiveSessionInvalid) {
		t.Fatal("bad generation")
	}
	if _, err := NewLiveSession("valid", 1, now, LiveSessionPolicy{UserMaxDuration: -time.Second}); !errors.Is(err, ErrLiveSessionInvalid) {
		t.Fatal("negative limit")
	}
	s, t0 := mp09Start(t, LiveSessionPolicy{})
	if _, err := s.Tick(t0.Add(-time.Second)); !errors.Is(err, ErrLiveSessionClock) {
		t.Fatal("backwards clock")
	}
}
func TestMP09NoLeakyReceiptOrFakeReadiness(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	mp09Add(t, s, now.Add(time.Second), "seg-1")
	r, _ := s.Snapshot()
	fields := reflect.TypeOf(r)
	for i := 0; i < fields.NumField(); i++ {
		name := strings.ToLower(fields.Field(i).Name)
		for _, secret := range []string{"url", "cookie", "token", "header", "credential", "artifact", "path"} {
			if strings.Contains(name, secret) {
				t.Fatal("secret field exposed", name)
			}
		}
	}
	if r.DownloadReady || r.Published {
		t.Fatal("premature qualified receipt")
	}
}
func TestMP09ConcurrentDuplicateDoesNotDoubleCount(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	rec := mp09Record(t, 1, "seg-1")
	var wg sync.WaitGroup
	errorsCh := make(chan error, 32)
	for i := 0; i < 32; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); errorsCh <- s.ObserveCommitted(now.Add(time.Second), mp09StubStore{}, rec) }()
	}
	wg.Wait()
	close(errorsCh)
	for err := range errorsCh {
		if err != nil {
			t.Fatal(err)
		}
	}
	r, _ := s.Snapshot()
	if r.DurableFragments != 1 || r.DurableBytes != 512 {
		t.Fatal(r)
	}
}

func TestMP09PollDeadlineIsRequestScoped(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{PollTimeout: time.Second})
	ctx, cancel, err := s.PollContext(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := ctx.Deadline(); !ok {
		t.Fatal("missing single-poll deadline")
	}
	cancel()
	r, _ := s.Tick(now.Add(10 * time.Hour))
	if r.State != LiveSessionCapturing || r.DownloadReady {
		t.Fatal("poll cancelled the recording", r)
	}
}

func TestMP09InitOnlyCannotClaimMedia(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{})
	rec := mp09Record(t, 1, "only-init")
	rec.Role = "init"
	if !errors.Is(s.ObserveCommitted(now, mp09StubStore{}, rec), ErrLiveSessionDurability) {
		t.Fatal("init map counted as playable media")
	}
	if _, err := s.StopAndSave(now); !errors.Is(err, ErrLiveSessionNoMedia) {
		t.Fatal("init-only stop accepted")
	}
}
func TestMP09EmptyUserBoundAllowsCleanup(t *testing.T) {
	s, now := mp09Start(t, LiveSessionPolicy{UserMaxDuration: time.Second})
	r, err := s.Tick(now.Add(time.Second))
	if err != nil || r.State != LiveSessionStopPending {
		t.Fatal(r, err)
	}
	if _, err = s.StopAndSave(now.Add(time.Second)); !errors.Is(err, ErrLiveSessionNoMedia) {
		t.Fatal("empty output staged")
	}
	r, err = s.CancelAndDiscard(now.Add(time.Second))
	if err != nil || r.State != LiveSessionCancelPending || !r.CleanupRequired {
		t.Fatal(r, err)
	}
}

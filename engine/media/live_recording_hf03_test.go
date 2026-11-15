package media

import (
    "context"
    "errors"
    "testing"
    "time"
)

// Regression: a live manifest may be reachable again without adding a new
// fragment. This still transitions out of recoverable once all tracks succeed.
func TestMP09HF03SuccessfulEmptyRefreshRecovers(t *testing.T) {
    r, _, _, now, video, audio := mp09Fixture(t)
    if _, err := r.PollDue(context.Background(), now); err != nil { t.Fatal(err) }
    video.fail, audio.fail = true, true
    if _, err := r.PollDue(context.Background(), now.Add(13*time.Hour)); err == nil {
        t.Fatal("expected recoverable source outage")
    }
    s, _ := r.session.Snapshot()
    if s.State != LiveSessionRecoverable || s.DownloadReady { t.Fatal("outage marked complete", s) }
    video.fail, audio.fail = false, false
    s1, err := r.PollDue(context.Background(), now.Add(13*time.Hour+time.Second))
    if err != nil || s1.State != LiveSessionRecoverable { t.Fatal("no due fresh poll may resume", s1, err) }
    s1, err = r.PollDue(context.Background(), now.Add(13*time.Hour+3*time.Second))
    if err != nil || s1.State != LiveSessionCapturing || s1.DurableFragments != 4 || s1.DownloadReady || s1.Published {
        t.Fatalf("fresh authorized refresh did not recover: %+v %v", s1, err)
    }
}

// A successful video poll must not cover up the audio rendition still failing.
func TestMP09HF03MixedTrackOutageRetainsRecoverable(t *testing.T) {
    r, _, _, now, video, audio := mp09Fixture(t)
    if _, err := r.PollDue(context.Background(), now); err != nil { t.Fatal(err) }
    video.fail, audio.fail = true, true
    _, err := r.PollDue(context.Background(), now.Add(13*time.Hour))
    if err == nil { t.Fatal("outage expected") }
    video.fail, audio.fail = false, true
    _, err = r.PollDue(context.Background(), now.Add(13*time.Hour+3*time.Second))
    if err == nil || !errors.Is(err, ErrLivePollFetch) { t.Fatal("audio failure hidden", err) }
    snap, _ := r.session.Snapshot()
    if snap.State != LiveSessionRecoverable || snap.DownloadReady { t.Fatalf("partial recovery hidden: %+v", snap) }
    audio.fail = false
    status, err := r.PollDue(context.Background(), now.Add(13*time.Hour+4*time.Second))
    if err != nil || status.State != LiveSessionRecoverable { t.Fatal("audio retry not yet due", status, err) }
    status, err = r.PollDue(context.Background(), now.Add(13*time.Hour+8*time.Second))
    if err != nil || status.State != LiveSessionCapturing || status.DownloadReady { t.Fatal("all tracks not recovered", status, err) }
}

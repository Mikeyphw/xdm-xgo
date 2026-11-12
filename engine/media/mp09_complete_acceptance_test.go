package media

// MP09 deterministic, bounded portions of the LIVE01-LIVE14 matrix. Genuine
// real-time >=12m, FFmpeg/FFprobe output and physical API36 are separate
// opt-in acceptance gates, never faked by advancing the mock clock here.
import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestMP09LIVE06NoImplicitElevenMinuteCap(t *testing.T) {
	r, _, _, now, _, _ := mp09Fixture(t)
	if _, e := r.PollDue(context.Background(), now); e != nil {
		t.Fatal(e)
	}
	status, e := r.PollDue(context.Background(), now.Add(12*time.Minute))
	if e != nil {
		t.Fatal(e)
	}
	if status.DownloadReady || status.Published || status.DurableFragments != 4 {
		t.Fatalf("12min live recording became complete or lost durable fragments: %+v", status)
	}
	if _, e := r.Stop(now.Add(12*time.Minute + time.Second)); e != nil {
		t.Fatal(e)
	}
}
func TestMP09LIVE07StopSaveMustNotInventPublishedBytes(t *testing.T) {
	r, _, _, now, _, _ := mp09Fixture(t)
	if _, e := r.PollDue(context.Background(), now); e != nil {
		t.Fatal(e)
	}
	if _, e := r.Stop(now.Add(4 * time.Second)); e != nil {
		t.Fatal(e)
	}
	receipt, e := r.Finalize(context.Background(), "live_asset", 4*time.Second, mp09RejectHost{})
	if !errors.Is(e, ErrMP08Publication) || receipt.DownloadReady {
		t.Fatalf("false completion %+v %v", receipt, e)
	}
}
func TestMP09LIVE08SeparateAudioMandatoryForSelectedOutput(t *testing.T) {
	r, _, _, now, _, _ := mp09Fixture(t)
	if _, e := r.PollDue(context.Background(), now); e != nil {
		t.Fatal(e)
	}
	if _, e := r.Stop(now.Add(4 * time.Second)); e != nil {
		t.Fatal(e)
	}
	r.tracks = r.tracks[:1] // synthetic missing audio; never a usable plan
	if _, e := mp09LiveMP08Plan(r.tracks, true, "asset", 4*time.Second); e == nil {
		t.Fatal("missing selected audio accepted")
	}
}
func TestMP09LIVE09ExplicitCancelAfterFailedSave(t *testing.T) {
	r, _, _, now, _, _ := mp09Fixture(t)
	if _, e := r.PollDue(context.Background(), now); e != nil {
		t.Fatal(e)
	}
	if _, e := r.Stop(now.Add(4 * time.Second)); e != nil {
		t.Fatal(e)
	}
	_, _ = r.Finalize(context.Background(), "asset", 4*time.Second, mp09RejectHost{})
	cleaner := &mp09DiscardProbe{}
	status, e := r.Cancel(context.Background(), now.Add(5*time.Second), cleaner)
	if e != nil || status.DownloadReady || status.Published || cleaner.calls != 1 {
		t.Fatalf("cleanup failed %+v %v", status, e)
	}
}
func TestMP09LIVE10EndlistStillRequiresUserSave(t *testing.T) {
	r, _, _, now, video, audio := mp09Fixture(t)
	video.manifests[0] += "#EXT-X-ENDLIST\n"
	audio.manifests[0] += "#EXT-X-ENDLIST\n"
	status, e := r.PollDue(context.Background(), now)
	if e != nil || !status.AllTracksEnded || status.DownloadReady {
		t.Fatalf("source end falsely completed %+v %v", status, e)
	}
}
func TestMP09LIVE11OfflineThenResumesWithoutUserDurationLimit(t *testing.T) {
	r, _, _, now, video, audio := mp09Fixture(t)
	if _, e := r.PollDue(context.Background(), now); e != nil {
		t.Fatal(e)
	}
	video.fail = true
	audio.fail = true
	if _, e := r.PollDue(context.Background(), now.Add(13*time.Hour)); e == nil {
		t.Fatal("unreachable source marked success")
	}
	video.fail = false
	audio.fail = false
	status, e := r.PollDue(context.Background(), now.Add(13*time.Hour+time.Minute))
	if e != nil || status.DownloadReady || status.DurableFragments != 4 {
		t.Fatalf("recovered stream invalid %+v %v", status, e)
	}
}

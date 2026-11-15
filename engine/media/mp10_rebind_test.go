package media

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"
	"time"
)

func mp10NewApprovedTracks(r *MP09Recording, video, audio *mp09Feed) []MP10RefreshCandidate {
	return []MP10RefreshCandidate{
		{Role: "video", ManifestURL: "https://media.example/stream-v.m3u8?token=NEW_SIGNED", HLS: video},
		{Role: "audio", ManifestURL: "https://media.example/stream-a.m3u8?token=NEW_SIGNED", HLS: audio},
	}
}
func TestMP10P02TwoTrackAuthorizedRefreshKeepsMP05Bytes(t *testing.T) {
	r, v, a, now, video, audio := mp09Fixture(t)
	if _, err := r.PollDue(context.Background(), now); err != nil {
		t.Fatal(err)
	}
	before, _ := r.session.Snapshot()
	if len(v.CommittedRecords()) != 2 || len(a.CommittedRecords()) != 2 {
		t.Fatal("no durable fixture")
	}
	tracks := mp10NewApprovedTracks(r, video, audio)
	if err := r.MP10Reauthorize(context.Background(), now.Add(time.Second), true,
		"https://media.example/master.m3u8?token=old", "https://media.example/master.m3u8?token=NEW_SIGNED", 1, tracks...); err != nil {
		t.Fatal(err)
	}
	after, _ := r.session.Snapshot()
	if before.DurableFragments != after.DurableFragments || before.DurableBytes != after.DurableBytes ||
		after.DownloadReady || after.Published || r.refreshGeneration != 1 {
		t.Fatal("refresh rewrote durability", before, after)
	}
	for _, tr := range r.tracks {
		if !strings.Contains(tr.poll.spec.ManifestURL, "token=NEW_SIGNED") {
			t.Fatal("not rebound", tr.role)
		}
	}
	if _, err := r.PollDue(context.Background(), now.Add(2*time.Second)); err != nil {
		t.Fatal("post-rebind poll", err)
	}
}
func TestMP10P02ChangedAudioTimelineQuarantinesBoth(t *testing.T) {
	r, v, a, now, video, _ := mp09Fixture(t)
	if _, err := r.PollDue(context.Background(), now); err != nil {
		t.Fatal(err)
	}
	badAudio := &mp09Feed{manifests: []string{"#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:900\n#EXTINF:2,\nforeign.ts\n"}}
	tracks := mp10NewApprovedTracks(r, video, badAudio)
	err := r.MP10Reauthorize(context.Background(), now.Add(time.Second), true,
		"https://media.example/master.m3u8?token=old", "https://media.example/master.m3u8?token=new", 1, tracks...)
	if !errors.Is(err, ErrMP10RefreshIdentity) {
		t.Fatal("changed audio accepted", err)
	}
	if r.refreshGeneration != 0 {
		t.Fatal("unauthorized generation updated")
	}
	for _, tr := range r.tracks {
		if strings.Contains(tr.poll.spec.ManifestURL, "token=new") {
			t.Fatal("partial two-track swap")
		}
	}
	if len(v.CommittedRecords()) != 2 || len(a.CommittedRecords()) != 2 {
		t.Fatal("quarantine deleted old media")
	}
}
func TestMP10P02StaleGenerationAndUnapprovedDenied(t *testing.T) {
	r, _, _, now, video, audio := mp09Fixture(t)
	if _, err := r.PollDue(context.Background(), now); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		approved bool
		gen      uint64
		old, new string
	}{
		{false, 1, "https://media.example/master.m3u8", "https://media.example/master.m3u8?sig=new"},
		{true, 0, "https://media.example/master.m3u8", "https://media.example/master.m3u8?sig=new"},
		{true, 1, "https://media.example/master.m3u8", "https://foreign.example/master.m3u8?sig=new"},
	}
	for _, c := range cases {
		err := r.MP10Reauthorize(context.Background(), now.Add(time.Second), c.approved, c.old, c.new, c.gen, mp10NewApprovedTracks(r, video, audio)...)
		if !errors.Is(err, ErrMP10RefreshIdentity) {
			t.Fatal("unauthorized rebind", c, err)
		}
	}
}
func TestMP10P02CorruptReadbackRefusesAndKeepsEvidence(t *testing.T) {
	r, v, _, now, video, audio := mp09Fixture(t)
	if _, err := r.PollDue(context.Background(), now); err != nil {
		t.Fatal(err)
	}
	rec := v.CommittedRecords()[0]
	path, err := v.fullPath(rec.LocalArtifactRef)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, []byte("poison"), 0600); err != nil {
		t.Fatal(err)
	}
	err = r.MP10Reauthorize(context.Background(), now.Add(time.Second), true,
		"https://media.example/master.m3u8", "https://media.example/master.m3u8?sig=new", 1, mp10NewApprovedTracks(r, video, audio)...)
	if !errors.Is(err, ErrMP10RefreshIdentity) {
		t.Fatal("corrupt committed readback accepted", err)
	}
	if _, err = os.Stat(path); err != nil {
		t.Fatal("corrupt evidence unexpectedly removed", err)
	}
}

func TestMP10P02DASHRotatedManifestAttestsSamePeriodAndMedia(t *testing.T) {
	session, store, now := mp09NewLive(t)
	feed := &mp09DASHLiveFeed{manifests: []string{mp09DASHManifest(1)}, objects: map[string][]byte{
		"https://live.example/dash/v1-1.m4s": []byte("dash-v1-1"),
		"https://live.example/dash/v1-2.m4s": []byte("dash-v1-2"),
	}}
	poll, err := NewLivePollEngine(session, store, nil, feed,
		LivePollSpec{Protocol: FragmentProtocolDASH, ManifestURL: "https://live.example/manifest.mpd", DASHRepresentationID: "v1"})
	if err != nil {
		t.Fatal(err)
	}
	record, err := NewMP09Recording(session, false, MP09TrackBinding{Role: "video", Poll: poll, Store: store})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = record.PollDue(context.Background(), now); err != nil {
		t.Fatal(err)
	}
	old, _ := session.Snapshot()
	fresh := &mp09DASHLiveFeed{manifests: []string{mp09DASHManifest(1)}}
	err = record.MP10Reauthorize(context.Background(), now.Add(time.Second), true,
		"https://live.example/master.mpd?x-amz-signature=one",
		"https://live.example/master.mpd?x-amz-signature=two", 1,
		MP10RefreshCandidate{Role: "video", ManifestURL: "https://live.example/manifest.mpd?x-amz-signature=two", DASH: fresh})
	if err != nil {
		t.Fatal("DASH same timeline should rebind", err)
	}
	got, _ := session.Snapshot()
	if got.DurableFragments != old.DurableFragments || got.DurableBytes != old.DurableBytes ||
		got.DownloadReady || got.Published {
		t.Fatal("DASH refresh changed durable state", got)
	}
}

func TestMP10P02DASHIncompatiblePeriodAndNoOverlapRemainQuarantined(t *testing.T) {
	session, store, now := mp09NewLive(t)
	feed := &mp09DASHLiveFeed{manifests: []string{mp09DASHManifest(1)}, objects: map[string][]byte{
		"https://live.example/dash/v1-1.m4s": []byte("dash-v1-1"),
		"https://live.example/dash/v1-2.m4s": []byte("dash-v1-2"),
	}}
	poll, err := NewLivePollEngine(session, store, nil, feed, LivePollSpec{Protocol: FragmentProtocolDASH, ManifestURL: "https://live.example/manifest.mpd", DASHRepresentationID: "v1"})
	if err != nil {
		t.Fatal(err)
	}
	rec, err := NewMP09Recording(session, false, MP09TrackBinding{Role: "video", Poll: poll, Store: store})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = rec.PollDue(context.Background(), now); err != nil {
		t.Fatal(err)
	}
	before, _ := session.Snapshot()
	for _, body := range []string{
		mp09DASHManifest(99),
		strings.Replace(mp09DASHManifest(1), `<Period id="p0">`, `<Period id="different">`, 1),
	} {
		fresh := &mp09DASHLiveFeed{manifests: []string{body}}
		err = rec.MP10Reauthorize(context.Background(), now.Add(time.Second), true,
			"https://live.example/master.mpd", "https://live.example/master.mpd?token=NEW", 1,
			MP10RefreshCandidate{Role: "video", ManifestURL: "https://live.example/manifest.mpd?token=NEW", DASH: fresh})
		if !errors.Is(err, ErrMP10RefreshIdentity) {
			t.Fatal("DASH incompatible timeline was accepted", err)
		}
		if rec.refreshGeneration != 0 || strings.Contains(poll.spec.ManifestURL, "token=NEW") {
			t.Fatal("DASH quarantined generation was mutated")
		}
	}
	after, _ := session.Snapshot()
	if before.DurableFragments != after.DurableFragments || before.DurableBytes != after.DurableBytes {
		t.Fatal("DASH quarantined fragments changed")
	}
}

// A poisoned historical fragment may be absent from the new sliding window;
// reauthorization must still reject instead of accepting a different overlap.
func TestMP10P02NonOverlappingCorruptAudioRefusesAndKeepsEvidence(t *testing.T) {
	r, _, audioStore, now, video, audio := mp09Fixture(t)
	if _, err := r.PollDue(context.Background(), now); err != nil {
		t.Fatal(err)
	}
	records := audioStore.CommittedRecords()
	if len(records) != 2 {
		t.Fatalf("fixture expected 2 audio fragments, got %d", len(records))
	}
	// The next manifest only overlaps a2.ts, while the poisoned a1.ts was
	// observed and committed in the prior session.
	bad := records[0]
	for _, record := range records {
		if strings.HasSuffix(record.Identity.TimelineKey, ":1") {
			bad = record
		}
	}
	path, err := audioStore.fullPath(bad.LocalArtifactRef)
	if err != nil {
		t.Fatal(err)
	}
	old, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	poisoned := append([]byte(nil), old...)
	poisoned[0] ^= 0x5a // same byte length; hash mismatch only
	if err := os.WriteFile(path, poisoned, 0600); err != nil {
		t.Fatal(err)
	}
	audio.manifests = []string{"#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:2\n#EXTINF:2,\na2.ts\n"}
	err = r.MP10Reauthorize(context.Background(), now.Add(time.Second), true,
		"https://media.example/master.m3u8", "https://media.example/master.m3u8?sig=new", 1,
		mp10NewApprovedTracks(r, video, audio)...)
	if !errors.Is(err, ErrMP10RefreshIdentity) {
		t.Fatal("hidden audio corruption accepted", err)
	}
	if r.refreshGeneration != 0 {
		t.Fatal("generation advanced after corrupt audio readback")
	}
	if actual, err := os.ReadFile(path); err != nil || !strings.EqualFold(string(actual), string(poisoned)) {
		t.Fatal("corrupt audio evidence deleted or mutated", err)
	}
}

package media

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type mp09HLSLiveFeed struct {
	objects   map[string][]byte
	manifests []string
	polls     int
	requests  map[string]int
	fail      bool
}

func (f *mp09HLSLiveFeed) FetchHLS(_ context.Context, r HLSFetchRequest) (HLSFetchResponse, error) {
	if f.requests == nil {
		f.requests = make(map[string]int)
	}
	f.requests[string(r.Kind)+" "+r.URI]++
	if f.fail {
		return HLSFetchResponse{}, errors.New("deliberate private-source failure")
	}
	if r.Kind == HLSFetchManifest {
		n := f.polls
		f.polls++
		if n >= len(f.manifests) {
			n = len(f.manifests) - 1
		}
		if n < 0 {
			return HLSFetchResponse{}, errors.New("no playlist")
		}
		return HLSFetchResponse{Bytes: []byte(f.manifests[n])}, nil
	}
	raw, ok := f.objects[r.URI]
	if !ok {
		return HLSFetchResponse{}, errors.New("fixture missing")
	}
	return HLSFetchResponse{Bytes: append([]byte(nil), raw...)}, nil
}
func mp09Playlist(start int, segments []string, gap bool) string {
	s := fmt.Sprintf("#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:%d\n", start)
	for i, part := range segments {
		if gap && i == 0 {
			s += "#EXT-X-GAP\n"
		}
		s += "#EXTINF:2,\n" + part + "\n"
	}
	return s
}
func mp09NewLive(t *testing.T) (*LiveSession, *FileFragmentStore, time.Time) {
	t.Helper()
	now := time.Date(2026, 11, 11, 0, 0, 0, 0, time.UTC)
	s, e := NewLiveSession("mp09_p02", 1, now, LiveSessionPolicy{IdleTimeout: 5 * time.Second, PollTimeout: time.Second})
	if e != nil {
		t.Fatal(e)
	}
	store, e := NewFileFragmentStore(filepath.Join(t.TempDir(), "private_fragments"), 8<<20)
	if e != nil {
		t.Fatal(e)
	}
	return s, store, now
}
func mp09EngineHLS(t *testing.T, s *LiveSession, store *FileFragmentStore, feed *mp09HLSLiveFeed) *LivePollEngine {
	t.Helper()
	e, err := NewLivePollEngine(s, store, feed, nil, LivePollSpec{Protocol: FragmentProtocolHLS, ManifestURL: "https://live.example/media/stream.m3u8", CredentialRef: "private-opaque-ref"})
	if err != nil {
		t.Fatal(err)
	}
	return e
}
func TestMP09P02HLSRealDurableSlidingWindowAndReplay(t *testing.T) {
	s, store, now := mp09NewLive(t)
	feed := &mp09HLSLiveFeed{manifests: []string{mp09Playlist(100, []string{"a.ts", "b.ts"}, false), mp09Playlist(101, []string{"b.ts", "c.ts"}, false)}, objects: map[string][]byte{
		"https://live.example/media/a.ts": []byte("segment-100"), "https://live.example/media/b.ts": []byte("segment-101"), "https://live.example/media/c.ts": []byte("segment-102")}}
	engine := mp09EngineHLS(t, s, store, feed)
	a, e := engine.Poll(context.Background(), now.Add(time.Second))
	if e != nil || a.NewDurableFragments != 2 || a.TotalDurableFragments != 2 || a.DownloadReady || a.Published {
		t.Fatalf("first %+v %v", a, e)
	}
	b, e := engine.Poll(context.Background(), now.Add(3*time.Second))
	if e != nil || b.NewDurableFragments != 1 || b.TotalDurableFragments != 3 || b.GapOrPartial || b.NextPollAfter != time.Second {
		t.Fatalf("second %+v %v", b, e)
	}
	if feed.requests["segment https://live.example/media/b.ts"] != 1 {
		t.Fatal("re-fetched durable duplicate")
	}
	if len(store.CommittedRecords()) != 3 {
		t.Fatal("expected three actual MP05 durable records")
	}
	if _, e = s.StopAndSave(now.Add(4 * time.Second)); e != nil {
		t.Fatal(e)
	}
	if _, e = engine.Poll(context.Background(), now.Add(5*time.Second)); !errors.Is(e, ErrLiveSessionState) {
		t.Fatal("polled after StopAndSave", e)
	}
}
func TestMP09P02HLSExplicitGapTriggersPartialReview(t *testing.T) {
	s, store, now := mp09NewLive(t)
	feed := &mp09HLSLiveFeed{manifests: []string{mp09Playlist(1, []string{"missing.ts", "b.ts"}, true)}, objects: map[string][]byte{"https://live.example/media/b.ts": []byte("segment-b")}}
	r, e := mp09EngineHLS(t, s, store, feed).Poll(context.Background(), now.Add(time.Second))
	if e != nil || r.NewDurableFragments != 1 || !r.GapOrPartial || r.Published {
		t.Fatalf("gap %+v %v", r, e)
	}
}
func TestMP09P02HLSLostWindowDeclaredPartial(t *testing.T) {
	s, store, now := mp09NewLive(t)
	feed := &mp09HLSLiveFeed{manifests: []string{mp09Playlist(1, []string{"a.ts"}, false), mp09Playlist(4, []string{"d.ts"}, false)}, objects: map[string][]byte{
		"https://live.example/media/a.ts": []byte("segment-a"), "https://live.example/media/d.ts": []byte("segment-d")}}
	engine := mp09EngineHLS(t, s, store, feed)
	if _, e := engine.Poll(context.Background(), now.Add(time.Second)); e != nil {
		t.Fatal(e)
	}
	r, e := engine.Poll(context.Background(), now.Add(3*time.Second))
	if e != nil || !r.GapOrPartial || r.TotalDurableFragments != 2 {
		t.Fatalf("lost-window %+v %v", r, e)
	}
}
func TestMP09P02HLSNetworkStallIsRecoverableWithoutLifetimeCutoff(t *testing.T) {
	s, store, now := mp09NewLive(t)
	feed := &mp09HLSLiveFeed{fail: true, manifests: []string{mp09Playlist(1, []string{"a.ts"}, false)}, objects: map[string][]byte{"https://live.example/media/a.ts": []byte("a")}}
	engine := mp09EngineHLS(t, s, store, feed)
	r, e := engine.Poll(context.Background(), now.Add(13*time.Hour))
	if !errors.Is(e, ErrLivePollFetch) || r.State != LiveSessionRecoverable || r.Published {
		t.Fatalf("stall %+v %v", r, e)
	}
	feed.fail = false
	r, e = engine.Poll(context.Background(), now.Add(13*time.Hour+time.Second))
	if e != nil || r.TotalDurableFragments != 1 || r.State != LiveSessionCapturing || r.Published {
		t.Fatalf("resume %+v %v", r, e)
	}
}
func TestMP09P02HLSNoMasterImplicitSelection(t *testing.T) {
	s, store, now := mp09NewLive(t)
	f := &mp09HLSLiveFeed{manifests: []string{"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000\nother.m3u8\n"}}
	_, e := mp09EngineHLS(t, s, store, f).Poll(context.Background(), now.Add(time.Second))
	if !errors.Is(e, ErrLivePollManifest) {
		t.Fatal("master silently selected", e)
	}
}
func TestMP09P02HLSMalformedAndOverlargeManifestRefused(t *testing.T) {
	for _, body := range []string{"not an m3u8", "", strings.Repeat("A", 2<<20+1)} {
		s, store, now := mp09NewLive(t)
		f := &mp09HLSLiveFeed{manifests: []string{body}}
		_, e := mp09EngineHLS(t, s, store, f).Poll(context.Background(), now.Add(time.Second))
		if !errors.Is(e, ErrLivePollManifest) {
			t.Fatal("invalid manifest accepted", e)
		}
	}
}
func TestMP09P02EmptyStoreAndUnsafeSelection(t *testing.T) {
	s, store, _ := mp09NewLive(t)
	if _, e := NewLivePollEngine(s, nil, &mp09HLSLiveFeed{}, nil, LivePollSpec{Protocol: FragmentProtocolHLS, ManifestURL: "https://live.example/a.m3u8"}); !errors.Is(e, ErrLivePollInvalid) {
		t.Fatal(e)
	}
	if _, e := NewLivePollEngine(s, store, nil, nil, LivePollSpec{Protocol: FragmentProtocolHLS, ManifestURL: "https://live.example/a.m3u8"}); !errors.Is(e, ErrLivePollSelection) {
		t.Fatal(e)
	}
	if _, e := NewLivePollEngine(s, store, &mp09HLSLiveFeed{}, nil, LivePollSpec{Protocol: FragmentProtocolHLS, ManifestURL: "file:///private"}); !errors.Is(e, ErrLivePollInvalid) {
		t.Fatal(e)
	}
	if _, e := NewLivePollEngine(s, store, nil, &mp09DASHLiveFeed{}, LivePollSpec{Protocol: FragmentProtocolDASH, ManifestURL: "https://live.example/d.mpd", DASHRepresentationID: ""}); !errors.Is(e, ErrLivePollSelection) {
		t.Fatal(e)
	}
}

type mp09DASHLiveFeed struct {
	objects   map[string][]byte
	manifests []string
	polls     int
	counts    map[string]int
	fail      bool
}

func (f *mp09DASHLiveFeed) FetchDASH(_ context.Context, r DASHFetchRequest) (DASHFetchResponse, error) {
	if f.counts == nil {
		f.counts = map[string]int{}
	}
	f.counts[string(r.Kind)+" "+r.URI]++
	if f.fail {
		return DASHFetchResponse{}, errors.New("private media unavailable")
	}
	if r.Kind == DASHFetchManifest {
		n := f.polls
		f.polls++
		if n >= len(f.manifests) {
			n = len(f.manifests) - 1
		}
		if n < 0 {
			return DASHFetchResponse{}, errors.New("missing mpd")
		}
		return DASHFetchResponse{Bytes: []byte(f.manifests[n])}, nil
	}
	b, ok := f.objects[r.URI]
	if !ok {
		return DASHFetchResponse{}, errors.New("missing segment")
	}
	return DASHFetchResponse{Bytes: append([]byte(nil), b...)}, nil
}
func mp09DASHManifest(start int) string {
	return fmt.Sprintf(`<MPD type="dynamic" minimumUpdatePeriod="PT2S"><BaseURL>https://live.example/dash/</BaseURL><Period id="p0"><AdaptationSet id="video" contentType="video" mimeType="video/mp4"><SegmentTemplate timescale="1" startNumber="%d" media="$RepresentationID$-$Number$.m4s"><SegmentTimeline><S t="%d" d="2" r="1"/></SegmentTimeline></SegmentTemplate><Representation id="v1" bandwidth="1000000"/><Representation id="v2" bandwidth="2000000"/></AdaptationSet></Period></MPD>`, start, (start-1)*2)
}
func TestMP09P02DASHRealDurableExplicitSelection(t *testing.T) {
	s, store, now := mp09NewLive(t)
	f := &mp09DASHLiveFeed{manifests: []string{mp09DASHManifest(1), mp09DASHManifest(2)}, objects: map[string][]byte{
		"https://live.example/dash/v1-1.m4s": []byte("v1-1"), "https://live.example/dash/v1-2.m4s": []byte("v1-2"), "https://live.example/dash/v1-3.m4s": []byte("v1-3")}}
	e, err := NewLivePollEngine(s, store, nil, f, LivePollSpec{Protocol: FragmentProtocolDASH, ManifestURL: "https://live.example/manifest.mpd", DASHRepresentationID: "v1"})
	if err != nil {
		t.Fatal(err)
	}
	r, err := e.Poll(context.Background(), now.Add(time.Second))
	if err != nil || r.NewDurableFragments != 2 || r.Published {
		t.Fatalf("dash first %+v %v", r, err)
	}
	r, err = e.Poll(context.Background(), now.Add(3*time.Second))
	if err != nil || r.TotalDurableFragments != 3 || r.GapOrPartial {
		t.Fatalf("dash second %+v %v", r, err)
	}
	if f.counts["media https://live.example/dash/v1-2.m4s"] != 1 || f.counts["media https://live.example/dash/v2-2.m4s"] != 0 {
		t.Fatal("wrong representation or duplicate fetch", f.counts)
	}
}
func TestMP09P02ReceiptHasNoSecrets(t *testing.T) {
	s, store, now := mp09NewLive(t)
	f := &mp09HLSLiveFeed{manifests: []string{mp09Playlist(1, []string{"a.ts"}, false)}, objects: map[string][]byte{"https://live.example/media/a.ts": []byte("secret-proof")}}
	e, err := NewLivePollEngine(s, store, f, nil, LivePollSpec{Protocol: FragmentProtocolHLS, ManifestURL: "https://live.example/media/stream.m3u8?token=SECRET", CredentialRef: "SENSITIVE_KEY"})
	if err != nil {
		t.Fatal(err)
	}
	// Input is not embedded in any exported report field, even when source fetch fails.
	r, err := e.Poll(context.Background(), now.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(fmt.Sprintf("%+v", r), "SECRET") || strings.Contains(fmt.Sprintf("%+v", r), "SENSITIVE") || r.DownloadReady || r.Published {
		t.Fatal("leaky or falsely qualified report")
	}
}

package runtime

import (
	"strings"
	"testing"
)

// LIVE12–14 are source-level and exact-binding acceptance only. They must not
// be mistaken for API36 or physical recordings/verified MediaStore publication.
func TestMP09LIVE12CrashRecoveryUsesSourceBoundOpaqueFingerprint(t *testing.T) {
	req := mp09LiveCommand{CaptureID: "capture1", Protocol: "dash", VideoURL: "https://media.example/live.mpd?sig=TOPSECRET",
		AudioURL: "https://media.example/live.mpd?sig=TOPSECRET", VideoRepresentationID: "v1080", AudioRepresentationID: "a-en", RequireAudio: true}
	root := "https://media.example/live.mpd?sig=TOPSECRET"
	fingerprint := mp09SourceBinding(root, req)
	if !strings.HasPrefix(fingerprint, "sha256:") || len(fingerprint) != 71 || strings.Contains(fingerprint, "TOPSECRET") {
		t.Fatal("non-opaque source fingerprint")
	}
	req.AudioRepresentationID = "other"
	if fingerprint == mp09SourceBinding(root, req) {
		t.Fatal("changed DASH representation reattached")
	}
}
func TestMP09LIVE13CrashRecoveryRejectsReauthorizedDifferentSource(t *testing.T) {
	req := mp09LiveCommand{CaptureID: "capture1", Protocol: "hls", VideoURL: "https://media.example/v.m3u8?s=1", AudioURL: "https://media.example/a.m3u8?s=1", RequireAudio: true}
	base := mp09SourceBinding("https://media.example/master.m3u8", req)
	for _, mutate := range []func(*mp09LiveCommand){
		func(r *mp09LiveCommand) { r.VideoURL = "https://other.example/v.m3u8" },
		func(r *mp09LiveCommand) { r.AudioURL = "https://media.example/a.m3u8?s=2" },
		func(r *mp09LiveCommand) { r.Protocol = "dash" },
		func(r *mp09LiveCommand) { r.VideoRepresentationID = "spoof" },
	} {
		other := req
		mutate(&other)
		if base == mp09SourceBinding("https://media.example/master.m3u8", other) {
			t.Fatal("source drift accepted")
		}
	}
}
func TestMP09LIVE14DASHRevisionAndNativeOptionGuard(t *testing.T) {
	for _, input := range []string{"", strings.Repeat("0", 63), strings.Repeat("G", 64), strings.Repeat("/", 64), strings.Repeat("a", 65)} {
		if mp09Hex64(input) {
			t.Fatalf("invalid revision accepted %q", input)
		}
	}
	if !mp09Hex64(strings.Repeat("a", 64)) {
		t.Fatal("valid revision rejected")
	}
}

// A signed-URL refresh must not break explicit authorized resume, while
// meaningful query, representation, path and origin changes must remain bound.
func TestMP09LIVE15SignedTokenRotationDoesNotOverrideSourceIdentity(t *testing.T) {
	req := mp09LiveCommand{CaptureID: "c", Protocol: "dash", VideoURL: "https://media.example/live.mpd?quality=high&sig=one", AudioURL: "https://media.example/live.mpd?quality=high&sig=one", VideoRepresentationID: "v1", AudioRepresentationID: "a1", RequireAudio: true}
	old := mp09SourceBinding("https://media.example/live.mpd?quality=high&sig=one", req)
	req.VideoURL = "https://media.example/live.mpd?sig=two&quality=high"
	req.AudioURL = req.VideoURL
	if old != mp09SourceBinding("https://media.example/live.mpd?quality=high&sig=three", req) {
		t.Fatal("renewed authorization changed stable binding")
	}
	req.AudioURL = "https://media.example/live.mpd?quality=low&sig=two"
	if old == mp09SourceBinding("https://media.example/live.mpd?quality=high&sig=three", req) {
		t.Fatal("meaningful query change accepted")
	}
	req.AudioURL = "https://media.example/live.mpd?quality=high&sig=two"
	req.AudioRepresentationID = "different"
	if old == mp09SourceBinding("https://media.example/live.mpd?quality=high&sig=three", req) {
		t.Fatal("raw representation drift accepted")
	}
}

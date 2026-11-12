package runtime

import (
	"context"
	"encoding/json"
	"github.com/subhra74/xdm/engine/runtime/platform"
	"strings"
	"testing"
	"time"
)

func TestMP09LIVE17PublicationFenceRefusesPostCrashRepublish(t *testing.T) {
	root := "https://media.example/master.m3u8?sig=fresh"
	req := mp09LiveCommand{CaptureID: "cap1", Protocol: "hls", VideoURL: "https://media.example/video.m3u8?sig=new", AudioURL: "https://media.example/audio.m3u8?sig=new", RequireAudio: true}
	for _, phase := range []string{"recording", "publishing", "published", "", "rewound"} {
		t.Run(phase, func(t *testing.T) {
			inv := &Invocation{handlers: map[string]func([]byte) Reply{
				string(platform.AndroidFragmentStore): func([]byte) Reply {
					row := mp09StoredSession{OK: true, Binding: mp09SourceBinding(root, req), StartedMS: time.Now().Add(-time.Minute).UnixMilli(), Generation: 1, Protocol: "hls", RequireAudio: true, Phase: phase}
					b, _ := json.Marshal(row)
					return Reply{OK: true, Payload: b}
				},
			}}
			_, err := mp09ReadSession(context.Background(), inv, "cap1", root, req, time.Now())
			if (err == nil) != (phase == "recording") {
				t.Fatalf("phase %q permitted resume=%v", phase, err == nil)
			}
		})
	}
}

func TestMP09LIVE18PublicationPhaseOnlyAdvancesAndStatusIsScoped(t *testing.T) {
	var called int
	inv := &Invocation{handlers: map[string]func([]byte) Reply{
		string(platform.AndroidFragmentStore): func(raw []byte) Reply {
			var q struct {
				Action  string `json:"action"`
				Capture string `json:"capture_id"`
				Phase   string `json:"phase"`
				Scope   bool   `json:"mp09_live"`
			}
			if json.Unmarshal(raw, &q) != nil || !q.Scope || q.Capture != "cap1" {
				t.Fatal("missing bounded session scope")
			}
			called++
			switch q.Action {
			case "session_phase":
				if q.Phase != "publishing" && q.Phase != "published" {
					t.Fatal("unexpected phase")
				}
				b, _ := json.Marshal(map[string]any{"ok": true, "phase": q.Phase})
				return Reply{OK: true, Payload: b}
			case "session_status":
				return Reply{OK: true, Payload: []byte(`{"ok":true,"phase":"publishing"}`)}
			default:
				t.Fatalf("unexpected action %q", q.Action)
			}
			return Reply{}
		},
	}}
	for _, phase := range []string{"recording", "missing", "", "untrusted"} {
		if err := mp09SetSessionPhase(context.Background(), inv, "cap1", phase); err == nil {
			t.Fatal("invalid phase sent")
		}
	}
	if called != 0 {
		t.Fatal("invalid phase touched store")
	}
	for _, phase := range []string{"publishing", "published"} {
		if err := mp09SetSessionPhase(context.Background(), inv, "cap1", phase); err != nil {
			t.Fatal(err)
		}
	}
	if phase, err := mp09InspectSession(context.Background(), inv, "cap1"); err != nil || phase != "publishing" {
		t.Fatalf("phase status %q %v", phase, err)
	}
	if called != 3 {
		t.Fatalf("expected two transitions + one status call, got %d", called)
	}
	spoof := &Invocation{handlers: map[string]func([]byte) Reply{
		string(platform.AndroidFragmentStore): func([]byte) Reply { return Reply{OK: true, Payload: []byte(`{"ok":true,"phase":"recording"}`)} }}}
	if err := mp09SetSessionPhase(context.Background(), spoof, "cap1", "published"); err == nil {
		t.Fatal("unconfirmed publication phase treated as durable")
	}

	if strings.Contains(mp09SourceBinding("https://media.example/master.m3u8?sig=SECRET", mp09LiveCommand{Protocol: "hls"}), "SECRET") {
		t.Fatal("source binding leaks token")
	}
}

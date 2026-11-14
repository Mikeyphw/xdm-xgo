package runtime

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/subhra74/xdm/engine/runtime/platform"
)

// Real platform.Broker + Invocation rather than a made-up Invocation.handlers
// map. Every request traverses the same correlated request/reply port as Go.
func mp09TestPlatformInvocation(t *testing.T, handle func(json.RawMessage) platform.Reply) (*Invocation, context.Context) {
	t.Helper()
	broker := platform.NewBroker(8)
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	t.Cleanup(func() { cancel(); broker.Shutdown() })
	go func() {
		for {
			req, err := broker.NextRequest(ctx)
			if err != nil {
				return
			}
			if req.Kind != platform.AndroidFragmentStore {
				t.Errorf("unexpected platform request kind: %s", req.Kind)
				_ = broker.Reply(platform.Reply{RequestID: req.ID, Session: req.Session, OK: false})
				continue
			}
			reply := handle(req.Payload)
			reply.RequestID = req.ID
			reply.Session = req.Session
			if err := broker.Reply(reply); err != nil && ctx.Err() == nil {
				t.Errorf("platform reply: %v", err)
			}
		}
	}()
	return &Invocation{engine: &Engine{broker: broker}, ctx: ctx}, ctx
}

func TestMP09LIVE17PublicationFenceRefusesPostCrashRepublish(t *testing.T) {
	root := "https://media.example/master.m3u8?sig=fresh"
	req := mp09LiveCommand{CaptureID: "cap1", Protocol: "hls", VideoURL: "https://media.example/video.m3u8?sig=new", AudioURL: "https://media.example/audio.m3u8?sig=new", RequireAudio: true}
	for _, phase := range []string{"recording", "publishing", "published", "", "rewound"} {
		t.Run(phase, func(t *testing.T) {
			inv, ctx := mp09TestPlatformInvocation(t, func(raw json.RawMessage) platform.Reply {
				var request struct {
					Action  string `json:"action"`
					Capture string `json:"capture_id"`
					MP09    bool   `json:"mp09_live"`
				}
				if err := json.Unmarshal(raw, &request); err != nil || request.Action != "session_read" || request.Capture != "cap1" || !request.MP09 {
					t.Errorf("unscoped recovery session read")
					return platform.Reply{OK: false}
				}
				row := mp09StoredSession{OK: true, Binding: mp09SourceBinding(root, req), StartedMS: time.Now().Add(-time.Minute).UnixMilli(), Generation: 1, Protocol: "hls", RequireAudio: true, Phase: phase}
				b, _ := json.Marshal(row)
				return platform.Reply{OK: true, Payload: b}
			})
			_, err := mp09ReadSession(ctx, inv, "cap1", root, req, time.Now())
			if (err == nil) != (phase == "recording") {
				t.Fatalf("phase %q permitted resume=%v", phase, err == nil)
			}
		})
	}
}

func TestMP09LIVE18PublicationPhaseOnlyAdvancesAndStatusIsScoped(t *testing.T) {
	var called int
	inv, ctx := mp09TestPlatformInvocation(t, func(raw json.RawMessage) platform.Reply {
		var q struct {
			Action  string `json:"action"`
			Capture string `json:"capture_id"`
			Phase   string `json:"phase"`
			Scope   bool   `json:"mp09_live"`
		}
		if json.Unmarshal(raw, &q) != nil || !q.Scope || q.Capture != "cap1" {
			t.Errorf("missing bounded session scope")
			return platform.Reply{OK: false}
		}
		called++
		switch q.Action {
		case "session_phase":
			if q.Phase != "publishing" && q.Phase != "published" {
				t.Errorf("unexpected phase %q", q.Phase)
				return platform.Reply{OK: false}
			}
			b, _ := json.Marshal(map[string]any{"ok": true, "phase": q.Phase})
			return platform.Reply{OK: true, Payload: b}
		case "session_status":
			return platform.Reply{OK: true, Payload: []byte(`{"ok":true,"phase":"publishing"}`)}
		default:
			t.Errorf("unexpected action %q", q.Action)
			return platform.Reply{OK: false}
		}
	})
	for _, phase := range []string{"recording", "missing", "", "untrusted"} {
		if err := mp09SetSessionPhase(ctx, inv, "cap1", phase); err == nil {
			t.Fatal("invalid phase sent")
		}
	}
	if called != 0 {
		t.Fatalf("invalid phase touched store: %d", called)
	}
	for _, phase := range []string{"publishing", "published"} {
		if err := mp09SetSessionPhase(ctx, inv, "cap1", phase); err != nil {
			t.Fatal(err)
		}
	}
	if phase, err := mp09InspectSession(ctx, inv, "cap1"); err != nil || phase != "publishing" {
		t.Fatalf("phase status %q %v", phase, err)
	}
	if called != 3 {
		t.Fatalf("expected two transitions + status call, got %d", called)
	}

	spoof, spoofCtx := mp09TestPlatformInvocation(t, func(json.RawMessage) platform.Reply {
		return platform.Reply{OK: true, Payload: []byte(`{"ok":true,"phase":"recording"}`)}
	})
	if err := mp09SetSessionPhase(spoofCtx, spoof, "cap1", "published"); err == nil {
		t.Fatal("unconfirmed publication phase treated as durable")
	}
	if strings.Contains(mp09SourceBinding("https://media.example/master.m3u8?sig=SECRET", mp09LiveCommand{Protocol: "hls"}), "SECRET") {
		t.Fatal("source binding leaks token")
	}
}

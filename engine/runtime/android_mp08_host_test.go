package runtime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"
	"time"

	"github.com/subhra74/xdm/engine/media"
	"github.com/subhra74/xdm/engine/runtime/platform"
)

type mp08TestWire struct {
	t       *testing.T
	body    []byte
	saved   []map[string]any
	fail    string
	corrupt bool
}

func (w *mp08TestWire) PlatformRequest(_ context.Context, kind platform.Kind, _ platform.Refs, raw json.RawMessage) (platform.Reply, error) {
	if kind != platform.MP08Finalization {
		w.t.Fatalf("wrong platform kind %q", kind)
	}
	var req map[string]any
	if err := json.Unmarshal(raw, &req); err != nil {
		return platform.Reply{}, err
	}
	w.saved = append(w.saved, req)
	action := req["action"].(string)
	if w.fail == action {
		return platform.Reply{OK: false}, nil
	}
	d := sha256.Sum256(w.body)
	hash := "sha256:" + hex.EncodeToString(d[:])
	reply := map[string]any{"ok": true, "download_ready": false}
	switch action {
	case "assemble_verified":
		// The real Android journal verifies these claims against persisted bytes.
		tracks, ok := req["tracks"].([]any)
		if !ok {
			return platform.Reply{OK: false}, nil
		}
		expected := sha256.Sum256([]byte("fragment"))
		want := "sha256:" + hex.EncodeToString(expected[:])
		for _, rawTrack := range tracks {
			tr := rawTrack.(map[string]any)
			for _, rawPart := range tr["parts"].([]any) {
				part := rawPart.(map[string]any)
				if part["media"].(map[string]any)["hash"] != want {
					return platform.Reply{OK: false}, nil
				}
			}
		}
		reply["status"] = "verified_app_private"
		reply["publication_ref"] = "dest_1"
		reply["sha256"] = hash
		reply["bytes"] = len(w.body)
		reply["media_store_published"] = false
	case "probe_staged":
		reply["probe"] = map[string]any{"container": "mp4", "size": len(w.body), "duration_ms": 5000, "streams": []map[string]any{{"kind": "video", "codec": "h264"}, {"kind": "audio", "codec": "aac"}}}
	case "read_staged", "read_published":
		offset := int(req["offset"].(float64))
		n := int(req["max_bytes"].(float64))
		if offset+n > len(w.body) {
			w.t.Fatalf("out of range read %d %d", offset, n)
		}
		fragment := append([]byte{}, w.body[offset:offset+n]...)
		if w.corrupt && len(fragment) > 0 {
			fragment[0] ^= 0xff
		}
		reply["offset"] = offset
		reply["body_base64"] = base64.StdEncoding.EncodeToString(fragment)
		reply["eof"] = offset+n == len(w.body)
	case "publish_verified":
		reply["publication_id"] = "published_123"
		reply["uri"] = "content://media/external/downloads/5"
		reply["sha256"] = hash
		reply["size"] = len(w.body)
		reply["atomic"] = true
	default:
		w.t.Fatalf("unexpected action %q", action)
	}
	out, _ := json.Marshal(reply)
	return platform.Reply{OK: true, Payload: out}, nil
}
func mp08TestPlan(t *testing.T) media.MP08FinalizationPlan {
	t.Helper()
	id := media.FragmentIdentity{Protocol: media.FragmentProtocolHLS, TimelineKey: "timeline:1", ResourceID: "resource:1"}
	fragmentID, e := media.FragmentID(id)
	if e != nil {
		t.Fatal(e)
	}
	b := []byte("fragment")
	sum := sha256.Sum256(b)
	rec := media.FragmentRecord{ID: fragmentID, Identity: id, Role: "media", State: media.FragmentCommitted,
		AttemptGeneration: 1, ExpectedLength: int64(len(b)), Hash: "sha256:" + hex.EncodeToString(sum[:]), DurableBytesWritten: true}
	return media.MP08FinalizationPlan{SchemaVersion: 1, Source: "hls_vod", Container: "mp4", DestinationKey: "dest_1",
		ExpectedDurationMS: 5000, RequireAudio: false, Tracks: []media.MP08Track{{Role: "video", StartMS: 0, DurationMS: 5000, Parts: []media.FragmentRecord{rec}, InitForPart: []*media.FragmentRecord{nil}}}}
}
func mp08TestHost(t *testing.T) (*androidMP08Host, *mp08TestWire, media.MP08FinalizationPlan) {
	t.Helper()
	b := bytes.Repeat([]byte("media-output"), 200)
	wire := &mp08TestWire{t: t, body: b}
	host, e := newAndroidMP08Host(wire, "capture_1")
	if e != nil {
		t.Fatal(e)
	}
	return host, wire, mp08TestPlan(t)
}
func TestMP08B2HOST01ExactStagedAndPublishedReadback(t *testing.T) {
	host, wire, plan := mp08TestHost(t)
	ctx := context.Background()
	stage, e := host.Assemble(ctx, plan)
	if e != nil {
		t.Fatal(e)
	}
	probe, e := host.Probe(ctx, stage)
	if e != nil || probe.Size != stage.Size || len(probe.Streams) != 2 {
		t.Fatalf("probe %v %+v", e, probe)
	}
	reader, e := host.ReadStaged(ctx, stage)
	if e != nil {
		t.Fatal(e)
	}
	got, e := io.ReadAll(reader)
	reader.Close()
	if e != nil || !bytes.Equal(got, wire.body) {
		t.Fatal("staged readback mismatch", e)
	}
	publication, e := host.PublishAtomic(ctx, stage, plan.DestinationKey)
	if e != nil {
		t.Fatal(e)
	}
	stream, e := host.ReadPublished(ctx, publication)
	if e != nil {
		t.Fatal(e)
	}
	again, e := io.ReadAll(stream)
	stream.Close()
	if e != nil || !bytes.Equal(again, wire.body) {
		t.Fatal("published readback mismatch", e)
	}
	for _, request := range wire.saved {
		if request["download_ready"] == true || request["url"] != nil || request["argv"] != nil || request["path"] != nil {
			t.Fatalf("untrusted request: %+v", request)
		}
	}
}
func TestMP08B2HOST02AndroidJournalRejectsForgedReceipt(t *testing.T) {
	host, wire, plan := mp08TestHost(t)
	plan.Tracks[0].Parts[0].Hash = "sha256:" + strings.Repeat("0", 64)
	if _, e := host.Assemble(context.Background(), plan); e == nil {
		t.Fatal("forged receipt accepted")
	}
	if len(wire.saved) != 1 {
		t.Fatal("expected one Android journal refusal")
	}
}
func TestMP08B2HOST03RejectsUnsupportedMultiPeriod(t *testing.T) {
	host, wire, plan := mp08TestHost(t)
	second := plan.Tracks[0]
	second.StartMS = 5000
	second.PeriodID = "second"
	plan.Tracks = append(plan.Tracks, second)
	if _, e := host.Assemble(context.Background(), plan); e == nil {
		t.Fatal("second period accepted")
	}
	if len(wire.saved) != 0 {
		t.Fatal("network reached")
	}
}
func TestMP08B2HOST04RejectsPartialAndSubtitle(t *testing.T) {
	host, _, plan := mp08TestHost(t)
	plan.Partial = true
	if _, e := host.Assemble(context.Background(), plan); e == nil {
		t.Fatal("partial accepted")
	}
	plan.Partial = false
	plan.RequireSubtitle = true
	if _, e := host.Assemble(context.Background(), plan); e == nil {
		t.Fatal("subtitle accepted")
	}
}
func TestMP08B2HOST05RejectsUnapprovedAudioRequirement(t *testing.T) {
	host, _, plan := mp08TestHost(t)
	plan.RequireAudio = true
	if _, e := host.Assemble(context.Background(), plan); e == nil {
		t.Fatal("missing audio accepted")
	}
}
func TestMP08B2HOST06RejectsMissingInitProof(t *testing.T) {
	host, _, plan := mp08TestHost(t)
	plan.Tracks[0].InitForPart = nil
	if _, e := host.Assemble(context.Background(), plan); e == nil {
		t.Fatal("missing init list accepted")
	}
}
func TestMP08B2HOST07RejectsStageTokenSwap(t *testing.T) {
	host, _, plan := mp08TestHost(t)
	stage, e := host.Assemble(context.Background(), plan)
	if e != nil {
		t.Fatal(e)
	}
	stage.HostToken = "attacker"
	if _, e := host.ReadStaged(context.Background(), stage); e == nil {
		t.Fatal("swapped token accepted")
	}
	if _, e := host.PublishAtomic(context.Background(), stage, "attacker"); e == nil {
		t.Fatal("swapped token published")
	}
}
func TestMP08B2HOST08RejectsPublishedReceiptSwap(t *testing.T) {
	host, _, plan := mp08TestHost(t)
	stage, e := host.Assemble(context.Background(), plan)
	if e != nil {
		t.Fatal(e)
	}
	pub, e := host.PublishAtomic(context.Background(), stage, "dest_1")
	if e != nil {
		t.Fatal(e)
	}
	pub.URI = "content://media/external/downloads/other"
	if _, e := host.ReadPublished(context.Background(), pub); e == nil {
		t.Fatal("swapped published URI accepted")
	}
}
func TestMP08B2HOST09TransportRefusalNeverReturnsOutput(t *testing.T) {
	host, wire, plan := mp08TestHost(t)
	wire.fail = "assemble_verified"
	if _, e := host.Assemble(context.Background(), plan); e == nil {
		t.Fatal("transport error accepted")
	}
}
func TestMP08B2HOST10ChunkReaderFailClosed(t *testing.T) {
	host, wire, plan := mp08TestHost(t)
	stage, e := host.Assemble(context.Background(), plan)
	if e != nil {
		t.Fatal(e)
	}
	wire.fail = "read_staged"
	rd, e := host.ReadStaged(context.Background(), stage)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = io.ReadAll(rd); !errors.Is(e, errAndroidMP08Host) {
		t.Fatalf("expected refusal got %v", e)
	}
}
func TestMP08B2HOST11ChunkedLargeOutput(t *testing.T) {
	host, wire, plan := mp08TestHost(t)
	wire.body = bytes.Repeat([]byte("x"), 3*mp08WireChunk+17)
	stage, e := host.Assemble(context.Background(), plan)
	if e != nil {
		t.Fatal(e)
	}
	r, e := host.ReadStaged(context.Background(), stage)
	if e != nil {
		t.Fatal(e)
	}
	got, e := io.ReadAll(r)
	r.Close()
	if e != nil || !bytes.Equal(got, wire.body) {
		t.Fatalf("chunk loss %v", e)
	}
	n := 0
	for _, q := range wire.saved {
		if q["action"] == "read_staged" {
			n++
		}
	}
	if n != 4 {
		t.Fatalf("expected 4 chunks got %d", n)
	}
}
func TestMP08B2HOST12ClosedReaderRefuses(t *testing.T) {
	host, _, plan := mp08TestHost(t)
	stage, e := host.Assemble(context.Background(), plan)
	if e != nil {
		t.Fatal(e)
	}
	r, e := host.ReadStaged(context.Background(), stage)
	if e != nil {
		t.Fatal(e)
	}
	r.Close()
	var b [1]byte
	if _, e = r.Read(b[:]); !errors.Is(e, io.ErrClosedPipe) {
		t.Fatalf("closed reader %v", e)
	}
}
func TestMP08B2HOST13NoCompletionClaimBeforeGo(t *testing.T) {
	host, wire, plan := mp08TestHost(t)
	stage, e := host.Assemble(context.Background(), plan)
	if e != nil {
		t.Fatal(e)
	}
	_, e = host.PublishAtomic(context.Background(), stage, "dest_1")
	if e != nil {
		t.Fatal(e)
	}
	for _, request := range wire.saved {
		if request["download_ready"] == true {
			t.Fatal("Android cannot complete Go download")
		}
	}
}
func TestMP08B2HOST14CaptureIsRequired(t *testing.T) {
	_, e := newAndroidMP08Host(nil, "capture")
	if e == nil {
		t.Fatal("nil requester accepted")
	}
	host, wire, _ := mp08TestHost(t)
	_, e = newAndroidMP08Host(wire, "\ninvalid")
	if e == nil || host == nil {
		t.Fatal("invalid capture accepted")
	}
}

var _ = time.Second

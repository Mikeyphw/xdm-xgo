package runtime

// MP08B2: transport for the Go-validated MP08 plan through the Android
// app-private staged broker and MediaStore pending-visibility publisher.
// This is opt-in: existing capture routing is not silently cut over.
// The host can never itself issue DownloadReady; only
// media.RunMP08VerifiedPublication verifies both streams and completes.
import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/subhra74/xdm/engine/media"
	"github.com/subhra74/xdm/engine/runtime/platform"
)

var errAndroidMP08Host = errors.New("MP08B2 Android publication host refused")
var mp08WireName = regexp.MustCompile(`^[A-Za-z0-9_-]{1,96}$`)
var mp08WireHash = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)

const mp08WireChunk = 64 * 1024
const mp08WireMaxReply = 128 * 1024

type mp08PlatformRequester interface {
	PlatformRequest(context.Context, platform.Kind, platform.Refs, json.RawMessage) (platform.Reply, error)
}

type androidMP08Host struct {
	inv       mp08PlatformRequester
	capture   string
	mu        sync.Mutex
	staged    media.MP08StagedOutput
	published media.MP08PublishedOutput
	dest      string
}

// NewAndroidMP08HostForCapture creates an explicit host capability for a
// currently authorized capture. It does NOT trigger a download or publication.
func NewAndroidMP08HostForCapture(inv *Invocation, captureID string) (media.MP08Host, error) {
	return newAndroidMP08Host(inv, captureID)
}
func newAndroidMP08Host(inv mp08PlatformRequester, capture string) (*androidMP08Host, error) {
	if inv == nil || strings.TrimSpace(capture) != capture || capture == "" || len(capture) > 256 {
		return nil, errAndroidMP08Host
	}
	return &androidMP08Host{inv: inv, capture: capture}, nil
}

func (h *androidMP08Host) call(ctx context.Context, body map[string]any) (json.RawMessage, error) {
	if h == nil || h.inv == nil || ctx == nil {
		return nil, errAndroidMP08Host
	}
	body["schema_version"] = 1
	body["capture_id"] = h.capture
	raw, e := json.Marshal(body)
	if e != nil || len(raw) > 2<<20 {
		return nil, errAndroidMP08Host
	}
	reply, e := h.inv.PlatformRequest(ctx, platform.MP08Finalization, platform.Refs{}, raw)
	if e != nil || !reply.OK || len(reply.Payload) == 0 || len(reply.Payload) > mp08WireMaxReply {
		return nil, errAndroidMP08Host
	}
	var status struct {
		OK            bool `json:"ok"`
		DownloadReady bool `json:"download_ready"`
	}
	if json.Unmarshal(reply.Payload, &status) != nil || !status.OK || status.DownloadReady {
		return nil, errAndroidMP08Host
	}
	return reply.Payload, nil
}

type mp08WireProof struct {
	ID         string `json:"fragment_id"`
	Generation int64  `json:"generation"`
	Hash       string `json:"hash"`
	Length     int64  `json:"length"`
}

func mp08ProofWire(rec media.FragmentRecord) (mp08WireProof, error) {
	id, e := media.FragmentID(rec.Identity)
	if e != nil || rec.ID != id || rec.AttemptGeneration <= 0 || !rec.DurableBytesWritten || rec.State != media.FragmentCommitted ||
		rec.ExpectedLength <= 0 || rec.ExpectedLength > 2<<20 || !mp08WireHash.MatchString(rec.Hash) {
		return mp08WireProof{}, errAndroidMP08Host
	}
	return mp08WireProof{ID: id, Generation: rec.AttemptGeneration, Hash: rec.Hash, Length: rec.ExpectedLength}, nil
}

func (h *androidMP08Host) Assemble(ctx context.Context, p media.MP08FinalizationPlan) (media.MP08StagedOutput, error) {
	empty := media.MP08StagedOutput{}
	if p.SchemaVersion != 1 || p.Partial || p.Container != "mp4" || p.ExpectedDurationMS < 1000 ||
		p.ExpectedDurationMS > 24*60*60*1000 || !mp08WireName.MatchString(p.DestinationKey) ||
		(p.Source != "hls_vod" && p.Source != "dash_static" && p.Source != "hls_live" && p.Source != "dash_live") || p.RequireSubtitle ||
		len(p.Tracks) < 1 || len(p.Tracks) > 2 {
		return empty, errAndroidMP08Host
	}
	tracks := make([]map[string]any, 0, len(p.Tracks))
	seen := map[string]bool{}
	roles := map[string]bool{}
	var periodID string
	for _, t := range p.Tracks {
		if roles[t.Role] || (t.Role != "video" && t.Role != "audio") || len(t.Parts) == 0 || len(t.Parts) > 4096 || len(t.InitForPart) != len(t.Parts) || t.StartMS != 0 || t.DurationMS != p.ExpectedDurationMS {
			return empty, errAndroidMP08Host
		}
		if periodID != "" && periodID != t.PeriodID {
			return empty, errAndroidMP08Host
		}
		periodID = t.PeriodID
		roles[t.Role] = true
		parts := make([]map[string]any, 0, len(t.Parts))
		for i, rec := range t.Parts {
			proof, e := mp08ProofWire(rec)
			if e != nil || seen[proof.ID] {
				return empty, errAndroidMP08Host
			}
			seen[proof.ID] = true
			unit := map[string]any{"index": i, "media": proof}
			if t.InitForPart[i] != nil {
				initial, e := mp08ProofWire(*t.InitForPart[i])
				if e != nil || t.InitForPart[i].Role != "init" {
					return empty, errAndroidMP08Host
				}
				unit["init"] = initial
			}
			parts = append(parts, unit)
		}
		tracks = append(tracks, map[string]any{"role": t.Role, "parts": parts})
	}
	if !roles["video"] || (p.RequireAudio && !roles["audio"]) || p.Tracks[0].Role != "video" {
		return empty, errAndroidMP08Host
	}
	body := map[string]any{"action": "assemble_verified", "source": p.Source, "destination_key": p.DestinationKey,
		"period_count": 1, "container": "mp4", "expected_duration_ms": p.ExpectedDurationMS, "require_audio": p.RequireAudio,
		"require_subtitle": false, "partial": false, "has_gaps": false, "is_dynamic": false, "tracks": tracks}
	reply, e := h.call(ctx, body)
	if e != nil {
		return empty, e
	}
	var got struct {
		Token     string `json:"publication_ref"`
		Status    string `json:"status"`
		Hash      string `json:"sha256"`
		Bytes     int64  `json:"bytes"`
		Published bool   `json:"media_store_published"`
	}
	if json.Unmarshal(reply, &got) != nil || got.Status != "verified_app_private" || got.Token != p.DestinationKey ||
		!mp08WireHash.MatchString(got.Hash) || got.Bytes < 1024 || got.Bytes > 512<<20 || got.Published {
		return empty, errAndroidMP08Host
	}
	result := media.MP08StagedOutput{HostToken: got.Token, Size: got.Bytes, SHA256: got.Hash}
	h.mu.Lock()
	h.staged = result
	h.dest = p.DestinationKey
	h.mu.Unlock()
	return result, nil
}
func (h *androidMP08Host) checkStaged(stage media.MP08StagedOutput) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	return stage == h.staged && stage.HostToken == h.dest && mp08WireName.MatchString(stage.HostToken) &&
		stage.Size >= 1024 && stage.Size <= 512<<20 && mp08WireHash.MatchString(stage.SHA256)
}
func (h *androidMP08Host) Probe(ctx context.Context, stage media.MP08StagedOutput) (media.FFProbeReport, error) {
	if !h.checkStaged(stage) {
		return media.FFProbeReport{}, errAndroidMP08Host
	}
	raw, e := h.call(ctx, map[string]any{"action": "probe_staged", "destination_key": stage.HostToken, "sha256": stage.SHA256, "bytes": stage.Size})
	if e != nil {
		return media.FFProbeReport{}, e
	}
	var v struct {
		Probe struct {
			Container  string `json:"container"`
			DurationMS int64  `json:"duration_ms"`
			Size       int64  `json:"size"`
			Streams    []struct {
				Kind  string `json:"kind"`
				Codec string `json:"codec"`
			} `json:"streams"`
		} `json:"probe"`
	}
	if json.Unmarshal(raw, &v) != nil || v.Probe.Container != "mp4" || v.Probe.Size != stage.Size || v.Probe.DurationMS <= 0 || len(v.Probe.Streams) == 0 || len(v.Probe.Streams) > 16 {
		return media.FFProbeReport{}, errAndroidMP08Host
	}
	out := media.FFProbeReport{Container: "mp4", Size: v.Probe.Size, Duration: timeDurationMS(v.Probe.DurationMS)}
	for _, s := range v.Probe.Streams {
		switch s.Kind {
		case "video", "audio", "subtitle":
		default:
			return media.FFProbeReport{}, errAndroidMP08Host
		}
		out.Streams = append(out.Streams, media.FFProbeStream{Kind: media.StreamKind(s.Kind), Codec: s.Codec})
	}
	return out, nil
}

func timeDurationMS(ms int64) time.Duration { return time.Duration(ms) * time.Millisecond }
func (h *androidMP08Host) ReadStaged(ctx context.Context, stage media.MP08StagedOutput) (io.ReadCloser, error) {
	if !h.checkStaged(stage) {
		return nil, errAndroidMP08Host
	}
	return &mp08AndroidReader{host: h, ctx: ctx, kind: "read_staged", dest: stage.HostToken, size: stage.Size, hash: stage.SHA256}, nil
}
func (h *androidMP08Host) PublishAtomic(ctx context.Context, stage media.MP08StagedOutput, dest string) (media.MP08PublishedOutput, error) {
	empty := media.MP08PublishedOutput{}
	if !h.checkStaged(stage) || dest != stage.HostToken {
		return empty, errAndroidMP08Host
	}
	raw, e := h.call(ctx, map[string]any{"action": "publish_verified", "destination_key": dest, "sha256": stage.SHA256, "bytes": stage.Size})
	if e != nil {
		return empty, e
	}
	var got struct {
		ID     string `json:"publication_id"`
		URI    string `json:"uri"`
		Hash   string `json:"sha256"`
		Size   int64  `json:"size"`
		Atomic bool   `json:"atomic"`
	}
	if json.Unmarshal(raw, &got) != nil || !mp08WireName.MatchString(got.ID) || !strings.HasPrefix(got.URI, "content://") ||
		strings.ContainsAny(got.URI, "\r\n\x00?#") || got.Size != stage.Size || got.Hash != stage.SHA256 || !got.Atomic {
		return empty, errAndroidMP08Host
	}
	result := media.MP08PublishedOutput{URI: got.URI, PublicationID: got.ID, SHA256: got.Hash, Size: got.Size, Atomic: true}
	h.mu.Lock()
	h.published = result
	h.mu.Unlock()
	return result, nil
}
func (h *androidMP08Host) ReadPublished(ctx context.Context, output media.MP08PublishedOutput) (io.ReadCloser, error) {
	h.mu.Lock()
	valid := output == h.published && output.Atomic && h.dest != ""
	dest := h.dest
	h.mu.Unlock()
	if !valid {
		return nil, errAndroidMP08Host
	}
	return &mp08AndroidReader{host: h, ctx: ctx, kind: "read_published", dest: dest, id: output.PublicationID, size: output.Size, hash: output.SHA256}, nil
}

type mp08AndroidReader struct {
	host                 *androidMP08Host
	ctx                  context.Context
	kind, dest, id, hash string
	size, offset         int64
	buffered             []byte
	closed               bool
}

func (r *mp08AndroidReader) Read(p []byte) (int, error) {
	if r.closed {
		return 0, io.ErrClosedPipe
	}
	if len(p) == 0 {
		return 0, nil
	}
	if len(r.buffered) == 0 && r.offset == r.size {
		return 0, io.EOF
	}
	if len(r.buffered) == 0 {
		n := int64(mp08WireChunk)
		if r.size-r.offset < n {
			n = r.size - r.offset
		}
		raw, e := r.host.call(r.ctx, map[string]any{"action": r.kind, "destination_key": r.dest,
			"publication_id": r.id, "sha256": r.hash, "bytes": r.size, "offset": r.offset, "max_bytes": int(n)})
		if e != nil {
			return 0, e
		}
		var got struct {
			Offset int64  `json:"offset"`
			Body   string `json:"body_base64"`
			EOF    bool   `json:"eof"`
		}
		if json.Unmarshal(raw, &got) != nil || got.Offset != r.offset || len(got.Body) > base64.StdEncoding.EncodedLen(int(n)) {
			return 0, errAndroidMP08Host
		}
		bytes, e := base64.StdEncoding.Strict().DecodeString(got.Body)
		if e != nil || len(bytes) != int(n) || got.EOF != (r.offset+n == r.size) {
			return 0, errAndroidMP08Host
		}
		r.offset += n
		r.buffered = bytes
	}
	k := copy(p, r.buffered)
	r.buffered = r.buffered[k:]
	return k, nil
}
func (r *mp08AndroidReader) Close() error { r.closed = true; r.buffered = nil; return nil }

var _ media.MP08Host = (*androidMP08Host)(nil)

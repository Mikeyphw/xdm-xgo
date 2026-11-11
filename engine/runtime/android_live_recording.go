package runtime

// MP09 consolidated: typed Go-owned recording commands. All network bytes
// are fetched by Android's previously paired, scope-checking platform broker;
// the Go engine owns fragment identity, timing, durable proof and publication.
import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/subhra74/xdm/engine/media"
	"github.com/subhra74/xdm/engine/runtime/command"
	"github.com/subhra74/xdm/engine/runtime/platform"
)

const AndroidMediaLiveKind = "android.media.live"

var errMP09Android = errors.New("MP09 live controller refused")

type mp09LiveCommand struct {
	ClientRequestID       string `json:"client_request_id"`
	CaptureID             string `json:"capture_id"`
	Action                string `json:"action"`
	VideoURL              string `json:"video_url"`
	AudioURL              string `json:"audio_url"`
	VideoRepresentationID string `json:"video_representation_id"`
	AudioRepresentationID string `json:"audio_representation_id"`
	Protocol              string `json:"protocol"`
	RequireAudio          bool   `json:"require_audio"`
	DVRCapable            bool   `json:"dvr_capable"`
	UserLimitMS           int64  `json:"user_limit_ms"`
	UserLimitBytes        int64  `json:"user_limit_bytes"`
	DestinationKey        string `json:"destination_key"`
}

type mp09AndroidRecording struct {
	root      string
	ctrl      *media.MP09Recording
	session   *media.LiveSession
	video     *mp09AndroidStore
	audio     *mp09AndroidStore
	videoPoll *media.LivePollEngine
	audioPoll *media.LivePollEngine
}

type mp09AndroidState struct {
	mu      sync.Mutex
	entries map[string]*mp09AndroidRecording
}

type mp09AndroidFetcher struct {
	inv           *Invocation
	capture, root string
}

func (f *mp09AndroidFetcher) fetch(ctx context.Context, urlValue string, kind string, rng *media.ByteRange) ([]byte, error) {
	if f == nil || f.inv == nil || ctx == nil {
		return nil, errMP09Android
	}
	uri, e := url.Parse(urlValue)
	if e != nil || uri.Host == "" || uri.User != nil || uri.Fragment != "" || uri.Scheme != "https" && uri.Scheme != "http" {
		return nil, errMP09Android
	}
	root, e := url.Parse(f.root)
	if e != nil || !strings.EqualFold(uri.Host, root.Host) || uri.Scheme != root.Scheme {
		return nil, errMP09Android
	}
	payload := map[string]any{"capture_id": f.capture, "root_url": f.root, "requested_url": urlValue,
		"parent_url": f.root, "may_replay_credentials": true, "max_response_bytes": 2 << 20, "mp09_media_kind": kind}
	if rng != nil {
		if rng.Offset < 0 || rng.Length <= 0 || rng.Length > 2<<20 {
			return nil, errMP09Android
		}
		payload["range_offset"] = rng.Offset
		payload["range_length"] = rng.Length
	}
	raw, _ := json.Marshal(payload)
	reply, e := f.inv.PlatformRequest(ctx, platform.ManifestFetch, platform.Refs{}, raw)
	if e != nil || !reply.OK {
		return nil, errMP09Android
	}
	decoded, e := decodeAndroidManifestFetch(reply.Payload)
	if e != nil || len(decoded.Body) == 0 || len(decoded.Body) > 2<<20 {
		return nil, errMP09Android
	}
	// The Android broker verifies each redirect. A drifted final authority is
	// never consumed, even if it returned plausible segment bytes.
	final, e := url.Parse(decoded.FinalURL)
	if e != nil || final.Scheme != root.Scheme || !strings.EqualFold(final.Host, root.Host) {
		return nil, errMP09Android
	}
	if rng != nil && int64(len(decoded.Body)) != rng.Length {
		return nil, errMP09Android
	}
	return decoded.Body, nil
}
func (f *mp09AndroidFetcher) FetchHLS(ctx context.Context, req media.HLSFetchRequest) (media.HLSFetchResponse, error) {
	b, e := f.fetch(ctx, req.URI, string(req.Kind), req.Range)
	return media.HLSFetchResponse{Bytes: b}, e
}
func (f *mp09AndroidFetcher) FetchDASH(ctx context.Context, req media.DASHFetchRequest) (media.DASHFetchResponse, error) {
	b, e := f.fetch(ctx, req.URI, string(req.Kind), req.Range)
	return media.DASHFetchResponse{Bytes: b}, e
}

type mp09AndroidStore struct {
	base    *mp09FragmentStoreAdapter
	records map[string]media.FragmentRecord
}

func newMP09AndroidStore(inv *Invocation, captureID, role string) (*mp09AndroidStore, error) {
	raw, e := newMP09FragmentStoreAdapter(inv, captureID)
	if e != nil {
		return nil, e
	}
	store := raw.(*mp09FragmentStoreAdapter)
	store.roleHint = role
	return &mp09AndroidStore{base: store, records: make(map[string]media.FragmentRecord)}, nil
}
func (s *mp09AndroidStore) use(inv *Invocation) { s.base.inv = inv }

// Existing fragments from a process-dead session cannot be mistaken for a
// fresh recording start. Reauthorization and source-fingerprint reconciliation
// must be explicitly qualified before restoring such fragments in-place.
func (s *mp09AndroidStore) preflightNoUnboundJournal(ctx context.Context) error {
	raw, _ := json.Marshal(map[string]any{
		"action": "inventory", "capture_id": s.base.captureID, "track_role": "all", "mp09_live": true,
	})
	reply, err := s.base.inv.PlatformRequest(ctx, platform.AndroidFragmentStore, platform.Refs{}, raw)
	if err != nil || !reply.OK || len(reply.Payload) > 512<<10 {
		return media.ErrFragmentDurability
	}
	var inventory struct {
		Records []json.RawMessage `json:"records"`
	}
	if json.Unmarshal(reply.Payload, &inventory) != nil || len(inventory.Records) > 0 {
		return media.ErrFragmentDurability
	}
	return nil
}

func (s *mp09AndroidStore) WriteAndCommitFragment(ctx context.Context, r media.FragmentRecord, b []byte) (media.FragmentRecord, error) {
	out, e := s.base.WriteAndCommitFragment(ctx, r, b)
	if e == nil {
		s.records[out.ID] = out
	}
	return out, e
}
func (s *mp09AndroidStore) VerifyCommitted(r media.FragmentRecord) error {
	return s.base.VerifyCommitted(r)
}
func (s *mp09AndroidStore) CommittedRecords() []media.FragmentRecord {
	list := make([]media.FragmentRecord, 0, len(s.records))
	for _, r := range s.records {
		list = append(list, r)
	}
	return list
}

// Go's independent MP08 proof requires reading app-private staged bytes.
// Android returns only requested, redacted, readback-verified 64-KiB chunks.
func (s *mp09AndroidStore) ReadVerified(id media.FragmentIdentity) ([]byte, error) {
	key, e := media.FragmentID(id)
	if e != nil {
		return nil, e
	}
	rec, ok := s.records[key]
	if !ok || rec.ExpectedLength <= 0 || rec.ExpectedLength > 2<<20 {
		return nil, media.ErrFragmentDurability
	}
	if e := s.VerifyCommitted(rec); e != nil {
		return nil, e
	}
	out := make([]byte, 0, int(rec.ExpectedLength))
	for offset := int64(0); offset < rec.ExpectedLength; {
		chunk := int64(64 << 10)
		if rem := rec.ExpectedLength - offset; rem < chunk {
			chunk = rem
		}
		raw, _ := json.Marshal(map[string]any{"action": "read_chunk", "capture_id": s.base.captureID,
			"fragment_id": key, "generation": rec.AttemptGeneration, "hash": rec.Hash,
			"expected_length": rec.ExpectedLength, "offset": offset, "length": chunk, "mp09_live": true})
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		reply, ee := s.base.inv.PlatformRequest(ctx, platform.AndroidFragmentStore, platform.Refs{}, raw)
		cancel()
		if ee != nil || !reply.OK || len(reply.Payload) > 128<<10 {
			return nil, media.ErrFragmentDurability
		}
		var got struct {
			Body   string `json:"body_base64"`
			Length int64  `json:"length"`
		}
		if json.Unmarshal(reply.Payload, &got) != nil || got.Length != chunk {
			return nil, media.ErrFragmentDurability
		}
		bytes, ee := base64.StdEncoding.DecodeString(got.Body)
		if ee != nil || int64(len(bytes)) != chunk {
			return nil, media.ErrFragmentDurability
		}
		out = append(out, bytes...)
		offset += chunk
	}
	sum := sha256.Sum256(out)
	if "sha256:"+hex.EncodeToString(sum[:]) != rec.Hash {
		return nil, media.ErrFragmentDurability
	}
	return out, nil
}

func (e *Engine) androidMediaLiveHandler(ctx context.Context, inv *Invocation, env command.Envelope) error {
	var req mp09LiveCommand
	if json.Unmarshal(env.Payload, &req) != nil || req.ClientRequestID == "" || len(req.ClientRequestID) > 128 ||
		req.CaptureID == "" || len(req.CaptureID) > 256 {
		return errMP09Android
	}
	failed := func(code string) error {
		_ = emitAndroidMediaResult(inv, req.ClientRequestID, "live", false, map[string]any{
			"capture_id": req.CaptureID, "error_code": code, "status": "refused"})
		return errMP09Android
	}
	e.mu.Lock()
	if e.liveRecording == nil {
		e.liveRecording = &mp09AndroidState{entries: map[string]*mp09AndroidRecording{}}
	}
	state := e.liveRecording
	e.mu.Unlock()
	state.mu.Lock()
	defer state.mu.Unlock()
	now := time.Now().UTC()
	active := state.entries[req.CaptureID]
	var status media.MP09RecordingStatus
	var err error
	switch req.Action {
	case "start":
		if active != nil {
			return failed("already_recording")
		}
		if req.UserLimitMS < 0 || req.UserLimitBytes < 0 {
			return failed("invalid_explicit_limit")
		}
		root, ee := e.androidMedia.manifestRoot(req.CaptureID)
		if ee != nil {
			return failed("capture_not_authorized")
		}
		parsedRoot, ee := url.Parse(root)
		if ee != nil || parsedRoot.Host == "" {
			return failed("capture_scope_invalid")
		}
		if req.Protocol != "hls" && req.Protocol != "dash" {
			return failed("protocol_invalid")
		}
		protocol := media.FragmentProtocol(req.Protocol)
		if req.UserLimitMS > int64((24*time.Hour)/time.Millisecond)*365 {
			return failed("user_duration_overflow")
		}
		sidHash := sha256.Sum256([]byte(req.CaptureID))
		sessionID := "live_" + hex.EncodeToString(sidHash[:12])
		session, ee := media.NewLiveSession(sessionID, 1, now, media.LiveSessionPolicy{
			SourceDVRCapable: req.DVRCapable, IdleTimeout: 15 * time.Second, PollTimeout: 20 * time.Second,
			UserMaxDuration: time.Duration(req.UserLimitMS) * time.Millisecond, UserMaxDurableBytes: req.UserLimitBytes})
		if ee != nil {
			return failed("session_invalid")
		}
		fetcher := &mp09AndroidFetcher{inv: inv, capture: req.CaptureID, root: root}
		build := func(role, uri, rep string) (*mp09AndroidStore, *media.LivePollEngine, error) {
			store, x := newMP09AndroidStore(inv, req.CaptureID, role)
			if x != nil {
				return nil, nil, x
			}
			if x = store.preflightNoUnboundJournal(ctx); x != nil {
				return nil, nil, x
			}
			spec := media.LivePollSpec{Protocol: protocol, ManifestURL: uri, DASHRepresentationID: rep}
			poll, x := media.NewLivePollEngine(session, store, fetcher, fetcher, spec)
			return store, poll, x
		}
		if req.VideoURL == "" {
			return failed("video_selection_missing")
		}
		video, vpoll, ee := build("video", req.VideoURL, req.VideoRepresentationID)
		if ee != nil {
			return failed("video_selection_refused")
		}
		var audio *mp09AndroidStore
		var apoll *media.LivePollEngine
		bindings := []media.MP09TrackBinding{{Role: "video", Poll: vpoll, Store: video}}
		if req.AudioURL != "" {
			audio, apoll, ee = build("audio", req.AudioURL, req.AudioRepresentationID)
			if ee != nil {
				return failed("audio_selection_refused")
			}
			bindings = append(bindings, media.MP09TrackBinding{Role: "audio", Poll: apoll, Store: audio})
		} else if req.RequireAudio {
			return failed("required_audio_missing")
		}
		controller, ee := media.NewMP09Recording(session, req.RequireAudio, bindings...)
		if ee != nil {
			return failed("track_binding_refused")
		}
		active = &mp09AndroidRecording{root: root, ctrl: controller, session: session, video: video,
			audio: audio, videoPoll: vpoll, audioPoll: apoll}
		state.entries[req.CaptureID] = active
		status, err = active.ctrl.PollDue(ctx, now)
		if err != nil && !errors.Is(err, media.ErrLivePollFetch) && !errors.Is(err, media.ErrLivePollIncomplete) {
			// Invalid first attempts cannot leave a phantom active session.
			delete(state.entries, req.CaptureID)
		}
	case "poll":
		if active == nil {
			return failed("session_not_found_recover_authorization")
		}
		fetcher := &mp09AndroidFetcher{inv: inv, capture: req.CaptureID, root: active.root}
		active.video.use(inv)
		active.videoPoll.BindForMP09(fetcher, fetcher)
		if active.audio != nil {
			active.audio.use(inv)
			active.audioPoll.BindForMP09(fetcher, fetcher)
		}
		status, err = active.ctrl.PollDue(ctx, now)
	case "pause":
		if active == nil {
			return failed("session_not_found")
		}
		err = active.ctrl.Pause(now)
	case "resume":
		if active == nil {
			return failed("session_not_found")
		}
		err = active.ctrl.Resume(now)
	case "stop_save":
		if active == nil {
			return failed("session_not_found")
		}
		status, err = active.ctrl.Stop(now)
		if err == nil {
			host, ee := newAndroidMP08Host(inv, req.CaptureID)
			if ee != nil {
				return failed("mp08_host_unavailable")
			}
			// Stop time is an observed clip lifetime. FFprobe independently verifies
			// bounded output against media duration and never accepts a phantom file.
			duration := now.Sub(active.session.StartedAtForMP09())
			if duration < time.Second {
				return failed("recording_too_short")
			}
			result, finalErr := active.ctrl.Finalize(ctx, req.DestinationKey, duration, host)
			if finalErr != nil || !result.DownloadReady {
				return failed("mp08_verify_or_publication_failed")
			}
			delete(state.entries, req.CaptureID)
			return emitAndroidMediaResult(inv, req.ClientRequestID, "live", true, map[string]any{
				"capture_id": req.CaptureID, "status": "completed", "publication_id": result.PublicationID, "output_uri": result.OutputURI, "download_ready": true})
		}
	case "cancel_discard":
		if active == nil {
			return failed("session_not_found")
		}
		cleaner := &mp09AndroidCleaner{inv: inv, capture: req.CaptureID}
		status, err = active.ctrl.Cancel(ctx, now, cleaner)
		if err == nil {
			delete(state.entries, req.CaptureID)
		}
	default:
		return failed("unsupported_action")
	}
	if err != nil && !errors.Is(err, media.ErrLivePollFetch) && !errors.Is(err, media.ErrLivePollIncomplete) {
		return failed("recording_state_or_durability_refused")
	}
	if req.Action == "pause" || req.Action == "resume" {
		status, _ = active.ctrl.SnapshotForMP09()
	}
	stateName := string(status.State)
	if stateName == "" {
		snap, _ := active.session.Snapshot()
		stateName = string(snap.State)
	}
	return emitAndroidMediaResult(inv, req.ClientRequestID, "live", true, map[string]any{
		"capture_id": req.CaptureID, "status": stateName, "next_poll_after_ms": int64(status.NextPollAfter / time.Millisecond),
		"durable_fragments": status.DurableFragments, "durable_bytes": status.DurableBytes,
		"partial_review_required": status.PartialReviewRequired, "all_tracks_ended": status.AllTracksEnded,
		"download_ready": false})
}

type mp09AndroidCleaner struct {
	inv     *Invocation
	capture string
}

func (c *mp09AndroidCleaner) DiscardAndVerify(ctx context.Context, records []media.FragmentRecord) error {
	raw, _ := json.Marshal(map[string]any{"action": "discard_capture", "capture_id": c.capture, "mp09_live": true})
	result, e := c.inv.PlatformRequest(ctx, platform.AndroidFragmentStore, platform.Refs{}, raw)
	if e != nil || !result.OK {
		return media.ErrMP09Cleanup
	}
	var receipt struct {
		Status    string `json:"status"`
		Remaining int    `json:"remaining"`
	}
	if json.Unmarshal(result.Payload, &receipt) != nil || receipt.Status != "discarded_verified" || receipt.Remaining != 0 {
		return media.ErrMP09Cleanup
	}
	return nil
}

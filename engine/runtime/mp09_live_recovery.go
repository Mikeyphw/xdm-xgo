package runtime

// MP09 process-death recovery. The storage journal is not a transport
// credential cache: a restarted session is recoverable only after an explicit
// user action, a fresh authorized capture and verified, source-bound readback.
import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/url"
	"strings"
	"time"

	"github.com/subhra74/xdm/engine/media"
	"github.com/subhra74/xdm/engine/runtime/platform"
)

var errMP09Restore = errors.New("MP09 recovery requires fresh authorization and exact durable proof")

type mp09StoredSession struct {
	OK           bool   `json:"ok"`
	Binding      string `json:"binding_sha256"`
	StartedMS    int64  `json:"started_at_epoch_ms"`
	Generation   int64  `json:"generation"`
	Protocol     string `json:"protocol"`
	RequireAudio bool   `json:"require_audio"`
	DVR          bool   `json:"dvr_capable"`
	LimitMS      int64  `json:"user_limit_ms"`
	LimitBytes   int64  `json:"user_limit_bytes"`
	Phase        string `json:"phase"`
}

// mp09StableSourceURL intentionally drops only well-known expiring signed-URL
// parameters; all other query values, origin, path, and port remain bound.
// This lets an owner reauthorize the SAME source after token rotation without
// treating a different representation or arbitrary query as interchangeable.
// The returned value is used only for SHA-256, never logged or persisted.
func mp09StableSourceURL(raw string) string {
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" || u.User != nil || u.Fragment != "" ||
		(u.Scheme != "https" && u.Scheme != "http") {
		// Invalid URLs fail later through the real manifest broker; keep this
		// opaque input distinct from all syntactically valid sources.
		return "invalid:" + raw
	}
	u.Scheme = strings.ToLower(u.Scheme)
	u.Host = strings.ToLower(u.Host)
	query := u.Query()
	for key := range query {
		// Mirror engine/media/resource.go's transport-only signed-query policy.
		// Do NOT drop arbitrary "session", "policy", "key" or custom fields:
		// they may be part of the logical media identity.
		switch strings.ToLower(key) {
		case "sig", "signature", "token", "access_token", "auth", "expires", "expiry",
			"x-amz-signature", "x-amz-credential", "x-amz-date", "x-amz-expires", "x-amz-security-token":
			query.Del(key)
		}
	}
	u.RawQuery = query.Encode()
	return u.String()
}

func mp09SourceBinding(root string, req mp09LiveCommand) string {
	value := strings.Join([]string{req.Protocol, mp09StableSourceURL(root),
		mp09StableSourceURL(req.VideoURL), mp09StableSourceURL(req.AudioURL),
		req.VideoRepresentationID, req.AudioRepresentationID}, "\x00")
	sum := sha256.Sum256([]byte(value))
	return "sha256:" + hex.EncodeToString(sum[:])
}

func mp09SessionRequest(ctx context.Context, inv *Invocation, request map[string]any) ([]byte, error) {
	if inv == nil || ctx == nil {
		return nil, errMP09Restore
	}
	request["mp09_live"] = true
	raw, err := json.Marshal(request)
	if err != nil {
		return nil, errMP09Restore
	}
	reply, err := inv.PlatformRequest(ctx, platform.AndroidFragmentStore, platform.Refs{}, raw)
	if err != nil || !reply.OK || len(reply.Payload) == 0 || len(reply.Payload) > 512<<10 {
		return nil, errMP09Restore
	}
	var ok struct {
		OK bool `json:"ok"`
	}
	if json.Unmarshal(reply.Payload, &ok) != nil || !ok.OK {
		return nil, errMP09Restore
	}
	return reply.Payload, nil
}
func mp09BeginSession(ctx context.Context, inv *Invocation, capture, root string, req mp09LiveCommand, now time.Time) error {
	_, err := mp09SessionRequest(ctx, inv, map[string]any{
		"action": "session_begin", "capture_id": capture,
		"binding_sha256":      mp09SourceBinding(root, req),
		"started_at_epoch_ms": now.UnixMilli(), "generation": int64(1),
		"protocol": req.Protocol, "require_audio": req.RequireAudio,
		"dvr_capable": req.DVRCapable, "user_limit_ms": req.UserLimitMS,
		"user_limit_bytes": req.UserLimitBytes, "destination_key": req.DestinationKey,
		"fresh_user_start": req.Action == "start",
	})
	return err
}
func mp09ReadSession(ctx context.Context, inv *Invocation, capture, root string, req mp09LiveCommand, now time.Time) (mp09StoredSession, error) {
	var empty mp09StoredSession
	payload, err := mp09SessionRequest(ctx, inv, map[string]any{"action": "session_read", "capture_id": capture})
	if err != nil {
		return empty, err
	}
	var meta mp09StoredSession
	if json.Unmarshal(payload, &meta) != nil || !meta.OK ||
		meta.Binding != mp09SourceBinding(root, req) ||
		meta.Protocol != req.Protocol || !meta.RequireAudio || !req.RequireAudio ||
		meta.DVR != req.DVRCapable || meta.LimitMS != req.UserLimitMS ||
		meta.LimitBytes != req.UserLimitBytes || meta.Generation != 1 ||
		meta.Phase != "recording" || meta.StartedMS <= 0 || meta.StartedMS > now.UnixMilli() ||
		now.Sub(time.UnixMilli(meta.StartedMS)) > 365*24*time.Hour {
		return empty, errMP09Restore
	}
	return meta, nil
}

// A publishing phase is recorded before invoking MP08. After a crash,
// no interrupted session may be resumed or re-published without review.
func mp09SetSessionPhase(ctx context.Context, inv *Invocation, capture, phase string) error {
	if phase != "publishing" && phase != "published" {
		return errMP09Restore
	}
	payload, err := mp09SessionRequest(ctx, inv, map[string]any{
		"action": "session_phase", "capture_id": capture, "phase": phase,
	})
	if err != nil {
		return err
	}
	var receipt struct {
		Phase string `json:"phase"`
	}
	if json.Unmarshal(payload, &receipt) != nil || receipt.Phase != phase {
		return errMP09Restore
	}
	return nil
}
func mp09InspectSession(ctx context.Context, inv *Invocation, capture string) (string, error) {
	payload, err := mp09SessionRequest(ctx, inv, map[string]any{"action": "session_status", "capture_id": capture})
	if err != nil {
		return "", err
	}
	var row struct {
		Phase string `json:"phase"`
	}
	if json.Unmarshal(payload, &row) != nil {
		return "", errMP09Restore
	}
	switch row.Phase {
	case "missing", "recording", "publishing", "published", "published_clean":
		return row.Phase, nil
	}
	return "", errMP09Restore
}
func mp09FinishSession(ctx context.Context, inv *Invocation, capture string) error {
	_, err := mp09SessionRequest(ctx, inv, map[string]any{"action": "session_finish", "capture_id": capture})
	return err
}

type mp09RecoveredFragmentWire struct {
	FragmentID string                 `json:"fragment_id"`
	Generation int64                  `json:"generation"`
	Hash       string                 `json:"hash"`
	Length     int64                  `json:"length"`
	Role       string                 `json:"role"`
	TrackRole  string                 `json:"track_role"`
	Artifact   string                 `json:"artifact_ref"`
	Identity   media.FragmentIdentity `json:"identity"`
}

func (s *mp09AndroidStore) mp09RestoreVerified(ctx context.Context, role string, generation int64) error {
	if s == nil || s.base == nil || s.base.inv == nil || (role != "video" && role != "audio") {
		return errMP09Restore
	}
	raw, err := mp09SessionRequest(ctx, s.base.inv, map[string]any{
		"action": "inventory", "capture_id": s.base.captureID, "track_role": role,
	})
	if err != nil {
		return err
	}
	var inventory struct {
		Records          []mp09RecoveredFragmentWire `json:"records"`
		UnboundFragments int                         `json:"unbound_fragments"`
	}
	if json.Unmarshal(raw, &inventory) != nil || inventory.Records == nil || len(inventory.Records) > 4096 || inventory.UnboundFragments != 0 {
		return errMP09Restore
	}
	for _, item := range inventory.Records {
		if item.TrackRole != role || (item.Role != "media" && item.Role != role && item.Role != "init") ||
			(role == "audio" && item.Role == "video") || (role == "video" && item.Role == "audio") ||
			item.Generation != generation || item.Length <= 0 || item.Length > 2<<20 ||
			len(item.Hash) != 71 || !strings.HasPrefix(item.Hash, "sha256:") ||
			item.Role != "media" && item.Role != "init" && item.Role != role ||
			item.Identity.Protocol != media.FragmentProtocolHLS && item.Identity.Protocol != media.FragmentProtocolDASH ||
			item.Identity.ResourceID == "" || strings.Contains(item.Identity.ResourceID, "://") ||
			len(item.Artifact) > 240 || !strings.HasPrefix(item.Artifact, "parts/") ||
			strings.Contains(item.Artifact, "..") {
			return errMP09Restore
		}
		id, ee := media.FragmentID(item.Identity)
		if ee != nil || id != item.FragmentID || s.records[id].ID != "" {
			return errMP09Restore
		}
		rec := media.FragmentRecord{ID: id, Identity: item.Identity, Role: item.Role,
			State: media.FragmentCommitted, Hash: item.Hash, ExpectedLength: item.Length,
			AttemptGeneration: item.Generation, LocalArtifactRef: item.Artifact, DurableBytesWritten: true}
		if ee = s.base.VerifyCommitted(rec); ee != nil {
			return errMP09Restore
		}
		// MP08-grade readback/rehash is the only admissible recovered receipt.
		s.records[id] = rec
		bytes, ee := s.ReadVerified(rec.Identity)
		if ee != nil || int64(len(bytes)) != rec.ExpectedLength {
			delete(s.records, id)
			return errMP09Restore
		}
	}
	return nil
}

// mp09Rehydrate binds recovered records to ONE fresh Go LiveSession. The
// journal's private artifact refs never escape the engine's transient host.
func mp09Rehydrate(session *media.LiveSession, now time.Time,
	video, audio *mp09AndroidStore, videoPoll, audioPoll *media.LivePollEngine) error {
	if session == nil || video == nil || videoPoll == nil || audio == nil || audioPoll == nil {
		return errMP09Restore
	}
	for _, store := range []*mp09AndroidStore{video, audio} {
		for _, record := range store.CommittedRecords() {
			if record.Role == "init" {
				if store.VerifyCommitted(record) != nil {
					return errMP09Restore
				}
				continue
			}
			if err := session.ObserveCommitted(now, store, record); err != nil {
				return errMP09Restore
			}
		}
	}
	if err := videoPoll.MP09RestoreVerifiedTimeline(video.CommittedRecords()); err != nil {
		return errMP09Restore
	}
	if err := audioPoll.MP09RestoreVerifiedTimeline(audio.CommittedRecords()); err != nil {
		return errMP09Restore
	}
	// A process death is an explicit network interruption. Mark recoverable
	// even when all old fragments were reattached at the same timestamp;
	// a subsequent *healthy* poll, not journal readback, may resume capturing.
	if err := session.NetworkFailure(now); err != nil {
		return errMP09Restore
	}
	return nil
}

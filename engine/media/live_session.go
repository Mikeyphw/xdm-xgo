package media

// MP09 P01: live-session policy and durable-fragment ownership.
// This is NOT the native recorder, muxer or publisher. Every Stop & Save
// receipt remains unqualified until the existing MP08 media verifier and
// publisher complete actual staged-byte and published-byte checks.

import (
	"context"
	"errors"
	"math"
	"regexp"
	"strings"
	"sync"
	"time"
)

var (
	ErrLiveSessionInvalid    = errors.New("MP09 invalid live session")
	ErrLiveSessionState      = errors.New("MP09 invalid live transition")
	ErrLiveSessionClock      = errors.New("MP09 non-monotonic observation")
	ErrLiveSessionGeneration = errors.New("MP09 stale fragment generation")
	ErrLiveSessionDurability = errors.New("MP09 fragment not readback-verified")
	ErrLiveSessionConflict   = errors.New("MP09 conflicting durable fragment")
	ErrLiveSessionNoMedia    = errors.New("MP09 no verified media to stage")
	ErrLiveSessionNoDVR      = errors.New("MP09 pause requires DVR-capable source")
)

// LiveSessionState describes the logical recording session, never an FFmpeg
// process state or a claim of published playable output.
type LiveSessionState string

const (
	LiveSessionCapturing     LiveSessionState = "capturing"
	LiveSessionRecoverable   LiveSessionState = "recoverable"
	LiveSessionPaused        LiveSessionState = "paused"
	LiveSessionStopPending   LiveSessionState = "stop_pending_verification"
	LiveSessionCancelPending LiveSessionState = "cancel_pending_cleanup"
)

// Recording limits are *only* set by an explicit user choice. A zero bound
// means unlimited, including across arbitrary wall-clock and idle periods.
type LiveSessionPolicy struct {
	SourceDVRCapable bool
	// IdleTimeout influences retry/recovery state only, never Stop & Save.
	IdleTimeout time.Duration
	// PollTimeout bounds a single network operation, never the session lifetime.
	PollTimeout         time.Duration
	UserMaxDuration     time.Duration
	UserMaxDurableBytes int64
}

// LiveSessionReceipt is intentionally safe to serialize to logs or UI. It
// contains no media URLs, cookies, credential refs or artifact paths.
type LiveSessionReceipt struct {
	SchemaVersion           int              `json:"schema_version"`
	SessionID               string           `json:"session_id"`
	Generation              int64            `json:"generation"`
	State                   LiveSessionState `json:"state"`
	DurableFragments        int              `json:"durable_fragments"`
	DurableBytes            int64            `json:"durable_bytes"`
	HasGaps                 bool             `json:"has_gaps"`
	UserBoundReached        bool             `json:"user_bound_reached"`
	MuxVerificationRequired bool             `json:"mux_verification_required"`
	PartialReviewRequired   bool             `json:"partial_review_required"`
	CleanupRequired         bool             `json:"cleanup_required"`
	DownloadReady           bool             `json:"download_ready"`
	Published               bool             `json:"published"`
}

type LiveSession struct {
	mu           sync.Mutex
	id           string
	generation   int64
	startedAt    time.Time
	lastSeen     time.Time
	lastProgress time.Time
	policy       LiveSessionPolicy
	state        LiveSessionState
	parts        map[string]FragmentRecord
	bytes        int64
	gaps         bool
	reachedBound bool
}

var mp09LiveID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,96}$`)

func NewLiveSession(id string, generation int64, now time.Time, p LiveSessionPolicy) (*LiveSession, error) {
	if !mp09LiveID.MatchString(id) || generation <= 0 || now.IsZero() ||
		p.IdleTimeout < 0 || p.PollTimeout < 0 || p.UserMaxDuration < 0 || p.UserMaxDurableBytes < 0 {
		return nil, ErrLiveSessionInvalid
	}
	return &LiveSession{id: id, generation: generation, startedAt: now, lastSeen: now, lastProgress: now,
		policy: p, state: LiveSessionCapturing, parts: make(map[string]FragmentRecord)}, nil
}

func (s *LiveSession) timestamp(now time.Time) error {
	if now.IsZero() || now.Before(s.lastSeen) {
		return ErrLiveSessionClock
	}
	s.lastSeen = now
	return nil
}

func (s *LiveSession) receipt() LiveSessionReceipt {
	return LiveSessionReceipt{SchemaVersion: 1, SessionID: s.id, Generation: s.generation,
		State: s.state, DurableFragments: len(s.parts), DurableBytes: s.bytes, HasGaps: s.gaps,
		UserBoundReached: s.reachedBound, MuxVerificationRequired: s.state == LiveSessionStopPending,
		PartialReviewRequired: s.gaps, CleanupRequired: s.state == LiveSessionCancelPending,
		DownloadReady: false, Published: false}
}

func (s *LiveSession) Snapshot() (LiveSessionReceipt, error) {
	if s == nil {
		return LiveSessionReceipt{}, ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.receipt(), nil
}

// ObserveCommitted accepts only an MP05 durable-store readback-verified record.
// An identity replay is idempotent; changed bytes or generation are refused.
func (s *LiveSession) ObserveCommitted(now time.Time, sink DurableFragmentSink, rec FragmentRecord) error {
	if s == nil {
		return ErrLiveSessionInvalid
	}
	if rec.AttemptGeneration != s.generation {
		return ErrLiveSessionGeneration
	}
	if sink == nil || rec.State != FragmentCommitted ||
		!rec.DurableBytesWritten || rec.ExpectedLength <= 0 || len(rec.Hash) != 71 ||
		!strings.HasPrefix(rec.Hash, "sha256:") || rec.LocalArtifactRef == "" ||
		(rec.Role != "video" && rec.Role != "audio" && rec.Role != "media") {
		return ErrLiveSessionDurability
	}
	for _, c := range rec.Hash[len("sha256:"):] {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			return ErrLiveSessionDurability
		}
	}
	if rec.Identity.Protocol != FragmentProtocolHLS && rec.Identity.Protocol != FragmentProtocolDASH {
		return ErrLiveSessionDurability
	}
	ident, err := FragmentID(rec.Identity)
	if err != nil || ident != rec.ID {
		return ErrLiveSessionDurability
	}
	if err = sink.VerifyCommitted(rec); err != nil {
		return ErrLiveSessionDurability
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err = s.timestamp(now); err != nil {
		return err
	}
	if s.state != LiveSessionCapturing && s.state != LiveSessionRecoverable {
		return ErrLiveSessionState
	}
	if old, ok := s.parts[ident]; ok {
		if old.Hash != rec.Hash || old.ExpectedLength != rec.ExpectedLength || old.LocalArtifactRef != rec.LocalArtifactRef || old.AttemptGeneration != rec.AttemptGeneration || old.Role != rec.Role {
			return ErrLiveSessionConflict
		}
		return nil
	}
	if rec.ExpectedLength > math.MaxInt64-s.bytes {
		return ErrLiveSessionInvalid
	}
	s.parts[ident] = rec
	s.bytes += rec.ExpectedLength
	s.lastProgress = now
	s.state = LiveSessionCapturing
	s.checkUserLimits(now)
	return nil
}

func (s *LiveSession) checkUserLimits(now time.Time) {
	if (s.policy.UserMaxDuration > 0 && now.Sub(s.startedAt) >= s.policy.UserMaxDuration) ||
		(s.policy.UserMaxDurableBytes > 0 && s.bytes >= s.policy.UserMaxDurableBytes) {
		s.reachedBound = true
		s.state = LiveSessionStopPending
	}
}

// Tick checks inactivity and explicit user limits. An idle timeout can only
// request a recovery/retry; it cannot stop or publish a recording.
func (s *LiveSession) Tick(now time.Time) (LiveSessionReceipt, error) {
	if s == nil {
		return LiveSessionReceipt{}, ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.timestamp(now); err != nil {
		return LiveSessionReceipt{}, err
	}
	if s.state == LiveSessionCapturing || s.state == LiveSessionRecoverable {
		s.checkUserLimits(now)
		if s.state != LiveSessionStopPending && s.policy.IdleTimeout > 0 && now.Sub(s.lastProgress) >= s.policy.IdleTimeout {
			s.state = LiveSessionRecoverable
		}
	}
	return s.receipt(), nil
}

// PollContext creates a deadline for ONE remote manifest/segment request.
// Canceling this context cannot change the recording state or mark it done.
func (s *LiveSession) PollContext(parent context.Context) (context.Context, context.CancelFunc, error) {
	if s == nil || parent == nil {
		return nil, nil, ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.state != LiveSessionCapturing && s.state != LiveSessionRecoverable {
		return nil, nil, ErrLiveSessionState
	}
	if s.policy.PollTimeout > 0 {
		ctx, cancel := context.WithTimeout(parent, s.policy.PollTimeout)
		return ctx, cancel, nil
	}
	ctx, cancel := context.WithCancel(parent)
	return ctx, cancel, nil
}

// NetworkFailure never terminates a live recording. The caller can retry
// according to its own policy and later Resume after the transport recovers.
func (s *LiveSession) NetworkFailure(now time.Time) error {
	if s == nil {
		return ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.timestamp(now); err != nil {
		return err
	}
	if s.state != LiveSessionCapturing && s.state != LiveSessionRecoverable {
		return ErrLiveSessionState
	}
	s.state = LiveSessionRecoverable
	return nil
}

// MarkGap is explicit partial-media evidence, not a successful fragment.
func (s *LiveSession) MarkGap(now time.Time) error {
	if s == nil {
		return ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.timestamp(now); err != nil {
		return err
	}
	if s.state != LiveSessionCapturing && s.state != LiveSessionRecoverable {
		return ErrLiveSessionState
	}
	s.gaps = true
	return nil
}

func (s *LiveSession) Pause(now time.Time) error {
	if s == nil {
		return ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.timestamp(now); err != nil {
		return err
	}
	if !s.policy.SourceDVRCapable {
		return ErrLiveSessionNoDVR
	}
	if s.state != LiveSessionCapturing && s.state != LiveSessionRecoverable {
		return ErrLiveSessionState
	}
	s.state = LiveSessionPaused
	return nil
}

func (s *LiveSession) Resume(now time.Time) error {
	if s == nil {
		return ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.timestamp(now); err != nil {
		return err
	}
	if s.state != LiveSessionPaused && s.state != LiveSessionRecoverable {
		return ErrLiveSessionState
	}
	s.state = LiveSessionCapturing
	s.lastProgress = now // restarting the observation window is NOT a session reset
	s.checkUserLimits(now)
	return nil
}

// StopAndSave only requests mux/FFprobe/Go-published-byte verification. It
// never claims DownloadReady and cannot publish with zero durable fragments.
func (s *LiveSession) StopAndSave(now time.Time) (LiveSessionReceipt, error) {
	if s == nil {
		return LiveSessionReceipt{}, ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.timestamp(now); err != nil {
		return LiveSessionReceipt{}, err
	}
	if s.state == LiveSessionCancelPending {
		return LiveSessionReceipt{}, ErrLiveSessionState
	}
	if len(s.parts) == 0 {
		return s.receipt(), ErrLiveSessionNoMedia
	}
	s.state = LiveSessionStopPending
	return s.receipt(), nil
}

// CancelAndDiscard requests owner cleanup. The receipt remains explicitly
// pending until the actual durable store confirms all artifacts are gone.
func (s *LiveSession) CancelAndDiscard(now time.Time) (LiveSessionReceipt, error) {
	if s == nil {
		return LiveSessionReceipt{}, ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.timestamp(now); err != nil {
		return LiveSessionReceipt{}, err
	}
	if s.state == LiveSessionStopPending && len(s.parts) > 0 {
		return LiveSessionReceipt{}, ErrLiveSessionState
	}
	s.state = LiveSessionCancelPending
	return s.receipt(), nil
}

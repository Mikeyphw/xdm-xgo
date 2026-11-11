package media

// MP09 consolidated: one recording lifetime, multiple independently selected
// renditions, request-scoped deadlines and verified Stop & Save.
// The user/Android host supplies the authorized fetchers, durable stores and
// typed MP08 publisher. This layer never opens sockets or runs arbitrary argv.
import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

var (
	ErrMP09Track    = errors.New("MP09 invalid or conflicting track")
	ErrMP09Partial  = errors.New("MP09 gap or missing durable fragment: partial review required")
	ErrMP09NotReady = errors.New("MP09 recording must stop before publishing")
	ErrMP09Cleanup  = errors.New("MP09 durable cleanup not confirmed")
)

type MP09TrackBinding struct {
	Role  string // video or audio; never guessed from a manifest
	Poll  *LivePollEngine
	Store MP08VerifiedStore
}

type MP09TrackStatus struct {
	Role       string `json:"role"`
	Due        bool   `json:"due"`
	Ended      bool   `json:"ended"`
	NewDurable int    `json:"new_durable"`
	Recorded   int    `json:"recorded"`
	Partial    bool   `json:"partial"`
}

type MP09RecordingStatus struct {
	SchemaVersion         int               `json:"schema_version"`
	State                 LiveSessionState  `json:"state"`
	DurableFragments      int               `json:"durable_fragments"`
	DurableBytes          int64             `json:"durable_bytes"`
	TrackCount            int               `json:"track_count"`
	Tracks                []MP09TrackStatus `json:"tracks"`
	NextPollAfter         time.Duration     `json:"next_poll_after"`
	PartialReviewRequired bool              `json:"partial_review_required"`
	DownloadReady         bool              `json:"download_ready"`
	Published             bool              `json:"published"`
	AllTracksEnded        bool              `json:"all_tracks_ended"`
}

type mp09BoundTrack struct {
	role     string
	poll     *LivePollEngine
	store    MP08VerifiedStore
	next     time.Time
	ended    bool
	failures int
}

type MP09Recording struct {
	mu           sync.Mutex
	session      *LiveSession
	tracks       []*mp09BoundTrack
	requireAudio bool
	stopped      bool
	cancelled    bool
	finalized    bool
}

// NewMP09Recording requires explicit role and rendition selection. One
// LiveSession owns the lifetime across every track and the same generation
// is enforced for all verified fragments, including on reconnect.
func NewMP09Recording(session *LiveSession, requireAudio bool, tracks ...MP09TrackBinding) (*MP09Recording, error) {
	if session == nil || len(tracks) == 0 || len(tracks) > 2 {
		return nil, ErrMP09Track
	}
	out := &MP09Recording{session: session, requireAudio: requireAudio}
	seen := map[string]bool{}
	for _, t := range tracks {
		if t.Role != "video" && t.Role != "audio" {
			return nil, ErrMP09Track
		}
		if seen[t.Role] || t.Poll == nil || t.Store == nil || t.Poll.session != session {
			return nil, ErrMP09Track
		}
		if t.Poll.store != t.Store {
			return nil, ErrMP09Track
		}
		seen[t.Role] = true
		out.tracks = append(out.tracks, &mp09BoundTrack{role: t.Role, poll: t.Poll, store: t.Store, next: session.startedAt})
	}
	if !seen["video"] || (requireAudio && !seen["audio"]) {
		return nil, ErrMP09Track
	}
	sort.Slice(out.tracks, func(i, j int) bool { return out.tracks[i].role > out.tracks[j].role }) // video first
	return out, nil
}

func (r *MP09Recording) status(after time.Duration) (MP09RecordingStatus, error) {
	s, err := r.session.Snapshot()
	if err != nil {
		return MP09RecordingStatus{}, err
	}
	out := MP09RecordingStatus{SchemaVersion: 1, State: s.State, DurableFragments: s.DurableFragments,
		DurableBytes: s.DurableBytes, TrackCount: len(r.tracks), NextPollAfter: after,
		PartialReviewRequired: s.PartialReviewRequired || s.HasGaps, DownloadReady: false, Published: false}
	allEnded := len(r.tracks) > 0
	for _, t := range r.tracks {
		out.Tracks = append(out.Tracks, MP09TrackStatus{Role: t.role, Ended: t.ended, Partial: out.PartialReviewRequired})
		allEnded = allEnded && t.ended
	}
	out.AllTracksEnded = allEnded
	return out, nil
}

// PollDue executes due observations, never a fixed duration or a fixed number
// of polls. One failed track does not silently complete another track.
// Network errors yield recoverable states and bounded retry delays.
func (r *MP09Recording) PollDue(ctx context.Context, now time.Time) (MP09RecordingStatus, error) {
	if r == nil || ctx == nil {
		return MP09RecordingStatus{}, ErrMP09Track
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.stopped || r.cancelled || r.finalized {
		return MP09RecordingStatus{}, ErrLiveSessionState
	}
	snapshot, err := r.session.Snapshot()
	if err != nil {
		return MP09RecordingStatus{}, err
	}
	if snapshot.State == LiveSessionPaused || snapshot.State == LiveSessionStopPending {
		return r.status(0)
	}
	smallest := 30 * time.Second
	var firstErr error
	for _, t := range r.tracks {
		if t.ended {
			continue
		}
		if now.Before(t.next) {
			if d := t.next.Sub(now); d < smallest {
				smallest = d
			}
			continue
		}
		got, e := t.poll.Poll(ctx, now)
		if errors.Is(e, ErrLiveSessionState) {
			// A user-configured duration/byte bound may have switched the
			// shared session into StopPending during this poll. Surface the
			// pending state instead of treating a requested limit as corruption.
			snap, readErr := r.session.Snapshot()
			if readErr == nil && snap.State == LiveSessionStopPending {
				return r.status(0)
			}
		}
		if e != nil && !errors.Is(e, ErrLivePollFetch) && !errors.Is(e, ErrLivePollIncomplete) {
			return MP09RecordingStatus{}, e
		}
		if e != nil {
			t.failures++
			// Network interruption never marks completed. Bound the retry wait,
			// not the total recording lifetime. Gaps persist for partial review.
			if firstErr == nil {
				firstErr = e
			}
		} else {
			t.failures = 0
		}
		delay := got.NextPollAfter
		if e != nil {
			delay = 2 * time.Second
			for i := 1; i < t.failures && i < 5; i++ {
				delay *= 2
			}
			if delay > 30*time.Second {
				delay = 30 * time.Second
			}
		}
		delay = livePollInterval(delay)
		t.next = now.Add(delay)
		if got.SourceEnded && e == nil {
			t.ended = true
		}
		if delay < smallest {
			smallest = delay
		}
	}
	if smallest < 100*time.Millisecond {
		smallest = 100 * time.Millisecond
	}
	s, err := r.status(smallest)
	return s, errors.Join(firstErr, err)
}

func (r *MP09Recording) Pause(now time.Time) error {
	if r == nil {
		return ErrMP09Track
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.stopped || r.cancelled {
		return ErrLiveSessionState
	}
	return r.session.Pause(now)
}
func (r *MP09Recording) Resume(now time.Time) error {
	if r == nil {
		return ErrMP09Track
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.stopped || r.cancelled {
		return ErrLiveSessionState
	}
	if err := r.session.Resume(now); err != nil {
		return err
	}
	for _, t := range r.tracks {
		if !t.ended {
			t.next = now
		}
	}
	return nil
}

// Stop freezes polling before building a Go-sealed MP08 plan. No pending or
// partial session is ever presented as an already published download.
func (r *MP09Recording) Stop(now time.Time) (MP09RecordingStatus, error) {
	if r == nil {
		return MP09RecordingStatus{}, ErrMP09Track
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.cancelled || r.finalized {
		return MP09RecordingStatus{}, ErrLiveSessionState
	}
	// A failed MP08 mux/probe/publish must not strand the user. The same
	// stopped recording may be retried or explicitly discarded.
	if r.stopped {
		snapshot, err := r.session.Snapshot()
		if err != nil || snapshot.State != LiveSessionStopPending {
			return MP09RecordingStatus{}, ErrLiveSessionState
		}
		return r.status(0)
	}
	if _, err := r.session.StopAndSave(now); err != nil {
		return MP09RecordingStatus{}, err
	}
	r.stopped = true
	return r.status(0)
}

// Finalize performs the actual MP08 final-stage and published-byte readback.
// An expected duration is a *measured bounded clip*, never a VOD-provided
// arbitrary lifetime cap. FFprobe will refuse a mismatched duration.
func (r *MP09Recording) Finalize(ctx context.Context, destination string, expectedDuration time.Duration, host MP08Host) (MP08FinalizationReceipt, error) {
	fail := MP08FinalizationReceipt{SchemaVersion: MP08SchemaV1, Status: "refused", DownloadReady: false}
	if r == nil || ctx == nil || host == nil {
		return fail, ErrMP09NotReady
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if !r.stopped || r.cancelled || r.finalized {
		return fail, ErrMP09NotReady
	}
	s, e := r.session.Snapshot()
	if e != nil {
		return fail, e
	}
	if s.HasGaps || s.PartialReviewRequired {
		return fail, ErrMP09Partial
	}
	plan, e := mp09LiveMP08Plan(r.tracks, r.requireAudio, destination, expectedDuration)
	if e != nil {
		return fail, e
	}
	result, e := RunMP08VerifiedPublication(ctx, plan, host)
	if e != nil {
		return result, e
	}
	if !result.DownloadReady || result.Status != "completed" {
		return fail, ErrMP08Publication
	}
	r.finalized = true
	return result, nil
}

// Discard only reports success after a caller-owned durable cleanup authority
// verifies deletion. It intentionally cannot delete files through a path string.
type MP09VerifiedDiscard interface {
	DiscardAndVerify(context.Context, []FragmentRecord) error
}

func (r *MP09Recording) Cancel(ctx context.Context, now time.Time, cleaner MP09VerifiedDiscard) (MP09RecordingStatus, error) {
	if r == nil || ctx == nil || cleaner == nil {
		return MP09RecordingStatus{}, ErrMP09Cleanup
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.finalized || r.cancelled {
		return MP09RecordingStatus{}, ErrLiveSessionState
	}
	// A failed Stop & Save is still discardable by a new explicit user
	// action. A failed previous cleanup can be retried; no success is claimed.
	s, e := r.session.CancelExplicitForMP09(now)
	if e != nil {
		return MP09RecordingStatus{}, e
	}
	var records []FragmentRecord
	for _, t := range r.tracks {
		records = append(records, t.store.CommittedRecords()...)
	}
	if err := cleaner.DiscardAndVerify(ctx, records); err != nil {
		out, _ := r.status(0)
		return out, ErrMP09Cleanup
	}
	r.cancelled = true
	return MP09RecordingStatus{SchemaVersion: 1, State: s.State, TrackCount: len(r.tracks),
		DownloadReady: false, Published: false}, nil
}

func mp09LiveMP08Plan(tracks []*mp09BoundTrack, requiredAudio bool, dest string, duration time.Duration) (MP08FinalizationPlan, error) {
	if duration < time.Second || duration > 24*time.Hour || len(tracks) == 0 {
		return MP08FinalizationPlan{}, ErrMP09NotReady
	}
	plan := MP08FinalizationPlan{SchemaVersion: MP08SchemaV1, DestinationKey: dest,
		Container: "mp4", ExpectedDurationMS: int64(duration / time.Millisecond), RequireAudio: requiredAudio}
	firstProtocol := FragmentProtocol("")
	for _, t := range tracks {
		records := t.store.CommittedRecords()
		mediaParts := make([]FragmentRecord, 0, len(records))
		initial := map[string][]FragmentRecord{}
		for _, rec := range records {
			if rec.AttemptGeneration != t.poll.session.generation || rec.State != FragmentCommitted || !mp08Proof(t.store, rec) {
				return MP08FinalizationPlan{}, ErrMP08MissingProof
			}
			if rec.Role == "init" {
				initial[strings.TrimPrefix(rec.Identity.TimelineKey, "init:")] = append(initial[strings.TrimPrefix(rec.Identity.TimelineKey, "init:")], rec)
				continue
			}
			if rec.Role != "media" && rec.Role != t.role {
				return MP08FinalizationPlan{}, ErrMP09Track
			}
			if firstProtocol == "" {
				firstProtocol = rec.Identity.Protocol
			} else if firstProtocol != rec.Identity.Protocol {
				return MP08FinalizationPlan{}, ErrMP09Track
			}
			mediaParts = append(mediaParts, rec)
		}
		if len(mediaParts) == 0 || len(mediaParts) > 4096 {
			return MP08FinalizationPlan{}, ErrMP09Partial
		}
		// Timeline numeric sort: HLS discontinuity/sequence and DASH period,
		// start-time/number. Lexicographic ordering would corrupt e.g. 9 -> 10.
		sort.Slice(mediaParts, func(i, j int) bool {
			return mp09Earlier(mediaParts[i].Identity.TimelineKey, mediaParts[j].Identity.TimelineKey)
		})
		if err := mp09Continuous(mediaParts); err != nil {
			return MP08FinalizationPlan{}, err
		}
		track := MP08Track{Role: t.role, PeriodID: "mp09", StartMS: 0, DurationMS: plan.ExpectedDurationMS,
			Parts: mediaParts, store: t.store}
		for _, p := range mediaParts {
			list := initial[p.Identity.TimelineKey]
			if len(list) > 1 {
				return MP08FinalizationPlan{}, ErrMP09Partial
			}
			if len(list) == 1 {
				a := list[0]
				track.InitForPart = append(track.InitForPart, &a)
				if track.Init == nil {
					track.Init = &a
				}
			} else {
				track.InitForPart = append(track.InitForPart, nil)
			}
		}
		plan.Tracks = append(plan.Tracks, track)
	}
	if firstProtocol == FragmentProtocolHLS {
		plan.Source = "hls_live"
	} else if firstProtocol == FragmentProtocolDASH {
		plan.Source = "dash_live"
	} else {
		return MP08FinalizationPlan{}, ErrMP09Track
	}
	if err := mp08CheckPlan(plan); err != nil {
		return MP08FinalizationPlan{}, err
	}
	plan.validated = true
	plan.seal = mp08PlanSeal(plan)
	return plan, nil
}
func mp09Earlier(a, b string) bool {
	ap, bp := strings.Split(a, ":"), strings.Split(b, ":")
	for i := 0; i < len(ap) && i < len(bp); i++ {
		aa, ea := strconv.ParseInt(ap[i], 10, 64)
		bb, eb := strconv.ParseInt(bp[i], 10, 64)
		if ea == nil && eb == nil {
			if aa != bb {
				return aa < bb
			}
			continue
		}
		if ap[i] != bp[i] {
			return ap[i] < bp[i]
		}
	}
	return len(ap) < len(bp)
}
func mp09Continuous(records []FragmentRecord) error {
	for i := 1; i < len(records); i++ {
		a, b := records[i-1].Identity.TimelineKey, records[i].Identity.TimelineKey
		aa, bb := strings.Split(a, ":"), strings.Split(b, ":")
		if len(aa) != len(bb) || len(aa) < 3 || aa[0] != bb[0] {
			return ErrMP09Partial
		}
		if aa[0] == "hls" {
			ad, e := strconv.ParseInt(aa[1], 10, 64)
			bd, f := strconv.ParseInt(bb[1], 10, 64)
			as, g := strconv.ParseInt(aa[2], 10, 64)
			bs, h := strconv.ParseInt(bb[2], 10, 64)
			if e != nil || f != nil || g != nil || h != nil || bd < ad || bs != as+1 {
				return ErrMP09Partial
			}
		} else if aa[0] == "dash" {
			if aa[1] != bb[1] || aa[2] != bb[2] || aa[3] != bb[3] {
				return ErrMP09Partial
			}
			an, e := strconv.ParseInt(aa[len(aa)-1], 10, 64)
			bn, f := strconv.ParseInt(bb[len(bb)-1], 10, 64)
			if e != nil || f != nil || bn != an+1 {
				return ErrMP09Partial
			}
		} else {
			return ErrMP09Track
		}
	}
	return nil
}

// MP09ResumeVerified re-establishes a session only with fresh, caller-supplied
// authorization and with every existing fragment independently reverified.
// It never persists URL, cookie, token, or credential material.
func MP09ResumeVerified(id string, generation int64, started, now time.Time, policy LiveSessionPolicy, stores ...MP08VerifiedStore) (*LiveSession, error) {
	s, e := NewLiveSession(id, generation, started, policy)
	if e != nil {
		return nil, e
	}
	if now.Before(started) {
		return nil, ErrLiveSessionClock
	}
	for _, store := range stores {
		if store == nil {
			return nil, ErrLiveSessionDurability
		}
		for _, rec := range store.CommittedRecords() {
			if rec.Role == "init" {
				if !mp08Proof(store, rec) {
					return nil, ErrLiveSessionDurability
				}
				continue
			}
			if err := s.ObserveCommitted(now, store, rec); err != nil {
				return nil, err
			}
		}
	}
	if _, err := s.Tick(now); err != nil {
		return nil, fmt.Errorf("MP09 restore clock: %w", err)
	}
	return s, nil
}

// These narrowly scoped accessors avoid exporting mutable session internals.
func (s *LiveSession) StartedAtForMP09() time.Time {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.startedAt
}
func (e *LivePollEngine) BindForMP09(hls HLSFetcher, dash DASHFetcher) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.hls = hls
	e.dash = dash
}
func (r *MP09Recording) SnapshotForMP09() (MP09RecordingStatus, error) {
	if r == nil {
		return MP09RecordingStatus{}, ErrMP09Track
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.status(0)
}

// CancelExplicitForMP09 is invoked only by a user-confirmed destructive command.
// It can supersede an automatic user size/duration stop request before output
// publication, but it never claims that file deletion already happened.
func (s *LiveSession) CancelExplicitForMP09(now time.Time) (LiveSessionReceipt, error) {
	if s == nil {
		return LiveSessionReceipt{}, ErrLiveSessionInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.timestamp(now); err != nil {
		return LiveSessionReceipt{}, err
	}
	s.state = LiveSessionCancelPending
	return s.receipt(), nil
}

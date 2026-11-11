package media

// MP09 P02: bounded, authorized live HLS/DASH manifest polling and actual MP05
// durable fragment staging. No built-in HTTP client, credential serialization,
// mux, FFmpeg process management, foreground service, or file publication.
// A single poll is never a recording lifetime bound.

import (
	"context"
	"errors"
	"strings"
	"sync"
	"time"
)

var (
	ErrLivePollInvalid    = errors.New("MP09 live poll configuration refused")
	ErrLivePollSelection  = errors.New("MP09 live track selection refused")
	ErrLivePollManifest   = errors.New("MP09 live manifest invalid or exceeds resource bound")
	ErrLivePollFetch      = errors.New("MP09 live source fetch failed; recording is recoverable")
	ErrLivePollIncomplete = errors.New("MP09 live fragments incomplete; partial review required")
)

// A real MP05 sink must expose the durable journal for crash-safe replay.
// This is not a synthetic ledger: every restored receipt is readback-verified.
type LivePollStore interface {
	DurableFragmentSink
	CommittedRecords() []FragmentRecord
}

type LivePollSpec struct {
	Protocol FragmentProtocol
	// Secrets, signed query parameters and headers remain transient, never in receipts.
	ManifestURL   string
	CredentialRef string
	// HLS requires an explicitly selected media playlist, not a master.
	// DASH requires one explicitly selected representation. The caller must
	// run independent role-specific sessions for separate audio tracks.
	DASHRepresentationID string
	MaxManifestBytes     int
	MaxFragmentsPerPoll  int
}

// Safe to log: never contains a URL, credential, artifact path, content hash
// or fragment identity. No boolean in this receipt proves playable output.
type LivePollReceipt struct {
	SchemaVersion         int              `json:"schema_version"`
	Protocol              FragmentProtocol `json:"protocol"`
	State                 LiveSessionState `json:"state"`
	ObservedFragments     int              `json:"observed_fragments"`
	NewDurableFragments   int              `json:"new_durable_fragments"`
	TotalDurableFragments int              `json:"total_durable_fragments"`
	TotalDurableBytes     int64            `json:"total_durable_bytes"`
	SourceEnded           bool             `json:"source_ended"`
	GapOrPartial          bool             `json:"gap_or_partial"`
	NextPollAfter         time.Duration    `json:"next_poll_after"`
	DownloadReady         bool             `json:"download_ready"`
	Published             bool             `json:"published"`
}

type LivePollEngine struct {
	mu         sync.Mutex
	session    *LiveSession
	store      LivePollStore
	hls        HLSFetcher
	dash       DASHFetcher
	spec       LivePollSpec
	lastHLSSeq int64
	seenHLS    bool
	lastDASH   map[string]int64
}

func NewLivePollEngine(session *LiveSession, store LivePollStore, hls HLSFetcher, dash DASHFetcher, spec LivePollSpec) (*LivePollEngine, error) {
	if session == nil || store == nil || strings.TrimSpace(spec.ManifestURL) == "" ||
		spec.MaxManifestBytes < 0 || spec.MaxManifestBytes > 2<<20 ||
		spec.MaxFragmentsPerPoll < 0 || spec.MaxFragmentsPerPoll > 512 {
		return nil, ErrLivePollInvalid
	}
	if _, err := NewMediaResource(MediaResourceInput{TransportURL: spec.ManifestURL}); err != nil {
		return nil, ErrLivePollInvalid
	}
	switch spec.Protocol {
	case FragmentProtocolHLS:
		if hls == nil || strings.TrimSpace(spec.DASHRepresentationID) != "" {
			return nil, ErrLivePollSelection
		}
	case FragmentProtocolDASH:
		if dash == nil || !mp07SafeID.MatchString(spec.DASHRepresentationID) {
			return nil, ErrLivePollSelection
		}
	default:
		return nil, ErrLivePollInvalid
	}
	if spec.MaxManifestBytes == 0 {
		spec.MaxManifestBytes = 2 << 20
	}
	if spec.MaxFragmentsPerPoll == 0 {
		spec.MaxFragmentsPerPoll = 128
	}
	return &LivePollEngine{session: session, store: store, hls: hls, dash: dash, spec: spec, lastDASH: make(map[string]int64)}, nil
}

func livePollInterval(d time.Duration) time.Duration {
	if d <= 0 {
		return 3 * time.Second
	}
	if d < 500*time.Millisecond {
		return 500 * time.Millisecond
	}
	if d > 30*time.Second {
		return 30 * time.Second
	}
	return d
}

func (e *LivePollEngine) safeReceipt(sourceEnded bool, observed, newFragments int, after time.Duration) (LivePollReceipt, error) {
	snapshot, err := e.session.Snapshot()
	if err != nil {
		return LivePollReceipt{}, err
	}
	return LivePollReceipt{SchemaVersion: 1, Protocol: e.spec.Protocol, State: snapshot.State,
		ObservedFragments: observed, NewDurableFragments: newFragments,
		TotalDurableFragments: snapshot.DurableFragments, TotalDurableBytes: snapshot.DurableBytes,
		SourceEnded: sourceEnded, GapOrPartial: snapshot.HasGaps || snapshot.PartialReviewRequired,
		NextPollAfter: livePollInterval(after), DownloadReady: false, Published: false}, nil
}

// Poll performs one live manifest observation and durable fragment staging.
// The caller schedules subsequent Poll calls using NextPollAfter, without a
// hidden lifetime ceiling. A terminal source still needs explicit StopAndSave
// and MP08 verification before publication can ever be claimed.
func (e *LivePollEngine) Poll(ctx context.Context, now time.Time) (LivePollReceipt, error) {
	if e == nil || ctx == nil {
		return LivePollReceipt{}, ErrLivePollInvalid
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	snapshot, err := e.session.Tick(now)
	if err != nil {
		return LivePollReceipt{}, err
	}
	if snapshot.State != LiveSessionCapturing && snapshot.State != LiveSessionRecoverable {
		return LivePollReceipt{}, ErrLiveSessionState
	}
	requestCtx, cancel, err := e.session.PollContext(ctx)
	if err != nil {
		return LivePollReceipt{}, err
	}
	var body []byte
	if e.spec.Protocol == FragmentProtocolHLS {
		var r HLSFetchResponse
		r, err = e.hls.FetchHLS(requestCtx, HLSFetchRequest{URI: e.spec.ManifestURL, Kind: HLSFetchManifest, CredentialRef: e.spec.CredentialRef})
		body = r.Bytes
	} else {
		var r DASHFetchResponse
		r, err = e.dash.FetchDASH(requestCtx, DASHFetchRequest{URI: e.spec.ManifestURL, Kind: DASHFetchManifest, CredentialRef: e.spec.CredentialRef})
		body = r.Bytes
	}
	cancel()
	if err != nil {
		_ = e.session.NetworkFailure(now)
		r, _ := e.safeReceipt(false, 0, 0, 3*time.Second)
		return r, ErrLivePollFetch
	}
	if len(body) == 0 || len(body) > e.spec.MaxManifestBytes {
		return LivePollReceipt{}, ErrLivePollManifest
	}
	// Each individual fetch is bound by the same request-scoped policy, not
	// by the recording lifetime. The request context is fresh for this poll.
	stageCtx, stageCancel, err := e.session.PollContext(ctx)
	if err != nil {
		return LivePollReceipt{}, err
	}
	defer stageCancel()
	if e.spec.Protocol == FragmentProtocolHLS {
		return e.pollHLS(stageCtx, now, string(body))
	}
	return e.pollDASH(stageCtx, now, string(body))
}

func (e *LivePollEngine) pollHLS(ctx context.Context, now time.Time, body string) (LivePollReceipt, error) {
	p, err := ParseHLSPlaylist(e.spec.ManifestURL, body)
	if err != nil || p.Kind != HLSPlaylistMedia || len(p.Segments) > e.spec.MaxFragmentsPerPoll || len(p.Segments) == 0 {
		return LivePollReceipt{}, ErrLivePollManifest
	}
	if e.seenHLS {
		first := p.Segments[0].MediaSequence
		if first > e.lastHLSSeq+1 {
			if err = e.session.MarkGap(now); err != nil {
				return LivePollReceipt{}, err
			}
		}
		// A sequence rollback may mean a different stream under the same
		// signed URL. Never mix its fragments into the previous generation.
		if p.Segments[len(p.Segments)-1].MediaSequence < e.lastHLSSeq {
			return LivePollReceipt{}, ErrLivePollManifest
		}
	}
	for _, seg := range p.Segments {
		if seg.Gap {
			if err = e.session.MarkGap(now); err != nil {
				return LivePollReceipt{}, err
			}
		}
	}
	exec, err := NewHLSExecutor(e.hls, nil)
	if err != nil {
		return LivePollReceipt{}, ErrLivePollInvalid
	}
	if err = exec.BindDurableStore(e.store); err != nil {
		return LivePollReceipt{}, ErrLivePollIncomplete
	}
	res, execErr := exec.Execute(ctx, HLSExecutionPlan{BaseURL: e.spec.ManifestURL, Playlists: []string{body}, AttemptGeneration: e.session.generation, CredentialRef: e.spec.CredentialRef})
	observed := 0
	// Read back the exact expected stream identities, never the executor's
	// URL-bearing outcomes. Also rehydrates session state after restart.
	for _, seg := range p.Segments {
		if seg.Gap {
			continue
		}
		id, idErr := HLSTimelineIdentity(seg)
		if idErr != nil {
			return LivePollReceipt{}, ErrLivePollIncomplete
		}
		rec, ok := exec.Ledger().Get(id)
		if !ok || rec.State != FragmentCommitted {
			continue
		}
		if err = e.session.ObserveCommitted(now, e.store, rec); err != nil {
			return LivePollReceipt{}, err
		}
		observed++
	}
	e.lastHLSSeq = p.Segments[len(p.Segments)-1].MediaSequence
	e.seenHLS = true
	if res.Unsupported > 0 || res.KeyFailures > 0 || res.DecryptFailures > 0 || res.FetchFailures > 0 || execErr != nil {
		_ = e.session.MarkGap(now)
		if res.FetchFailures > 0 {
			_ = e.session.NetworkFailure(now)
		}
		r, _ := e.safeReceipt(p.EndList, observed, res.Completed, time.Duration(p.TargetDuration*float64(time.Second))/2)
		return r, ErrLivePollIncomplete
	}
	return e.safeReceipt(p.EndList, observed, res.Completed, time.Duration(p.TargetDuration*float64(time.Second))/2)
}

func (e *LivePollEngine) pollDASH(ctx context.Context, now time.Time, body string) (LivePollReceipt, error) {
	p, err := ParseDASHManifest(e.spec.ManifestURL, body)
	if err != nil {
		return LivePollReceipt{}, ErrLivePollManifest
	}
	all, err := ExpandDASHFragments(p)
	if err != nil || len(all) > e.spec.MaxFragmentsPerPoll*8 {
		return LivePollReceipt{}, ErrLivePollManifest
	}
	selected := make([]DASHFragment, 0)
	for _, f := range all {
		if f.RepresentationID == e.spec.DASHRepresentationID {
			selected = append(selected, f)
		}
	}
	if len(selected) == 0 || len(selected) > e.spec.MaxFragmentsPerPoll {
		return LivePollReceipt{}, ErrLivePollSelection
	}
	// Detect missing media from a previously observed timeline. Period changes
	// have independent counters; first observed sequence can be nonzero.
	pendingLast := make(map[string]int64, len(e.lastDASH))
	for k, v := range e.lastDASH {
		pendingLast[k] = v
	}
	for _, f := range selected {
		key := f.PeriodID + "/" + f.AdaptationID + "/" + f.RepresentationID
		if prev, ok := pendingLast[key]; ok && f.Number > prev+1 {
			if err = e.session.MarkGap(now); err != nil {
				return LivePollReceipt{}, err
			}
		}
		if last, ok := pendingLast[key]; !ok || f.Number > last {
			pendingLast[key] = f.Number
		}
	}
	exec, err := NewDASHExecutor(e.dash, nil)
	if err != nil {
		return LivePollReceipt{}, ErrLivePollInvalid
	}
	if err = exec.BindDurableStore(e.store); err != nil {
		return LivePollReceipt{}, ErrLivePollIncomplete
	}
	res, execErr := exec.Execute(ctx, DASHExecutionPlan{BaseURL: e.spec.ManifestURL, Manifests: []string{body}, AttemptGeneration: e.session.generation, CredentialRef: e.spec.CredentialRef, RepresentationIDs: []string{e.spec.DASHRepresentationID}})
	observed := 0
	for _, f := range selected {
		rec, ok := exec.Ledger().Get(f.Identity)
		if !ok || rec.State != FragmentCommitted {
			continue
		}
		if err = e.session.ObserveCommitted(now, e.store, rec); err != nil {
			return LivePollReceipt{}, err
		}
		observed++
	}
	e.lastDASH = pendingLast
	if res.Unsupported > 0 || res.FetchFailures > 0 || execErr != nil {
		_ = e.session.MarkGap(now)
		if res.FetchFailures > 0 {
			_ = e.session.NetworkFailure(now)
		}
		r, _ := e.safeReceipt(p.Type == DASHStatic, observed, res.Completed, p.MinUpdatePeriod)
		return r, ErrLivePollIncomplete
	}
	return e.safeReceipt(p.Type == DASHStatic, observed, res.Completed, p.MinUpdatePeriod)
}

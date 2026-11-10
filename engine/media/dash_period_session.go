package media

// MP07: deterministic per-period DASH selection and verified staging.
// The caller supplies an authorized MPD body and a DASHFetcher. This layer
// never opens network connections, persists URLs or publishes media output.
import (
	"context"
	"errors"
	"math"
	"regexp"
	"strings"
	"time"
)

var (
	ErrDASHPeriodSelection  = errors.New("MP07 period/representation selection refused")
	ErrDASHPeriodIncomplete = errors.New("MP07 verified period staging incomplete")
)

const (
	DASHPeriodSchemaV1             = 1
	mp07MaxPeriods                 = 16
	mp07MaxTrackFragments          = 4096
	mp07MaxTotalFragments          = 65536
	mp07AlignmentToleranceMS int64 = 250
)

var mp07SafeID = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,128}$`)

type DASHTrackSelector struct {
	AdaptationID     string `json:"adaptation_id"`
	RepresentationID string `json:"representation_id"`
}

func (k DASHTrackSelector) set() bool { return k.AdaptationID != "" || k.RepresentationID != "" }
func (k DASHTrackSelector) valid() bool {
	return mp07SafeID.MatchString(k.AdaptationID) && mp07SafeID.MatchString(k.RepresentationID)
}

type DASHPeriodChoice struct {
	PeriodID string            `json:"period_id"`
	Video    DASHTrackSelector `json:"video"`
	Audio    DASHTrackSelector `json:"audio"`
	Subtitle DASHTrackSelector `json:"subtitle"`
}

type DASHPeriodRequest struct {
	MPDURL            string
	MPDBody           string
	Periods           []DASHPeriodChoice
	AttemptGeneration int64
	CredentialRef     string
	RequireAudio      bool
	// Dynamic MPDs are bounded observations. Never ready for mux/publication.
	DynamicPollBound int
}

type DASHSelectedTrack struct {
	Role             string `json:"role"`
	PeriodID         string `json:"period_id"`
	AdaptationID     string `json:"adaptation_id"`
	RepresentationID string `json:"representation_id"`
	FragmentCount    int    `json:"fragment_count"`
	RequiresInit     bool   `json:"requires_init"`
	// Transient executable plan only; never serialize raw fragment URLs.
	fragments []DASHFragment
}

type DASHSelectedPeriod struct {
	ID         string              `json:"id"`
	StartMS    int64               `json:"start_ms"`
	DurationMS int64               `json:"duration_ms"`
	Tracks     []DASHSelectedTrack `json:"tracks"`
}

type DASHPeriodPlan struct {
	SchemaVersion           int                  `json:"schema_version"`
	IsDynamic               bool                 `json:"is_dynamic"`
	Periods                 []DASHSelectedPeriod `json:"periods"`
	NeedsEmbeddedAudioProof bool                 `json:"needs_embedded_audio_proof"`
	NeedsMuxVerification    bool                 `json:"needs_mux_verification"`
}

type DASHPeriodTrackReceipt struct {
	Role             string   `json:"role"`
	PeriodID         string   `json:"period_id"`
	RepresentationID string   `json:"representation_id"`
	Expected         int      `json:"expected"`
	Verified         int      `json:"verified"`
	Resumed          int      `json:"resumed"`
	Missing          int      `json:"missing"`
	InitVerified     bool     `json:"init_verified"`
	ArtifactRefs     []string `json:"artifact_refs"`
}

type DASHPeriodSessionReceipt struct {
	SchemaVersion           int                      `json:"schema_version"`
	Status                  string                   `json:"status"` // staged, bounded_live_staged, partial
	Periods                 int                      `json:"periods"`
	Tracks                  []DASHPeriodTrackReceipt `json:"tracks"`
	ReadyForMux             bool                     `json:"ready_for_mux"`
	DownloadReady           bool                     `json:"download_ready"` // MP08 only
	NeedsEmbeddedAudioProof bool                     `json:"needs_embedded_audio_proof"`
}

func mp07MS(d time.Duration) int64 { return int64(d / time.Millisecond) }
func mp07Abs(n int64) int64 {
	if n < 0 {
		return -n
	}
	return n
}
func mp07UnitsMS(n, timescale int64) (int64, bool) {
	if n < 0 || timescale <= 0 || n > math.MaxInt64/1000 {
		return 0, false
	}
	return n * 1000 / timescale, true
}
func mp07Timescale(a DASHAdaptationSet, r DASHRepresentation) int64 {
	if r.SegmentTemplate != nil {
		return r.SegmentTemplate.Timescale
	}
	if a.SegmentTemplate != nil {
		return a.SegmentTemplate.Timescale
	}
	if r.SegmentList != nil {
		return r.SegmentList.Timescale
	}
	if a.SegmentList != nil {
		return a.SegmentList.Timescale
	}
	return 1
}

func mp07ChooseTrack(period DASHPeriod, choice DASHTrackSelector, role string, all []DASHFragment, periodMS int64) (DASHSelectedTrack, error) {
	if !choice.valid() {
		return DASHSelectedTrack{}, ErrDASHPeriodSelection
	}
	var matching *DASHRepresentation
	var adaptation *DASHAdaptationSet
	for ai := range period.AdaptationSets {
		a := &period.AdaptationSets[ai]
		if a.ID != choice.AdaptationID || normalizeDASHRole(a.ContentType, a.Roles) != role {
			continue
		}
		for ri := range a.Representations {
			if a.Representations[ri].ID != choice.RepresentationID {
				continue
			}
			if matching != nil {
				return DASHSelectedTrack{}, ErrDASHPeriodSelection
			}
			matching = &a.Representations[ri]
			adaptation = a
		}
	}
	if matching == nil || adaptation == nil ||
		(mergeDASHProtection(adaptation.Protection, matching.Protection) != DASHProtectionClear) {
		return DASHSelectedTrack{}, ErrDASHPeriodSelection
	}
	fragments := make([]DASHFragment, 0)
	for _, f := range all {
		if f.PeriodID == period.ID && f.AdaptationID == choice.AdaptationID &&
			f.RepresentationID == choice.RepresentationID && f.Role == role {
			if f.Protection != "" && f.Protection != DASHProtectionClear {
				return DASHSelectedTrack{}, ErrDASHPeriodSelection
			}
			fragments = append(fragments, f)
		}
	}
	if len(fragments) == 0 || len(fragments) > mp07MaxTrackFragments {
		return DASHSelectedTrack{}, ErrDASHPeriodSelection
	}
	// MP4/fMP4 needs the representation's initialization section.
	mime := strings.ToLower(strings.TrimSpace(matching.MimeType))
	needInit := strings.Contains(mime, "mp4")
	scale := mp07Timescale(*adaptation, *matching)
	first := int64(-1)
	prevEnd := int64(-1)
	var initURI string
	for _, f := range fragments {
		if f.Duration <= 0 || f.Time < 0 {
			return DASHSelectedTrack{}, ErrDASHPeriodSelection
		}
		begin, ok1 := mp07UnitsMS(f.Time, scale)
		length, ok2 := mp07UnitsMS(f.Duration, scale)
		if !ok1 || !ok2 || length <= 0 || begin > math.MaxInt64-length {
			return DASHSelectedTrack{}, ErrDASHPeriodSelection
		}
		if first == -1 {
			first = begin
		}
		if prevEnd >= 0 && mp07Abs(begin-prevEnd) > mp07AlignmentToleranceMS {
			return DASHSelectedTrack{}, ErrDASHPeriodSelection // gap, overlap or reordered fragments
		}
		prevEnd = begin + length
		if needInit && strings.TrimSpace(f.InitializationURL) == "" {
			return DASHSelectedTrack{}, ErrDASHPeriodSelection
		}
		if initURI == "" {
			initURI = f.InitializationURL
		}
		if f.InitializationURL != initURI {
			return DASHSelectedTrack{}, ErrDASHPeriodSelection
		}
	}
	if periodMS > 0 && mp07Abs((prevEnd-first)-periodMS) > mp07AlignmentToleranceMS {
		return DASHSelectedTrack{}, ErrDASHPeriodSelection // selected track does not cover required period
	}
	return DASHSelectedTrack{Role: role, PeriodID: period.ID, AdaptationID: choice.AdaptationID,
		RepresentationID: choice.RepresentationID, FragmentCount: len(fragments),
		RequiresInit: needInit, fragments: fragments}, nil
}

func PlanDASHPeriods(req DASHPeriodRequest) (DASHPeriodPlan, error) {
	if req.AttemptGeneration <= 0 || strings.TrimSpace(req.MPDURL) == "" ||
		len(req.MPDBody) == 0 || len(req.MPDBody) > 2<<20 ||
		len(req.Periods) == 0 || len(req.Periods) > mp07MaxPeriods {
		return DASHPeriodPlan{}, ErrDASHPeriodSelection
	}
	m, err := ParseDASHManifest(req.MPDURL, req.MPDBody)
	if err != nil || len(m.Periods) != len(req.Periods) || len(m.Periods) > mp07MaxPeriods {
		return DASHPeriodPlan{}, ErrDASHPeriodSelection
	}
	dynamic := m.Type == DASHDynamic
	if dynamic && (req.DynamicPollBound < 1 || req.DynamicPollBound > 4 || len(m.Periods) > 4 || m.MinUpdatePeriod <= 0) {
		return DASHPeriodPlan{}, ErrDASHPeriodSelection
	}
	if !dynamic && req.DynamicPollBound != 0 {
		return DASHPeriodPlan{}, ErrDASHPeriodSelection
	}
	expanded, err := ExpandDASHFragments(m)
	if err != nil || len(expanded) > mp07MaxTotalFragments {
		return DASHPeriodPlan{}, ErrDASHPeriodSelection
	}
	p := DASHPeriodPlan{SchemaVersion: DASHPeriodSchemaV1, IsDynamic: dynamic, NeedsMuxVerification: true}
	seenPeriod := map[string]bool{}
	seenFragments := map[string]bool{}
	startMS := int64(0)
	for i, period := range m.Periods {
		sel := req.Periods[i]
		if !mp07SafeID.MatchString(period.ID) || seenPeriod[period.ID] || sel.PeriodID != period.ID || !sel.Video.valid() {
			return DASHPeriodPlan{}, ErrDASHPeriodSelection
		}
		seenPeriod[period.ID] = true
		if i == 0 && mp07MS(period.Start) != 0 {
			return DASHPeriodPlan{}, ErrDASHPeriodSelection
		}
		if i > 0 && period.Start != 0 && mp07Abs(mp07MS(period.Start)-startMS) > mp07AlignmentToleranceMS {
			return DASHPeriodPlan{}, ErrDASHPeriodSelection // period gap or overlap
		}
		durMS := mp07MS(period.Duration)
		if durMS <= 0 && i+1 < len(m.Periods) && m.Periods[i+1].Start > 0 {
			durMS = mp07MS(m.Periods[i+1].Start) - startMS
		}
		if durMS <= 0 && i == len(m.Periods)-1 && m.MediaPresentationDuration > 0 {
			durMS = mp07MS(m.MediaPresentationDuration) - startMS
		}
		if durMS <= 0 && !dynamic {
			return DASHPeriodPlan{}, ErrDASHPeriodSelection
		}
		if durMS < 0 || durMS > int64((24*time.Hour)/time.Millisecond) || startMS > math.MaxInt64-durMS {
			return DASHPeriodPlan{}, ErrDASHPeriodSelection
		}
		pp := DASHSelectedPeriod{ID: period.ID, StartMS: startMS, DurationMS: durMS}
		video, err := mp07ChooseTrack(period, sel.Video, "video", expanded, durMS)
		if err != nil {
			return DASHPeriodPlan{}, err
		}
		pp.Tracks = append(pp.Tracks, video)
		if sel.Audio.set() {
			audio, err := mp07ChooseTrack(period, sel.Audio, "audio", expanded, durMS)
			if err != nil {
				return DASHPeriodPlan{}, err
			}
			pp.Tracks = append(pp.Tracks, audio)
		} else if req.RequireAudio {
			return DASHPeriodPlan{}, ErrDASHPeriodSelection
		} else {
			p.NeedsEmbeddedAudioProof = true
		}
		if sel.Subtitle.set() {
			sub, err := mp07ChooseTrack(period, sel.Subtitle, "subtitle", expanded, durMS)
			if err != nil {
				return DASHPeriodPlan{}, err
			}
			pp.Tracks = append(pp.Tracks, sub)
		}
		for _, tr := range pp.Tracks {
			for _, f := range tr.fragments {
				id, idErr := FragmentID(f.Identity)
				if idErr != nil || seenFragments[id] {
					return DASHPeriodPlan{}, ErrDASHPeriodSelection
				}
				seenFragments[id] = true
			}
		}
		p.Periods = append(p.Periods, pp)
		startMS += durMS
	}
	if !dynamic && m.MediaPresentationDuration > 0 &&
		mp07Abs(startMS-mp07MS(m.MediaPresentationDuration)) > mp07AlignmentToleranceMS {
		return DASHPeriodPlan{}, ErrDASHPeriodSelection
	}
	return p, nil
}

func mp07VerifiedInventory(sink DurableFragmentSink) map[string]FragmentRecord {
	out := map[string]FragmentRecord{}
	if inv, ok := sink.(interface{ CommittedRecords() []FragmentRecord }); ok {
		for _, rec := range inv.CommittedRecords() {
			out[rec.ID] = rec
		}
	}
	return out
}
func mp07InitIdentity(f DASHFragment) FragmentIdentity {
	return FragmentIdentity{Protocol: FragmentProtocolDASH, TimelineKey: "init:" + f.Identity.TimelineKey,
		ResourceID: f.Identity.ResourceID + ":init"}
}
func mp07VerifyInit(sink DurableFragmentSink, inventory map[string]FragmentRecord, f DASHFragment) bool {
	if f.InitializationURL == "" {
		return true
	}
	id, err := FragmentID(mp07InitIdentity(f))
	if err != nil {
		return false
	}
	rec, present := inventory[id]
	return present && rec.Role == "init" && sink.VerifyCommitted(rec) == nil
}

// ExecuteDASHPeriods verifies every required selected period and track.
// A staged receipt is never DownloadReady; MP08 must mux, probe and publish.
func ExecuteDASHPeriods(ctx context.Context, req DASHPeriodRequest, fetcher DASHFetcher,
	videoSink, audioSink, subtitleSink DurableFragmentSink) (DASHPeriodSessionReceipt, error) {
	receipt := DASHPeriodSessionReceipt{SchemaVersion: DASHPeriodSchemaV1, Status: "partial", DownloadReady: false}
	plan, err := PlanDASHPeriods(req)
	if err != nil {
		return receipt, err
	}
	if ctx == nil || fetcher == nil || videoSink == nil {
		return receipt, ErrDASHPeriodIncomplete
	}
	for _, pp := range plan.Periods {
		for _, tr := range pp.Tracks {
			if tr.Role == "audio" && audioSink == nil {
				return receipt, ErrDASHPeriodIncomplete
			}
			if tr.Role == "subtitle" && subtitleSink == nil {
				return receipt, ErrDASHPeriodIncomplete
			}
		}
	}
	receipt.Periods = len(plan.Periods)
	receipt.NeedsEmbeddedAudioProof = plan.NeedsEmbeddedAudioProof
	complete := true
	for _, pp := range plan.Periods {
		for _, tr := range pp.Tracks {
			sink := videoSink
			if tr.Role == "audio" {
				sink = audioSink
			}
			if tr.Role == "subtitle" {
				sink = subtitleSink
			}
			rt := DASHPeriodTrackReceipt{Role: tr.Role, PeriodID: pp.ID,
				RepresentationID: tr.RepresentationID, Expected: len(tr.fragments), InitVerified: true}
			exec, execErr := NewDASHExecutor(fetcher, nil)
			if execErr != nil {
				return receipt, ErrDASHPeriodIncomplete
			}
			if execErr = exec.BindDurableStore(sink); execErr != nil {
				return receipt, ErrDASHPeriodIncomplete
			}
			inventory := mp07VerifiedInventory(sink)
			for _, f := range tr.fragments {
				if ctx.Err() != nil {
					return receipt, ctx.Err()
				}
				id, _ := FragmentID(f.Identity)
				if existing, found := inventory[id]; found {
					if existing.AttemptGeneration > req.AttemptGeneration || sink.VerifyCommitted(existing) != nil {
						return receipt, ErrDASHPeriodIncomplete
					}
					if mp07VerifyInit(sink, inventory, f) {
						rt.Resumed++
						rt.Verified++
						rt.ArtifactRefs = append(rt.ArtifactRefs, existing.LocalArtifactRef)
						continue
					}
				}
				outcome := exec.executeDASHFragment(ctx, f, req.AttemptGeneration, req.CredentialRef)
				if outcome.Status != "committed" {
					rt.Missing++
					complete = false
					continue
				}
				rec, found := exec.Ledger().Get(f.Identity)
				if !found || sink.VerifyCommitted(rec) != nil {
					rt.Missing++
					complete = false
					continue
				}
				inventory = mp07VerifiedInventory(sink)
				if !mp07VerifyInit(sink, inventory, f) {
					rt.Missing++
					rt.InitVerified = false
					complete = false
					continue
				}
				rt.Verified++
				rt.ArtifactRefs = append(rt.ArtifactRefs, rec.LocalArtifactRef)
			}
			if rt.Verified != rt.Expected || !rt.InitVerified {
				complete = false
			}
			receipt.Tracks = append(receipt.Tracks, rt)
		}
	}
	if complete && !plan.IsDynamic {
		receipt.Status = "staged"
		receipt.ReadyForMux = !plan.NeedsEmbeddedAudioProof
	} else if complete && plan.IsDynamic {
		receipt.Status = "bounded_live_staged"
	}
	return receipt, nil
}

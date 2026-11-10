package media

// MP06: exact master/rendition VOD coordination over app-authorized manifest
// bodies and MP05 durable sinks. No network, credentials, muxing, or publication
// occurs here. Signed URLs are transient inputs, never receipt metadata.
import (
	"context"
	"errors"
	"math"
	"strings"
)

var (
	ErrHLSVODSelection  = errors.New("MP06 HLS VOD selection refused")
	ErrHLSVODIncomplete = errors.New("MP06 HLS VOD incomplete")
)

const HLSVODSchemaV1 = 1
const mp06MaxParts = 20000

type HLSVODRequest struct {
	MasterURL         string
	MasterBody        string
	VideoURI          string
	AudioURI          string
	VideoBody         string
	AudioBody         string
	RequireAudio      bool
	AttemptGeneration int64
	CredentialRef     string
}

type HLSVODTrackPlan struct {
	Role            string
	SourceURL       string // transient; never persisted or emitted in completion receipts
	PlaylistBody    string // transient; never persisted or emitted in completion receipts
	ExpectedParts   int
	ExplicitGaps    int
	DurationSeconds float64
}

type HLSVODPlan struct {
	SchemaVersion           int
	Tracks                  []HLSVODTrackPlan
	NeedsEmbeddedAudioProof bool
	NeedsMuxVerification    bool
}

type HLSVODTrackReceipt struct {
	Role            string   `json:"role"`
	NonGapExpected  int      `json:"non_gap_expected"`
	DurableCount    int      `json:"durable_count"`
	IntentionalGaps int      `json:"intentional_gaps"`
	MissingCount    int      `json:"missing_count"`
	ArtifactRefs    []string `json:"artifact_refs"`
	Status          string   `json:"status"`
}

type HLSVODSessionReceipt struct {
	SchemaVersion           int                  `json:"schema_version"`
	Status                  string               `json:"status"` // "staged" or "partial"; never "completed"
	Tracks                  []HLSVODTrackReceipt `json:"tracks"`
	NeedsEmbeddedAudioProof bool                 `json:"needs_embedded_audio_proof"`
	ReadyForMux             bool                 `json:"ready_for_mux"`
	DownloadReady           bool                 `json:"download_ready"` // false until MP08 verified publication
}

func mp06MediaPlan(role, uri, body string) (HLSVODTrackPlan, error) {
	parsed, err := ParseHLSPlaylist(uri, body)
	if err != nil || parsed.Kind != HLSPlaylistMedia || !parsed.EndList || len(parsed.Segments) == 0 || len(parsed.Segments) > mp06MaxParts {
		return HLSVODTrackPlan{}, ErrHLSVODSelection
	}
	result := HLSVODTrackPlan{Role: role, SourceURL: uri, PlaylistBody: body}
	seen := make(map[string]bool, len(parsed.Segments))
	for _, seg := range parsed.Segments {
		// Missing/invalid EXTINF must never silently become a 0-second
		// successful media unit, especially around discontinuities.
		if seg.Duration <= 0 || math.IsNaN(seg.Duration) || math.IsInf(seg.Duration, 0) {
			return HLSVODTrackPlan{}, ErrHLSVODSelection
		}
		ident, e := HLSTimelineIdentity(seg)
		if e != nil {
			return HLSVODTrackPlan{}, ErrHLSVODSelection
		}
		id, e := FragmentID(ident)
		if e != nil || seen[id] {
			return HLSVODTrackPlan{}, ErrHLSVODSelection
		}
		seen[id] = true
		if seg.Gap {
			result.ExplicitGaps++
		} else {
			result.ExpectedParts++
		}
		if seg.Protection != HLSProtectionNone && seg.Protection != HLSProtectionAES128 {
			return HLSVODTrackPlan{}, ErrHLSVODSelection
		}
		if seg.Map != nil && seg.Key != nil && seg.Key.Method == HLSProtectionAES128 && strings.TrimSpace(seg.Key.IV) == "" {
			return HLSVODTrackPlan{}, ErrHLSVODSelection // encrypted init-map requires explicit IV
		}
		result.DurationSeconds += seg.Duration
	}
	if result.ExpectedParts == 0 {
		return HLSVODTrackPlan{}, ErrHLSVODSelection
	}
	return result, nil
}

func PlanHLSVOD(req HLSVODRequest) (HLSVODPlan, error) {
	if req.AttemptGeneration <= 0 || req.MasterURL == "" || req.VideoURI == "" || req.VideoBody == "" || len(req.MasterBody) > 2<<20 || len(req.VideoBody) > 2<<20 || len(req.AudioBody) > 2<<20 {
		return HLSVODPlan{}, ErrHLSVODSelection
	}
	master, err := ParseHLSPlaylist(req.MasterURL, req.MasterBody)
	if err != nil || master.Kind != HLSPlaylistMaster || len(master.Variants) == 0 || len(master.Variants) > 256 || len(master.Renditions) > 512 {
		return HLSVODPlan{}, ErrHLSVODSelection
	}
	var selected *HLSVariant
	for i := range master.Variants {
		if master.Variants[i].ResolvedURI != req.VideoURI {
			continue
		}
		if selected != nil {
			return HLSVODPlan{}, ErrHLSVODSelection
		}
		selected = &master.Variants[i]
	}
	if selected == nil {
		return HLSVODPlan{}, ErrHLSVODSelection
	}
	video, err := mp06MediaPlan("video", req.VideoURI, req.VideoBody)
	if err != nil {
		return HLSVODPlan{}, err
	}
	p := HLSVODPlan{SchemaVersion: HLSVODSchemaV1, Tracks: []HLSVODTrackPlan{video}, NeedsMuxVerification: true}
	if req.AudioURI != "" {
		if selected.AudioGroup == "" || req.AudioBody == "" {
			return HLSVODPlan{}, ErrHLSVODSelection
		}
		matches := 0
		for _, rendition := range master.Renditions {
			if rendition.Type == "audio" && rendition.GroupID == selected.AudioGroup && rendition.ResolvedURI == req.AudioURI {
				matches++
			}
		}
		if matches != 1 {
			return HLSVODPlan{}, ErrHLSVODSelection
		}
		audio, err := mp06MediaPlan("audio", req.AudioURI, req.AudioBody)
		if err != nil {
			return HLSVODPlan{}, err
		}
		// Different segment counts are valid, but wildly different durations
		// are not a safe A/V pair. Timestamp verification remains MP08.
		if math.Abs(video.DurationSeconds-audio.DurationSeconds) > math.Max(2.0, math.Max(video.DurationSeconds, audio.DurationSeconds)*0.03) {
			return HLSVODPlan{}, ErrHLSVODSelection
		}
		p.Tracks = append(p.Tracks, audio)
	} else {
		if req.AudioBody != "" {
			return HLSVODPlan{}, ErrHLSVODSelection
		}
		externalAudio := false
		for _, rendition := range master.Renditions {
			if selected.AudioGroup != "" && rendition.Type == "audio" && rendition.GroupID == selected.AudioGroup && rendition.ResolvedURI != "" {
				externalAudio = true
			}
		}
		if externalAudio {
			return HLSVODPlan{}, ErrHLSVODSelection
		}
		p.NeedsEmbeddedAudioProof = req.RequireAudio
	}
	return p, nil
}

// ExecuteHLSVOD uses existing MP05 sinks; caller owns all network authorization.
// A partial or fully staged receipt is NOT evidence of playable or published output.
func ExecuteHLSVOD(ctx context.Context, req HLSVODRequest, fetcher HLSFetcher, videoStore, audioStore DurableFragmentSink) (HLSVODSessionReceipt, error) {
	plan, err := PlanHLSVOD(req)
	if err != nil {
		return HLSVODSessionReceipt{}, err
	}
	if ctx == nil || fetcher == nil || videoStore == nil || (len(plan.Tracks) == 2 && audioStore == nil) {
		return HLSVODSessionReceipt{}, ErrHLSVODSelection
	}
	receipt := HLSVODSessionReceipt{SchemaVersion: HLSVODSchemaV1, Status: "partial", NeedsEmbeddedAudioProof: plan.NeedsEmbeddedAudioProof, DownloadReady: false}
	complete := true
	for i, track := range plan.Tracks {
		sink := videoStore
		if i == 1 {
			sink = audioStore
		}
		runner, e := NewHLSExecutor(fetcher, nil)
		if e != nil {
			return receipt, e
		}
		if e = runner.BindDurableStore(sink); e != nil {
			return receipt, e
		}
		result, e := runner.Execute(ctx, HLSExecutionPlan{BaseURL: track.SourceURL, Playlists: []string{track.PlaylistBody}, AttemptGeneration: req.AttemptGeneration, CredentialRef: req.CredentialRef})
		tr := HLSVODTrackReceipt{Role: track.Role, NonGapExpected: track.ExpectedParts, IntentionalGaps: track.ExplicitGaps, Status: "partial"}
		parsed, _ := ParseHLSPlaylist(track.SourceURL, track.PlaylistBody)
		for _, segment := range parsed.Segments {
			if segment.Gap {
				continue
			}
			identity, ie := HLSTimelineIdentity(segment)
			if ie != nil {
				return receipt, ErrHLSVODIncomplete
			}
			record, found := runner.Ledger().Get(identity)
			if found && record.State == FragmentCommitted && sink.VerifyCommitted(record) == nil {
				tr.ArtifactRefs = append(tr.ArtifactRefs, record.LocalArtifactRef)
				tr.DurableCount++
			} else {
				tr.MissingCount++
			}
		}
		if e == nil && result.Status == HLSExecutionCompleted && tr.MissingCount == 0 && tr.IntentionalGaps == 0 {
			tr.Status = "staged"
		} else {
			complete = false
		}
		receipt.Tracks = append(receipt.Tracks, tr)
		if e != nil || result.Status == HLSExecutionFailed {
			return receipt, ErrHLSVODIncomplete
		}
	}
	if complete {
		receipt.Status = "staged"
		receipt.ReadyForMux = true
	}
	// MP08 alone may claim a verified final file. Even a fully staged session
	// is not a DownloadReady or playable output receipt.
	return receipt, nil
}

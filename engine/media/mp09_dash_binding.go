package media

// MP09 binds transient MP03 graph option IDs to actual DASH representation IDs.
// It does not change MP03's immutable read-only source contracts or confer
// publication authority. The caller must independently re-fetch and verify
// the MPD/revision through the already-authorized Android manifest broker.
import (
	"errors"
	"strings"
)

var ErrMP09DASHBinding = errors.New("MP09 DASH selection requires fresh exact representation binding")

type MP09DASHBinding struct {
	VideoRepresentationID string
	AudioRepresentationID string
	ManifestURL           string
}

// MP09MapDASHIDs refuses DRM, ambiguous ID reuse, multiple periods, changed
// transport URLs, absent separate audio, and synthetic MP03 option IDs passed
// as native DASH IDs. Never serialize this result to permanent UI state.
func MP09MapDASHIDs(graph ManifestGraphV1, plan ManifestSelectionPlanV1, mpd DASHManifest) (MP09DASHBinding, error) {
	bad := func() (MP09DASHBinding, error) { return MP09DASHBinding{}, ErrMP09DASHBinding }
	if graph.SchemaVersion != ManifestGraphSchemaV1 || graph.Protocol != "dash" ||
		graph.Kind != "live" || graph.Protected || graph.DownloadReady ||
		plan.Intent != "live_recording" || plan.Container != "mp4" ||
		plan.ExecutionReady || plan.Status != "planned_unverified" ||
		!plan.Required.Video || !plan.Required.Audio || plan.Required.Subtitle ||
		plan.Required.VerifyEmbeddedAudio || !plan.Required.VerifyEveryPeriod ||
		mpd.Type != DASHDynamic || len(mpd.Periods) != 1 || len(graph.Periods) != 1 ||
		len(plan.VideoID) == 0 || len(plan.AudioID) == 0 || graph.RootURL == "" {
		return bad()
	}
	out := MP09DASHBinding{ManifestURL: graph.RootURL}
	// Raw DASH Representation IDs can collide across adaptation sets, yet the
	// P02 poller selects by raw representation ID. Require global uniqueness.
	rawIDs := make(map[string]bool)
	var video, audio int
	for _, period := range mpd.Periods {
		if period.ID != graph.Periods[0].ID {
			return bad()
		}
		for _, adaptation := range period.AdaptationSets {
			if adaptation.Protection != DASHProtectionClear && adaptation.Protection != "" {
				return bad()
			}
			for _, rep := range adaptation.Representations {
				if rep.Protection != DASHProtectionClear && rep.Protection != "" {
					return bad()
				}
				if !mp07SafeID.MatchString(rep.ID) || rawIDs[rep.ID] {
					return bad()
				}
				rawIDs[rep.ID] = true
				key := period.ID + "|" + adaptation.ID + "|" + rep.ID
				if mp03Identity("video", key) == plan.VideoID {
					for _, item := range graph.Variants {
						if item.ID == plan.VideoID && item.URL == rep.BaseURL &&
							(item.Protection == "" || item.Protection == "clear" || item.Protection == "none") &&
							strings.HasPrefix(rep.MimeType, "video/") {
							out.VideoRepresentationID = rep.ID
							video++
						}
					}
				}
				if mp03Identity("track", key) == plan.AudioID {
					for _, item := range graph.AudioTracks {
						if item.ID == plan.AudioID && item.URL == rep.BaseURL && !item.Embedded &&
							(item.Protection == "" || item.Protection == "clear" || item.Protection == "none") &&
							strings.HasPrefix(rep.MimeType, "audio/") {
							out.AudioRepresentationID = rep.ID
							audio++
						}
					}
				}
			}
		}
	}
	if video != 1 || audio != 1 || out.VideoRepresentationID == out.AudioRepresentationID {
		return bad()
	}
	return out, nil
}

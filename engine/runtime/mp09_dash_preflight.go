package runtime

// MP09: a fresh, read-only DASH-to-native binding using Android's paired
// transport broker. MP03 synthetic option IDs must never be used as raw DASH
// representation IDs. No URL is stored in the session journal or telemetry.
import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/subhra74/xdm/engine/media"
	"github.com/subhra74/xdm/engine/runtime/platform"
)

var errMP09DASHPreflight = errors.New("MP09 DASH binding denied")

func (e *Engine) mp09BindDASH(ctx context.Context, inv *Invocation, req mp09LiveCommand) (media.MP09DASHBinding, string, error) {
	invalid := func() (media.MP09DASHBinding, string, error) {
		return media.MP09DASHBinding{}, "", errMP09DASHPreflight
	}
	if ctx == nil || inv == nil || req.CaptureID == "" || len(req.CaptureID) > 256 ||
		len(req.VideoOptionID) == 0 || len(req.AudioOptionID) == 0 ||
		len(req.VideoOptionID) > 256 || len(req.AudioOptionID) > 256 ||
		len(req.ExpectedRevision) != 64 || !mp09Hex64(req.ExpectedRevision) {
		return invalid()
	}
	root, err := e.androidMedia.manifestRoot(req.CaptureID)
	if err != nil {
		return invalid()
	}
	rootOrigin, err := androidManifestOrigin(root)
	if err != nil {
		return invalid()
	}
	// Capture only the root response already validated by ResolveManifestGraph.
	// Parsing a second root fetch would create a TOCTOU window on a moving
	// live MPD: the graph and raw native IDs could describe different media.
	var authorizedRoot *media.ManifestFetchResponse
	rootResponses := 0
	fetch := media.ManifestFetchFunc(func(callCtx context.Context, item media.ManifestFetchRequest) (media.ManifestFetchResponse, error) {
		if item.MaxResponseBytes < 0 || item.MaxResponseBytes > 2<<20 {
			return media.ManifestFetchResponse{}, errMP09DASHPreflight
		}
		data, encErr := json.Marshal(map[string]any{
			"capture_id": req.CaptureID, "root_url": root, "requested_url": item.URL, "parent_url": item.ParentURL,
			"may_replay_credentials": item.MayReplayCredentials, "max_response_bytes": item.MaxResponseBytes,
		})
		if encErr != nil {
			return media.ManifestFetchResponse{}, errMP09DASHPreflight
		}
		reply, callErr := inv.PlatformRequest(callCtx, platform.ManifestFetch, platform.Refs{}, data)
		if callErr != nil || !reply.OK {
			return media.ManifestFetchResponse{}, errMP09DASHPreflight
		}
		body, decodeErr := decodeAndroidManifestFetch(reply.Payload)
		if decodeErr != nil || body.FinalURL == "" || len(body.Redirects) > 5 {
			return media.ManifestFetchResponse{}, errMP09DASHPreflight
		}
		finalOrigin, origErr := androidManifestOrigin(body.FinalURL)
		if origErr != nil || finalOrigin != rootOrigin {
			return media.ManifestFetchResponse{}, errMP09DASHPreflight
		}
		for _, hop := range body.Redirects {
			hopOrigin, hopErr := androidManifestOrigin(hop)
			if hopErr != nil || hopOrigin != rootOrigin {
				return media.ManifestFetchResponse{}, errMP09DASHPreflight
			}
		}
		if !body.ExpiresAt.IsZero() && !body.ExpiresAt.After(time.Now()) {
			return media.ManifestFetchResponse{}, errMP09DASHPreflight
		}
		if item.URL == root && item.ParentURL == "" {
			rootResponses++
			if rootResponses != 1 {
				return media.ManifestFetchResponse{}, errMP09DASHPreflight
			}
			copyBody := body
			copyBody.Body = append([]byte(nil), body.Body...)
			authorizedRoot = &copyBody
		}
		return body, nil
	})
	policy := media.ManifestResolvePolicy{AuthorizedOrigin: rootOrigin, CredentialReplayApproved: true,
		MaxManifests: 24, MaxDepth: 5, MaxTotalBytes: 8 << 20, MaxOptions: 256}
	graph, err := media.ResolveManifestGraph(ctx, root, fetch, policy)
	if err != nil || graph.Protected || graph.Kind != "live" || graph.Protocol != "dash" {
		return invalid()
	}
	revision, err := media.ManifestGraphRevision(graph)
	if err != nil || revision != req.ExpectedRevision {
		return invalid()
	}
	plan, err := media.SelectManifestGraph(graph, media.ManifestSelectionInputV1{
		Intent: "live_recording", VideoID: req.VideoOptionID, AudioID: req.AudioOptionID,
		Container: "mp4", SubtitlePolicy: "disabled",
	})
	if err != nil || plan.VideoID != req.VideoOptionID || plan.AudioID != req.AudioOptionID {
		return invalid()
	}
	// MP03's graph and the DASH parser now use one identical authorized
	// manifest snapshot, including the exact native representation identities.
	// A fresh start separately revalidates the current revision, and further
	// polls independently validate the user's selected native representation.
	if rootResponses != 1 || authorizedRoot == nil ||
		len(authorizedRoot.Body) == 0 ||
		(authorizedRoot.ContentType != "" &&
			!strings.Contains(strings.ToLower(authorizedRoot.ContentType), "xml") &&
			!strings.Contains(strings.ToLower(authorizedRoot.ContentType), "dash")) {
		return invalid()
	}
	mpd, err := media.ParseDASHManifest(authorizedRoot.FinalURL, string(authorizedRoot.Body))
	if err != nil {
		return invalid()
	}
	binding, err := media.MP09MapDASHIDs(graph, plan, mpd)
	if err != nil {
		return invalid()
	}
	binding.ManifestURL = root // only the original app-authorized manifest root
	return binding, revision, nil
}

func mp09Hex64(value string) bool {
	if len(value) != 64 {
		return false
	}
	for _, c := range value {
		if c < '0' || c > '9' && c < 'a' || c > 'f' {
			return false
		}
	}
	return true
}

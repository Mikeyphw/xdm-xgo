package runtime

// MP03: read-only, per-capture Go manifest resolution through Android's
// authorized media request store. Go cannot create HTTP clients or invent
// browser credentials. A graph is never a download/execution authorization.
import (
    "context"
    "encoding/base64"
    "encoding/json"
    "errors"
    "net/url"
    "strings"
    "time"

    "github.com/subhra74/xdm/engine/media"
    "github.com/subhra74/xdm/engine/runtime/command"
    "github.com/subhra74/xdm/engine/runtime/event"
    "github.com/subhra74/xdm/engine/runtime/platform"
)

const AndroidMediaResolveKind = "android.media.resolve_manifest"
const mp03AndroidMaximumBody = 2 << 20

type androidManifestResolveInput struct {
    ClientRequestID string `json:"client_request_id"`
    CaptureID string `json:"capture_id"`
    Selection *media.ManifestSelectionInputV1 `json:"selection,omitempty"`
    ExpectedRevision string `json:"expected_revision,omitempty"`
}
type androidManifestFetchWire struct {
    BodyBase64 string `json:"body_base64"`
    FinalURL string `json:"final_url"`
    Redirects []string `json:"redirects"`
    ContentType string `json:"content_type"`
    ExpiresAtEpochMS int64 `json:"expires_at_epoch_ms"`
}

func androidManifestOrigin(raw string) (string, error) {
    parsed, err := url.Parse(raw)
    if err != nil || parsed.User != nil || parsed.Fragment != "" || parsed.Hostname() == "" ||
        (parsed.Scheme != "https" && parsed.Scheme != "http") {
        return "", media.ErrManifestScope
    }
    return strings.ToLower(parsed.Scheme + "://" + parsed.Host), nil
}

func decodeAndroidManifestFetch(payload []byte) (media.ManifestFetchResponse, error) {
    var wire androidManifestFetchWire
    if len(payload) == 0 || len(payload) > 3*mp03AndroidMaximumBody+8192 || json.Unmarshal(payload, &wire) != nil {
        return media.ManifestFetchResponse{}, media.ErrManifestInvalid
    }
    if len(wire.BodyBase64) == 0 || len(wire.BodyBase64) > base64.StdEncoding.EncodedLen(mp03AndroidMaximumBody) {
        return media.ManifestFetchResponse{}, media.ErrManifestLimit
    }
    body, err := base64.StdEncoding.Strict().DecodeString(wire.BodyBase64)
    if err != nil || len(body) == 0 || len(body) > mp03AndroidMaximumBody || len(wire.Redirects) > 5 {
        return media.ManifestFetchResponse{}, media.ErrManifestInvalid
    }
    result := media.ManifestFetchResponse{Body: body, FinalURL: wire.FinalURL,
        Redirects: wire.Redirects, ContentType: wire.ContentType}
    if wire.ExpiresAtEpochMS > 0 { result.ExpiresAt = time.UnixMilli(wire.ExpiresAtEpochMS) }
    return result, nil
}

func (s *androidMediaState) manifestRoot(captureID string) (string, error) {
    s.mu.RLock()
    defer s.mu.RUnlock()
    state := s.captures[captureID]
    if state == nil || state.capture.SourceURL == "" || state.envelope.Request.URL != state.capture.SourceURL {
        return "", media.ErrManifestScope
    }
    return state.capture.SourceURL, nil
}

func (e *Engine) androidMediaResolveHandler(ctx context.Context, inv *Invocation, env command.Envelope) error {
    var input androidManifestResolveInput
    if json.Unmarshal(env.Payload, &input) != nil ||
        strings.TrimSpace(input.ClientRequestID) == "" || strings.TrimSpace(input.CaptureID) == "" ||
        len(input.ClientRequestID) > 128 || len(input.CaptureID) > 256 {
        return errors.New("MP03 manifest request invalid")
    }
    failed := func(code string) error {
        // URL, raw manifest, headers and credential-bearing remote failures must
        // never appear in result telemetry, durable events or generic errors.
        _ = emitAndroidMediaResult(inv, input.ClientRequestID, "resolve_manifest", false,
            map[string]any{"capture_id": input.CaptureID, "error_code": code})
        return errors.New("MP03 manifest resolution denied: " + code)
    }
    root, err := e.androidMedia.manifestRoot(input.CaptureID)
    if err != nil { return failed("capture_not_found_or_stale") }
    origin, err := androidManifestOrigin(root)
    if err != nil { return failed("invalid_capture_url") }

    // Every fetch waits on the existing correlated native platform broker. The
    // Android side separately verifies the exact capture URL, scope and expiry.
    fetch := media.ManifestFetchFunc(func(ctx context.Context, req media.ManifestFetchRequest) (media.ManifestFetchResponse, error) {
        body, err := json.Marshal(map[string]any{
            "capture_id": input.CaptureID, "root_url": root,
            "requested_url": req.URL, "parent_url": req.ParentURL,
            "may_replay_credentials": req.MayReplayCredentials,
            "max_response_bytes": req.MaxResponseBytes,
        })
        if err != nil { return media.ManifestFetchResponse{}, media.ErrManifestInvalid }
        reply, err := inv.PlatformRequest(ctx, platform.ManifestFetch, platform.Refs{OperationID: env.OperationID}, body)
        if err != nil || !reply.OK { return media.ManifestFetchResponse{}, media.ErrManifestScope }
        return decodeAndroidManifestFetch(reply.Payload)
    })
    policy := media.ManifestResolvePolicy{
        AuthorizedOrigin: origin, CredentialReplayApproved: true,
        MaxManifests: 24, MaxDepth: 5, MaxTotalBytes: 8 << 20, MaxOptions: 256,
    }
    graph, err := media.ResolveManifestGraph(ctx, root, fetch, policy)
    if err != nil { return failed("manifest_unavailable_or_unsupported") }
    if graph.SchemaVersion != media.ManifestGraphSchemaV1 || graph.DownloadReady {
        return failed("manifest_schema_invalid")
    }
    revision, err := media.ManifestGraphRevision(graph)
    if err != nil { return failed("manifest_revision_invalid") }
    if input.ExpectedRevision != "" && input.ExpectedRevision != revision {
        return failed("manifest_changed_refresh_required")
    }
    var plan *media.ManifestSelectionPlanV1
    request := media.ManifestSelectionInputV1{}
    if input.Selection != nil { request = *input.Selection }
    candidate, selectionErr := media.SelectManifestGraph(graph, request)
    if selectionErr != nil && input.Selection != nil { return failed("selection_incompatible_or_stale") }
    if selectionErr == nil { plan = &candidate }
    // Telemetry is volatile, not durable: transport URLs exist solely in the
    // in-memory app review result. The UI decoder never logs them.
    result, err := json.Marshal(map[string]any{
        "client_request_id": input.ClientRequestID, "action": "resolve_manifest",
        "capture_id": input.CaptureID, "ok": true, "status": "resolved_read_only",
        "manifest_graph": graph, "manifest_revision": revision, "manifest_selection_plan": plan,
    })
    if err != nil { return failed("manifest_encoding_failed") }
    _, err = inv.Emit(event.Telemetry, "android.media.command_result", result, "")
    return err
}

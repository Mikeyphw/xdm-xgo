package media

// MP03: a bounded, policy-driven manifest graph resolver. The fetch port is
// deliberately owned by the caller (Android's paired network broker in production):
// Go must never manufacture Authorization/Cookie headers or follow redirects itself.
// This stage is a read-only graph and does not replace the Kotlin HLS executor.

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"time"
)

const ManifestGraphSchemaV1 = 1
const mp03MaxManifestBytes = 2 << 20

var (
	ErrManifestInvalid  = errors.New("manifest resolver: invalid or unsupported manifest")
	ErrManifestScope    = errors.New("manifest resolver: origin or credential scope denied")
	ErrManifestLimit    = errors.New("manifest resolver: source graph bound exceeded")
	ErrManifestCycle    = errors.New("manifest resolver: recursive manifest cycle")
	ErrManifestExpired  = errors.New("manifest resolver: signed request expired")
	ErrManifestRedirect = errors.New("manifest resolver: unverified redirect chain")
)

type ManifestFetchRequest struct {
	URL                  string
	ParentURL            string
	MayReplayCredentials bool
	MaxResponseBytes     int
}
type ManifestFetchResponse struct {
	Body     []byte
	FinalURL string
	// Every redirect hop must be supplied in order, excluding the requested URL;
	// for a redirecting request this list must end with FinalURL.
	Redirects   []string
	ContentType string
	ExpiresAt   time.Time
}
type ManifestFetcher interface {
	FetchManifest(context.Context, ManifestFetchRequest) (ManifestFetchResponse, error)
}
type ManifestFetchFunc func(context.Context, ManifestFetchRequest) (ManifestFetchResponse, error)

func (f ManifestFetchFunc) FetchManifest(ctx context.Context, req ManifestFetchRequest) (ManifestFetchResponse, error) {
	return f(ctx, req)
}

type ManifestResolvePolicy struct {
	// Root origin must match the authorized capture. An empty value means no
	// root credentials and still enforces origin checks on recursive children.
	AuthorizedOrigin         string
	CredentialReplayApproved bool
	// Cross-origin manifests are never credential-bearing, even when allowed.
	AllowedManifestOrigins []string
	MaxManifests           int
	MaxDepth               int
	MaxTotalBytes          int
	MaxOptions             int
	Now                    func() time.Time
}

type ManifestGraphV1 struct {
	SchemaVersion  int                 `json:"schema_version"`
	Protocol       string              `json:"protocol"`
	Kind           string              `json:"kind"` // vod, event, live
	RootID         string              `json:"root_id"`
	RootURL        string              `json:"root_url"` // transport-only; never log or expose in diagnostics
	Periods        []ManifestPeriodV1  `json:"periods"`
	Variants       []ManifestVariantV1 `json:"variants"`
	AudioTracks    []ManifestTrackV1   `json:"audio_tracks"`
	SubtitleTracks []ManifestTrackV1   `json:"subtitle_tracks"`
	Sources        []ManifestSourceV1  `json:"sources"`
	Protected      bool                `json:"protected"`
	Protection     []string            `json:"protection"`
	// A graph is for choosing tracks, not proof of durable stored fragments.
	DownloadReady bool `json:"download_ready"`
}
type ManifestPeriodV1 struct {
	ID             string `json:"id"`
	StartMillis    int64  `json:"start_ms"`
	DurationMillis int64  `json:"duration_ms"`
	Discontinuity  int64  `json:"discontinuity"`
}
type ManifestVariantV1 struct {
	ContentKind   string   `json:"kind"` // video or undetermined; never guess audio presence
	ID            string   `json:"id"`
	URL           string   `json:"url"`
	PeriodID      string   `json:"period_id"`
	Bandwidth     int      `json:"bandwidth"`
	Width         int      `json:"width"`
	Height        int      `json:"height"`
	Codecs        []string `json:"codecs"`
	MIMEType      string   `json:"mime_type"`
	AudioGroup    string   `json:"audio_group"`
	SubtitleGroup string   `json:"subtitle_group"`
	Protection    string   `json:"protection"`
}
type ManifestTrackV1 struct {
	ID         string `json:"id"`
	URL        string `json:"url,omitempty"` // empty for embedded/muxed audio
	PeriodID   string `json:"period_id"`
	Type       string `json:"type"`
	Group      string `json:"group"`
	Name       string `json:"name"`
	Language   string `json:"language"`
	Codec      string `json:"codec"`
	Default    bool   `json:"default"`
	Embedded   bool   `json:"embedded"`
	Protection string `json:"protection"`
}
type ManifestSourceV1 struct {
	ID               string `json:"id"`
	URL              string `json:"url"`
	ParentID         string `json:"parent_id,omitempty"`
	Kind             string `json:"kind"`
	MIMEType         string `json:"mime_type,omitempty"`
	BodyBytes        int    `json:"body_bytes"`
	CredentialReplay bool   `json:"credential_replay"`
}

// SafeManifestSummary is the only graph representation permitted in diagnostic
// reports: URLs, signed parameters, headers and raw manifest bodies are omitted.
type SafeManifestSummary struct {
	SchemaVersion      int    `json:"schema_version"`
	Protocol           string `json:"protocol"`
	Kind               string `json:"kind"`
	PeriodCount        int    `json:"period_count"`
	VariantCount       int    `json:"variant_count"`
	AudioTrackCount    int    `json:"audio_track_count"`
	SubtitleTrackCount int    `json:"subtitle_track_count"`
	ManifestCount      int    `json:"manifest_count"`
	Protected          bool   `json:"protected"`
}

func (g ManifestGraphV1) SafeSummary() SafeManifestSummary {
	return SafeManifestSummary{g.SchemaVersion, g.Protocol, g.Kind, len(g.Periods), len(g.Variants), len(g.AudioTracks), len(g.SubtitleTracks), len(g.Sources), g.Protected}
}

func mp03Identity(kind, raw string) string {
	u, err := url.Parse(raw)
	if err == nil && u.Host != "" {
		u.Fragment = ""
		q := u.Query()
		for key := range q {
			k := strings.ToLower(strings.ReplaceAll(key, "-", "_"))
			if strings.Contains(k, "token") || strings.Contains(k, "sig") || strings.Contains(k, "auth") || strings.Contains(k, "expire") || strings.Contains(k, "policy") || strings.Contains(k, "credential") || strings.Contains(k, "session") || k == "key" {
				q.Del(key)
			}
		}
		u.RawQuery = q.Encode()
		raw = u.String()
	}
	digest := sha256.Sum256([]byte(kind + "|" + raw))
	return kind + "-" + hex.EncodeToString(digest[:9])
}
func mp03Origin(raw string) (string, error) {
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" || u.User != nil {
		return "", ErrManifestScope
	}
	return strings.ToLower(u.Scheme + "://" + u.Host), nil
}
func mp03URL(raw string) (string, error) {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Hostname() == "" || u.User != nil || u.Fragment != "" {
		return "", ErrManifestScope
	}
	return u.String(), nil
}
func mp03Resolution(v string) (int, int) {
	var w, h int
	if _, err := fmt.Sscanf(strings.ToLower(v), "%dx%d", &w, &h); err != nil || w < 0 || h < 0 {
		return 0, 0
	}
	return w, h
}
func mp03Type(raw string, body []byte) string {
	sample := strings.TrimSpace(string(body))
	if strings.HasPrefix(sample, "#EXTM3U") {
		return "hls"
	}
	if strings.HasPrefix(sample, "<?xml") {
		if idx := strings.Index(sample, "?>"); idx >= 0 && idx < 300 {
			sample = strings.TrimSpace(sample[idx+2:])
		}
	}
	if strings.HasPrefix(sample, "<MPD") && !strings.Contains(sample, "<!DOCTYPE") && !strings.Contains(sample, "<!ENTITY") {
		return "dash"
	}
	return ""
}
func mp03ContentType(raw string) string {
	return strings.ToLower(strings.TrimSpace(strings.SplitN(raw, ";", 2)[0]))
}
func mp03AllowedMIME(mime, protocol string) bool {
	switch mime {
	case "", "application/octet-stream", "binary/octet-stream", "text/plain":
		return true
	case "application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "audio/x-mpegurl":
		return protocol == "hls"
	case "application/dash+xml", "application/xml", "text/xml":
		return protocol == "dash"
	default:
		return false
	}
}

// ResolveManifestGraph provides a deterministic graph of actually parsed options.
// Request transport, credentials and retries belong to the Android-authorized
// fetcher; this function never creates HTTP clients or follows redirects.
func ResolveManifestGraph(ctx context.Context, root string, fetcher ManifestFetcher, policy ManifestResolvePolicy) (ManifestGraphV1, error) {
	var empty ManifestGraphV1
	if fetcher == nil {
		return empty, ErrManifestInvalid
	}
	var err error
	root, err = mp03URL(root)
	if err != nil {
		return empty, err
	}
	rootOrigin, _ := mp03Origin(root)
	if policy.AuthorizedOrigin != "" {
		auth, err := mp03Origin(policy.AuthorizedOrigin)
		if err != nil || auth != rootOrigin {
			return empty, ErrManifestScope
		}
	}
	maxNodes := policy.MaxManifests
	if maxNodes <= 0 {
		maxNodes = 48
	}
	if maxNodes > 128 {
		maxNodes = 128
	}
	maxDepth := policy.MaxDepth
	if maxDepth <= 0 {
		maxDepth = 6
	}
	if maxDepth > 12 {
		maxDepth = 12
	}
	maxBytes := policy.MaxTotalBytes
	if maxBytes <= 0 {
		maxBytes = 8 << 20
	}
	if maxBytes > 16<<20 {
		maxBytes = 16 << 20
	}
	maxOptions := policy.MaxOptions
	if maxOptions <= 0 {
		maxOptions = 256
	}
	if maxOptions > 512 {
		maxOptions = 512
	}
	clock := policy.Now
	if clock == nil {
		clock = time.Now
	}
	allowed := map[string]bool{rootOrigin: true}
	for _, raw := range policy.AllowedManifestOrigins {
		origin, err := mp03Origin(raw)
		if err != nil || origin != raw {
			return empty, ErrManifestScope
		}
		allowed[origin] = true
	}
	graph := ManifestGraphV1{SchemaVersion: ManifestGraphSchemaV1, RootURL: root, RootID: mp03Identity("manifest", root), DownloadReady: false}
	seen := map[string]bool{}
	onStack := map[string]bool{}
	total := 0
	protected := map[string]bool{}
	nodeKind := map[string]string{}
	var walk func(string, string, int) error
	walk = func(requested, parent string, depth int) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		if depth > maxDepth {
			return ErrManifestLimit
		}
		requested, err = mp03URL(requested)
		if err != nil {
			return err
		}
		origin, _ := mp03Origin(requested)
		if !allowed[origin] {
			return ErrManifestScope
		}
		if onStack[requested] {
			return ErrManifestCycle
		}
		if seen[requested] {
			return nil
		}
		if len(seen) >= maxNodes {
			return ErrManifestLimit
		}
		// Tentative cycles mark before fetching to detect self-referential playlists.
		onStack[requested] = true
		defer delete(onStack, requested)
		replay := policy.CredentialReplayApproved && origin == rootOrigin && policy.AuthorizedOrigin == rootOrigin
		response, err := fetcher.FetchManifest(ctx, ManifestFetchRequest{URL: requested, ParentURL: parent, MayReplayCredentials: replay, MaxResponseBytes: mp03MaxManifestBytes})
		if err != nil {
			return ErrManifestInvalid // never wrap untrusted error strings carrying signed request URLs
		}
		if !response.ExpiresAt.IsZero() && !clock().Before(response.ExpiresAt) {
			return ErrManifestExpired
		}
		if len(response.Body) == 0 || len(response.Body) > mp03MaxManifestBytes {
			return ErrManifestLimit
		}
		total += len(response.Body)
		if total > maxBytes {
			return ErrManifestLimit
		}
		finalURL := requested
		if response.FinalURL != "" {
			finalURL, err = mp03URL(response.FinalURL)
			if err != nil {
				return err
			}
		}
		current := requested
		for _, hop := range response.Redirects {
			hop, err = mp03URL(hop)
			if err != nil {
				return ErrManifestRedirect
			}
			hopOrigin, _ := mp03Origin(hop)
			if !allowed[hopOrigin] {
				return ErrManifestRedirect
			}
			// A credential-bearing cross-origin redirect cannot be safely replayed.
			if replay && hopOrigin != rootOrigin {
				return ErrManifestRedirect
			}
			if hop == current {
				return ErrManifestRedirect
			}
			current = hop
		}
		if current != finalURL {
			return ErrManifestRedirect
		}
		if requested != finalURL && len(response.Redirects) == 0 {
			return ErrManifestRedirect
		}
		if onStack[finalURL] && finalURL != requested {
			return ErrManifestCycle
		}
		if seen[finalURL] {
			return ErrManifestCycle
		}
		bodyUpper := strings.ToUpper(string(response.Body))
		if strings.Contains(bodyUpper, "<!DOCTYPE") || strings.Contains(bodyUpper, "<!ENTITY") {
			return ErrManifestInvalid
		}
		protocol := mp03Type(finalURL, response.Body)
		mime := mp03ContentType(response.ContentType)
		if protocol == "" || !mp03AllowedMIME(mime, protocol) {
			return ErrManifestInvalid
		}
		if graph.Protocol != "" && graph.Protocol != protocol {
			return ErrManifestInvalid
		}
		graph.Protocol = protocol
		seen[requested] = true
		seen[finalURL] = true
		if len(graph.Sources) >= maxNodes {
			return ErrManifestLimit
		}
		id := mp03Identity("manifest", finalURL)
		parentID := ""
		if parent != "" {
			parentID = mp03Identity("manifest", parent)
		}
		graph.Sources = append(graph.Sources, ManifestSourceV1{ID: id, URL: finalURL, ParentID: parentID, Kind: protocol, MIMEType: mime, BodyBytes: len(response.Body), CredentialReplay: replay})
		nodeKind[finalURL] = protocol
		if protocol == "hls" {
			playlist, err := ParseHLSPlaylist(finalURL, string(response.Body))
			if err != nil {
				return fmt.Errorf("manifest parse rejected: %w", ErrManifestInvalid)
			}
			if playlist.Kind == HLSPlaylistMaster {
				if len(playlist.Variants) == 0 && len(playlist.Renditions) == 0 {
					return ErrManifestInvalid
				}
				for _, v := range playlist.Variants {
					if len(graph.Variants) >= maxOptions {
						return ErrManifestLimit
					}
					w, h := mp03Resolution(v.Resolution)
					kind := "undetermined"
					if w > 0 && h > 0 {
						kind = "video"
					}
					graph.Variants = append(graph.Variants, ManifestVariantV1{ContentKind: kind, ID: mp03Identity("video", v.ResolvedURI), URL: v.ResolvedURI, PeriodID: "hls-0", Bandwidth: v.Bandwidth, Width: w, Height: h, Codecs: append([]string(nil), v.Codecs...), AudioGroup: v.AudioGroup, SubtitleGroup: v.SubtitleGroup, Protection: "unresolved"})
					if err := walk(v.ResolvedURI, finalURL, depth+1); err != nil {
						return err
					}
				}
				for _, r := range playlist.Renditions {
					typ := strings.ToLower(r.Type)
					if typ != "audio" && typ != "subtitles" {
						continue
					}
					if len(graph.AudioTracks)+len(graph.SubtitleTracks) >= maxOptions {
						return ErrManifestLimit
					}
					tr := ManifestTrackV1{ID: mp03Identity(typ, r.GroupID+"|"+r.Name+"|"+r.ResolvedURI), URL: r.ResolvedURI, PeriodID: "hls-0", Type: typ, Group: r.GroupID, Name: r.Name, Language: r.Language, Default: r.Default, Embedded: r.ResolvedURI == "", Protection: "unresolved"}
					if typ == "audio" {
						graph.AudioTracks = append(graph.AudioTracks, tr)
					} else {
						graph.SubtitleTracks = append(graph.SubtitleTracks, tr)
					}
					if r.ResolvedURI != "" {
						if err := walk(r.ResolvedURI, finalURL, depth+1); err != nil {
							return err
						}
					}
				}
			} else {
				if len(playlist.Segments) == 0 {
					return ErrManifestInvalid
				}
				if len(playlist.Segments) > 20000 {
					return ErrManifestLimit
				}
				if playlist.EndList && graph.Kind == "" {
					graph.Kind = "vod"
				}
				if !playlist.EndList && (graph.Kind == "" || graph.Kind == "vod") {
					graph.Kind = "live"
				}
				if strings.EqualFold(playlist.PlaylistType, "event") && !playlist.EndList {
					graph.Kind = "event"
				}
				for _, seg := range playlist.Segments {
					name := string(seg.Protection)
					if name != "none" && name != "" {
						protected[name] = true
					}
					pid := fmt.Sprintf("hls-disc-%d", seg.DiscontinuitySequence)
					if !mp03HasPeriod(graph.Periods, pid) {
						graph.Periods = append(graph.Periods, ManifestPeriodV1{ID: pid, Discontinuity: seg.DiscontinuitySequence})
					}
				}
				if parent == "" && len(graph.Variants) == 0 {
					graph.Variants = append(graph.Variants, ManifestVariantV1{ContentKind: "undetermined", ID: mp03Identity("video", finalURL), URL: finalURL, PeriodID: "hls-0", Protection: "unresolved"})
				}
			}
		} else {
			if parent != "" {
				return ErrManifestInvalid
			}
			dash, err := ParseDASHManifest(finalURL, string(response.Body))
			if err != nil {
				return fmt.Errorf("manifest parse rejected: %w", ErrManifestInvalid)
			}
			if dash.Type == DASHDynamic {
				graph.Kind = "live"
			} else {
				graph.Kind = "vod"
			}
			for _, p := range dash.Periods {
				if len(graph.Periods) >= maxOptions {
					return ErrManifestLimit
				}
				graph.Periods = append(graph.Periods, ManifestPeriodV1{ID: p.ID, StartMillis: p.Start.Milliseconds(), DurationMillis: p.Duration.Milliseconds()})
				for _, a := range p.AdaptationSets {
					prot := string(a.Protection)
					if prot != "" && prot != "clear" {
						protected[prot] = true
					}
					for _, rep := range a.Representations {
						if len(graph.Variants)+len(graph.AudioTracks)+len(graph.SubtitleTracks) >= maxOptions {
							return ErrManifestLimit
						}
						protection := string(rep.Protection)
						if protection != "" && protection != "clear" {
							protected[protection] = true
						}
						typ := strings.ToLower(a.ContentType)
						if typ == "" {
							if strings.HasPrefix(rep.MimeType, "audio/") {
								typ = "audio"
							} else if strings.HasPrefix(rep.MimeType, "text/") {
								typ = "subtitles"
							} else {
								typ = "video"
							}
						}
						uri := rep.BaseURL
						if _, err := mp03URL(uri); err != nil {
							return ErrManifestScope
						}
						repOrigin, _ := mp03Origin(uri)
						if !allowed[repOrigin] {
							return ErrManifestScope
						}
						idKey := p.ID + "|" + a.ID + "|" + rep.ID
						if typ == "audio" || typ == "text" || typ == "subtitles" {
							tr := ManifestTrackV1{ID: mp03Identity("track", idKey), URL: uri, PeriodID: p.ID, Type: typ, Group: a.ID, Name: rep.ID, Language: a.Language, Codec: rep.Codecs, Protection: protection}
							if typ == "audio" {
								graph.AudioTracks = append(graph.AudioTracks, tr)
							} else {
								graph.SubtitleTracks = append(graph.SubtitleTracks, tr)
							}
						} else if typ == "video" {
							graph.Variants = append(graph.Variants, ManifestVariantV1{ContentKind: "video", ID: mp03Identity("video", idKey), URL: uri, PeriodID: p.ID, Bandwidth: rep.Bandwidth, Width: rep.Width, Height: rep.Height, Codecs: mp03SplitCodecs(rep.Codecs), MIMEType: rep.MimeType, AudioGroup: "", Protection: protection})
						}
					}
				}
			}
			if len(graph.Periods) == 0 {
				return ErrManifestInvalid
			}
		}
		return nil
	}
	if err := walk(root, "", 0); err != nil {
		return empty, err
	}
	if len(graph.Variants) == 0 && len(graph.AudioTracks) == 0 {
		return empty, ErrManifestInvalid
	}
	if graph.Kind == "" {
		graph.Kind = "live"
	}
	// Do not silently classify protected streams as downloadable.
	for p := range protected {
		graph.Protection = append(graph.Protection, p)
	}
	sort.Strings(graph.Protection)
	for _, p := range graph.Protection {
		if p != "aes-128" && p != "none" && p != "clear" {
			graph.Protected = true
		}
	}
	sort.SliceStable(graph.Periods, func(i, j int) bool {
		if graph.Periods[i].StartMillis != graph.Periods[j].StartMillis {
			return graph.Periods[i].StartMillis < graph.Periods[j].StartMillis
		}
		return graph.Periods[i].Discontinuity < graph.Periods[j].Discontinuity
	})
	sort.Slice(graph.Variants, func(i, j int) bool { return graph.Variants[i].ID < graph.Variants[j].ID })
	sort.Slice(graph.AudioTracks, func(i, j int) bool { return graph.AudioTracks[i].ID < graph.AudioTracks[j].ID })
	sort.Slice(graph.SubtitleTracks, func(i, j int) bool { return graph.SubtitleTracks[i].ID < graph.SubtitleTracks[j].ID })
	sort.Slice(graph.Sources, func(i, j int) bool { return graph.Sources[i].ID < graph.Sources[j].ID })
	return graph, nil
}
func mp03SplitCodecs(raw string) []string {
	var out []string
	for _, s := range strings.Split(raw, ",") {
		if x := strings.TrimSpace(s); x != "" {
			out = append(out, x)
		}
	}
	return out
}
func mp03HasPeriod(periods []ManifestPeriodV1, id string) bool {
	for _, p := range periods {
		if p.ID == id {
			return true
		}
	}
	return false
}

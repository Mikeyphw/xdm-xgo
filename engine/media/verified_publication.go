package media

// MP08A: source-bound finalization and publication gate for MP05/06/07.
// It supplies a verified, typed fragment graph to an app-owned FFmpeg/FFprobe
// host. No fragment URL, header, key, arbitrary command or shell is accepted.
// The Android host implementation and MediaStore acceptance are separate gates.
import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"math"
	"regexp"
	"strings"
	"time"
)

var (
	ErrMP08InvalidStage   = errors.New("MP08 incomplete or untrusted staging")
	ErrMP08MissingProof   = errors.New("MP08 durable fragment proof failed")
	ErrMP08Probe          = errors.New("MP08 FFprobe rejected final artifact")
	ErrMP08Publication    = errors.New("MP08 atomic publication not confirmed")
	ErrMP08PartialConsent = errors.New("MP08 partial recovery requires separate consent")
)

const MP08SchemaV1 = 1
const mp08MinOutputBytes int64 = 1024
const mp08MaxTracks = 64
const mp08MaxPartsPerTrack = 20000

var mp08SafeName = regexp.MustCompile(`^[A-Za-z0-9_-]{1,96}$`)

// MP08VerifiedStore is implemented by MP05 FileFragmentStore. ReadVerified
// reads and rehashes source bytes, rather than trusting a journal claim alone.
type MP08VerifiedStore interface {
	DurableFragmentSink
	CommittedRecords() []FragmentRecord
	ReadVerified(FragmentIdentity) ([]byte, error)
}

type MP08Track struct {
	Role             string            `json:"role"`
	PeriodID         string            `json:"period_id"`
	RepresentationID string            `json:"representation_id,omitempty"`
	StartMS          int64             `json:"start_ms"`
	DurationMS       int64             `json:"duration_ms"`
	Init             *FragmentRecord   `json:"init,omitempty"`
	InitForPart      []*FragmentRecord `json:"init_for_part"`
	Parts            []FragmentRecord  `json:"parts"`
	store            MP08VerifiedStore // never serialize; app-private capability
}

type MP08FinalizationPlan struct {
	SchemaVersion      int         `json:"schema_version"`
	Source             string      `json:"source"` // hls_vod or dash_static
	DestinationKey     string      `json:"destination_key"`
	Container          string      `json:"container"` // mp4 or mkv
	ExpectedDurationMS int64       `json:"expected_duration_ms"`
	RequireAudio       bool        `json:"require_audio"`
	RequireSubtitle    bool        `json:"require_subtitle"`
	Partial            bool        `json:"partial"`
	Tracks             []MP08Track `json:"tracks"`
	validated          bool        // only exact MP06/07 stage constructors may activate
	seal               string      // detects post-preparation field mutation
}

// MP08Host must implement a typed, app-private FFmpeg/FFprobe transaction.
// Assemble must not report a playable output; only Probe+atomic Publish+readback
// may advance the returned receipt to completed or partial_published.
type MP08Host interface {
	Assemble(context.Context, MP08FinalizationPlan) (MP08StagedOutput, error)
	Probe(context.Context, MP08StagedOutput) (FFProbeReport, error)
	ReadStaged(context.Context, MP08StagedOutput) (io.ReadCloser, error)
	PublishAtomic(context.Context, MP08StagedOutput, string) (MP08PublishedOutput, error)
	ReadPublished(context.Context, MP08PublishedOutput) (io.ReadCloser, error)
}
type MP08StagedOutput struct {
	HostToken string `json:"host_token"`
	Size      int64  `json:"size"`
	SHA256    string `json:"sha256"`
}
type MP08PublishedOutput struct {
	URI           string `json:"uri"`
	PublicationID string `json:"publication_id"`
	Size          int64  `json:"size"`
	SHA256        string `json:"sha256"`
	Atomic        bool   `json:"atomic"`
}
type MP08FinalizationReceipt struct {
	SchemaVersion int    `json:"schema_version"`
	Status        string `json:"status"` // refused, verified, completed, partial_published
	DownloadReady bool   `json:"download_ready"`
	Partial       bool   `json:"partial"`
	PublicationID string `json:"publication_id,omitempty"`
	OutputURI     string `json:"output_uri,omitempty"`
	SHA256        string `json:"sha256,omitempty"`
	Bytes         int64  `json:"bytes,omitempty"`
}

// MP08DASHPlan binds the exact MP07 selection and staged receipt to journal
// entries *by identity*, not by caller-provided paths or just representation IDs.
func MP08DASHPlan(req DASHPeriodRequest, staged DASHPeriodSessionReceipt,
	video, audio, subtitle MP08VerifiedStore, destination, container string) (MP08FinalizationPlan, error) {
	p, err := PlanDASHPeriods(req)
	if err != nil || p.IsDynamic || p.NeedsEmbeddedAudioProof || staged.SchemaVersion != DASHPeriodSchemaV1 ||
		staged.Status != "staged" || !staged.ReadyForMux || staged.DownloadReady || staged.NeedsEmbeddedAudioProof || staged.Periods != len(p.Periods) {
		return MP08FinalizationPlan{}, ErrMP08InvalidStage
	}
	result := MP08FinalizationPlan{SchemaVersion: MP08SchemaV1, Source: "dash_static", DestinationKey: destination,
		Container: container, RequireAudio: req.RequireAudio}
	totalTracks := 0
	for _, pp := range p.Periods {
		totalTracks += len(pp.Tracks)
		result.ExpectedDurationMS += pp.DurationMS
	}
	if totalTracks == 0 || totalTracks > mp08MaxTracks || len(staged.Tracks) != totalTracks {
		return MP08FinalizationPlan{}, ErrMP08InvalidStage
	}
	index := 0
	for _, pp := range p.Periods {
		for _, selected := range pp.Tracks {
			rt := staged.Tracks[index]
			index++
			if rt.Role != selected.Role || rt.PeriodID != pp.ID || rt.RepresentationID != selected.RepresentationID ||
				rt.Expected != len(selected.fragments) || rt.Verified != rt.Expected || rt.Missing != 0 ||
				len(rt.ArtifactRefs) != rt.Expected || (selected.RequiresInit && !rt.InitVerified) {
				return MP08FinalizationPlan{}, ErrMP08InvalidStage
			}
			if selected.Role == "audio" {
				result.RequireAudio = true
			}
			store := video
			if selected.Role == "audio" {
				store = audio
			} else if selected.Role == "subtitle" {
				store = subtitle
				result.RequireSubtitle = true
			}
			if store == nil {
				return MP08FinalizationPlan{}, ErrMP08MissingProof
			}
			inventory := mp08Inventory(store)
			track := MP08Track{Role: selected.Role, PeriodID: pp.ID, RepresentationID: selected.RepresentationID,
				StartMS: pp.StartMS, DurationMS: pp.DurationMS, store: store}
			for i, f := range selected.fragments {
				id, e := FragmentID(f.Identity)
				if e != nil {
					return MP08FinalizationPlan{}, ErrMP08MissingProof
				}
				rec, ok := inventory[id]
				if !ok || rec.ID != id || rec.LocalArtifactRef != rt.ArtifactRefs[i] || rec.Role != selected.Role ||
					rec.AttemptGeneration <= 0 || rec.AttemptGeneration > req.AttemptGeneration || !mp08Proof(store, rec) {
					return MP08FinalizationPlan{}, ErrMP08MissingProof
				}
				track.Parts = append(track.Parts, rec)
				var initForThis *FragmentRecord
				if f.InitializationURL != "" {
					initID, e := FragmentID(mp07InitIdentity(f))
					if e != nil {
						return MP08FinalizationPlan{}, ErrMP08MissingProof
					}
					initRec, ok := inventory[initID]
					if !ok || initRec.Role != "init" || !mp08Proof(store, initRec) {
						return MP08FinalizationPlan{}, ErrMP08MissingProof
					}
					initForThis = &initRec
					if track.Init == nil {
						track.Init = &initRec
					}
				}
				track.InitForPart = append(track.InitForPart, initForThis)
			}
			if selected.RequiresInit && track.Init == nil {
				return MP08FinalizationPlan{}, ErrMP08MissingProof
			}
			result.Tracks = append(result.Tracks, track)
		}
	}
	if err := mp08CheckPlan(result); err != nil {
		return MP08FinalizationPlan{}, err
	}
	result.validated = true
	result.seal = mp08PlanSeal(result)
	return result, nil
}

// MP08HLSPlan uses MP06's exact selected playlists, not arbitrary art refs.
// The map identity matches the MP06 declaration-time encryption binding.
func MP08HLSPlan(req HLSVODRequest, staged HLSVODSessionReceipt,
	video, audio MP08VerifiedStore, destination, container string) (MP08FinalizationPlan, error) {
	p, err := PlanHLSVOD(req)
	if err != nil || p.NeedsEmbeddedAudioProof || staged.SchemaVersion != HLSVODSchemaV1 ||
		staged.Status != "staged" || !staged.ReadyForMux || staged.DownloadReady || staged.NeedsEmbeddedAudioProof ||
		len(p.Tracks) != len(staged.Tracks) {
		return MP08FinalizationPlan{}, ErrMP08InvalidStage
	}
	result := MP08FinalizationPlan{SchemaVersion: MP08SchemaV1, Source: "hls_vod", DestinationKey: destination,
		Container: container, RequireAudio: req.RequireAudio, ExpectedDurationMS: int64(math.Round(p.Tracks[0].DurationSeconds * 1000))}
	for i, planned := range p.Tracks {
		rt := staged.Tracks[i]
		if rt.Role != planned.Role || rt.Status != "staged" || rt.MissingCount != 0 || rt.IntentionalGaps != 0 ||
			rt.NonGapExpected != planned.ExpectedParts || rt.DurableCount != rt.NonGapExpected ||
			len(rt.ArtifactRefs) != rt.DurableCount {
			return MP08FinalizationPlan{}, ErrMP08InvalidStage
		}
		if planned.Role == "audio" {
			result.RequireAudio = true
		}
		store := video
		if planned.Role == "audio" {
			store = audio
		}
		if store == nil {
			return MP08FinalizationPlan{}, ErrMP08MissingProof
		}
		parsed, e := ParseHLSPlaylist(planned.SourceURL, planned.PlaylistBody)
		if e != nil || len(parsed.Segments) != rt.NonGapExpected {
			return MP08FinalizationPlan{}, ErrMP08InvalidStage
		}
		track := MP08Track{Role: planned.Role, PeriodID: "hls-vod", DurationMS: result.ExpectedDurationMS, store: store}
		inventory := mp08Inventory(store)
		for j, seg := range parsed.Segments {
			if seg.Gap {
				return MP08FinalizationPlan{}, ErrMP08InvalidStage
			}
			iden, e := HLSTimelineIdentity(seg)
			if e != nil {
				return MP08FinalizationPlan{}, ErrMP08MissingProof
			}
			id, e := FragmentID(iden)
			if e != nil {
				return MP08FinalizationPlan{}, ErrMP08MissingProof
			}
			rec, ok := inventory[id]
			if !ok || rec.Role != "media" || rec.LocalArtifactRef != rt.ArtifactRefs[j] ||
				rec.AttemptGeneration <= 0 || rec.AttemptGeneration > req.AttemptGeneration || !mp08Proof(store, rec) {
				return MP08FinalizationPlan{}, ErrMP08MissingProof
			}
			track.Parts = append(track.Parts, rec)
			var initForThis *FragmentRecord
			if seg.Map != nil {
				mID := FragmentIdentity{Protocol: FragmentProtocolHLS, TimelineKey: "init:" + iden.TimelineKey,
					ResourceID: iden.ResourceID + ":init-map", Range: cloneByteRange(seg.Map.Range)}
				if key := seg.Map.Key; key != nil && key.Method == HLSProtectionAES128 {
					mID.Range = nil
					mID.EncryptionID = string(key.Method) + ":" + digestID("hls-init-key", strings.Join([]string{key.ResolvedURI, key.IV}, "\x00"))
				}
				mid, e := FragmentID(mID)
				if e != nil {
					return MP08FinalizationPlan{}, ErrMP08MissingProof
				}
				initRec, ok := inventory[mid]
				if !ok || initRec.Role != "init" || !mp08Proof(store, initRec) {
					return MP08FinalizationPlan{}, ErrMP08MissingProof
				}
				initForThis = &initRec
				if track.Init == nil {
					track.Init = &initRec
				}
			}
			track.InitForPart = append(track.InitForPart, initForThis)
		}
		result.Tracks = append(result.Tracks, track)
	}
	if err := mp08CheckPlan(result); err != nil {
		return MP08FinalizationPlan{}, err
	}
	result.validated = true
	result.seal = mp08PlanSeal(result)
	return result, nil
}

func mp08Inventory(store MP08VerifiedStore) map[string]FragmentRecord {
	out := map[string]FragmentRecord{}
	if store == nil {
		return out
	}
	for _, r := range store.CommittedRecords() {
		if r.ID != "" {
			out[r.ID] = r
		}
	}
	return out
}
func mp08Proof(store MP08VerifiedStore, rec FragmentRecord) bool {
	if store == nil || rec.State != FragmentCommitted || !rec.DurableBytesWritten ||
		rec.AttemptGeneration <= 0 || rec.ExpectedLength <= 0 || rec.LocalArtifactRef == "" ||
		len(rec.Hash) != 71 || !strings.HasPrefix(rec.Hash, "sha256:") || store.VerifyCommitted(rec) != nil {
		return false
	}
	body, err := store.ReadVerified(rec.Identity)
	if err != nil || int64(len(body)) != rec.ExpectedLength {
		return false
	}
	sum := sha256.Sum256(body)
	return "sha256:"+hex.EncodeToString(sum[:]) == rec.Hash
}
func mp08PlanSeal(p MP08FinalizationPlan) string {
	// Private store capabilities are intentionally omitted from JSON; the
	// underlying MP05 receipts are independently rechecked before mux.
	b, e := json.Marshal(p)
	if e != nil {
		return ""
	}
	d := sha256.Sum256(b)
	return hex.EncodeToString(d[:])
}

func mp08CheckPlan(p MP08FinalizationPlan) error {
	if p.SchemaVersion != MP08SchemaV1 || !mp08SafeName.MatchString(p.DestinationKey) ||
		(p.Container != "mp4" && p.Container != "mkv") || p.ExpectedDurationMS <= 0 || p.ExpectedDurationMS > 24*60*60*1000 ||
		len(p.Tracks) == 0 || len(p.Tracks) > mp08MaxTracks {
		return ErrMP08InvalidStage
	}
	roles := map[string]int{}
	prevStart := int64(-1)
	for _, t := range p.Tracks {
		if t.Role != "video" && t.Role != "audio" && t.Role != "subtitle" {
			return ErrMP08InvalidStage
		}
		if len(t.Parts) == 0 || len(t.Parts) > mp08MaxPartsPerTrack || len(t.InitForPart) != len(t.Parts) || t.store == nil ||
			t.DurationMS <= 0 || t.StartMS < 0 || t.StartMS > p.ExpectedDurationMS {
			return ErrMP08InvalidStage
		}
		if t.Init != nil {
			for _, init := range t.InitForPart {
				if init == nil {
					return ErrMP08MissingProof
				}
			}
		}
		if prevStart > t.StartMS {
			return ErrMP08InvalidStage
		}
		prevStart = t.StartMS
		roles[t.Role]++
	}
	if roles["video"] == 0 || (p.RequireAudio && roles["audio"] == 0) || (p.RequireSubtitle && roles["subtitle"] == 0) {
		return ErrMP08InvalidStage
	}
	return nil
}

// RunMP08VerifiedPublication revalidates every source immediately before mux.
// A trusted host must execute typed FFmpeg, probe the staged file, atomically
// publish then independently read back the *published* bytes. Failure never
// returns DownloadReady or a fabricated completion receipt.
func RunMP08VerifiedPublication(ctx context.Context, p MP08FinalizationPlan, host MP08Host) (MP08FinalizationReceipt, error) {
	receipt := MP08FinalizationReceipt{SchemaVersion: MP08SchemaV1, Status: "refused"}
	if !p.validated || p.seal == "" || p.seal != mp08PlanSeal(p) {
		return receipt, ErrMP08InvalidStage
	}
	if ctx == nil || host == nil || p.Partial {
		return receipt, ErrMP08InvalidStage
	}
	if err := mp08CheckPlan(p); err != nil {
		return receipt, err
	}
	for _, t := range p.Tracks {
		for _, init := range t.InitForPart {
			if init != nil && !mp08Proof(t.store, *init) {
				return receipt, ErrMP08MissingProof
			}
		}
		for _, rec := range t.Parts {
			if !mp08Proof(t.store, rec) {
				return receipt, ErrMP08MissingProof
			}
		}
	}
	if err := ctx.Err(); err != nil {
		return receipt, err
	}
	staged, err := host.Assemble(ctx, p)
	if err != nil || !mp08OutputValid(staged.Size, staged.SHA256) || !mp08SafeName.MatchString(staged.HostToken) {
		return receipt, ErrMP08Publication
	}
	stream, err := host.ReadStaged(ctx, staged)
	if err != nil || mp08HashStream(stream, staged.Size, staged.SHA256) != nil {
		return receipt, ErrMP08Publication
	}
	probe, err := host.Probe(ctx, staged)
	if err != nil || mp08ProbeCheck(p, probe, staged.Size) != nil {
		return receipt, ErrMP08Probe
	}
	if err := ctx.Err(); err != nil {
		return receipt, err
	}
	output, err := host.PublishAtomic(ctx, staged, p.DestinationKey)
	if err != nil || !output.Atomic || output.Size != staged.Size || output.SHA256 != staged.SHA256 ||
		!mp08OutputValid(output.Size, output.SHA256) || !mp08SafeName.MatchString(output.PublicationID) ||
		!strings.HasPrefix(output.URI, "content://") || strings.ContainsAny(output.URI, "\r\n\x00?#") {
		return receipt, ErrMP08Publication
	}
	published, err := host.ReadPublished(ctx, output)
	if err != nil || mp08HashStream(published, output.Size, output.SHA256) != nil {
		return receipt, ErrMP08Publication
	}
	receipt.Status = "completed"
	receipt.DownloadReady = true
	receipt.OutputURI = output.URI
	receipt.PublicationID = output.PublicationID
	receipt.SHA256 = output.SHA256
	receipt.Bytes = output.Size
	return receipt, nil
}

// Partial salvage remains separate and opt-in. Even a verified partial artifact
// can never be promoted to completed/DownloadReady by this automatic API.
func RunMP08PartialRecovery(ctx context.Context, p MP08FinalizationPlan, host MP08Host, ack bool) (MP08FinalizationReceipt, error) {
	receipt := MP08FinalizationReceipt{SchemaVersion: MP08SchemaV1, Status: "partial_refused", Partial: true}
	if !ack || !p.Partial || ctx == nil || host == nil {
		return receipt, ErrMP08PartialConsent
	}
	// The UI/recovery approval and Android publication adapter are not yet
	// qualified: fail closed instead of making a phantom partial-publication.
	return receipt, ErrMP08PartialConsent
}
func mp08OutputValid(size int64, digest string) bool {
	if size < mp08MinOutputBytes || len(digest) != 71 || !strings.HasPrefix(digest, "sha256:") {
		return false
	}
	for _, ch := range digest[7:] {
		if !(ch >= '0' && ch <= '9' || ch >= 'a' && ch <= 'f') {
			return false
		}
	}
	return true
}
func mp08HashStream(stream io.ReadCloser, size int64, digest string) error {
	if stream == nil {
		return ErrMP08Publication
	}
	defer stream.Close()
	h := sha256.New()
	n, err := io.Copy(h, io.LimitReader(stream, size+1))
	if err != nil || n != size || "sha256:"+hex.EncodeToString(h.Sum(nil)) != digest {
		return ErrMP08Publication
	}
	return nil
}
func mp08ProbeCheck(p MP08FinalizationPlan, probe FFProbeReport, size int64) error {
	if probe.Size != size || probe.Size < mp08MinOutputBytes || probe.Duration <= 0 ||
		probe.Container != p.Container || len(probe.Streams) == 0 {
		return ErrMP08Probe
	}
	expected := time.Duration(p.ExpectedDurationMS) * time.Millisecond
	diff := probe.Duration - expected
	if diff < 0 {
		diff = -diff
	}
	tol := expected / 20
	if tol < 2*time.Second {
		tol = 2 * time.Second
	}
	if diff > tol {
		return ErrMP08Probe
	}
	roles := map[StreamKind]int{}
	for _, st := range probe.Streams {
		if st.Kind != StreamVideo && st.Kind != StreamAudio && st.Kind != StreamSubtitle {
			return ErrMP08Probe
		}
		roles[st.Kind]++
	}
	if roles[StreamVideo] == 0 || (p.RequireAudio && roles[StreamAudio] == 0) || (p.RequireSubtitle && roles[StreamSubtitle] == 0) {
		return ErrMP08Probe
	}
	return nil
}

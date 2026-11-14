package media

// MP10 P02: all-track two-phase live URL reauthorization. Preview reads are
// scoped by the Android authorized broker. No preview byte is committed, and
// an incompatible timeline never rewrites or deletes the MP05 fragment journal.
import (
	"context"
	"time"
)

type MP10RefreshCandidate struct {
	Role        string
	ManifestURL string // ephemeral: never log or serialize the candidate
	HLS         HLSFetcher
	DASH        DASHFetcher
}

type mp10PreparedRefresh struct {
	poll        *LivePollEngine
	originalURL string
	newURL      string
	hls         HLSFetcher
	dash        DASHFetcher
}

func (e *LivePollEngine) mp10PrepareRefresh(ctx context.Context, next MP10RefreshCandidate) (mp10PreparedRefresh, error) {
	if e == nil || ctx == nil {
		return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if err := MP10ValidateRefreshBinding(e.spec.ManifestURL, next.ManifestURL); err != nil {
		return mp10PreparedRefresh{}, err
	}
	previous := e.store.CommittedRecords()
	if len(previous) == 0 || len(previous) > 4096 {
		return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
	}
	committed := make(map[string]FragmentRecord, len(previous))
	for _, rec := range previous {
		if rec.State != FragmentCommitted || rec.AttemptGeneration != e.session.generation || !rec.DurableBytesWritten {
			continue
		}
		id, err := FragmentID(rec.Identity)
		if err != nil || id != rec.ID {
			return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
		}
		committed[id] = rec
	}
	// The new manifest must overlap a readback-verified fragment of this exact
	// source. An advanced live window with no overlap remains quarantined.
	overlap := false
	request, cancel, err := e.session.PollContext(ctx)
	if err != nil {
		return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
	}
	defer cancel()
	switch e.spec.Protocol {
	case FragmentProtocolHLS:
		if next.HLS == nil {
			return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
		}
		response, err := next.HLS.FetchHLS(request, HLSFetchRequest{URI: next.ManifestURL, Kind: HLSFetchManifest, CredentialRef: e.spec.CredentialRef})
		if err != nil || len(response.Bytes) == 0 || len(response.Bytes) > e.spec.MaxManifestBytes {
			return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
		}
		manifest, err := ParseHLSPlaylist(next.ManifestURL, string(response.Bytes))
		if err != nil || manifest.Kind != HLSPlaylistMedia || len(manifest.Segments) == 0 || len(manifest.Segments) > e.spec.MaxFragmentsPerPoll {
			return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
		}
		for _, seg := range manifest.Segments {
			if seg.Gap {
				continue
			}
			ident, err := HLSTimelineIdentity(seg)
			if err != nil {
				return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
			}
			id, err := FragmentID(ident)
			if err != nil {
				return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
			}
			if old, ok := committed[id]; ok {
				if e.store.VerifyCommitted(old) != nil {
					return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
				}
				overlap = true
			}
		}
	case FragmentProtocolDASH:
		if next.DASH == nil {
			return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
		}
		response, err := next.DASH.FetchDASH(request, DASHFetchRequest{URI: next.ManifestURL, Kind: DASHFetchManifest, CredentialRef: e.spec.CredentialRef})
		if err != nil || len(response.Bytes) == 0 || len(response.Bytes) > e.spec.MaxManifestBytes {
			return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
		}
		manifest, err := ParseDASHManifest(next.ManifestURL, string(response.Bytes))
		if err != nil || len(manifest.Periods) != 1 {
			return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
		}
		parts, err := ExpandDASHFragments(manifest)
		if err != nil || len(parts) == 0 || len(parts) > 8*e.spec.MaxFragmentsPerPoll {
			return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
		}
		selected := 0
		for _, seg := range parts {
			if seg.RepresentationID != e.spec.DASHRepresentationID {
				continue
			}
			selected++
			if selected > e.spec.MaxFragmentsPerPoll {
				return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
			}
			id, err := FragmentID(seg.Identity)
			if err != nil {
				return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
			}
			if old, ok := committed[id]; ok {
				if e.store.VerifyCommitted(old) != nil {
					return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
				}
				overlap = true
			}
		}
	default:
		return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
	}
	if !overlap {
		return mp10PreparedRefresh{}, ErrMP10RefreshIdentity
	}
	return mp10PreparedRefresh{poll: e, originalURL: e.spec.ManifestURL, newURL: next.ManifestURL, hls: next.HLS, dash: next.DASH}, nil
}

// mp10VerifySessionMedia proves the complete session-owned media inventory,
// not merely the fragments that a store elects to return as healthy.
// In particular FileFragmentStore.CommittedRecords silently filters files
// failing readback. Comparing it against the session's previously observed
// inventory ensures that corruption cannot be hidden by that filtering.
// This is called while MP09Recording.mu holds the recording authority.
func (r *MP09Recording) mp10VerifySessionMedia() error {
	if r == nil || r.session == nil || len(r.tracks) == 0 {
		return ErrMP10RefreshIdentity
	}
	r.session.mu.Lock()
	expected := make(map[string]FragmentRecord, len(r.session.parts))
	for key, rec := range r.session.parts {
		expected[key] = rec
	}
	expectedBytes := r.session.bytes
	r.session.mu.Unlock()
	if len(expected) == 0 || len(expected) > 4096 || expectedBytes <= 0 {
		return ErrMP10RefreshIdentity
	}
	seen := make(map[string]bool, len(expected))
	var observedBytes int64
	for _, track := range r.tracks {
		if track == nil || track.store == nil {
			return ErrMP10RefreshIdentity
		}
		// This list is NOT authoritative by itself: a corrupt committed file
		// can disappear from it. Every session record must be found below.
		healthy := track.store.CommittedRecords()
		if len(healthy) > 4096 {
			return ErrMP10RefreshIdentity
		}
		mediaCount := 0
		for _, rec := range healthy {
			if rec.Role == "init" {
				// Initialization maps do not appear in LiveSession.parts,
				// but any returned init receipt must still pass readback.
				if track.store.VerifyCommitted(rec) != nil {
					return ErrMP10RefreshIdentity
				}
				continue
			}
			want, ok := expected[rec.ID]
			if !ok || seen[rec.ID] || want.ID != rec.ID ||
				want.State != FragmentCommitted || !want.DurableBytesWritten ||
				want.AttemptGeneration != r.session.generation ||
				want.ExpectedLength <= 0 || want.ExpectedLength != rec.ExpectedLength ||
				want.Hash != rec.Hash || want.LocalArtifactRef != rec.LocalArtifactRef ||
				want.AttemptGeneration != rec.AttemptGeneration || want.Role != rec.Role {
				return ErrMP10RefreshIdentity
			}
			id, err := FragmentID(rec.Identity)
			if err != nil || id != rec.ID {
				return ErrMP10RefreshIdentity
			}
			wantID, err := FragmentID(want.Identity)
			if err != nil || wantID != rec.ID {
				return ErrMP10RefreshIdentity
			}
			if track.store.VerifyCommitted(want) != nil {
				return ErrMP10RefreshIdentity
			}
			if observedBytes > expectedBytes-want.ExpectedLength {
				return ErrMP10RefreshIdentity
			}
			observedBytes += want.ExpectedLength
			seen[rec.ID] = true
			mediaCount++
		}
		if mediaCount == 0 {
			return ErrMP10RefreshIdentity
		}
	}
	// A missing record may have been hidden by CommittedRecords' health
	// filter; a mismatch always refuses without changing or deleting bytes.
	if len(seen) != len(expected) || observedBytes != expectedBytes {
		return ErrMP10RefreshIdentity
	}
	return nil
}

func (r *MP09Recording) MP10Reauthorize(ctx context.Context, now time.Time, approved bool, formerRoot, renewedRoot string, generation uint64, candidates ...MP10RefreshCandidate) error {
	if r == nil || ctx == nil || !approved || generation == 0 || now.IsZero() {
		return ErrMP10RefreshIdentity
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.stopped || r.cancelled || r.finalized || generation <= r.refreshGeneration || len(candidates) != len(r.tracks) {
		return ErrMP10RefreshIdentity
	}
	if err := MP10ValidateRefreshBinding(formerRoot, renewedRoot); err != nil {
		return err
	}
	snapshot, err := r.session.Snapshot()
	if err != nil || (snapshot.State != LiveSessionRecoverable && snapshot.State != LiveSessionCapturing) {
		return ErrMP10RefreshIdentity
	}
	// Verify ALL previously observed video/audio media before any preview.
	// A corrupt non-overlapping fragment is a failed rebind, too.
	if err := r.mp10VerifySessionMedia(); err != nil {
		return ErrMP10RefreshIdentity
	}
	plans := make([]mp10PreparedRefresh, 0, len(candidates))
	roles := make(map[string]bool, len(candidates))
	for _, candidate := range candidates {
		if roles[candidate.Role] {
			return ErrMP10RefreshIdentity
		}
		roles[candidate.Role] = true
		found := false
		for _, track := range r.tracks {
			if track.role != candidate.Role {
				continue
			}
			found = true
			plan, e := track.poll.mp10PrepareRefresh(ctx, candidate)
			if e != nil {
				return ErrMP10RefreshIdentity
			}
			plans = append(plans, plan)
		}
		if !found {
			return ErrMP10RefreshIdentity
		}
	}
	if len(plans) != len(r.tracks) {
		return ErrMP10RefreshIdentity
	}
	// All previews and durable readbacks succeeded. Apply both bindings only
	// now, and preserve journal generation, bytes, gaps and previous coverage.
	for _, p := range plans {
		p.poll.mu.Lock()
		if p.poll.spec.ManifestURL != p.originalURL {
			p.poll.mu.Unlock()
			return ErrMP10RefreshIdentity
		}
		p.poll.mu.Unlock()
	}
	for _, p := range plans {
		p.poll.mu.Lock()
		p.poll.spec.ManifestURL = p.newURL
		p.poll.hls = p.hls
		p.poll.dash = p.dash
		p.poll.refreshRequired = false
		p.poll.mu.Unlock()
	}
	r.refreshGeneration = generation
	for _, track := range r.tracks {
		if !track.ended {
			track.next = now
			track.failures = 0
		}
	}
	return nil
}

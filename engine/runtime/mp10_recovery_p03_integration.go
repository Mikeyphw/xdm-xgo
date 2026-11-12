package runtime

// MP10 P03: process-death inventory fencing is bolted onto the existing
// MP09 resume_interrupted path. There is no implicit network authorization,
// new storage location, auto-publication, journal rewrite or cleanup here.
import (
	"context"
	"time"

	"github.com/subhra74/xdm/engine/media"
)

func mp10FenceInterruptedRecording(ctx context.Context, inv *Invocation, capture, root string,
	req mp09LiveCommand, sealed mp09StoredSession, now time.Time,
	video, audio *mp09AndroidStore) ([32]byte, error) {
	var empty [32]byte
	if ctx == nil || inv == nil || video == nil || audio == nil ||
		video.base == nil || audio.base == nil || video.base.captureID != capture || audio.base.captureID != capture {
		return empty, errMP10RecoveryFence
	}
	// A source journal may have entered publishing/published while Go was
	// re-reading the fragments. The source binding and phase are rechecked
	// before AND after each all-role inventory barrier.
	repeat, err := mp09ReadSession(ctx, inv, capture, root, req, now)
	if err != nil || repeat != sealed || sealed.Phase != "recording" {
		return empty, errMP10RecoveryFence
	}
	expected := make([]mp10RecoveryExpected, 0, len(video.records)+len(audio.records))
	actual := make(map[string]struct {
		rec   media.FragmentRecord
		store *mp09AndroidStore
	})
	for _, item := range []struct {
		role  string
		store *mp09AndroidStore
	}{
		{"video", video}, {"audio", audio},
	} {
        for _, rec := range item.store.CommittedRecords() {
            var span *mp10RecoveryRange
            if rec.Identity.Range != nil {
                span = &mp10RecoveryRange{Offset: rec.Identity.Range.Offset, Length: rec.Identity.Range.Length}
            }
			if _, present := actual[rec.ID]; present {
				return empty, errMP10RecoveryFence
			}
			expected = append(expected, mp10RecoveryExpected{
				FragmentID: rec.ID, Hash: rec.Hash, Artifact: rec.LocalArtifactRef,
				TrackRole: item.role, Role: rec.Role, Generation: rec.AttemptGeneration,
				Length: rec.ExpectedLength, Protocol: string(rec.Identity.Protocol),
				Timeline: rec.Identity.TimelineKey, ResourceID: rec.Identity.ResourceID,
                Range: span, EncryptionID: rec.Identity.EncryptionID,
			})
			actual[rec.ID] = struct {
				rec   media.FragmentRecord
				store *mp09AndroidStore
			}{rec, item.store}
		}
	}
	payload, err := mp09SessionRequest(ctx, inv, map[string]any{
		"action": "inventory", "capture_id": capture, "track_role": "all",
	})
	if err != nil {
		return empty, errMP10RecoveryFence
	}
	proof, err := mp10CheckRecoveryFence(payload, capture, sealed.Binding,
		mp09SourceBinding(root, req), sealed.Phase, sealed.Protocol, sealed.Generation, expected,
		func(item mp10RecoveryExpected) error {
			found, ok := actual[item.FragmentID]
			if !ok || found.store.VerifyCommitted(found.rec) != nil {
				return errMP10RecoveryFence
			}
			return nil
		})
	if err != nil {
		return empty, errMP10RecoveryFence
	}
	confirmed, err := mp09ReadSession(ctx, inv, capture, root, req, now)
	if err != nil || confirmed != sealed {
		return empty, errMP10RecoveryFence
	}
	return proof, nil
}

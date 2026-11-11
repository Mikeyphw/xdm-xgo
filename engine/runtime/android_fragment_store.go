package runtime

// MP05: typed Go -> Android app-private durability port. Android is the only
// file writer in this mode. A correlated write *and a second verify* must both
// succeed before Go may claim DurableBytesWritten. No DRM, URL or credentials
// are carried over this port. MP06 will bind this to the unified executor.
import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"strings"
	"time"

	"github.com/subhra74/xdm/engine/media"
	"github.com/subhra74/xdm/engine/runtime/platform"
)

const mp05MaxBridgeFragmentBytes = 2 << 20

type androidFragmentStoreAdapter struct {
	inv       *Invocation
	captureID string
	roleHint string // MP09 per-track inventory only; never emitted in public receipt
}

func newAndroidFragmentStoreAdapter(inv *Invocation, captureID string) (media.DurableFragmentSink, error) {
	if inv == nil || strings.TrimSpace(captureID) == "" || len(captureID) > 256 {
		return nil, media.ErrFragmentDurability
	}
	return &androidFragmentStoreAdapter{inv: inv, captureID: captureID}, nil
}

type androidFragmentReceipt struct {
	FragmentID     string `json:"fragment_id"`
	Generation     int64  `json:"generation"`
	Hash           string `json:"hash"`
	ExpectedLength int64  `json:"expected_length"`
	ArtifactRef    string `json:"artifact_ref"`
}

func (a *androidFragmentStoreAdapter) request(ctx context.Context, payload map[string]any) (androidFragmentReceipt, error) {
	var empty androidFragmentReceipt
	raw, err := json.Marshal(payload)
	if err != nil {
		return empty, media.ErrFragmentDurability
	}
	reply, err := a.inv.PlatformRequest(ctx, platform.AndroidFragmentStore, platform.Refs{}, raw)
	if err != nil || !reply.OK {
		return empty, media.ErrFragmentDurability
	}
	var r androidFragmentReceipt
	if len(reply.Payload) > 4096 || json.Unmarshal(reply.Payload, &r) != nil {
		return empty, media.ErrFragmentDurability
	}
	return r, nil
}
func (a *androidFragmentStoreAdapter) WriteAndCommitFragment(ctx context.Context, rec media.FragmentRecord, bytes []byte) (media.FragmentRecord, error) {
	if a == nil || len(bytes) == 0 || len(bytes) > mp05MaxBridgeFragmentBytes || rec.Role == "key" || rec.AttemptGeneration <= 0 {
		return media.FragmentRecord{}, media.ErrFragmentDurability
	}
	id, err := media.FragmentID(rec.Identity)
	if err != nil {
		return media.FragmentRecord{}, err
	}
	sum := sha256.Sum256(bytes)
	hash := "sha256:" + hex.EncodeToString(sum[:])
	if rec.Hash != "" && rec.Hash != hash {
		return media.FragmentRecord{}, media.ErrFragmentHashMismatch
	}
	r, err := a.request(ctx, map[string]any{
		"action": "write", "capture_id": a.captureID, "fragment_id": id,
		"generation": rec.AttemptGeneration, "role": rec.Role, "expected_length": int64(len(bytes)),
		"hash": hash, "body_base64": base64.StdEncoding.EncodeToString(bytes),
        "identity":rec.Identity, "track_role":a.roleHint,
	})
	if err != nil {
		return media.FragmentRecord{}, err
	}
	if !receiptMatches(r, id, rec.AttemptGeneration, hash, int64(len(bytes))) {
		return media.FragmentRecord{}, media.ErrFragmentDurability
	}
	verified, err := a.request(ctx, map[string]any{"action": "verify", "capture_id": a.captureID,
		"fragment_id": id, "generation": rec.AttemptGeneration, "expected_length": int64(len(bytes)), "hash": hash})
	if err != nil || verified != r {
		return media.FragmentRecord{}, media.ErrFragmentDurability
	}
	rec.ID = id
	rec.State = media.FragmentCommitted
	rec.ExpectedLength = int64(len(bytes))
	rec.Hash = hash
	rec.LocalArtifactRef = r.ArtifactRef
	rec.DurableBytesWritten = true
	return rec, nil
}
func (a *androidFragmentStoreAdapter) VerifyCommitted(rec media.FragmentRecord) error {
	if a == nil || !rec.DurableBytesWritten || rec.State != media.FragmentCommitted || rec.AttemptGeneration <= 0 {
		return media.ErrFragmentDurability
	}
	id, err := media.FragmentID(rec.Identity)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	r, err := a.request(ctx, map[string]any{"action": "verify", "capture_id": a.captureID, "fragment_id": id,
		"generation": rec.AttemptGeneration, "expected_length": rec.ExpectedLength, "hash": rec.Hash})
	if err != nil {
		return err
	}
	if !receiptMatches(r, id, rec.AttemptGeneration, rec.Hash, rec.ExpectedLength) || r.ArtifactRef != rec.LocalArtifactRef {
		return media.ErrFragmentDurability
	}
	return nil
}
func receiptMatches(r androidFragmentReceipt, id string, generation int64, hash string, length int64) bool {
	return r.FragmentID == id && r.Generation == generation && r.Hash == hash && r.ExpectedLength == length &&
		strings.HasPrefix(r.ArtifactRef, "parts/") && len(r.ArtifactRef) < 240 &&
		!strings.Contains(r.ArtifactRef, "..") && !strings.Contains(r.ArtifactRef, "\\") &&
		strings.Count(r.ArtifactRef, "/") == 1
}

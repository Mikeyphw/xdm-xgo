package runtime

// MP10 P03: bounded, fail-closed, credential-free recovery inventory fence.
// Android's app-private MP05 journal is the authoritative inventory, but a
// process-death resume is admitted only if two independent observations match
// the already readback-verified Go records and the sealed source binding.
// No URL, secret, key, cookie or filesystem path is emitted in an error.
import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
)

var errMP10RecoveryFence = errors.New("MP10 restart recovery integrity or authorization refused")
var mp10RecoveryCaptureID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,96}$`)
var mp10RecoveryFragmentID = regexp.MustCompile(`^fragment_[0-9a-f]{64}$`)
var mp10RecoveryDigest = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)

// mp10RecoveryExpected comes only from Go's verified MP09 video/audio stores.
// Transport data is intentionally absent; the Artifact is app-private.
// A byterange is identity-bearing for HLS/DASH. A pointer distinguishes
// absent range from a present zero-valued or malformed range.
type mp10RecoveryRange struct {
    Offset int64 `json:"offset"`
    Length int64 `json:"length"`
}

type mp10RecoveryExpected struct {
	FragmentID string
	Hash       string
	Artifact   string
	TrackRole  string
	Role       string
	Protocol   string
	Timeline   string
	ResourceID string
	Range *mp10RecoveryRange
	EncryptionID string
	Generation int64
	Length     int64
}

type mp10RecoveryRecord struct {
	FragmentID string `json:"fragment_id"`
	Hash       string `json:"hash"`
	Artifact   string `json:"artifact_ref"`
	TrackRole  string `json:"track_role"`
	Role       string `json:"role"`
	Generation int64  `json:"generation"`
	Length     int64  `json:"length"`
	Identity   struct {
		Protocol   string `json:"protocol"`
		Timeline   string `json:"timeline_key"`
		ResourceID string `json:"resource_id"`
        Range *mp10RecoveryRange `json:"range,omitempty"`
        EncryptionID string `json:"encryption_id,omitempty"`
	} `json:"identity"`
}

type mp10RecoveryInventory struct {
	OK      bool                 `json:"ok"`
	Records []mp10RecoveryRecord `json:"records"`
	Unbound int                  `json:"unbound_fragments"`
}

// mp10CheckRecoveryFence deliberately contains no platform dependencies so
// its refusals can be tested without Android, Gradle or a real user account.
// verify must perform an independent committed-receipt readback check.
func mp10CheckRecoveryFence(raw []byte, capture, sealedBinding, currentBinding, phase, protocol string,
	generation int64, expected []mp10RecoveryExpected,
	verify func(mp10RecoveryExpected) error) ([32]byte, error) {
	var zero [32]byte
	if !mp10RecoveryCaptureID.MatchString(capture) || !mp10RecoveryDigest.MatchString(sealedBinding) ||
		sealedBinding != currentBinding || phase != "recording" ||
		(protocol != "hls" && protocol != "dash") || generation != 1 ||
		len(raw) == 0 || len(raw) > 512<<10 || verify == nil ||
		len(expected) < 2 || len(expected) > 4096 {
		return zero, errMP10RecoveryFence
	}
	var inventory mp10RecoveryInventory
	if json.Unmarshal(raw, &inventory) != nil || !inventory.OK || inventory.Records == nil ||
		inventory.Unbound != 0 || len(inventory.Records) != len(expected) {
		return zero, errMP10RecoveryFence
	}
	owner := sha256.Sum256([]byte(capture))
	ownerPrefix := hex.EncodeToString(owner[:])
	byID := make(map[string]mp10RecoveryExpected, len(expected))
	paths := make(map[string]bool, len(expected))
	roleMedia := map[string]int{"video": 0, "audio": 0}
	for _, item := range expected {
		if !mp10RecoveryFragmentID.MatchString(item.FragmentID) || !mp10RecoveryDigest.MatchString(item.Hash) ||
			item.Length <= 0 || item.Length > 2<<20 || item.Generation != generation ||
			(item.TrackRole != "video" && item.TrackRole != "audio") ||
			(item.Role != "init" && item.Role != "media" && item.Role != item.TrackRole) ||
			item.Protocol != protocol ||
            item.Timeline == "" || item.ResourceID == "" || len(item.Timeline) > 256 || len(item.ResourceID) > 256 ||
            len(item.EncryptionID) > 256 ||
            (item.Range != nil && (item.Range.Offset < 0 || item.Range.Length <= 0 ||
                item.Range.Offset > (1<<63-1)-item.Range.Length)) {
			return zero, errMP10RecoveryFence
		}
		safeName := fmt.Sprintf("parts/%s-%s-g%d.part", ownerPrefix, item.FragmentID, generation)
		if item.Artifact != safeName || paths[item.Artifact] {
			return zero, errMP10RecoveryFence
		}
		paths[item.Artifact] = true
		if _, exists := byID[item.FragmentID]; exists {
			return zero, errMP10RecoveryFence
		}
		byID[item.FragmentID] = item
		if item.Role != "init" {
			roleMedia[item.TrackRole]++
		}
	}
	if roleMedia["video"] == 0 || roleMedia["audio"] == 0 {
		return zero, errMP10RecoveryFence
	}
	present := make(map[string]bool, len(expected))
	for _, got := range inventory.Records {
		want, exists := byID[got.FragmentID]
		if !exists || present[got.FragmentID] || got.Hash != want.Hash ||
			got.Artifact != want.Artifact || got.TrackRole != want.TrackRole ||
			got.Role != want.Role || got.Generation != want.Generation || got.Length != want.Length ||
			got.Identity.Protocol != want.Protocol || got.Identity.Timeline != want.Timeline ||
            got.Identity.ResourceID != want.ResourceID ||
            got.Identity.EncryptionID != want.EncryptionID ||
            (got.Identity.Range == nil) != (want.Range == nil) ||
            (want.Range != nil && got.Identity.Range != nil &&
                (got.Identity.Range.Offset != want.Range.Offset || got.Identity.Range.Length != want.Range.Length)) {
			return zero, errMP10RecoveryFence
		}
		present[got.FragmentID] = true
	}
	ordered := make([]string, 0, len(byID))
	for id := range byID {
		ordered = append(ordered, id)
	}
	sort.Strings(ordered)
	digest := sha256.New()
	appendField := func(value string) {
		var size [8]byte
		binary.BigEndian.PutUint64(size[:], uint64(len(value)))
		_, _ = digest.Write(size[:])
		_, _ = digest.Write([]byte(value))
	}
	appendField(sealedBinding)
	appendField(capture)
	appendField(phase)
	for _, id := range ordered {
		item := byID[id]
		// Reverify the already restored file after the complete inventory has
		// been checked. A mutated receipt or missing part is never accepted.
		if err := verify(item); err != nil {
			return zero, errMP10RecoveryFence
		}
        rangeMarker := "absent"
        if item.Range != nil { rangeMarker = fmt.Sprintf("%d:%d", item.Range.Offset, item.Range.Length) }
		for _, field := range []string{item.FragmentID, item.TrackRole, item.Role,
			item.Hash, item.Artifact, item.Protocol, item.Timeline, item.ResourceID,
            rangeMarker, item.EncryptionID,
			fmt.Sprint(item.Generation), fmt.Sprint(item.Length)} {
			appendField(field)
		}
	}
	sum := digest.Sum(nil)
	if len(sum) != len(zero) {
		return zero, errMP10RecoveryFence
	}
	copy(zero[:], sum)
	return zero, nil
}

// mp10SameRecoveryFence is constant-time to avoid making a short-circuit
// comparison part of the source's external error surface.
func mp10SameRecoveryFence(a, b [32]byte) bool { return subtle.ConstantTimeCompare(a[:], b[:]) == 1 }

package runtime

// REC01–REC16 are deterministic process-death *recovery fence* fault injection.
// They are real disk readbacks, NOT an API36 emulator or production qualification.
import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const mp10TestCapture = "verified_capture"
const mp10TestPhase = "recording"

type mp10DiskFixture struct {
	root     string
	rows     []mp10RecoveryRecord
	expected []mp10RecoveryExpected
	binding  string
}

func mp10Fixture(t *testing.T) mp10DiskFixture {
	t.Helper()
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "parts"), 0700); err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256([]byte(mp10TestCapture))
	owner := hex.EncodeToString(digest[:])
	f := mp10DiskFixture{root: root, binding: "sha256:" + strings.Repeat("c", 64)}
	for _, role := range []string{"video", "audio"} {
		b := []byte("mp10-p03-verified-" + role)
		idsum := sha256.Sum256([]byte("id:" + role))
		id := "fragment_" + hex.EncodeToString(idsum[:])
		sum := sha256.Sum256(b)
		hash := "sha256:" + hex.EncodeToString(sum[:])
		art := "parts/" + owner + "-" + id + "-g1.part"
		if err := os.WriteFile(filepath.Join(root, art), b, 0600); err != nil {
			t.Fatal(err)
		}
		rec := mp10RecoveryRecord{FragmentID: id, Hash: hash, Artifact: art, TrackRole: role, Role: role, Generation: 1, Length: int64(len(b))}
		rec.Identity.Protocol = "hls"
		rec.Identity.Timeline = "hls:0:1"
		rec.Identity.ResourceID = "mediares_" + hex.EncodeToString(idsum[:])
		f.rows = append(f.rows, rec)
		f.expected = append(f.expected, mp10RecoveryExpected{
			FragmentID: id, Hash: hash, Artifact: art, TrackRole: role, Role: role, Generation: 1,
			Length: int64(len(b)), Protocol: rec.Identity.Protocol, Timeline: rec.Identity.Timeline, ResourceID: rec.Identity.ResourceID,
		})
	}
	return f
}
func (f mp10DiskFixture) payload(unbound int) []byte {
	b, e := json.Marshal(mp10RecoveryInventory{OK: true, Records: f.rows, Unbound: unbound})
	if e != nil {
		panic(e)
	}
	return b
}
func (f mp10DiskFixture) readback(item mp10RecoveryExpected) error {
	path := filepath.Join(f.root, item.Artifact)
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
		return errMP10RecoveryFence
	}
	data, err := os.ReadFile(path)
	if err != nil || int64(len(data)) != item.Length {
		return errMP10RecoveryFence
	}
	sum := sha256.Sum256(data)
	if "sha256:"+hex.EncodeToString(sum[:]) != item.Hash {
		return errMP10RecoveryFence
	}
	return nil
}
func (f mp10DiskFixture) check(raw []byte) ([32]byte, error) {
	return mp10CheckRecoveryFence(raw, mp10TestCapture, f.binding, f.binding, mp10TestPhase, "hls", 1, f.expected, f.readback)
}
func reject(t *testing.T, err error) {
	t.Helper()
	if !errors.Is(err, errMP10RecoveryFence) {
		t.Fatalf("expected fail-closed recovery: %v", err)
	}
	if strings.Contains(err.Error(), mp10TestCapture) || strings.Contains(err.Error(), "parts/") {
		t.Fatal("private recovery metadata leaked")
	}
}
func TestMP10P03REC01ExactRestartReadbackAccepted(t *testing.T) {
	f := mp10Fixture(t)
	before, err := f.check(f.payload(0))
	if err != nil {
		t.Fatal(err)
	}
	after, err := f.check(f.payload(0))
	if err != nil || !mp10SameRecoveryFence(before, after) {
		t.Fatal("stable durable inventory refused", err)
	}
	if before == ([32]byte{}) {
		t.Fatal("missing recovery fingerprint")
	}
}
func TestMP10P03REC02OrphanPartsRefusedWithoutCleanup(t *testing.T) {
	f := mp10Fixture(t)
	_, err := f.check(f.payload(1))
	reject(t, err)
	for _, r := range f.rows {
		if _, err := os.Stat(filepath.Join(f.root, r.Artifact)); err != nil {
			t.Fatal("source evidence deleted", err)
		}
	}
}
func TestMP10P03REC03MissingVideoRefused(t *testing.T) {
	f := mp10Fixture(t)
	f.rows = f.rows[1:]
	_, err := f.check(f.payload(0))
	reject(t, err)
}
func TestMP10P03REC04MissingAudioRefused(t *testing.T) {
	f := mp10Fixture(t)
	f.expected = f.expected[:1]
	f.rows = f.rows[:1]
	_, err := f.check(f.payload(0))
	reject(t, err)
}
func TestMP10P03REC05CorruptBytesRejectedAndPreserved(t *testing.T) {
	f := mp10Fixture(t)
	target := filepath.Join(f.root, f.rows[0].Artifact)
	if err := os.WriteFile(target, []byte("different-but-still-present"), 0600); err != nil {
		t.Fatal(err)
	}
	_, err := f.check(f.payload(0))
	reject(t, err)
	if _, err := os.Stat(target); err != nil {
		t.Fatal("corrupted evidence unexpectedly removed")
	}
}
func TestMP10P03REC06StaleAttemptGenerationRefused(t *testing.T) {
	f := mp10Fixture(t)
	f.rows[0].Generation = 0
	_, err := f.check(f.payload(0))
	reject(t, err)
}
func TestMP10P03REC07DuplicateIdentityRefused(t *testing.T) {
	f := mp10Fixture(t)
	f.rows = append(f.rows, f.rows[0])
	f.expected = append(f.expected, f.expected[0])
	_, err := f.check(f.payload(0))
	reject(t, err)
}
func TestMP10P03REC08CrossTrackRoleSwapRefused(t *testing.T) {
	f := mp10Fixture(t)
	f.rows[0].TrackRole = "audio"
	_, err := f.check(f.payload(0))
	reject(t, err)
}
func TestMP10P03REC09TimelineIdentityDriftRefused(t *testing.T) {
	f := mp10Fixture(t)
	f.rows[0].Identity.Timeline = "hls:99:999"
	_, err := f.check(f.payload(0))
	reject(t, err)
}
func TestMP10P03REC10DifferentSourceBindingRefused(t *testing.T) {
	f := mp10Fixture(t)
	_, err := mp10CheckRecoveryFence(f.payload(0), mp10TestCapture, f.binding, "sha256:"+strings.Repeat("d", 64), "recording", "hls", 1, f.expected, f.readback)
	reject(t, err)
}
func TestMP10P03REC11PublishingOrPublishedNeverResumed(t *testing.T) {
	f := mp10Fixture(t)
	for _, phase := range []string{"publishing", "published", "published_clean", "missing"} {
		_, err := mp10CheckRecoveryFence(f.payload(0), mp10TestCapture, f.binding, f.binding, phase, "hls", 1, f.expected, f.readback)
		reject(t, err)
	}
}
func TestMP10P03REC12ConcurrentJournalMutationBreaksFence(t *testing.T) {
	f := mp10Fixture(t)
	first, err := f.check(f.payload(0))
	if err != nil {
		t.Fatal(err)
	}
	// The second inventory/readback barrier catches a journal row modified
	// while process-restart hydration is in progress.
	f.rows[0].Length++
	second, err := f.check(f.payload(0))
	reject(t, err)
	if second == first {
		t.Fatal("changed recovery inventory reused old digest")
	}
}
func TestMP10P03REC13SymlinkAndArtifactScopeRefused(t *testing.T) {
	f := mp10Fixture(t)
	f.expected[0].Artifact = "parts/../../escape.part"
	_, err := f.check(f.payload(0))
	reject(t, err)
	f = mp10Fixture(t)
	path := filepath.Join(f.root, f.rows[0].Artifact)
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(f.root, f.rows[1].Artifact), path); err != nil {
		t.Skip("symlink unsupported", err)
	}
	_, err = f.check(f.payload(0))
	reject(t, err)
}
func TestMP10P03REC14MalformedAndOversizedJournalRefused(t *testing.T) {
	f := mp10Fixture(t)
	for _, raw := range [][]byte{nil, []byte("{"), bytesRepeat('x', 512<<10+1), []byte(`{"ok":true,"records":null}`)} {
		_, err := f.check(raw)
		reject(t, err)
	}
}
func bytesRepeat(b byte, n int) []byte {
	out := make([]byte, n)
	for i := range out {
		out[i] = b
	}
	return out
}
func TestMP10P03REC15MissingReadbackVerifierRefused(t *testing.T) {
	f := mp10Fixture(t)
	_, err := mp10CheckRecoveryFence(f.payload(0), mp10TestCapture, f.binding, f.binding, "recording", "hls", 1, f.expected, nil)
	reject(t, err)
}

// REC16: even exact durable hashes cannot bind DASH parts to an HLS source.
func TestMP10P03REC16WrongRecordedProtocolRefused(t *testing.T) {
	f := mp10Fixture(t)
	f.expected[0].Protocol = "dash"
	f.rows[0].Identity.Protocol = "dash"
	_, err := f.check(f.payload(0))
	reject(t, err)
}

// REC17: modifying a byte-range alone must not pass the second inventory fence.
func TestMP10P03REC17ByteRangeIdentityDriftRefused(t *testing.T) {
    f := mp10Fixture(t)
    f.rows[0].Identity.Range = &mp10RecoveryRange{Offset: 1024, Length: 16}
    f.expected[0].Range = &mp10RecoveryRange{Offset: 1024, Length: 16}
    first, err := f.check(f.payload(0))
    if err != nil { t.Fatal("valid ranged identity rejected", err) }
    f.rows[0].Identity.Range.Offset++
    second, err := f.check(f.payload(0))
    reject(t, err)
    if mp10SameRecoveryFence(first, second) { t.Fatal("changed range retained fingerprint") }
    f.rows[0].Identity.Range = nil
    _, err = f.check(f.payload(0))
    reject(t, err)
}

// REC18: changed IV/key identity is significant even if the stored bytes match.
func TestMP10P03REC18EncryptionIdentityDriftRefused(t *testing.T) {
    f := mp10Fixture(t)
    f.rows[0].Identity.EncryptionID = "aes-128:hls-key_verified"
    f.expected[0].EncryptionID = "aes-128:hls-key_verified"
    first, err := f.check(f.payload(0))
    if err != nil { t.Fatal("valid encrypted identity rejected", err) }
    f.rows[0].Identity.EncryptionID = "aes-128:hls-key_changed"
    second, err := f.check(f.payload(0))
    reject(t, err)
    if mp10SameRecoveryFence(first, second) { t.Fatal("changed encryption identity retained fingerprint") }
}

// REC19: the fingerprint is sensitive to changed range+encryption metadata.
func TestMP10P03REC19FingerprintIncludesFullIdentity(t *testing.T) {
    f := mp10Fixture(t)
    first, err := f.check(f.payload(0))
    if err != nil { t.Fatal(err) }
    f.rows[0].Identity.Range = &mp10RecoveryRange{Offset: 0, Length: 64}
    f.expected[0].Range = &mp10RecoveryRange{Offset: 0, Length: 64}
    f.rows[0].Identity.EncryptionID = "aes-128:verified-key-id"
    f.expected[0].EncryptionID = "aes-128:verified-key-id"
    second, err := f.check(f.payload(0))
    if err != nil { t.Fatal(err) }
    if mp10SameRecoveryFence(first, second) {t.Fatal("full byte-range/cryptographic identity not fingerprinted")}
    // Bad range arithmetic and a zero-length range never become identity.
    f.rows[0].Identity.Range.Length = 0
    f.expected[0].Range.Length = 0
    _, err = f.check(f.payload(0))
    reject(t, err)
}

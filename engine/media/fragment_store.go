package media

// MP05: app-owned durable segment staging. A file and its journal receipt must
// both survive fsync + atomic rename before a fragment is considered committed.
// No signed URL, HTTP header, key material or browser cookie is persisted.
import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
)

var (
	ErrFragmentQuota       = errors.New("fragment store quota exceeded")
	ErrFragmentConflict    = errors.New("fragment store generation conflict")
	ErrFragmentMissing     = errors.New("fragment store durable receipt missing")
	ErrFragmentCorruptFile = errors.New("fragment store digest or length mismatch")
	ErrFragmentUnsafePath  = errors.New("fragment store unsafe path")
)

// DurableFragmentSink is the only MP05 writer admitted by the Go HLS/DASH
// executors. Callers must not synthesize DurableBytesWritten or artifact paths.
type DurableFragmentSink interface {
	WriteAndCommitFragment(context.Context, FragmentRecord, []byte) (FragmentRecord, error)
	VerifyCommitted(FragmentRecord) error
}

// FileFragmentStore is single-process scoped. Files may be opened from the
// app-private files directory, not shared storage; do not instantiate multiple
// writers for one root. The journal is authoritative after a process restart.
type FileFragmentStore struct {
	mu       sync.Mutex
	root     string
	maxBytes int64
	records  map[string]FragmentRecord
	// Injected only by same-package crash tests. Never set in production.
	failpoint func(string) error
}

type fragmentJournalV1 struct {
	Version int              `json:"version"`
	Records []FragmentRecord `json:"records"`
}

func fragmentCheckRoot(root string) error {
	if !filepath.IsAbs(root) || filepath.Clean(root) == "/" {
		return ErrFragmentUnsafePath
	}
	current := filepath.Clean(root)
	for {
		info, err := os.Lstat(current)
		if err == nil && info.Mode()&os.ModeSymlink != 0 {
			return ErrFragmentUnsafePath
		}
		if err != nil && !os.IsNotExist(err) {
			return err
		}
		parent := filepath.Dir(current)
		if parent == current {
			break
		}
		current = parent
	}
	return nil
}

func NewFileFragmentStore(root string, quotaBytes int64) (*FileFragmentStore, error) {
	if err := fragmentCheckRoot(root); err != nil {
		return nil, err
	}
	if quotaBytes <= 0 {
		return nil, ErrFragmentQuota
	}
	if err := os.MkdirAll(filepath.Join(root, "parts"), 0700); err != nil {
		return nil, err
	}
	if err := fragmentCheckRoot(filepath.Join(root, "parts")); err != nil {
		return nil, err
	}
	s := &FileFragmentStore{root: filepath.Clean(root), maxBytes: quotaBytes, records: make(map[string]FragmentRecord)}
	raw, err := os.ReadFile(filepath.Join(s.root, "journal-v1.json"))
	if err != nil && !os.IsNotExist(err) {
		return nil, err
	}
	if len(raw) != 0 {
		var j fragmentJournalV1
		if len(raw) > 32<<20 || json.Unmarshal(raw, &j) != nil || j.Version != 1 {
			return nil, ErrFragmentCorruptFile
		}
		for _, rec := range j.Records {
			id, err := FragmentID(rec.Identity)
			if err != nil || id != rec.ID || s.records[id].ID != "" || rec.AttemptGeneration <= 0 {
				return nil, ErrInvalidFragment
			}
			if rec.State == FragmentCommitted && (!rec.DurableBytesWritten || rec.ExpectedLength <= 0 || rec.LocalArtifactRef != fragmentFileName(id, rec.AttemptGeneration)) {
				return nil, ErrFragmentDurability
			}
			s.records[id] = rec
		}
	}
	if err := s.Reconcile(); err != nil {
		return nil, err
	}
	return s, nil
}

func fragmentFileName(id string, generation int64) string {
	return "parts/" + id + "-g" + fmt.Sprint(generation) + ".part"
}
func (s *FileFragmentStore) fullPath(ref string) (string, error) {
	if !strings.HasPrefix(ref, "parts/fragment_") || strings.Contains(ref, "..") || strings.Contains(ref, "\\") || strings.Contains(ref, "/./") || strings.Count(ref, "/") != 1 {
		return "", ErrFragmentUnsafePath
	}
	return filepath.Join(s.root, ref), nil
}
func (s *FileFragmentStore) fail(stage string) error {
	if s.failpoint != nil {
		return s.failpoint(stage)
	}
	return nil
}
func fragmentSyncDir(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Sync()
}
func fragmentAtomicWrite(path string, payload []byte, hook func(string) error) error {
	dir := filepath.Dir(path)
	f, err := os.CreateTemp(dir, ".mp05-stage-")
	if err != nil {
		return err
	}
	temp := f.Name()
	defer os.Remove(temp)
	if err = f.Chmod(0600); err != nil {
		f.Close()
		return err
	}
	if hook != nil {
		if err = hook("before_write"); err != nil {
			f.Close()
			return err
		}
	}
	n, err := f.Write(payload)
	if err == nil && n != len(payload) {
		err = io.ErrShortWrite
	}
	if err == nil && hook != nil {
		err = hook("after_write")
	}
	if err == nil {
		err = f.Sync()
	}
	if err == nil && hook != nil {
		err = hook("after_fsync")
	}
	cerr := f.Close()
	if err == nil {
		err = cerr
	}
	if err != nil {
		return err
	}
	if err = os.Rename(temp, path); err != nil {
		return err
	}
	if err = fragmentSyncDir(dir); err != nil {
		return err
	}
	if hook != nil {
		return hook("after_rename")
	}
	return nil
}
func fragmentSHA(payload []byte) string {
	sum := sha256.Sum256(payload)
	return "sha256:" + hex.EncodeToString(sum[:])
}

// The HLS media byte range is a CIPHERTEXT transport range. After authorized
// AES-128 CBC + PKCS#7 decryption, the stored plaintext is 1..16 bytes
// shorter. The journal records the real stored byte count and SHA-256; no
// mismatch is permitted for unencrypted media, DASH, or initialization maps.
// The key identity must be a one-way digest, never a signed URL.
func fragmentStoredRangeAllowed(input FragmentRecord, storedBytes int64) bool {
    rng := input.Identity.Range
    if rng == nil { return true }
    if input.Identity.Protocol == FragmentProtocolHLS && input.Role == "media" &&
        strings.HasPrefix(input.Identity.EncryptionID, "aes-128:hls-key_") {
        // A source ciphertext range may not be committed as undeciphered bytes.
        paddingBytes := rng.Length - storedBytes
        return rng.Length >= 16 && rng.Length%16 == 0 && storedBytes > 0 &&
            paddingBytes >= 1 && paddingBytes <= 16
    }
    return rng.Length == storedBytes
}

// WriteAndCommitFragment performs generation-CAS, quota checks, actual file
// flush, directory fsync, journal atomic replacement, then readback proof.
// A crash before journal commit leaves an unreferenced file, never a phantom
// committed record; Reconcile removes only such unreferenced files.
func (s *FileFragmentStore) WriteAndCommitFragment(ctx context.Context, input FragmentRecord, payload []byte) (FragmentRecord, error) {
	if s == nil {
		return FragmentRecord{}, ErrFragmentDurability
	}
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return FragmentRecord{}, err
	}
	id, err := FragmentID(input.Identity)
	if err != nil {
		return FragmentRecord{}, err
	}
	if input.AttemptGeneration <= 0 || len(payload) == 0 || int64(len(payload)) > s.maxBytes || input.Role == "key" {
		return FragmentRecord{}, ErrInvalidFragment
	}
	if strings.Contains(input.Identity.EncryptionID, "://") || !fragmentStoredRangeAllowed(input, int64(len(payload))) {
        return FragmentRecord{}, ErrInvalidFragment
    }
	digest := fragmentSHA(payload)
	if input.Hash != "" && input.Hash != digest {
		return FragmentRecord{}, ErrFragmentHashMismatch
	}
	if input.ExpectedLength > 0 && input.ExpectedLength != int64(len(payload)) {
		return FragmentRecord{}, ErrFragmentCorruptFile
	}
	input.ID = id
	input.State = FragmentCommitted
	input.Hash = digest
	input.ExpectedLength = int64(len(payload))
	input.LocalArtifactRef = fragmentFileName(id, input.AttemptGeneration)
	input.DurableBytesWritten = true
	s.mu.Lock()
	defer s.mu.Unlock()
	if old, exists := s.records[id]; exists {
		if input.AttemptGeneration < old.AttemptGeneration {
			return FragmentRecord{}, ErrFragmentStale
		}
		if input.AttemptGeneration == old.AttemptGeneration {
			if old.State != FragmentCommitted || old.Hash != digest || old.ExpectedLength != int64(len(payload)) || old.Role != input.Role {
				return FragmentRecord{}, ErrFragmentConflict
			}
			if err := s.verifyLocked(old); err != nil {
				return FragmentRecord{}, err
			}
			return old, nil
		}
	}
	if err := ctx.Err(); err != nil {
		return FragmentRecord{}, err
	}
	// Account for every on-disk byte, including orphan data not yet pruned.
	used, err := s.diskUsageLocked()
	if err != nil {
		return FragmentRecord{}, err
	}
	if int64(len(payload)) > s.maxBytes-used {
		return FragmentRecord{}, ErrFragmentQuota
	}
	target, err := s.fullPath(input.LocalArtifactRef)
	if err != nil {
		return FragmentRecord{}, err
	}
	if _, err = os.Lstat(target); err == nil {
		return FragmentRecord{}, ErrFragmentConflict
	} else if !os.IsNotExist(err) {
		return FragmentRecord{}, err
	}
	if err = fragmentAtomicWrite(target, payload, s.fail); err != nil {
		return FragmentRecord{}, err
	}
	if err = ctx.Err(); err != nil {
		return FragmentRecord{}, err
	}
	next := make(map[string]FragmentRecord, len(s.records)+1)
	for k, v := range s.records {
		next[k] = v
	}
	next[id] = input
	if err = s.writeJournalLocked(next); err != nil {
		return FragmentRecord{}, err
	}
	s.records = next
	if err = s.fail("after_journal"); err != nil {
		return FragmentRecord{}, err
	}
	if err = s.verifyLocked(input); err != nil {
		return FragmentRecord{}, err
	}
	return input, nil
}
func (s *FileFragmentStore) diskUsageLocked() (int64, error) {
	entries, err := os.ReadDir(filepath.Join(s.root, "parts"))
	if err != nil {
		return 0, err
	}
	var total int64
	for _, e := range entries {
		info, err := e.Info()
		if err != nil {
			return 0, err
		}
		if !info.Mode().IsRegular() {
			return 0, ErrFragmentUnsafePath
		}
		if info.Size() < 0 || total > s.maxBytes-info.Size() {
			return 0, ErrFragmentQuota
		}
		total += info.Size()
	}
	return total, nil
}
func (s *FileFragmentStore) writeJournalLocked(records map[string]FragmentRecord) error {
	ids := make([]string, 0, len(records))
	for id := range records {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	j := fragmentJournalV1{Version: 1, Records: make([]FragmentRecord, 0, len(ids))}
	for _, id := range ids {
		j.Records = append(j.Records, records[id])
	}
	raw, err := json.Marshal(j)
	if err != nil {
		return err
	}
	return fragmentAtomicWrite(filepath.Join(s.root, "journal-v1.json"), raw, nil)
}
func (s *FileFragmentStore) verifyLocked(rec FragmentRecord) error {
	if rec.State != FragmentCommitted || !rec.DurableBytesWritten || rec.ExpectedLength <= 0 || !strings.HasPrefix(rec.Hash, "sha256:") {
		return ErrFragmentDurability
	}
	path, err := s.fullPath(rec.LocalArtifactRef)
	if err != nil {
		return err
	}
	info, err := os.Lstat(path)
	if err != nil {
		if os.IsNotExist(err) {
			return ErrFragmentMissing
		}
		return err
	}
	if !info.Mode().IsRegular() || info.Size() != rec.ExpectedLength {
		return ErrFragmentCorruptFile
	}
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	hash := sha256.New()
	n, err := io.Copy(hash, file)
	if err != nil {
		return err
	}
	if n != rec.ExpectedLength || "sha256:"+hex.EncodeToString(hash.Sum(nil)) != rec.Hash {
		return ErrFragmentCorruptFile
	}
	return nil
}
func (s *FileFragmentStore) VerifyCommitted(rec FragmentRecord) error {
	if s == nil {
		return ErrFragmentDurability
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	id, err := FragmentID(rec.Identity)
	if err != nil {
		return err
	}
	stored, ok := s.records[id]
	if !ok || stored.AttemptGeneration != rec.AttemptGeneration || stored.Hash != rec.Hash || stored.LocalArtifactRef != rec.LocalArtifactRef {
		return ErrFragmentMissing
	}
	return s.verifyLocked(stored)
}
func (s *FileFragmentStore) ReadVerified(identity FragmentIdentity) ([]byte, error) {
	if s == nil {
		return nil, ErrFragmentDurability
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	id, err := FragmentID(identity)
	if err != nil {
		return nil, err
	}
	rec, ok := s.records[id]
	if !ok {
		return nil, ErrFragmentMissing
	}
	if err = s.verifyLocked(rec); err != nil {
		return nil, err
	}
	path, _ := s.fullPath(rec.LocalArtifactRef)
	return os.ReadFile(path)
}

// Reconcile is fail-closed: corrupted/missing files lose committed status and
// are never supplied to playback/merge. Orphans are not promoted to commits.
func (s *FileFragmentStore) Reconcile() error {
	if s == nil {
		return ErrFragmentDurability
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	changed := false
	live := map[string]bool{}
	for k, rec := range s.records {
		if rec.State != FragmentCommitted {
			continue
		}
		if err := s.verifyLocked(rec); err != nil {
			rec.State = FragmentCorrupt
			rec.DurableBytesWritten = false
			rec.RetryState = "durability_reconciliation_failed"
			s.records[k] = rec
			changed = true
		} else {
			live[rec.LocalArtifactRef] = true
		}
	}
	if changed {
		if err := s.writeJournalLocked(s.records); err != nil {
			return err
		}
	}
	entries, err := os.ReadDir(filepath.Join(s.root, "parts"))
	if err != nil {
		return err
	}
	for _, e := range entries {
		rel := "parts/" + e.Name()
		if !e.Type().IsRegular() {
			return ErrFragmentUnsafePath
		}
		if !live[rel] {
			if err := os.Remove(filepath.Join(s.root, rel)); err != nil {
				return err
			}
		}
	}
	return fragmentSyncDir(filepath.Join(s.root, "parts"))
}
func (s *FileFragmentStore) CommittedRecords() []FragmentRecord {
	if s == nil {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	ids := make([]string, 0, len(s.records))
	for id := range s.records {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	out := make([]FragmentRecord, 0, len(ids))
	for _, id := range ids {
		rec := s.records[id]
		if rec.State == FragmentCommitted && s.verifyLocked(rec) == nil {
			out = append(out, rec)
		}
	}
	return out
}

// StorageCapacity is int64 end-to-end; a 4GiB+ fragment cannot wrap an int32.
func StorageCapacity(used, incoming, quota int64) error {
	if used < 0 || incoming <= 0 || quota <= 0 || used > quota || incoming > quota-used {
		return ErrFragmentQuota
	}
	return nil
}

// Package canary implements MP12 P03's durable, legacy-first Go shadow canary.
// This package never owns downloads, starts a transfer, or authorizes a cutover.
// Callers may attach the shadow decision to a separately read-only verifier.
package canary

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sync"
)

var (
	ErrRefused = errors.New("MP12_P03_CANARY_REFUSED")
	shaRx      = regexp.MustCompile(`^[0-9a-f]{40}$`)
	ownerRx    = regexp.MustCompile(`^[A-Za-z0-9_-]{1,80}$`)
	reasonRx   = regexp.MustCompile(`^[a-z][a-z0-9_]{0,63}$`)
)

type Phase string

const (
	PhasePrepared        Phase = "prepared"
	PhaseShadow          Phase = "shadow"
	PhaseRollbackPending Phase = "rollback_pending"
	PhaseRolledBack      Phase = "rolled_back"
)

// Decision is deliberately non-authoritative for mutating transfers:
// Primary is always legacy, regardless of state or caller opt-in.
type Decision struct {
	Primary                     string `json:"primary"`
	ShadowGoReadOnly            bool   `json:"shadow_go_read_only"`
	Phase                       Phase  `json:"phase"`
	Revision                    uint64 `json:"revision"`
	ProductionCutoverAuthorized bool   `json:"production_cutover_authorized"`
}

type record struct {
	Schema           int    `json:"schema"`
	Revision         uint64 `json:"revision"`
	SourceSHA        string `json:"source_sha"`
	Owner            string `json:"owner"`
	Phase            Phase  `json:"phase"`
	Primary          string `json:"primary"`
	ShadowGoReadOnly bool   `json:"shadow_go_read_only"`
	Reason           string `json:"reason"`
	Seal             string `json:"seal"`
}

type Controller struct {
	mu    sync.Mutex
	dir   string
	sha   string
	state record
	// Fault hook is package-private and used only to model a lost write in tests.
	beforeWrite func(Phase) error
}

func refusal(code string) error { return fmt.Errorf("%w_%s", ErrRefused, code) }
func validPhase(p Phase) bool {
	return p == PhasePrepared || p == PhaseShadow || p == PhaseRollbackPending || p == PhaseRolledBack
}
func (c *Controller) stateFile() string { return filepath.Join(c.dir, "canary-state.json") }
func (c *Controller) lockFile() string  { return filepath.Join(c.dir, "canary-state.lock") }
func (c *Controller) tempFile() string  { return filepath.Join(c.dir, "canary-state.tmp") }

func validateDir(dir string) error {
	fi, err := os.Lstat(dir)
	if err != nil || !fi.IsDir() || fi.Mode()&os.ModeSymlink != 0 {
		return refusal("PRIVATE_DIR_MISSING")
	}
	if fi.Mode().Perm()&0077 != 0 {
		return refusal("PRIVATE_DIR_PERMISSIONS")
	}
	return nil
}
func existsOrLink(path string) bool { _, err := os.Lstat(path); return err == nil }
func (c *Controller) noInterruptedWrite() error {
	for _, p := range []string{c.lockFile(), c.tempFile()} {
		if existsOrLink(p) {
			return refusal("INTERRUPTED_TRANSACTION_MANUAL_REVIEW")
		}
		if _, err := os.Lstat(p); err != nil && !errors.Is(err, os.ErrNotExist) {
			return refusal("LOCK_STAT_FAILED")
		}
	}
	return nil
}
func seal(r record) string {
	r.Seal = ""
	b, _ := json.Marshal(r)
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}
func encode(r record) []byte { r.Seal = seal(r); b, _ := json.Marshal(r); return append(b, '\n') }
func validate(r record, expected string) error {
	if r.Schema != 1 || r.Revision == 0 || r.SourceSHA != expected || !shaRx.MatchString(r.SourceSHA) ||
		!ownerRx.MatchString(r.Owner) || !validPhase(r.Phase) || r.Primary != "legacy" ||
		r.ShadowGoReadOnly != (r.Phase == PhaseShadow) || !reasonRx.MatchString(r.Reason) ||
		len(r.Seal) != 64 || r.Seal != seal(r) {
		return refusal("JOURNAL_INTEGRITY_OR_SOURCE")
	}
	return nil
}
func (c *Controller) load() (record, error) {
	p := c.stateFile()
	fi, err := os.Lstat(p)
	if errors.Is(err, os.ErrNotExist) {
		return record{}, nil
	}
	if err != nil || !fi.Mode().IsRegular() || fi.Mode().Perm()&0077 != 0 || fi.Size() < 32 || fi.Size() > 4096 {
		return record{}, refusal("JOURNAL_FILE_UNSAFE")
	}
	b, err := os.ReadFile(p)
	if err != nil {
		return record{}, refusal("JOURNAL_READ_FAILED")
	}
	var r record
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	if dec.Decode(&r) != nil || dec.Decode(new(any)) != io.EOF {
		return record{}, refusal("JOURNAL_JSON_INVALID")
	}
	if err := validate(r, c.sha); err != nil {
		return record{}, err
	}
	if !bytes.Equal(b, encode(r)) {
		return record{}, refusal("JOURNAL_NONCANONICAL_OR_DUPLICATE")
	}
	return r, nil
}
func (c *Controller) guardAndCommit(next record, prior uint64) error {
	if err := validateDir(c.dir); err != nil {
		return err
	}
	if err := c.noInterruptedWrite(); err != nil {
		return err
	}
	// O_EXCL blocks competing writers and fails closed on symlink lock files.
	lock, err := os.OpenFile(c.lockFile(), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return refusal("SINGLE_OWNER_BUSY")
	}
	_ = lock.Close()
	defer os.Remove(c.lockFile())
	current, err := c.load()
	if err != nil {
		return err
	}
	if current.Revision != prior {
		return refusal("STALE_REVISION")
	}
	if next.Revision != prior+1 || next.SourceSHA != c.sha || next.Primary != "legacy" {
		return refusal("NONMONOTONIC_OR_CUTOVER")
	}
	if c.beforeWrite != nil {
		if err := c.beforeWrite(next.Phase); err != nil {
			return err
		}
	}
	b := encode(next)
	if len(b) > 4096 {
		return refusal("JOURNAL_TOO_LARGE")
	}
	out, err := os.OpenFile(c.tempFile(), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return refusal("TEMP_FILE_ALREADY_PRESENT")
	}
	// A mid-write crash leaves .tmp on disk, causing startup refusal rather than
	// trust in a potentially ambiguous or partially published transition.
	if _, err = out.Write(b); err == nil {
		err = out.Sync()
	}
	closeErr := out.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		_ = os.Remove(c.tempFile())
		return refusal("DURABLE_WRITE_FAILED")
	}
	if err = os.Rename(c.tempFile(), c.stateFile()); err != nil {
		_ = os.Remove(c.tempFile())
		return refusal("ATOMIC_RENAME_FAILED")
	}
	dir, err := os.Open(c.dir)
	if err != nil {
		return refusal("DIRECTORY_SYNC_OPEN_FAILED")
	}
	syncErr := dir.Sync()
	_ = dir.Close()
	if syncErr != nil {
		return refusal("DIRECTORY_SYNC_FAILED")
	}
	c.state = next
	return nil
}
func (c *Controller) transition(owner string, phase Phase, reason string) error {
	if !ownerRx.MatchString(owner) || !reasonRx.MatchString(reason) {
		return refusal("INVALID_OWNER_OR_REASON")
	}
	if c.state.Revision != 0 && c.state.Owner != owner {
		return refusal("OWNER_MISMATCH")
	}
	next := record{Schema: 1, Revision: c.state.Revision + 1, SourceSHA: c.sha,
		Owner: owner, Phase: phase, Primary: "legacy", ShadowGoReadOnly: phase == PhaseShadow, Reason: reason}
	return c.guardAndCommit(next, c.state.Revision)
}

// Open returns only after an incomplete active/rollback phase has been made
// durably legacy-only. Stale locks, partial temp files and forged records
// produce an error; callers MUST retain legacy and refuse shadow in that case.
func Open(dir, expectedSHA string) (*Controller, error) {
	if !shaRx.MatchString(expectedSHA) {
		return nil, refusal("SOURCE_SHA_INVALID")
	}
	c := &Controller{dir: dir, sha: expectedSHA}
	if err := validateDir(dir); err != nil {
		return nil, err
	}
	if err := c.noInterruptedWrite(); err != nil {
		return nil, err
	}
	state, err := c.load()
	if err != nil {
		return nil, err
	}
	c.state = state
	if state.Revision > 0 && state.Phase != PhaseRolledBack {
		if err := c.rollbackLocked(state.Owner, "recovery_restart"); err != nil {
			return nil, err
		}
	}
	return c, nil
}
func (c *Controller) Decision() Decision {
	c.mu.Lock()
	defer c.mu.Unlock()
	// A second host can durably roll back while this instance remains alive.
	// A stale or unreadable decision always stays legacy with shadow disabled.
	fallback := Decision{Primary: "legacy", ProductionCutoverAuthorized: false}
	if err := validateDir(c.dir); err != nil {
		return fallback
	}
	if err := c.noInterruptedWrite(); err != nil {
		return fallback
	}
	onDisk, err := c.load()
	if err != nil || onDisk.Revision != c.state.Revision ||
		onDisk.Phase != c.state.Phase || onDisk.Owner != c.state.Owner ||
		onDisk.SourceSHA != c.state.SourceSHA {
		return fallback
	}
	return Decision{Primary: "legacy", ShadowGoReadOnly: onDisk.Phase == PhaseShadow,
		Phase: onDisk.Phase, Revision: onDisk.Revision, ProductionCutoverAuthorized: false}
}

// Prepare only enables an explicit shadow *candidate*, never the primary.
// optIn is required on each fresh session and must originate from a trusted host.
func (c *Controller) Prepare(owner string, optIn bool) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !optIn {
		return refusal("EXPLICIT_OPT_IN_REQUIRED")
	}
	if c.state.Revision != 0 && c.state.Phase != PhaseRolledBack {
		return refusal("SESSION_ALREADY_ACTIVE")
	}
	// On a completed rollback, a fresh owner is allowed only with a fresh opt-in.
	if c.state.Revision > 0 && c.state.Owner != owner {
		return refusal("NEW_OWNER_REQUIRES_NEW_JOURNAL")
	}
	return c.transition(owner, PhasePrepared, "explicit_shadow_opt_in")
}
func (c *Controller) StartReadOnlyShadow(owner string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.state.Phase != PhasePrepared {
		return refusal("SHADOW_NOT_PREPARED")
	}
	return c.transition(owner, PhaseShadow, "shadow_read_only")
}

// Rollback is safe even when called repeatedly, and durably records a pending
// phase before the final receipt. An interrupted rollback always selects legacy.
func (c *Controller) rollbackLocked(owner, reason string) error {
	if c.state.Revision == 0 || c.state.Phase == PhaseRolledBack {
		return nil
	}
	if c.state.Owner != owner {
		return refusal("OWNER_MISMATCH")
	}
	if c.state.Phase != PhaseRollbackPending {
		if err := c.transition(owner, PhaseRollbackPending, reason); err != nil {
			return err
		}
	}
	return c.transition(owner, PhaseRolledBack, reason)
}
func (c *Controller) Rollback(owner, reason string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !reasonRx.MatchString(reason) {
		return refusal("REASON_INVALID")
	}
	return c.rollbackLocked(owner, reason)
}

// No automatic production promotion method exists by design.
// A future production authority must verify independent physical/signed gates.
func (c *Controller) UnsafePromotion() error { return refusal("PRODUCTION_CUTOVER_NOT_AUTHORIZED") }

package canary

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

const testSHA = "0123456789abcdef0123456789abcdef01234567"

func newTest(t *testing.T) (*Controller, string) {
	t.Helper()
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	c, err := Open(dir, testSHA)
	if err != nil {
		t.Fatal(err)
	}
	return c, dir
}
func requireLegacy(t *testing.T, c *Controller) {
	t.Helper()
	d := c.Decision()
	if d.Primary != "legacy" || d.ProductionCutoverAuthorized {
		t.Fatalf("unsafe %+v", d)
	}
}
func TestDefaultLegacyNoImplicitOptIn(t *testing.T) {
	c, _ := newTest(t)
	requireLegacy(t, c)
	if c.Decision().ShadowGoReadOnly {
		t.Fatal("shadow enabled by default")
	}
	if err := c.Prepare("owner1", false); err == nil {
		t.Fatal("opt in missing")
	}
}
func TestPrepareShadowAndRollbackDurable(t *testing.T) {
	c, dir := newTest(t)
	if err := c.Prepare("owner1", true); err != nil {
		t.Fatal(err)
	}
	requireLegacy(t, c)
	if c.Decision().ShadowGoReadOnly {
		t.Fatal("not yet shadow")
	}
	if err := c.StartReadOnlyShadow("owner1"); err != nil {
		t.Fatal(err)
	}
	if !c.Decision().ShadowGoReadOnly {
		t.Fatal("shadow missing")
	}
	requireLegacy(t, c)
	if err := c.Rollback("owner1", "injected_timeout"); err != nil {
		t.Fatal(err)
	}
	requireLegacy(t, c)
	if c.Decision().Phase != PhaseRolledBack || c.Decision().ShadowGoReadOnly || c.Decision().Revision != 4 {
		t.Fatalf("bad rollback %+v", c.Decision())
	}
	again, err := Open(dir, testSHA)
	if err != nil {
		t.Fatal(err)
	}
	requireLegacy(t, again)
	if again.Decision().Phase != PhaseRolledBack {
		t.Fatal("rollback not persisted")
	}
}
func TestCrashAfterShadowAutoRollback(t *testing.T) {
	c, dir := newTest(t)
	if err := c.Prepare("owner1", true); err != nil {
		t.Fatal(err)
	}
	if err := c.StartReadOnlyShadow("owner1"); err != nil {
		t.Fatal(err)
	}
	restarted, err := Open(dir, testSHA)
	if err != nil {
		t.Fatal(err)
	}
	requireLegacy(t, restarted)
	if restarted.Decision().Phase != PhaseRolledBack || restarted.Decision().Revision != 4 {
		t.Fatalf("crash recovery %+v", restarted.Decision())
	}
}
func TestCrashAfterPrepareAutoRollback(t *testing.T) {
	c, dir := newTest(t)
	if err := c.Prepare("owner1", true); err != nil {
		t.Fatal(err)
	}
	again, err := Open(dir, testSHA)
	if err != nil {
		t.Fatal(err)
	}
	if again.Decision().Phase != PhaseRolledBack || again.Decision().Revision != 3 {
		t.Fatalf("state=%+v", again.Decision())
	}
}
func TestRollbackFaultAfterPendingRecovers(t *testing.T) {
	c, dir := newTest(t)
	_ = c.Prepare("owner1", true)
	_ = c.StartReadOnlyShadow("owner1")
	c.beforeWrite = func(p Phase) error {
		if p == PhaseRolledBack {
			return errors.New("fault before durable second phase")
		}
		return nil
	}
	if err := c.Rollback("owner1", "service_crash"); err == nil {
		t.Fatal("fault unobserved")
	}
	if c.Decision().Phase != PhaseRollbackPending {
		t.Fatal("pending not durable")
	}
	again, err := Open(dir, testSHA)
	if err != nil {
		t.Fatal(err)
	}
	if again.Decision().Phase != PhaseRolledBack || again.Decision().Revision != 4 {
		t.Fatalf("pending recovery %+v", again.Decision())
	}
}
func TestFailedWriteLeavesPreviousRevision(t *testing.T) {
	c, dir := newTest(t)
	_ = c.Prepare("owner1", true)
	c.beforeWrite = func(Phase) error { return errors.New("fault") }
	if err := c.StartReadOnlyShadow("owner1"); err == nil {
		t.Fatal("accepted failed durable write")
	}
	r, err := c.load()
	if err != nil || r.Revision != 1 || r.Phase != PhasePrepared {
		t.Fatalf("unexpected state %+v %v", r, err)
	}
	again, err := Open(dir, testSHA)
	if err != nil {
		t.Fatal(err)
	}
	requireLegacy(t, again)
}
func TestConcurrentWriterCASRefusal(t *testing.T) {
	c, dir := newTest(t)
	other, err := Open(dir, testSHA)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.Prepare("owner1", true); err != nil {
		t.Fatal(err)
	}
	if err := other.Prepare("owner1", true); err == nil || !strings.Contains(err.Error(), "STALE_REVISION") {
		t.Fatalf("stale writer accepted %v", err)
	}
}
func TestConcurrentPrepareOnlyOneSucceeds(t *testing.T) {
	c, dir := newTest(t)
	other, err := Open(dir, testSHA)
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	var errs [2]error
	wg.Add(2)
	go func() { defer wg.Done(); errs[0] = c.Prepare("owner1", true) }()
	go func() { defer wg.Done(); errs[1] = other.Prepare("owner1", true) }()
	wg.Wait()
	count := 0
	for _, e := range errs {
		if e == nil {
			count++
		}
	}
	if count != 1 {
		t.Fatalf("writers: %v", errs)
	}
}
func TestWrongOwnerAndNoProductionPromotion(t *testing.T) {
	c, _ := newTest(t)
	_ = c.Prepare("owner1", true)
	if c.StartReadOnlyShadow("intruder") == nil {
		t.Fatal("owner hijack")
	}
	if c.Rollback("intruder", "service_crash") == nil {
		t.Fatal("owner rollback")
	}
	if c.UnsafePromotion() == nil {
		t.Fatal("production promotion")
	}
	requireLegacy(t, c)
}
func TestMalformedNamesReasonsSHARefused(t *testing.T) {
	c, _ := newTest(t)
	for _, owner := range []string{"../escape", "", strings.Repeat("x", 90)} {
		if c.Prepare(owner, true) == nil {
			t.Fatal("accepted bad owner")
		}
	}
	if _, err := Open(t.TempDir(), "short"); err == nil {
		t.Fatal("invalid SHA")
	}
	if err := c.Prepare("owner1", true); err != nil {
		t.Fatal(err)
	}
	for _, reason := range []string{"", "../../escape", strings.Repeat("x", 90)} {
		if c.Rollback("owner1", reason) == nil {
			t.Fatal("accepted bad reason")
		}
	}
}
func TestSourceMismatchRefusesResume(t *testing.T) {
	c, dir := newTest(t)
	_ = c.Prepare("owner1", true)
	_, err := Open(dir, strings.Repeat("a", 40))
	if err == nil {
		t.Fatal("stale source accepted")
	}
}
func TestCorruptSealAndDuplicateJSONRefused(t *testing.T) {
	c, dir := newTest(t)
	_ = c.Prepare("owner1", true)
	p := filepath.Join(dir, "canary-state.json")
	good, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	bad := bytes.Replace(good, []byte(`"prepared"`), []byte(`"shadow"`), 1)
	if err := os.WriteFile(p, bad, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(dir, testSHA); err == nil {
		t.Fatal("tampered journal accepted")
	}
	bad = bytes.Replace(good, []byte(`"schema":1`), []byte(`"schema":1,"schema":1`), 1)
	if err := os.WriteFile(p, bad, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(dir, testSHA); err == nil {
		t.Fatal("duplicate JSON accepted")
	}
}
func TestLeftoverTmpAndLockRefuse(t *testing.T) {
	_, dir := newTest(t)
	for _, name := range []string{"canary-state.tmp", "canary-state.lock"} {
		p := filepath.Join(dir, name)
		if err := os.WriteFile(p, []byte("partial"), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := Open(dir, testSHA); err == nil {
			t.Fatal("stale lock/temp accepted: " + name)
		}
		_ = os.Remove(p)
	}
}
func TestSymlinkAndPermissionsRefused(t *testing.T) {
	c, dir := newTest(t)
	_ = c.Prepare("owner1", true)
	p := filepath.Join(dir, "canary-state.json")
	_ = os.Remove(p)
	if err := os.Symlink("/dev/null", p); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(dir, testSHA); err == nil {
		t.Fatal("symlink journal")
	}
	_ = os.Remove(p)
	if err := os.WriteFile(p, []byte(`{}`), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(dir, testSHA); err == nil {
		t.Fatal("public journal")
	}
	_ = os.Remove(p)
	if err := os.Chmod(dir, 0755); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(dir, testSHA); err == nil {
		t.Fatal("public directory")
	}
}
func TestRepeatRollbackIdempotent(t *testing.T) {
	c, _ := newTest(t)
	_ = c.Prepare("owner1", true)
	_ = c.Rollback("owner1", "abort_requested")
	rev := c.Decision().Revision
	if err := c.Rollback("owner1", "abort_requested"); err != nil {
		t.Fatal(err)
	}
	if c.Decision().Revision != rev {
		t.Fatal("repeat changed history")
	}
}
func TestNoSensitiveOrNativeDataInReceipt(t *testing.T) {
	c, dir := newTest(t)
	_ = c.Prepare("owner1", true)
	raw, err := os.ReadFile(filepath.Join(dir, "canary-state.json"))
	if err != nil {
		t.Fatal(err)
	}
	for _, v := range []string{"http", "token", "password", "download_id", "artifact_path", "credential", "go_cutover"} {
		if bytes.Contains(raw, []byte(v)) {
			t.Fatalf("private field in journal: %s", v)
		}
	}
}

func TestStaleControllerCannotReEnableShadowAfterExternalRollback(t *testing.T) {
	c, dir := newTest(t)
	if err := c.Prepare("owner1", true); err != nil {
		t.Fatal(err)
	}
	if err := c.StartReadOnlyShadow("owner1"); err != nil {
		t.Fatal(err)
	}
	if !c.Decision().ShadowGoReadOnly {
		t.Fatal("expected live read-only shadow")
	}
	another, err := Open(dir, testSHA)
	if err != nil {
		t.Fatal(err)
	}
	if another.Decision().Phase != PhaseRolledBack {
		t.Fatal("restart not safely rolled back")
	}
	stale := c.Decision()
	if stale.ShadowGoReadOnly || stale.Primary != "legacy" || stale.ProductionCutoverAuthorized {
		t.Fatalf("stale controller could re-enable shadow: %+v", stale)
	}
}

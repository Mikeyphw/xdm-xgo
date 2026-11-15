package desktopparity

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const fixtureSession = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

func frame(data []byte) []byte {
	out := make([]byte, 4+len(data))
	binary.LittleEndian.PutUint32(out[:4], uint32(len(data)))
	copy(out[4:], data)
	return out
}
func fixture(t *testing.T, name string) []byte {
	t.Helper()
	p := filepath.Join("testdata", name)
	b, e := os.ReadFile(p)
	if e != nil {
		t.Fatal(e)
	}
	return b
}
func checked(t *testing.T, name string) Evidence {
	t.Helper()
	got, err := InspectFrame(frame(fixture(t, name)), fixtureSession)
	if err != nil {
		t.Fatal(err)
	}
	return got
}
func denied(t *testing.T, raw []byte, session string) {
	t.Helper()
	_, err := InspectFrame(raw, session)
	if !errors.Is(err, ErrRefused) {
		t.Fatalf("expected refusal, got %v", err)
	}
}
func TestRecordedNativeCaptureScrubsCredentialsAndDoesNotExecute(t *testing.T) {
	got := checked(t, "native-capture.json")
	b, e := json.Marshal(got)
	if e != nil {
		t.Fatal(e)
	}
	if got.CaptureCount != 1 || got.ExecutionAuthorized || got.ProductionCutover || !got.RequiresHostResolution || !got.ReadOnlySnapshotOnly {
		t.Fatalf("unsafe evidence: %s", b)
	}
	for _, needle := range []string{"session=secret", "token=secret", "archive.zip", "https://", "0123456789abcdef"} {
		if bytes.Contains(b, []byte(needle)) {
			t.Fatalf("sensitive data leaked %q", needle)
		}
	}
}
func TestRecordedBatchPreservesCountWithoutWriting(t *testing.T) {
	got := checked(t, "native-batch.json")
	if got.CaptureCount != 2 || got.ExecutionAuthorized {
		t.Fatal(got)
	}
}
func TestRecordedPostIsInspectionOnly(t *testing.T) {
	got := checked(t, "native-post-capture.json")
	if got.CaptureCount != 1 || !got.ReadOnlySnapshotOnly || got.ExecutionAuthorized {
		t.Fatal(got)
	}
}
func TestRecordedHelloNeverBecomesSnapshot(t *testing.T) {
	denied(t, frame(fixture(t, "native-hello.json")), fixtureSession)
}
func TestUnknownNativeExecuteRefused(t *testing.T) {
	denied(t, frame(fixture(t, "native-unknown-command.json")), fixtureSession)
}
func TestInvalidFrameLengths(t *testing.T) {
	b := frame(fixture(t, "native-capture.json"))
	for _, raw := range [][]byte{nil, b[:3], b[:len(b)-1], append(bytes.Clone(b), 0)} {
		denied(t, raw, fixtureSession)
	}
	binary.LittleEndian.PutUint32(b[:4], MaxMessageBytes+1)
	denied(t, b, fixtureSession)
}
func TestSessionMismatchAndCallerForgery(t *testing.T) {
	b := frame(fixture(t, "native-capture.json"))
	denied(t, b, strings.Repeat("0", 64))
	denied(t, b, "")
}
func TestUnknownProtocolAndTopLevelFieldRefused(t *testing.T) {
	for _, s := range []string{`{"protocolVersion":"1.0","requestId":"a","type":"capture","sessionId":"` + fixtureSession + `","capture":{"url":"https://example.test"}}`, `{"protocolVersion":"2.0","requestId":"a","type":"capture","sessionId":"` + fixtureSession + `","capture":{"url":"https://example.test"},"execute":"now"}`} {
		denied(t, frame([]byte(s)), fixtureSession)
	}
}
func TestDuplicateKeysRejected(t *testing.T) {
	for _, s := range []string{`{"protocolVersion":"2.0","protocolVersion":"2.0","requestId":"x","type":"capture","sessionId":"` + fixtureSession + `","capture":{"url":"https://example.test"}}`, `{"protocolVersion":"2.0","requestId":"x","type":"capture","sessionId":"` + fixtureSession + `","capture":{"url":"https://example.test","url":"https://evil.test"}}`} {
		denied(t, frame([]byte(s)), fixtureSession)
	}
}
func TestRefusesUnknownNestedAndUnsafeURL(t *testing.T) {
	for _, url := range []string{"file:///etc/passwd", "https://alice:password@example.test/", "javascript:alert(1)", "https://"} {
		s := `{"protocolVersion":"2.0","requestId":"x","type":"capture","sessionId":"` + fixtureSession + `","capture":{"url":"` + url + `"}}`
		denied(t, frame([]byte(s)), fixtureSession)
	}
	s := `{"protocolVersion":"2.0","requestId":"x","type":"capture","sessionId":"` + fixtureSession + `","capture":{"url":"https://example.test","run":"yes"}}`
	denied(t, frame([]byte(s)), fixtureSession)
}
func TestIncognitoRefused(t *testing.T) {
	s := `{"protocolVersion":"2.0","requestId":"x","type":"capture","sessionId":"` + fixtureSession + `","capture":{"url":"https://example.test","isIncognito":true}}`
	denied(t, frame([]byte(s)), fixtureSession)
}
func TestDuplicateBatchIDsRefused(t *testing.T) {
	s := `{"protocolVersion":"2.0","requestId":"x","type":"capture-batch","sessionId":"` + fixtureSession + `","captures":[{"url":"https://example.test/1","requestId":"dup"},{"url":"https://example.test/2","requestId":"dup"}]}`
	denied(t, frame([]byte(s)), fixtureSession)
}
func TestNoSnapshotWithoutHostOptIn(t *testing.T) {
	e := checked(t, "native-capture.json")
	if _, err := SnapshotCommand(e, false); !errors.Is(err, ErrRefused) {
		t.Fatal(err)
	}
	if _, err := SnapshotCommand(Evidence{BrowserRequestID: e.BrowserRequestID, NativeProtocol: e.NativeProtocol, GoProtocolMajor: 1, CaptureFingerprint: e.CaptureFingerprint, CaptureCount: 1, RequiresHostResolution: true, ReadOnlySnapshotOnly: true}, true); !errors.Is(err, ErrRefused) {
		t.Fatal(err)
	}
}
func TestReadOnlyCommandUsesGoV1Only(t *testing.T) {
	e := checked(t, "native-capture.json")
	raw, err := SnapshotCommand(e, true)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err = json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	if m["kind"] != "desktop.ui.snapshot" {
		t.Fatal(string(raw))
	}
	p := m["protocol"].(map[string]any)
	if p["major"] != float64(1) || p["minor"] != float64(0) {
		t.Fatal(string(raw))
	}
	if strings.Contains(string(raw), "session=secret") || strings.Contains(string(raw), "https://") || strings.Contains(string(raw), "archive.zip") {
		t.Fatal("secret in command")
	}
}
func TestSourcePayloadHashChangesButNoSecretOutput(t *testing.T) {
	b := fixture(t, "native-capture.json")
	x := strings.Replace(string(b), "token=secret", "token=changed", 1)
	e1, _ := InspectFrame(frame(b), fixtureSession)
	e2, err := InspectFrame(frame([]byte(x)), fixtureSession)
	if err != nil {
		t.Fatal(err)
	}
	if e1.CaptureFingerprint == e2.CaptureFingerprint {
		t.Fatal("source fingerprint did not change")
	}
}

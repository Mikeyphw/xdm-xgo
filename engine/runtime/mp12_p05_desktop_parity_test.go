package runtime

// MP12 P05 proves an explicitly permitted read-only Firefox diagnostic can
// traverse the actual versioned Go v1 decoder and desktop runtime. It does
// not route browser captures to a download, publish media, or enable cutover.
import (
	"context"
	"encoding/binary"
	"os"
	"path/filepath"
	"testing"
	"time"

	v1 "github.com/subhra74/xdm/engine/api/v1"
	"github.com/subhra74/xdm/engine/runtime/desktopparity"
)

func TestMP12P05ReadOnlyBrowserDesktopSnapshotThroughGoRuntime(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("desktopparity", "testdata", "native-capture.json"))
	if err != nil {
		t.Fatal(err)
	}
	frame := make([]byte, 4+len(raw))
	binary.LittleEndian.PutUint32(frame[:4], uint32(len(raw)))
	copy(frame[4:], raw)
	evidence, err := desktopparity.InspectFrame(frame, "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
	if err != nil {
		t.Fatal(err)
	}
	commandBytes, err := desktopparity.SnapshotCommand(evidence, true)
	if err != nil {
		t.Fatal(err)
	}
	cmd, err := v1.DecodeCommand(commandBytes)
	if err != nil {
		t.Fatalf("Go v1 wire decoder refused shadow command: %v", err)
	}
	if cmd.Kind != DesktopUISnapshotKind {
		t.Fatalf("shadow command must be read-only: %s", cmd.Kind)
	}
	engine := New(Config{HostPlatform: "desktop", EventBuffer: 16})
	if err := engine.Start(); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	defer engine.Shutdown(context.Background())
	if err := engine.Submit(ctx, cmd); err != nil {
		t.Fatal(err)
	}
	first, err := engine.NextFrame(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if first.Kind != "desktop.ui.projection" {
		t.Fatalf("unexpected first event: %s", first.Kind)
	}
	second, err := engine.NextFrame(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if second.Kind != "command.completed" {
		t.Fatalf("unexpected completion event: %s", second.Kind)
	}
	if evidence.ExecutionAuthorized || evidence.ProductionCutover {
		t.Fatal("snapshot granted execution or cutover")
	}
}

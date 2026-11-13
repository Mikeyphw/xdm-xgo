package runtime

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"github.com/subhra74/xdm/engine/domain/identity"
	"github.com/subhra74/xdm/engine/runtime/canary"
	"github.com/subhra74/xdm/engine/runtime/command"
)

func mp12TestHandlerCommand(t *testing.T, index int, body string) command.Envelope {
	t.Helper()
	token := "0000000000000000000000000000000" + string("0123456789abcdef"[index%16])
	id, err := command.ParseID("cmd_" + token)
	if err != nil {
		t.Fatal(err)
	}
	op, err := identity.ParseOperationID("op_" + token)
	if err != nil {
		t.Fatal(err)
	}
	return command.Envelope{ID: id, OperationID: op, Kind: MP12CanaryCommandKind, Payload: json.RawMessage(body)}
}
func TestMP12CanaryRealEngineCommandProtocol(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	c, err := canary.Open(dir, "0123456789abcdef0123456789abcdef01234567")
	if err != nil {
		t.Fatal(err)
	}
	e := New(Config{Handlers: MP12CanaryHandlers(c, true), EventBuffer: 16})
	if err = e.Start(); err != nil {
		t.Fatal(err)
	}
	defer e.Shutdown(context.Background())
	cases := []struct {
		cmd    string
		shadow bool
	}{
		{`{"action":"inspect"}`, false},
		{`{"action":"prepare","owner":"owner1"}`, false},
		{`{"action":"start_read_only_shadow","owner":"owner1"}`, true},
		{`{"action":"rollback","owner":"owner1","reason":"negative_probe"}`, false},
	}
	for i, tc := range cases {
		if err = e.Submit(context.Background(), mp12TestHandlerCommand(t, i+1, tc.cmd)); err != nil {
			t.Fatal(err)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		frame, err := e.NextFrame(ctx)
		cancel()
		if err != nil {
			t.Fatal(err)
		}
		if frame.Kind != "runtime.canary.decision" {
			t.Fatalf("kind %q", frame.Kind)
		}
		var decision canary.Decision
		if err := json.Unmarshal(frame.Payload, &decision); err != nil {
			t.Fatal(err)
		}
		if decision.Primary != "legacy" || decision.ProductionCutoverAuthorized || decision.ShadowGoReadOnly != tc.shadow {
			t.Fatalf("unsafe decision %+v", decision)
		}
		ctx, cancel = context.WithTimeout(context.Background(), 3*time.Second)
		done, err := e.NextFrame(ctx)
		cancel()
		if err != nil {
			t.Fatal(err)
		}
		if done.Kind != "command.completed" {
			t.Fatalf("completion %q", done.Kind)
		}
	}
}
func TestMP12CanaryHostOptInNotGrantedFromPayload(t *testing.T) {
	dir := t.TempDir()
	_ = os.Chmod(dir, 0700)
	c, err := canary.Open(dir, "0123456789abcdef0123456789abcdef01234567")
	if err != nil {
		t.Fatal(err)
	}
	handlers := MP12CanaryHandlers(c, false)
	e := New(Config{Handlers: handlers, EventBuffer: 8})
	if err := e.Start(); err != nil {
		t.Fatal(err)
	}
	defer e.Shutdown(context.Background())
	for i, body := range []string{`{"action":"prepare","owner":"owner1","trusted_host_opt_in":true}`, `{"action":"prepare","owner":"owner1"}`} {
		if err := e.Submit(context.Background(), mp12TestHandlerCommand(t, 5+i, body)); err != nil {
			t.Fatal(err)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		f, err := e.NextFrame(ctx)
		cancel()
		if err != nil {
			t.Fatal(err)
		}
		if f.Kind != "command.failed" {
			t.Fatalf("unexpected %q", f.Kind)
		}
	}
	d := c.Decision()
	if d.ShadowGoReadOnly || d.Primary != "legacy" {
		t.Fatal("unsafe implicit optin")
	}
}

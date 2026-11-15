package runtime

// MP12 P03 optional host wiring for an explicitly read-only Go canary.
// No Android or desktop host installs this handler by default: producers must
// explicitly provide Config.Handlers and a trusted opt-in. It has no method
// for mutating transfers, switching primary engines, or promoting production.
import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"

	"github.com/subhra74/xdm/engine/runtime/canary"
	"github.com/subhra74/xdm/engine/runtime/command"
	"github.com/subhra74/xdm/engine/runtime/event"
)

const MP12CanaryCommandKind = "runtime.canary.inspect_or_shadow"

var ErrMP12CanaryHostRefused = errors.New("MP12_P03_CANARY_HOST_REFUSED")

type mp12CanaryRequest struct {
	Action string `json:"action"`
	Owner  string `json:"owner,omitempty"`
	Reason string `json:"reason,omitempty"`
}

// MP12CanaryHandlers creates an opt-in diagnostic handler; a nil controller
// or false opt-in never authorizes even read-only Go shadow diagnostics.
func MP12CanaryHandlers(controller *canary.Controller, trustedHostOptIn bool) map[string]Handler {
	return map[string]Handler{MP12CanaryCommandKind: func(ctx context.Context, inv *Invocation, env command.Envelope) error {
		if controller == nil || len(env.Payload) == 0 || len(env.Payload) > 1024 {
			return ErrMP12CanaryHostRefused
		}
		dec := json.NewDecoder(bytes.NewReader(env.Payload))
		dec.DisallowUnknownFields()
		var req mp12CanaryRequest
		if dec.Decode(&req) != nil || dec.Decode(new(any)) != io.EOF {
			return ErrMP12CanaryHostRefused
		}
		var err error
		switch req.Action {
		case "inspect":
			if req.Owner != "" || req.Reason != "" {
				return ErrMP12CanaryHostRefused
			}
		case "prepare":
			if !trustedHostOptIn || req.Reason != "" {
				return ErrMP12CanaryHostRefused
			}
			err = controller.Prepare(req.Owner, true)
		case "start_read_only_shadow":
			if !trustedHostOptIn || req.Reason != "" {
				return ErrMP12CanaryHostRefused
			}
			err = controller.StartReadOnlyShadow(req.Owner)
		case "rollback":
			if req.Reason == "" {
				return ErrMP12CanaryHostRefused
			}
			err = controller.Rollback(req.Owner, req.Reason)
		default:
			return ErrMP12CanaryHostRefused
		}
		if err != nil {
			return ErrMP12CanaryHostRefused
		}
		// Only a fixed, credential-free decision leaves the runtime.
		payload, err := json.Marshal(controller.Decision())
		if err != nil {
			return ErrMP12CanaryHostRefused
		}
		_, err = inv.Emit(event.Operational, "runtime.canary.decision", payload, "")
		return err
	}}
}

// Package desktopparity implements MP12 P05's fail-closed, read-only
// inspection of Firefox Native Messaging v2 into a Go v1 *snapshot* probe.
// It deliberately cannot turn a browser capture into an executable download.
package desktopparity

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"regexp"
	"strings"
)

const (
	NativeProtocolVersion = "2.0"
	GoProtocolMajor       = 1
	GoProtocolMinor       = 0
	MaxMessageBytes       = 256 * 1024
	MaxBatchItems         = 100
)

var ErrRefused = errors.New("MP12_P05_REFUSED_PROTOCOL_OR_AUTHORITY")
var requestIDPattern = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,128}$`)
var sessionPattern = regexp.MustCompile(`^[A-Za-z0-9]{32,256}$`)

type nativeMessage struct {
	ProtocolVersion string          `json:"protocolVersion"`
	RequestID       string          `json:"requestId"`
	Type            string          `json:"type"`
	SessionID       string          `json:"sessionId"`
	Capture         *nativeCapture  `json:"capture,omitempty"`
	Captures        []nativeCapture `json:"captures,omitempty"`
	Rules           json.RawMessage `json:"rules,omitempty"`
}

type nativeCapture struct {
	URL                    string            `json:"url"`
	RequestID              string            `json:"requestId,omitempty"`
	BrowserRequestID       string            `json:"browserRequestId,omitempty"`
	FileName               string            `json:"fileName,omitempty"`
	Headers                map[string]string `json:"headers,omitempty"`
	Cookie                 string            `json:"cookie,omitempty"`
	Referer                string            `json:"referer,omitempty"`
	UserAgent              string            `json:"userAgent,omitempty"`
	Browser                string            `json:"browser,omitempty"`
	QueueID                string            `json:"queueId,omitempty"`
	CategoryID             string            `json:"categoryId,omitempty"`
	MimeType               string            `json:"mimeType,omitempty"`
	FileSize               *int64            `json:"fileSize,omitempty"`
	Method                 string            `json:"method,omitempty"`
	RequestBodyBase64      string            `json:"requestBodyBase64,omitempty"`
	RequestBodyContentType string            `json:"requestBodyContentType,omitempty"`
	SourcePage             string            `json:"sourcePage,omitempty"`
	Operation              string            `json:"operation,omitempty"`
	IsIncognito            bool              `json:"isIncognito,omitempty"`
	BypassRules            bool              `json:"bypassRules,omitempty"`
}

// Evidence intentionally contains no URLs, cookies, headers, body, destination,
// resource keys, tokens, or platform execution flags. It is not a durable receipt.
type Evidence struct {
	NativeProtocol         string `json:"native_protocol"`
	GoProtocolMajor        int    `json:"go_protocol_major"`
	BrowserRequestID       string `json:"browser_request_id"`
	CaptureCount           int    `json:"capture_count"`
	CaptureFingerprint     string `json:"capture_fingerprint_sha256"`
	RequiresHostResolution bool   `json:"requires_host_resolution"`
	ExecutionAuthorized    bool   `json:"execution_authorized"`
	ProductionCutover      bool   `json:"production_cutover"`
	ReadOnlySnapshotOnly   bool   `json:"read_only_snapshot_only"`
	authenticated          bool
}

// inspectJSONKeys rejects duplicate JSON property names in nested objects,
// rather than silently allowing last-write-wins identity or session forgery.
func inspectJSONKeys(data []byte) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	var walk func() error
	walk = func() error {
		tok, err := dec.Token()
		if err != nil {
			return ErrRefused
		}
		delimiter, isDelim := tok.(json.Delim)
		if !isDelim {
			return nil
		}
		switch delimiter {
		case '{':
			seen := make(map[string]bool)
			for dec.More() {
				key, err := dec.Token()
				if err != nil {
					return ErrRefused
				}
				name, ok := key.(string)
				if !ok || seen[name] {
					return ErrRefused
				}
				seen[name] = true
				if err := walk(); err != nil {
					return err
				}
			}
			end, err := dec.Token()
			if err != nil || end != json.Delim('}') {
				return ErrRefused
			}
		case '[':
			for dec.More() {
				if err := walk(); err != nil {
					return err
				}
			}
			end, err := dec.Token()
			if err != nil || end != json.Delim(']') {
				return ErrRefused
			}
		default:
			return ErrRefused
		}
		return nil
	}
	if err := walk(); err != nil {
		return err
	}
	if _, err := dec.Token(); err != io.EOF {
		return ErrRefused
	}
	return nil
}

// InspectFrame accepts one complete little-endian Native Messaging message.
// expectedSession MUST come from the trusted desktop host; the message itself
// cannot supply its own authority. This method never performs I/O or downloads.
func InspectFrame(frame []byte, expectedSession string) (Evidence, error) {
	var empty Evidence
	if !sessionPattern.MatchString(expectedSession) || len(frame) < 5 {
		return empty, ErrRefused
	}
	size := binary.LittleEndian.Uint32(frame[:4])
	if size == 0 || size > MaxMessageBytes || uint64(size) != uint64(len(frame)-4) {
		return empty, ErrRefused
	}
	payload := frame[4:]
	if err := inspectJSONKeys(payload); err != nil {
		return empty, err
	}
	dec := json.NewDecoder(bytes.NewReader(payload))
	dec.DisallowUnknownFields()
	var message nativeMessage
	if err := dec.Decode(&message); err != nil {
		return empty, ErrRefused
	}
	if _, err := dec.Token(); err != io.EOF {
		return empty, ErrRefused
	}
	if message.ProtocolVersion != NativeProtocolVersion || !requestIDPattern.MatchString(message.RequestID) ||
		!sessionPattern.MatchString(message.SessionID) || message.SessionID != expectedSession {
		return empty, ErrRefused
	}
	var captures []nativeCapture
	switch message.Type {
	case "capture":
		if message.Capture == nil || len(message.Captures) != 0 {
			return empty, ErrRefused
		}
		captures = []nativeCapture{*message.Capture}
	case "capture-batch":
		if message.Capture != nil || len(message.Captures) < 1 || len(message.Captures) > MaxBatchItems {
			return empty, ErrRefused
		}
		captures = message.Captures
	default:
		return empty, ErrRefused // hello, health, execute: not shadow capture proof
	}
	ids := make(map[string]bool)
	for _, capture := range captures {
		u, err := url.Parse(capture.URL)
		if err != nil || u == nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" ||
			u.User != nil || len(capture.URL) > 16*1024 {
			return empty, ErrRefused
		}
		if capture.RequestID != "" && !requestIDPattern.MatchString(capture.RequestID) {
			return empty, ErrRefused
		}
		if capture.RequestID != "" && ids[capture.RequestID] {
			return empty, ErrRefused
		}
		if capture.RequestID != "" {
			ids[capture.RequestID] = true
		}
		method := strings.ToUpper(strings.TrimSpace(capture.Method))
		if method != "" && method != "GET" && method != "POST" {
			return empty, ErrRefused
		}
		if capture.FileSize != nil && *capture.FileSize < 0 {
			return empty, ErrRefused
		}
		if capture.IsIncognito {
			return empty, ErrRefused
		}
		// The native host supports POST; this audit can inspect it but cannot
		// build a write command, even with an apparently valid POST body.
	}
	digest := sha256.Sum256(payload)
	return Evidence{NativeProtocol: NativeProtocolVersion, GoProtocolMajor: GoProtocolMajor,
		BrowserRequestID: message.RequestID, CaptureCount: len(captures),
		CaptureFingerprint: hex.EncodeToString(digest[:]), RequiresHostResolution: true,
		ExecutionAuthorized: false, ProductionCutover: false, ReadOnlySnapshotOnly: true,
		authenticated: true}, nil
}

// SnapshotCommand builds a Go v1 read-only diagnostic command, never a capture
// or execute command. The trusted host must explicitly permit the shadow probe.
func SnapshotCommand(e Evidence, trustedHostOptIn bool) ([]byte, error) {
	if !trustedHostOptIn || !e.authenticated || e.NativeProtocol != NativeProtocolVersion ||
		e.GoProtocolMajor != GoProtocolMajor || !requestIDPattern.MatchString(e.BrowserRequestID) ||
		e.CaptureCount < 1 || e.CaptureCount > MaxBatchItems || !e.RequiresHostResolution ||
		e.ExecutionAuthorized || e.ProductionCutover || !e.ReadOnlySnapshotOnly {
		return nil, ErrRefused
	}
	hash := sha256.Sum256([]byte("mp12-p05:desktop:snapshot:" + e.BrowserRequestID + ":" + e.CaptureFingerprint))
	id := hex.EncodeToString(hash[:16])
	command := struct {
		Protocol struct {
			Major int `json:"major"`
			Minor int `json:"minor"`
		} `json:"protocol"`
		CommandID   string `json:"command_id"`
		OperationID string `json:"operation_id"`
		Kind        string `json:"kind"`
		Payload     struct {
			Probe string `json:"probe"`
		} `json:"payload"`
	}{}
	command.Protocol.Major, command.Protocol.Minor = GoProtocolMajor, GoProtocolMinor
	command.CommandID, command.OperationID = "cmd_"+id, "op_"+id
	command.Kind = "desktop.ui.snapshot"
	command.Payload.Probe = "mp12_p05_read_only"
	return json.Marshal(command)
}

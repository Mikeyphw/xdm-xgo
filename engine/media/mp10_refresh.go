package media

// MP10 P01: sanitized transport failure classification for browser-authorized
// HLS/DASH recording. No URI, credential, header, cookie, or response text
// enters a persistent receipt or an error message. A terminal authorization
// failure must not loop on the same expiring signed URL.
import (
	"time"
)

type MP10FetchFailureCode string

const (
	MP10Unknown             MP10FetchFailureCode = "transport_unavailable"
	MP10SessionExpired      MP10FetchFailureCode = "session_expired"
	MP10CaptureChanged      MP10FetchFailureCode = "capture_request_changed"
	MP10AuthorizationNeeded MP10FetchFailureCode = "authorization_required"
	MP10HTTP401             MP10FetchFailureCode = "http_401"
	MP10HTTP403             MP10FetchFailureCode = "http_403"
	MP10HTTP410             MP10FetchFailureCode = "http_410"
	MP10HTTP404             MP10FetchFailureCode = "http_404"
	MP10HTTP429             MP10FetchFailureCode = "http_429"
	MP10HTTP500             MP10FetchFailureCode = "http_500"
	MP10HTTP502             MP10FetchFailureCode = "http_502"
	MP10HTTP503             MP10FetchFailureCode = "http_503"
	MP10HTTP504             MP10FetchFailureCode = "http_504"
	MP10RangeInvalid        MP10FetchFailureCode = "range_identity_changed"
)

type MP10FetchFailure struct {
	Code       MP10FetchFailureCode
	RetryAfter time.Duration
}

func (f *MP10FetchFailure) Error() string {
	if f == nil {
		return "MP10 transport unavailable"
	}
	// Code can ONLY be a hardcoded enum, never an arbitrary remote error.
	return "MP10 authorized fetch refused"
}

func (f *MP10FetchFailure) RefreshRequired() bool {
	if f == nil {
		return false
	}
	switch f.Code {
	case MP10SessionExpired, MP10CaptureChanged, MP10AuthorizationNeeded,
		MP10HTTP401, MP10HTTP403, MP10HTTP410:
		return true
	default:
		return false
	}
}

// MP10DecodeFetchFailure never allows arbitrary host/error text through.
// Retry-After is only considered for 429 and 503, capped at five minutes;
// HTTP-date values are not accepted by the Android broker in this slice.
func MP10DecodeFetchFailure(rawCode string, retryAfterSeconds int64) *MP10FetchFailure {
	out := &MP10FetchFailure{Code: MP10Unknown}
	switch rawCode {
	case "session_expired":
		out.Code = MP10SessionExpired
	case "capture_request_changed":
		out.Code = MP10CaptureChanged
	case "missing_authorized_request", "credential_scope_denied":
		out.Code = MP10AuthorizationNeeded
	case "http_401":
		out.Code = MP10HTTP401
	case "http_403":
		out.Code = MP10HTTP403
	case "http_410":
		out.Code = MP10HTTP410
	case "http_404":
		out.Code = MP10HTTP404
	case "http_429":
		out.Code = MP10HTTP429
	case "http_500":
		out.Code = MP10HTTP500
	case "http_502":
		out.Code = MP10HTTP502
	case "http_503":
		out.Code = MP10HTTP503
	case "http_504":
		out.Code = MP10HTTP504
	case "range_http_status_invalid", "range_content_range_invalid", "range_length_invalid", "http_416":
		out.Code = MP10RangeInvalid
	}
	if (out.Code == MP10HTTP429 || out.Code == MP10HTTP503) &&
		retryAfterSeconds >= 1 && retryAfterSeconds <= 300 {
		out.RetryAfter = time.Duration(retryAfterSeconds) * time.Second
	}
	return out
}

// mp10PreferFetchFailure retains the strongest, longest bounded retry policy.
// RefreshRequired outranks a transient 429/503; URLs never enter this value.
func mp10PreferFetchFailure(current, next *MP10FetchFailure) *MP10FetchFailure {
    if next == nil { return current }
    if current == nil || next.RefreshRequired() && !current.RefreshRequired() { return next }
    if current.RefreshRequired() { return current }
    if next.RetryAfter > current.RetryAfter { return next }
    return current
}

package media

import (
	"strings"
	"testing"
	"time"
)

func TestMP10AuthorizationAndRetryClasses(t *testing.T) {
	for _, code := range []string{"session_expired", "capture_request_changed", "missing_authorized_request", "credential_scope_denied", "http_401", "http_403", "http_410"} {
		got := MP10DecodeFetchFailure(code, 240)
		if !got.RefreshRequired() || got.RetryAfter != 0 {
			t.Fatalf("required refresh misclassified: %s", code)
		}
	}
	for _, code := range []string{"http_404", "http_429", "http_500", "http_502", "http_503", "http_504", "http_416"} {
		if MP10DecodeFetchFailure(code, 20).RefreshRequired() {
			t.Fatalf("false refresh classification %s", code)
		}
	}
}

func TestMP10BoundedRetryAfter(t *testing.T) {
	for _, tc := range []struct {
		code string
		sec  int64
		want time.Duration
	}{
		{"http_429", 120, 120 * time.Second}, {"http_503", 300, 300 * time.Second},
		{"http_429", 301, 0}, {"http_503", -1, 0}, {"http_500", 3, 0},
		{"http_429", 0, 0},
	} {
		got := MP10DecodeFetchFailure(tc.code, tc.sec)
		if got.RetryAfter != tc.want {
			t.Fatalf("code=%s sec=%d got=%v want=%v", tc.code, tc.sec, got.RetryAfter, tc.want)
		}
	}
}

func TestMP10NoUntrustedErrorTextOrCredentials(t *testing.T) {
	secret := "https://a.invalid/live.m3u8?token=VERY_SECRET Cookie=hidden"
	got := MP10DecodeFetchFailure(secret, 100)
	if got.RefreshRequired() || got.RetryAfter != 0 || got.Code != MP10Unknown {
		t.Fatal("untrusted code accepted")
	}
	if strings.Contains((&MP10FetchFailure{Code: MP10FetchFailureCode(secret)}).Error(), "VERY_SECRET") {
		t.Fatal("untrusted typed error leaked")
	}
	if strings.Contains(got.Error(), "VERY_SECRET") || strings.Contains(got.Error(), "Cookie") || strings.Contains(got.Error(), "http") {
		t.Fatal("remote data in public failure")
	}
}

func TestMP10AllErrorsNeverImplyPublication(t *testing.T) {
	for _, code := range []string{"http_401", "http_429", "http_503", "session_expired", "unknown"} {
		got := MP10DecodeFetchFailure(code, 10)
		if got.Error() == "" || strings.Contains(got.Error(), "download_ready") {
			t.Fatal("invalid failure")
		}
	}
}

func TestMP10PrioritizeRefreshAndLongestRetry(t *testing.T) {
    short := MP10DecodeFetchFailure("http_503", 20)
    long := MP10DecodeFetchFailure("http_429", 240)
    refresh := MP10DecodeFetchFailure("http_401", 0)
    if got := mp10PreferFetchFailure(short,long); got != long { t.Fatal("longer retry lost") }
    if got := mp10PreferFetchFailure(long,refresh); got != refresh { t.Fatal("refresh not prioritized") }
    if got := mp10PreferFetchFailure(refresh,long); got != refresh { t.Fatal("refresh downgraded to retry") }
    if got := mp10PreferFetchFailure(nil,short); got != short { t.Fatal("first failure lost") }
}

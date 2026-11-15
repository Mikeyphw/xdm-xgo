package media

// MP10 P02: signed URL rotation must not change stream identity.
// This is a fail-closed *transport* policy, not a substitute for checking
// already committed fragment bytes and the new HLS/DASH timeline.
import (
	"errors"
	"net/url"
	"sort"
	"strings"
)

var ErrMP10RefreshIdentity = errors.New("MP10 source identity not proven; retain committed fragments for review")

var mp10TransportOnlyKeys = map[string]bool{
	"sig": true, "signature": true, "token": true, "access_token": true,
	"auth": true, "expires": true, "expiry": true,
	"x-amz-signature": true, "x-amz-credential": true, "x-amz-date": true,
	"x-amz-expires": true, "x-amz-security-token": true,
}

func mp10CanonicalRefreshURL(raw string) (string, error) {
	if len(raw) == 0 || len(raw) > 4096 || strings.TrimSpace(raw) != raw {
		return "", ErrMP10RefreshIdentity
	}
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "https" && u.Scheme != "http") ||
		u.Host == "" || u.Hostname() == "" || u.User != nil || u.Fragment != "" || u.Opaque != "" ||
		u.RawPath != "" && u.EscapedPath() != u.RawPath || u.Port() != "" && u.Port() == "0" {
		return "", ErrMP10RefreshIdentity
	}
	q, err := url.ParseQuery(u.RawQuery)
	if err != nil {
		return "", ErrMP10RefreshIdentity
	}
	normalized := url.Values{}
	for key, values := range q {
		if mp10TransportOnlyKeys[strings.ToLower(key)] {
			continue
		}
		if key == "" || len(key) > 160 || len(values) > 8 {
			return "", ErrMP10RefreshIdentity
		}
		vals := append([]string(nil), values...)
		sort.Strings(vals)
		for _, value := range vals {
			if len(value) > 1024 {
				return "", ErrMP10RefreshIdentity
			}
			normalized.Add(key, value)
		}
	}
	// Do not normalize a distinct path, port, scheme, or query argument away.
	u.RawQuery = normalized.Encode()
	u.ForceQuery = false
	u.Host = strings.ToLower(u.Host)
	return u.String(), nil
}

// MP10ValidateRefreshBinding is called for the root AND every selected track.
// Never return raw URLs or remote error text, even for invalid UTF-8 strings.
func MP10ValidateRefreshBinding(previous, replacement string) error {
	before, e1 := mp10CanonicalRefreshURL(previous)
	after, e2 := mp10CanonicalRefreshURL(replacement)
	if e1 != nil || e2 != nil || before != after {
		return ErrMP10RefreshIdentity
	}
	return nil
}

package media

import (
	"errors"
	"strings"
	"testing"
)

func TestMP10RefreshPolicySignedQueryOnly(t *testing.T) {
	good := [][2]string{
		{"https://media.invalid/video.m3u8?token=old&variant=1", "https://media.invalid/video.m3u8?variant=1&token=renewed"},
		{"https://media.invalid/stream.mpd?x-amz-signature=old&quality=hi", "https://media.invalid/stream.mpd?quality=hi&x-amz-signature=new"},
		{"https://media.invalid/v.mp4?expires=1&sig=x&v=2", "https://media.invalid/v.mp4?sig=y&v=2&expires=2"},
	}
	for _, tc := range good {
		if err := MP10ValidateRefreshBinding(tc[0], tc[1]); err != nil {
			t.Fatal(err)
		}
	}
	bad := [][2]string{
		{"https://media.invalid/v.m3u8?token=old", "https://evil.invalid/v.m3u8?token=new"},
		{"https://media.invalid/v.m3u8?token=old", "http://media.invalid/v.m3u8?token=new"},
		{"https://media.invalid/v.m3u8?token=old", "https://media.invalid/other.m3u8?token=new"},
		{"https://media.invalid/v.m3u8?quality=1&sig=a", "https://media.invalid/v.m3u8?quality=2&sig=b"},
		{"https://media.invalid/v.m3u8?sig=a", "https://media.invalid:444/v.m3u8?sig=b"},
		{"https://media.invalid/v.m3u8?sig=a", "https://user:pw@media.invalid/v.m3u8?sig=b"},
		{"https://media.invalid/v.m3u8?sig=a", "https://media.invalid/v.m3u8?sig=b#frag"},
		{"https://media.invalid/v.m3u8?sig=a", "file:///tmp/v.m3u8"},
		{"https://media.invalid/v.m3u8?sig=a", "https://media.invalid/v.m3u8?%bad"},
	}
	for _, tc := range bad {
		if err := MP10ValidateRefreshBinding(tc[0], tc[1]); !errors.Is(err, ErrMP10RefreshIdentity) {
			t.Fatalf("should refuse: %v", tc)
		}
	}
}
func TestMP10RefreshErrorNoCredentials(t *testing.T) {
	token := "VERY_SECRET_REFRESH_TOKEN"
	e := MP10ValidateRefreshBinding("https://media.invalid/v.m3u8?sig="+token, "https://other.invalid/v.m3u8?sig=x")
	if e == nil || strings.Contains(e.Error(), token) || strings.Contains(e.Error(), "media.invalid") {
		t.Fatal("leaked URL credentials")
	}
}

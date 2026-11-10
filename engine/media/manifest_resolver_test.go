package media

import (
	"context"
	"errors"
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"
)

func mp03Fixture(t *testing.T, pages map[string]ManifestFetchResponse, policy ManifestResolvePolicy) (ManifestGraphV1, []ManifestFetchRequest, error) {
	t.Helper()
	var requests []ManifestFetchRequest
	fetch := ManifestFetchFunc(func(ctx context.Context, request ManifestFetchRequest) (ManifestFetchResponse, error) {
		requests = append(requests, request)
		if v, ok := pages[request.URL]; ok {
			return v, nil
		}
		return ManifestFetchResponse{}, fmt.Errorf("fixture missing")
	})
	graph, err := ResolveManifestGraph(context.Background(), "https://media.example/opaque", fetch, policy)
	return graph, requests, err
}
func mp03Response(body string, mime string) ManifestFetchResponse {
	return ManifestFetchResponse{Body: []byte(body), ContentType: mime}
}

const mp03Master = `#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",LANGUAGE="en",DEFAULT=YES,URI="audio/en"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Portuguese",LANGUAGE="pt",URI="subs/pt"
#EXT-X-STREAM-INF:BANDWIDTH=1800000,RESOLUTION=1280x720,CODECS="avc1.42E01E,mp4a.40.2",AUDIO="aud",SUBTITLES="subs"
v/720
#EXT-X-STREAM-INF:BANDWIDTH=600000,RESOLUTION=640x360,AUDIO="aud"
v/360`
const mp03Media = `#EXTM3U
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:3
#EXTINF:6.0,
seg-3.ts
#EXT-X-ENDLIST`
const mp03Dash = `<MPD type="static" mediaPresentationDuration="PT12S"><BaseURL>https://media.example/root/</BaseURL><Period id="p0" duration="PT12S"><AdaptationSet id="v" contentType="video" mimeType="video/mp4"><Representation id="hi" bandwidth="2400000" width="1280" height="720" codecs="avc1.64001f"><BaseURL>v/hi/</BaseURL><SegmentTemplate timescale="1" duration="6" media="seg-$Number$.m4s" initialization="init.mp4"/></Representation><Representation id="lo" bandwidth="500000" width="640" height="360"><BaseURL>v/lo/</BaseURL></Representation></AdaptationSet><AdaptationSet id="a" contentType="audio" lang="en" mimeType="audio/mp4"><Representation id="en" bandwidth="64000" codecs="mp4a.40.2"><BaseURL>a/en/</BaseURL></Representation></AdaptationSet><AdaptationSet id="s" contentType="text" lang="pt"><Representation id="pt"><BaseURL>s/pt/</BaseURL></Representation></AdaptationSet></Period></MPD>`

func TestMP03HLS01Through07(t *testing.T) {
	root := "https://media.example/opaque"
	pages := map[string]ManifestFetchResponse{
		root:                             mp03Response(mp03Master, "application/octet-stream"),
		"https://media.example/v/720":    mp03Response(mp03Media, "application/vnd.apple.mpegurl"),
		"https://media.example/v/360":    mp03Response(mp03Media, "application/vnd.apple.mpegurl"),
		"https://media.example/audio/en": mp03Response(mp03Media, "application/vnd.apple.mpegurl"),
		"https://media.example/subs/pt":  mp03Response(mp03Media, "application/vnd.apple.mpegurl"),
	}
	t.Run("HLS01-qualities-audio-subtitles", func(t *testing.T) {
		graph, requests, err := mp03Fixture(t, pages, ManifestResolvePolicy{CredentialReplayApproved: true, AuthorizedOrigin: "https://media.example"})
		if err != nil {
			t.Fatal(err)
		}
		if graph.Protocol != "hls" || graph.Kind != "vod" || len(graph.Variants) != 2 || len(graph.AudioTracks) != 1 || len(graph.SubtitleTracks) != 1 || len(graph.Sources) != 5 {
			t.Fatalf("unexpected exact options: %+v", graph.SafeSummary())
		}
		if graph.AudioTracks[0].Language != "en" || graph.AudioTracks[0].Group != "aud" || !graph.AudioTracks[0].Default {
			t.Fatal("audio group lost")
		}
		for _, req := range requests {
			if !req.MayReplayCredentials {
				t.Fatal("same-origin approved capture replay missing")
			}
		}
		if graph.DownloadReady {
			t.Fatal("MP03 must not claim durable fragment execution readiness")
		}
	})
	t.Run("HLS02-extensionless-body", func(t *testing.T) {
		graph, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(mp03Media, "application/octet-stream")}, ManifestResolvePolicy{})
		if err != nil || graph.Protocol != "hls" {
			t.Fatalf("body signature %v", err)
		}
	})
	t.Run("HLS03-single-VOD", func(t *testing.T) {
		graph, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(mp03Media, "")}, ManifestResolvePolicy{})
		if err != nil || graph.Kind != "vod" || len(graph.Variants) != 1 {
			t.Fatalf("single playlist %v %+v", err, graph.SafeSummary())
		}
	})
	t.Run("HLS04-AES128-not-DRM", func(t *testing.T) {
		text := "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key.bin\"\n#EXTINF:6,\ns.ts\n#EXT-X-ENDLIST"
		g, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(text, "")}, ManifestResolvePolicy{})
		if err != nil || g.Protected || !reflect.DeepEqual(g.Protection, []string{"aes-128"}) {
			t.Fatalf("AES-128 incorrectly DRM classified %+v %v", g.Protection, err)
		}
	})
	t.Run("HLS05-DRM-diagnostic", func(t *testing.T) {
		text := "#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI=\"key.bin\"\n#EXTINF:6,\ns.ts"
		g, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(text, "")}, ManifestResolvePolicy{})
		if err != nil || !g.Protected {
			t.Fatalf("protected content silently allowed %v", err)
		}
	})
	t.Run("HLS06-live-event", func(t *testing.T) {
		text := "#EXTM3U\n#EXT-X-PLAYLIST-TYPE:EVENT\n#EXTINF:6,\ns.ts"
		g, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(text, "")}, ManifestResolvePolicy{})
		if err != nil || g.Kind != "event" {
			t.Fatalf("event %v %v", g.Kind, err)
		}
	})
	t.Run("HLS07-discontinuity", func(t *testing.T) {
		text := "#EXTM3U\n#EXT-X-DISCONTINUITY-SEQUENCE:3\n#EXTINF:6,\na.ts\n#EXT-X-DISCONTINUITY\n#EXTINF:6,\nb.ts\n#EXT-X-ENDLIST"
		g, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(text, "")}, ManifestResolvePolicy{})
		if err != nil || len(g.Periods) != 2 || g.Periods[0].Discontinuity != 3 || g.Periods[1].Discontinuity != 4 {
			t.Fatalf("discontinuity %+v %v", g.Periods, err)
		}
	})
}

func TestMP03DASH01Through06(t *testing.T) {
	root := "https://media.example/opaque"
	mpd := map[string]ManifestFetchResponse{root: mp03Response(mp03Dash, "application/dash+xml")}
	t.Run("DASH01-qualities", func(t *testing.T) {
		g, _, err := mp03Fixture(t, mpd, ManifestResolvePolicy{})
		if err != nil || g.Protocol != "dash" || g.Kind != "vod" || len(g.Variants) != 2 || len(g.AudioTracks) != 1 || len(g.SubtitleTracks) != 1 {
			t.Fatalf("DASH exact graph %+v %v", g.SafeSummary(), err)
		}
	})
	t.Run("DASH02-inherited-BaseURL", func(t *testing.T) {
		g, _, err := mp03Fixture(t, mpd, ManifestResolvePolicy{})
		if err != nil {
			t.Fatal(err)
		}
		found := false
		for _, v := range g.Variants {
			if strings.HasPrefix(v.URL, "https://media.example/root/v/hi/") {
				found = true
			}
		}
		if !found {
			t.Fatalf("lost nested BaseURL %+v", g.Variants)
		}
	})
	t.Run("DASH03-period-separation", func(t *testing.T) {
		body := strings.Replace(mp03Dash, "</MPD>", "<Period id=\"p1\" start=\"PT12S\" duration=\"PT6S\"><AdaptationSet id=\"v\" contentType=\"video\"><Representation id=\"hi\" bandwidth=\"100\"><BaseURL>v/next/</BaseURL></Representation></AdaptationSet></Period></MPD>", 1)
		g, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(body, "")}, ManifestResolvePolicy{})
		if err != nil || len(g.Periods) != 2 || len(g.Variants) != 3 {
			t.Fatalf("multi period %v %+v", err, g.SafeSummary())
		}
	})
	t.Run("DASH04-dynamic", func(t *testing.T) {
		body := strings.Replace(mp03Dash, `type="static"`, `type="dynamic"`, 1)
		g, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(body, "")}, ManifestResolvePolicy{})
		if err != nil || g.Kind != "live" {
			t.Fatalf("dynamic %v %v", g.Kind, err)
		}
	})
	t.Run("DASH05-ContentProtection", func(t *testing.T) {
		body := strings.Replace(mp03Dash, `<AdaptationSet id="v" contentType="video" mimeType="video/mp4">`, `<AdaptationSet id="v" contentType="video" mimeType="video/mp4"><ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/>`, 1)
		g, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(body, "")}, ManifestResolvePolicy{})
		if err != nil || !g.Protected {
			t.Fatalf("protected MPD not diagnosed %v", err)
		}
	})
	t.Run("DASH06-entities-denied", func(t *testing.T) {
		body := `<!DOCTYPE MPD [<!ENTITY x "bad">]>` + mp03Dash
		_, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(body, "")}, ManifestResolvePolicy{})
		if !errors.Is(err, ErrManifestInvalid) {
			t.Fatalf("XML entity accepted: %v", err)
		}
	})
}

func TestMP03RES01Through10(t *testing.T) {
	root := "https://media.example/opaque"
	t.Run("RES01-cycle", func(t *testing.T) {
		body := "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nopaque"
		_, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(body, "")}, ManifestResolvePolicy{})
		if !errors.Is(err, ErrManifestCycle) {
			t.Fatalf("cycle %v", err)
		}
	})
	t.Run("RES02-wrong-JSON-MIME", func(t *testing.T) {
		_, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(mp03Media, "application/json")}, ManifestResolvePolicy{})
		if !errors.Is(err, ErrManifestInvalid) {
			t.Fatalf("fake JSON MIME promoted %v", err)
		}
	})
	t.Run("RES03-redirect-unproven", func(t *testing.T) {
		r := mp03Response(mp03Media, "")
		r.FinalURL = "https://media.example/new"
		_, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: r}, ManifestResolvePolicy{})
		if !errors.Is(err, ErrManifestRedirect) {
			t.Fatalf("unproven redirect %v", err)
		}
	})
	t.Run("RES04-signed-expired", func(t *testing.T) {
		r := mp03Response(mp03Media, "")
		r.ExpiresAt = time.Unix(10, 0)
		_, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: r}, ManifestResolvePolicy{Now: func() time.Time { return time.Unix(11, 0) }})
		if !errors.Is(err, ErrManifestExpired) {
			t.Fatalf("expired URL accepted %v", err)
		}
	})
	t.Run("RES05-byte-bound", func(t *testing.T) {
		_, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(mp03Media, "")}, ManifestResolvePolicy{MaxTotalBytes: 16})
		if !errors.Is(err, ErrManifestLimit) {
			t.Fatalf("oversized %v", err)
		}
	})
	t.Run("RES06-false-positive-API", func(t *testing.T) {
		_, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(`{"file":"https://x.example/stream"}`, "application/octet-stream")}, ManifestResolvePolicy{})
		if !errors.Is(err, ErrManifestInvalid) {
			t.Fatalf("API promoted %v", err)
		}
	})
	t.Run("RES07-cross-origin-child-denied", func(t *testing.T) {
		master := "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=500\nhttps://evil.example/video.m3u8"
		_, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(master, "")}, ManifestResolvePolicy{})
		if !errors.Is(err, ErrManifestScope) {
			t.Fatalf("cross-origin %v", err)
		}
	})
	t.Run("RES08-allowlisted-cross-origin-no-credentials", func(t *testing.T) {
		master := "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=500\nhttps://other.example/video.m3u8"
		child := "https://other.example/video.m3u8"
		_, reqs, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(master, ""), child: mp03Response(mp03Media, "")}, ManifestResolvePolicy{AllowedManifestOrigins: []string{"https://other.example"}, CredentialReplayApproved: true, AuthorizedOrigin: "https://media.example"})
		if err != nil || len(reqs) != 2 || !reqs[0].MayReplayCredentials || reqs[1].MayReplayCredentials {
			t.Fatalf("credential scope regression %+v %v", reqs, err)
		}
	})
	t.Run("RES09-redirect-cross-origin-denied", func(t *testing.T) {
		r := mp03Response(mp03Media, "")
		r.FinalURL = "https://other.example/video"
		r.Redirects = []string{r.FinalURL}
		_, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: r}, ManifestResolvePolicy{AllowedManifestOrigins: []string{"https://other.example"}, CredentialReplayApproved: true, AuthorizedOrigin: "https://media.example"})
		if !errors.Is(err, ErrManifestRedirect) {
			t.Fatalf("secret-bearing redirect %v", err)
		}
	})
	t.Run("RES10-safe-summary-and-no-durable-claim", func(t *testing.T) {
		g, _, err := mp03Fixture(t, map[string]ManifestFetchResponse{root: mp03Response(mp03Media, "")}, ManifestResolvePolicy{})
		if err != nil {
			t.Fatal(err)
		}
		if fmt.Sprint(g.SafeSummary()) == "" || g.DownloadReady {
			t.Fatal("unsafe summary/durability")
		}
		if strings.Contains(fmt.Sprintf("%+v", g.SafeSummary()), "media.example") {
			t.Fatal("summary exposed source URL")
		}
	})
}

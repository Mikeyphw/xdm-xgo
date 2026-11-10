package media

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
)

const mp06Master = `#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="stereo",NAME="English",LANGUAGE="en",URI="en.m3u8",DEFAULT=YES
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="stereo",NAME="Spanish",LANGUAGE="es",URI="es.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="other",NAME="Other",LANGUAGE="en",URI="other.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=1280x720,AUDIO="stereo"
video.m3u8
`
const mp06Video = `#EXTM3U
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-MEDIA-SEQUENCE:4
#EXTINF:4,
v4.ts
#EXTINF:4,
v5.ts
#EXT-X-ENDLIST
`
const mp06SingleMaster = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000\nvideo.m3u8\n"
const mp06Audio = `#EXTM3U
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-MEDIA-SEQUENCE:12
#EXTINF:4,
a12.aac
#EXTINF:4,
a13.aac
#EXT-X-ENDLIST
`

func mp06Request() HLSVODRequest {
	return HLSVODRequest{
		MasterURL: "https://cdn.example/vod/master.m3u8", MasterBody: mp06Master,
		VideoURI: "https://cdn.example/vod/video.m3u8", VideoBody: mp06Video,
		AudioURI: "https://cdn.example/vod/en.m3u8", AudioBody: mp06Audio,
		RequireAudio: true, AttemptGeneration: 1,
	}
}
func mp06Sinks(t *testing.T) (*FileFragmentStore, *FileFragmentStore) {
	t.Helper()
	root := t.TempDir()
	a, e := NewFileFragmentStore(filepath.Join(root, "video"), 1<<20)
	if e != nil {
		t.Fatal(e)
	}
	b, e := NewFileFragmentStore(filepath.Join(root, "audio"), 1<<20)
	if e != nil {
		t.Fatal(e)
	}
	return a, b
}
func mp06Fetcher() *memoryHLSFetcher {
	return newMemoryHLSFetcher(map[string][]byte{
		"https://cdn.example/vod/v4.ts":   []byte("video-4"),
		"https://cdn.example/vod/v5.ts":   []byte("video-5"),
		"https://cdn.example/vod/a12.aac": []byte("audio-12"),
		"https://cdn.example/vod/a13.aac": []byte("audio-13"),
	})
}
func mp06Refused(t *testing.T, req HLSVODRequest) {
	t.Helper()
	if _, e := PlanHLSVOD(req); !errors.Is(e, ErrHLSVODSelection) {
		t.Fatalf("expected fail-closed plan, got %v", e)
	}
}

func TestMP06HLS01MasterVideoAndSeparateAudioStaging(t *testing.T) {
	req := mp06Request()
	v, a := mp06Sinks(t)
	f := mp06Fetcher()
	result, e := ExecuteHLSVOD(context.Background(), req, f, v, a)
	if e != nil || result.Status != "staged" || !result.ReadyForMux || result.DownloadReady || len(result.Tracks) != 2 || result.Tracks[0].DurableCount != 2 || result.Tracks[1].DurableCount != 2 {
		t.Fatalf("HLS01: %+v %v", result, e)
	}
	if len(v.CommittedRecords()) != 2 || len(a.CommittedRecords()) != 2 {
		t.Fatal("split ledgers not isolated")
	}
}
func TestMP06HLS02RestartDoesNotRepeatDurableParts(t *testing.T) {
	v, a := mp06Sinks(t)
	f := mp06Fetcher()
	req := mp06Request()
	for i := 0; i < 2; i++ {
		req.AttemptGeneration = int64(i + 1)
		r, e := ExecuteHLSVOD(context.Background(), req, f, v, a)
		if e != nil || !r.ReadyForMux {
			t.Fatal(r, e)
		}
	}
	for _, u := range []string{"v4.ts", "v5.ts", "a12.aac", "a13.aac"} {
		if f.counts["segment https://cdn.example/vod/"+u] != 1 {
			t.Fatalf("redownload %s: %+v", u, f.counts)
		}
	}
}
func TestMP06HLS03RequiredSeparateAudioCannotBeSilentlyDropped(t *testing.T) {
	req := mp06Request()
	req.AudioURI = ""
	req.AudioBody = ""
	mp06Refused(t, req)
}
func TestMP06HLS04WrongAudioGroupRejected(t *testing.T) {
	req := mp06Request()
	req.AudioURI = "https://cdn.example/vod/other.m3u8"
	mp06Refused(t, req)
}
func TestMP06HLS05UnlistedVariantRejected(t *testing.T) {
	req := mp06Request()
	req.VideoURI = "https://cdn.example/vod/unlisted.m3u8"
	mp06Refused(t, req)
}
func TestMP06HLS06DurationMismatchRejected(t *testing.T) {
	req := mp06Request()
	req.AudioBody = strings.ReplaceAll(mp06Audio, "#EXTINF:4,", "#EXTINF:7,")
	mp06Refused(t, req)
}
func TestMP06HLS07LiveChildRequiresRecordingPath(t *testing.T) {
	req := mp06Request()
	req.VideoBody = strings.ReplaceAll(mp06Video, "#EXT-X-ENDLIST\n", "")
	mp06Refused(t, req)
}
func TestMP06HLS08DRMOrSampleAESRejected(t *testing.T) {
	req := mp06Request()
	req.VideoBody = strings.Replace(mp06Video, "#EXTINF:4,", "#EXT-X-KEY:METHOD=SAMPLE-AES,URI=\"skd://license\"\n#EXTINF:4,", 1)
	mp06Refused(t, req)
}
func TestMP06HLS09ExplicitGapReportsPartial(t *testing.T) {
	req := mp06Request()
	req.AudioURI = ""
	req.AudioBody = ""
	req.RequireAudio = false
	req.MasterBody = mp06SingleMaster
	req.VideoBody = strings.Replace(req.VideoBody, "#EXTINF:4,\nv5.ts", "#EXT-X-GAP\n#EXTINF:4,\nv5.ts", 1)
	v, _ := mp06Sinks(t)
	f := mp06Fetcher()
	out, e := ExecuteHLSVOD(context.Background(), req, f, v, nil)
	if e != nil || out.Status != "partial" || out.ReadyForMux || out.DownloadReady || out.Tracks[0].IntentionalGaps != 1 || out.Tracks[0].DurableCount != 1 || out.Tracks[0].MissingCount != 0 {
		t.Fatalf("gap accidentally promoted: %+v %v", out, e)
	}
	if f.counts["segment https://cdn.example/vod/v5.ts"] != 0 {
		t.Fatal("explicit gap was fetched")
	}
}
func TestMP06HLS10AES128EncryptedInitMapDecryptedAndStored(t *testing.T) {
	req := mp06Request()
	req.AudioURI = ""
	req.AudioBody = ""
	req.RequireAudio = false
	req.MasterBody = mp06SingleMaster
	iv := "0x00000000000000000000000000000004"
	key := []byte("0123456789abcdef")
	req.VideoBody = fmt.Sprintf("#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-MEDIA-SEQUENCE:4\n#EXT-X-KEY:METHOD=AES-128,URI=\"secret.key\",IV=%s\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:4,\nv4.ts\n#EXT-X-ENDLIST\n", iv)
	f := newMemoryHLSFetcher(map[string][]byte{
		"https://cdn.example/vod/secret.key": key,
		"https://cdn.example/vod/init.mp4":   encryptHLSForTest(t, []byte("clear-init"), key, 4),
		"https://cdn.example/vod/v4.ts":      encryptHLSForTest(t, []byte("clear-media"), key, 4),
	})
	v, _ := mp06Sinks(t)
	out, e := ExecuteHLSVOD(context.Background(), req, f, v, nil)
	if e != nil || !out.ReadyForMux || len(v.CommittedRecords()) != 2 {
		t.Fatalf("AES map staging failed: %+v %v", out, e)
	}
	for _, rec := range v.CommittedRecords() {
		if rec.Role == "init" {
			plain, e := v.ReadVerified(rec.Identity)
			if e != nil || string(plain) != "clear-init" {
				t.Fatalf("encrypted init map not decrypted: %q %v", plain, e)
			}
			return
		}
	}
	t.Fatal("no verified init-map receipt")
}
func TestMP06HLS11EncryptedInitWithoutIVRefused(t *testing.T) {
	req := mp06Request()
	req.AudioURI = ""
	req.AudioBody = ""
	req.MasterBody = mp06SingleMaster
	req.VideoBody = "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:4\n#EXT-X-KEY:METHOD=AES-128,URI=\"key\"\n#EXT-X-MAP:URI=\"map\"\n#EXTINF:4,\nv4.ts\n#EXT-X-ENDLIST\n"
	mp06Refused(t, req)
}
func TestMP06HLS12InvalidKeyCannotClaimDurableStaging(t *testing.T) {
	req := mp06Request()
	req.AudioURI = ""
	req.AudioBody = ""
	req.MasterBody = mp06SingleMaster
	req.VideoBody = "#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"bad.key\"\n#EXTINF:4,\nv4.ts\n#EXT-X-ENDLIST\n"
	v, _ := mp06Sinks(t)
	f := mp06Fetcher()
	f.objects["https://cdn.example/vod/bad.key"] = []byte("wrong")
	out, e := ExecuteHLSVOD(context.Background(), req, f, v, nil)
	if !errors.Is(e, ErrHLSVODIncomplete) || out.ReadyForMux || out.DownloadReady {
		t.Fatalf("bad key promoted: %+v %v", out, e)
	}
}
func TestMP06HLS13MissingDurableAudioStoreFailClosedPreflight(t *testing.T) {
	req := mp06Request()
	v, _ := mp06Sinks(t)
	f := mp06Fetcher()
	_, e := ExecuteHLSVOD(context.Background(), req, f, v, nil)
	if !errors.Is(e, ErrHLSVODSelection) || len(v.CommittedRecords()) != 0 {
		t.Fatalf("audio sink missing admitted: %v", e)
	}
}
func TestMP06HLS14MuxOrEmbeddedAudioNeverClaimsPlayable(t *testing.T) {
	req := mp06Request()
	req.MasterBody = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=900000\nvideo.m3u8\n"
	req.AudioURI = ""
	req.AudioBody = ""
	req.RequireAudio = true
	p, e := PlanHLSVOD(req)
	if e != nil || !p.NeedsEmbeddedAudioProof {
		t.Fatal("embedded audio proof lost", e)
	}
	v, _ := mp06Sinks(t)
	res, e := ExecuteHLSVOD(context.Background(), req, mp06Fetcher(), v, nil)
	if e != nil || !res.NeedsEmbeddedAudioProof || res.DownloadReady || !res.ReadyForMux {
		t.Fatalf("incomplete readiness contract: %+v %v", res, e)
	}
}

// HLS15: a playlist cannot smuggle an un-timed segment into a “ready” stage.
func TestMP06HLS15MissingExtinfCannotStage(t *testing.T) {
	req := mp06Request()
	req.VideoBody = strings.Replace(req.VideoBody, "#EXTINF:4,\nv4.ts", "v4.ts", 1)
	mp06Refused(t, req)
}

package media

import (
 "errors"
 "strings"
 "testing"
)
func mp04Fixture() ManifestGraphV1 {
 return ManifestGraphV1{SchemaVersion:1,RootID:"root-test",RootURL:"https://media.example/master.m3u8?token=secret",Protocol:"hls",Kind:"vod",Periods:[]ManifestPeriodV1{{ID:"hls-disc-0"}},
 Variants:[]ManifestVariantV1{
 {ID:"v720",ContentKind:"video",URL:"https://media.example/720.m3u8",PeriodID:"hls-0",Width:1280,Height:720,Bandwidth:2000000,Codecs:[]string{"avc1.42E01E","mp4a.40.2"},AudioGroup:"audio",SubtitleGroup:"subs"},
 {ID:"v1080",ContentKind:"video",URL:"https://media.example/1080.m3u8",PeriodID:"hls-0",Width:1920,Height:1080,Bandwidth:4000000,Codecs:[]string{"hvc1.1.6.L93","mp4a.40.2"},AudioGroup:"audio",SubtitleGroup:"subs"},
 {ID:"vother",ContentKind:"video",URL:"https://media.example/other.m3u8",PeriodID:"hls-0",Width:3840,Height:2160,Bandwidth:5000000,Codecs:[]string{"vp09.00.10.08","opus"},AudioGroup:"alt-audio",SubtitleGroup:"alt-subs"},
 },AudioTracks:[]ManifestTrackV1{
 {ID:"a-en",Type:"audio",Group:"audio",PeriodID:"hls-0",Language:"en",Default:true,Codec:"mp4a",URL:"https://media.example/audio-en.m3u8"},
 {ID:"a-es",Type:"audio",Group:"audio",PeriodID:"hls-0",Language:"es",Codec:"mp4a",URL:"https://media.example/audio-es.m3u8"},
 {ID:"a-alt",Type:"audio",Group:"alt-audio",PeriodID:"hls-0",Language:"en",Default:true,Codec:"opus",URL:"https://media.example/audio-alt.m3u8"},
 },SubtitleTracks:[]ManifestTrackV1{
 {ID:"s-en",Type:"subtitles",Group:"subs",PeriodID:"hls-0",Language:"en",Default:true,Codec:"webvtt",URL:"https://media.example/en.vtt"},
 {ID:"s-alt",Type:"subtitles",Group:"alt-subs",PeriodID:"hls-0",Language:"en",Codec:"webvtt",URL:"https://media.example/alt.vtt"},
 }}
}
func mp04Must(t *testing.T,g ManifestGraphV1,req ManifestSelectionInputV1) ManifestSelectionPlanV1 {t.Helper();p,err:=SelectManifestGraph(g,req);if err!=nil {t.Fatal(err)};return p}
func mp04Reject(t *testing.T,g ManifestGraphV1,req ManifestSelectionInputV1){t.Helper();_,err:=SelectManifestGraph(g,req);if !errors.Is(err,ErrManifestSelection){t.Fatalf("expected selection refusal; got %v",err)}}
func TestMP04SEL01DeterministicQualityAndPreference(t *testing.T){g:=mp04Fixture();p:=mp04Must(t,g,ManifestSelectionInputV1{MaxHeight:1080,PreferredCodecs:[]string{"avc1"}});if p.VideoID!="v720"||p.AudioID!="a-en"{t.Fatalf("wrong selected quality or audio: %+v",p)};if !p.Required.Video||!p.Required.Audio||p.ExecutionReady{t.Fatal("required flags or false execution authority missing")}}
func TestMP04SEL02GroupMismatchRefused(t *testing.T){g:=mp04Fixture();mp04Reject(t,g,ManifestSelectionInputV1{VideoID:"v720",AudioID:"a-alt"});mp04Reject(t,g,ManifestSelectionInputV1{VideoID:"v720",SubtitleID:"s-alt"})}
func TestMP04SEL03DefaultLanguageAndExplicitSelection(t *testing.T){g:=mp04Fixture();p:=mp04Must(t,g,ManifestSelectionInputV1{VideoID:"v720",PreferredAudioLanguages:[]string{"es"}});if p.AudioID!="a-es"{t.Fatal("ignored preferred language")};p=mp04Must(t,g,ManifestSelectionInputV1{VideoID:"v720",PreferredAudioLanguages:[]string{"de"}});if p.AudioID!="a-en"{t.Fatal("default language fallback failed")}}
func TestMP04SEL04VideoOnlyAndAudioOnly(t *testing.T){g:=mp04Fixture();p:=mp04Must(t,g,ManifestSelectionInputV1{Intent:"video_only",VideoID:"v720"});if p.Required.Audio||p.AudioID!=""||!p.Required.Video {t.Fatal("video-only contract wrong")};p=mp04Must(t,g,ManifestSelectionInputV1{Intent:"audio_only",PreferredAudioLanguages:[]string{"es"}});if p.VideoID!=""||p.AudioID!="a-es"||p.Required.Video||!p.Required.Audio{t.Fatal("audio-only contract wrong")}}
func TestMP04SEL05RequiredSubtitle(t *testing.T){g:=mp04Fixture();p:=mp04Must(t,g,ManifestSelectionInputV1{VideoID:"v720",SubtitlePolicy:"required"});if !p.Required.Subtitle||p.SubtitleID!="s-en"{t.Fatal("required subtitle lost")};g.SubtitleTracks=nil;mp04Reject(t,g,ManifestSelectionInputV1{VideoID:"v720",SubtitlePolicy:"required"})}
func TestMP04SEL06CodecContainerCompatibility(t *testing.T){g:=mp04Fixture();p:=mp04Must(t,g,ManifestSelectionInputV1{VideoID:"vother"});if p.Container!="webm"{t.Fatalf("incompatible audio/video expected WEBM, got %s",p.Container)};mp04Reject(t,g,ManifestSelectionInputV1{VideoID:"vother",Container:"mp4"});p=mp04Must(t,g,ManifestSelectionInputV1{VideoID:"v1080"});if p.Container!="mp4"{t.Fatal("h265+AAC should be MP4 compatible")}}
func TestMP04SEL07StaleAndProtectedRefused(t *testing.T){g:=mp04Fixture();mp04Reject(t,g,ManifestSelectionInputV1{VideoID:"gone"});mp04Reject(t,g,ManifestSelectionInputV1{VideoID:"v720",AudioID:"gone"});g.Protected=true;mp04Reject(t,g,ManifestSelectionInputV1{})}
func TestMP04SEL08NoSilentAudioAndPeriodGates(t *testing.T){g:=mp04Fixture();g.Variants[0].AudioGroup="";g.AudioTracks=nil;p:=mp04Must(t,g,ManifestSelectionInputV1{VideoID:"v720"});if !p.Required.VerifyEmbeddedAudio||!p.Required.Audio {t.Fatal("unproven embedded audio must be required for validation")};g.Protocol="dash";g.Periods=append(g.Periods,ManifestPeriodV1{ID:"period-2"});mp04Reject(t,g,ManifestSelectionInputV1{})}
func TestMP04MUX01NoOptionalRequiredRoleAndNoSecretDiagnostics(t *testing.T){g:=mp04Fixture();p:=mp04Must(t,g,ManifestSelectionInputV1{VideoID:"v720",SubtitlePolicy:"required"});if p.Container!="mkv" {t.Fatalf("required webvtt must not promise MP4, got %s",p.Container)};for _,code:=range p.DiagnosticCodes{if strings.Contains(code,"https")||strings.Contains(code,"token")||strings.Contains(code,"secret"){t.Fatalf("sensitive diagnostic: %s",code)}};mp04Reject(t,g,ManifestSelectionInputV1{VideoID:"v720",SubtitlePolicy:"required",Container:"mp4"});if p.Status!="planned_unverified" || p.ExecutionReady {t.Fatal("never publish on plan")}}
func TestMP04RevisionRejectsMutation(t *testing.T){g:=mp04Fixture();a,_:=ManifestGraphRevision(g);g.Variants[0].URL += "&token=rotated";b,_:=ManifestGraphRevision(g);if a==b||len(a)!=64{t.Fatal("revision must bind transport and graph")}}

package media

// MP04: manifest-bound track selection and required-output contract.
// This plan is read-only. MP05/MP08 must verify and durably publish ALL required
// streams before claiming a Completed artifact. Never log transport URLs.
import (
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "errors"
    "sort"
    "strings"
)

const ManifestSelectionSchemaV1 = 1

var ErrManifestSelection = errors.New("MP04 manifest selection rejected")

type ManifestSelectionInputV1 struct {
    Intent string `json:"intent,omitempty"` // best_video, video_only, audio_only, live_recording
    VideoID string `json:"video_id,omitempty"`
    AudioID string `json:"audio_id,omitempty"`
    SubtitleID string `json:"subtitle_id,omitempty"`
    SubtitlePolicy string `json:"subtitle_policy,omitempty"` // disabled, optional, required
    PreferredAudioLanguages []string `json:"preferred_audio_languages,omitempty"`
    PreferredSubtitleLanguages []string `json:"preferred_subtitle_languages,omitempty"`
    PreferredCodecs []string `json:"preferred_codecs,omitempty"`
    MaxHeight int `json:"max_height,omitempty"`
    Container string `json:"container,omitempty"` // auto, mp4, mkv, webm
}

type ManifestRequiredStreamsV1 struct {
    Video bool `json:"video"`
    Audio bool `json:"audio"`
    Subtitle bool `json:"subtitle"`
    VerifyEmbeddedAudio bool `json:"verify_embedded_audio"`
    VerifyEveryPeriod bool `json:"verify_every_period"`
}

type ManifestSelectionPlanV1 struct {
    SchemaVersion int `json:"schema_version"`
    RootID string `json:"root_id"`
    GraphRevision string `json:"graph_revision"`
    Intent string `json:"intent"`
    VideoID string `json:"video_id,omitempty"`
    AudioID string `json:"audio_id,omitempty"`
    SubtitleID string `json:"subtitle_id,omitempty"`
    VideoURL string `json:"video_url,omitempty"` // only transient JNI reply, never durable log
    AudioURL string `json:"audio_url,omitempty"`
    SubtitleURL string `json:"subtitle_url,omitempty"`
    Container string `json:"container"`
    Required ManifestRequiredStreamsV1 `json:"required"`
    Status string `json:"status"` // planned_unverified; protected/invalid refused as error
    ExecutionReady bool `json:"execution_ready"` // always false before MP05 durability
    DiagnosticCodes []string `json:"diagnostic_codes"` // bounded codes, never URLs
}

// ManifestGraphRevision binds a UI selection to the exact observed manifest
// without disclosing signed URLs in the digest. Any refresh changes the hash.
func ManifestGraphRevision(g ManifestGraphV1) (string, error) {
    if g.SchemaVersion != ManifestGraphSchemaV1 || g.RootID == "" { return "", ErrManifestSelection }
    raw, err := json.Marshal(g)
    if err != nil { return "", ErrManifestSelection }
    h := sha256.Sum256(raw)
    return hex.EncodeToString(h[:]), nil
}

func manifestMatchLanguage(a string, preferences []string) int {
    lang := strings.ToLower(strings.TrimSpace(a))
    for i,p := range preferences {
        wanted := strings.ToLower(strings.TrimSpace(p))
        if lang != "" && wanted != "" && (lang == wanted || strings.Split(lang,"-")[0] == strings.Split(wanted,"-")[0]) { return i }
    }
    return len(preferences)+1
}
func manifestCodecRank(codecs []string, prefs []string) int {
    for i,p := range prefs {
        for _,v := range codecs { if strings.HasPrefix(strings.ToLower(v),strings.ToLower(strings.TrimSpace(p))) { return i } }
    }
    return len(prefs)+1
}
func manifestContainerCompatible(c string, codecs []string, subtitle bool) bool {
    if subtitle && c == "mp4" { return false } // explicit subtitle evidence needs verified mux route
    for _, raw := range codecs {
        token:= strings.ToLower(strings.TrimSpace(strings.Split(raw,".")[0]))
        switch c {
        case "mp4": if token!="avc1" && token!="avc3" && token!="h264" && token!="hev1" && token!="hvc1" && token!="hevc" && token!="h265" && token!="av01" && token!="mp4a" && token!="aac" && token!="ac-3" && token!="ec-3" { return false }
        case "webm": if token!="vp8" && token!="vp9" && token!="vp09" && token!="av01" && token!="opus" && token!="vorbis" { return false }
        case "mkv": // open generic Matroska container; codec-specific mux remains gated in MP08
        default: return false
        }
    }
    return true
}

// SelectManifestGraph creates ONE deterministic, testable selection intent.
// It refuses DRM, wrong rendition groups, unknown/stale explicit IDs, and
// incomplete mandatory audio. It never silently substitutes another track.
func SelectManifestGraph(g ManifestGraphV1, req ManifestSelectionInputV1) (ManifestSelectionPlanV1, error) {
    fail:=func()(ManifestSelectionPlanV1,error){return ManifestSelectionPlanV1{},ErrManifestSelection}
    if g.SchemaVersion!=ManifestGraphSchemaV1 || g.RootID=="" || g.DownloadReady || g.Protected || (g.Protocol!="hls" && g.Protocol!="dash") {return fail()}
    if len(g.Variants)+len(g.AudioTracks)+len(g.SubtitleTracks)>512 {return fail()}
    revision,err:=ManifestGraphRevision(g);if err!=nil{return fail()}
    intent:=req.Intent;if intent=="" {intent="best_video"}
    switch intent {case "best_video","video_only","audio_only","live_recording":default:return fail()}
    if intent=="live_recording" && g.Kind!="live" && g.Kind!="event" {return fail()}
    policy:=req.SubtitlePolicy;if policy=="" {policy="optional"}
    switch policy {case "optional","required","disabled":default:return fail()}
    if policy=="disabled" && req.SubtitleID!="" {return fail()}
    if req.MaxHeight<0 || req.MaxHeight>16000 || len(req.PreferredAudioLanguages)>16 || len(req.PreferredSubtitleLanguages)>16 || len(req.PreferredCodecs)>16 {return fail()}
    container:=req.Container;if container=="" {container="auto"}
    switch container {case "auto","mp4","mkv","webm":default:return fail()}
    if g.Protocol=="dash" && len(g.Periods)>1 { // MP07 must establish every-period alignment first
        return fail()
    }
    allIDs:=map[string]bool{}
    for _,v:=range g.Variants {if v.ID==""||allIDs[v.ID] {return fail()};allIDs[v.ID]=true}
    for _,t:=range append(append([]ManifestTrackV1{},g.AudioTracks...),g.SubtitleTracks...) {if t.ID==""||allIDs[t.ID] {return fail()};allIDs[t.ID]=true}
    var video *ManifestVariantV1
    if intent!="audio_only" {
        possible:=make([]ManifestVariantV1,0,len(g.Variants))
        for _,v:=range g.Variants {
            if v.Protection!="" && v.Protection!="none" && v.Protection!="clear" && v.Protection!="unresolved" {continue}
            if req.MaxHeight>0 && v.Height>req.MaxHeight {continue}
            if v.ContentKind!="video" && v.ContentKind!="undetermined" {continue}
            possible=append(possible,v)
        }
        sort.SliceStable(possible,func(i,j int)bool{
            a,b:=possible[i],possible[j]
            ra,rb:=manifestCodecRank(a.Codecs,req.PreferredCodecs),manifestCodecRank(b.Codecs,req.PreferredCodecs)
            if ra!=rb && len(req.PreferredCodecs)>0 {return ra<rb}
            if a.Height!=b.Height{return a.Height>b.Height}
            if a.Width!=b.Width{return a.Width>b.Width}
            if a.Bandwidth!=b.Bandwidth{return a.Bandwidth>b.Bandwidth}
            return a.ID<b.ID
        })
        if req.VideoID!="" {for i:=range possible {if possible[i].ID==req.VideoID {video=&possible[i];break}}} else if len(possible)>0 {video=&possible[0]}
        if video==nil{return fail()}
    } else if req.VideoID!="" {return fail()}
    if intent=="video_only" && req.AudioID!="" {return fail()}
    selectedPeriod:="";audioGroup:="";subsGroup:=""
    if video!=nil {selectedPeriod=video.PeriodID;audioGroup=video.AudioGroup;subsGroup=video.SubtitleGroup}
    audioCandidates:=make([]ManifestTrackV1,0)
    if intent!="video_only" {
        for _,a:=range g.AudioTracks {
            if a.Protection!="" && a.Protection!="none" && a.Protection!="clear" && a.Protection!="unresolved" {continue}
            if video!=nil {
                if g.Protocol=="hls" && (audioGroup=="" || a.Group!=audioGroup) {continue}
                if g.Protocol=="dash" && a.PeriodID!=selectedPeriod {continue}
            }
            audioCandidates=append(audioCandidates,a)
        }
    }
    sort.SliceStable(audioCandidates,func(i,j int)bool{
        a,b:=audioCandidates[i],audioCandidates[j]
        la,lb:=manifestMatchLanguage(a.Language,req.PreferredAudioLanguages),manifestMatchLanguage(b.Language,req.PreferredAudioLanguages)
        if la!=lb{return la<lb}
        if a.Default!=b.Default{return a.Default}
        return a.ID<b.ID
    })
    var audio *ManifestTrackV1
    if req.AudioID!="" {for i:=range audioCandidates {if audioCandidates[i].ID==req.AudioID {audio=&audioCandidates[i];break}};if audio==nil{return fail()}} else if len(audioCandidates)>0 {audio=&audioCandidates[0]}
    if intent=="audio_only" && audio==nil {return fail()}
    if video!=nil && audioGroup!="" && audio==nil && intent!="video_only" {return fail()}
    if video==nil && req.SubtitleID!="" && intent=="audio_only" {return fail()}
    subtitleCandidates:=make([]ManifestTrackV1,0)
    if policy!="disabled" {
        for _,s:=range g.SubtitleTracks {
            if s.Protection!="" && s.Protection!="none" && s.Protection!="clear" && s.Protection!="unresolved" {continue}
            if video!=nil {
                if g.Protocol=="hls" && (subsGroup=="" || s.Group!=subsGroup) {continue}
                if g.Protocol=="dash" && s.PeriodID!=selectedPeriod {continue}
            }
            subtitleCandidates=append(subtitleCandidates,s)
        }
    }
    sort.SliceStable(subtitleCandidates,func(i,j int)bool{
        a,b:=subtitleCandidates[i],subtitleCandidates[j]
        la,lb:=manifestMatchLanguage(a.Language,req.PreferredSubtitleLanguages),manifestMatchLanguage(b.Language,req.PreferredSubtitleLanguages)
        if la!=lb{return la<lb}
        if a.Default!=b.Default{return a.Default}
        return a.ID<b.ID
    })
    var subtitle *ManifestTrackV1
    if req.SubtitleID!="" {for i:=range subtitleCandidates {if subtitleCandidates[i].ID==req.SubtitleID {subtitle=&subtitleCandidates[i];break}};if subtitle==nil{return fail()}} else if policy=="required" && len(subtitleCandidates)>0 {subtitle=&subtitleCandidates[0]}
    if policy=="required" && subtitle==nil{return fail()}
    required:=ManifestRequiredStreamsV1{Video:video!=nil,Audio:intent!="video_only",Subtitle:subtitle!=nil,VerifyEveryPeriod:g.Protocol=="dash"}
    codes:=[]string{"selection_bound_to_manifest","durable_fragments_not_qualified"}
    if required.Audio && audio==nil { // No separately proven rendition: do not silently drop audio.
        required.VerifyEmbeddedAudio=true
        codes=append(codes,"embedded_audio_unverified_must_ffprobe")
    }
    codecs:=[]string{}
    if video!=nil {codecs=append(codecs,video.Codecs...)}
    if audio!=nil && audio.Codec!="" {codecs=append(codecs,audio.Codec)}
    if subtitle!=nil && subtitle.Codec!="" {codecs=append(codecs,subtitle.Codec)}
    if container=="auto" {
        if manifestContainerCompatible("mp4",codecs,subtitle!=nil) {container="mp4"} else if manifestContainerCompatible("webm",codecs,subtitle!=nil) {container="webm"} else {container="mkv"}
        if len(codecs)==0 {container="mkv";codes=append(codes,"codecs_unknown_must_ffprobe")}
    } else if !manifestContainerCompatible(container,codecs,subtitle!=nil) {return fail()}
    p:=ManifestSelectionPlanV1{SchemaVersion:ManifestSelectionSchemaV1,RootID:g.RootID,GraphRevision:revision,Intent:intent,Container:container,Required:required,
        Status:"planned_unverified",ExecutionReady:false,DiagnosticCodes:codes}
    if video!=nil {p.VideoID=video.ID;p.VideoURL=video.URL}
    if audio!=nil {p.AudioID=audio.ID;p.AudioURL=audio.URL}
    if subtitle!=nil {p.SubtitleID=subtitle.ID;p.SubtitleURL=subtitle.URL}
    return p,nil
}

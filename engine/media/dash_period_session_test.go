package media

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const mp07MPD = `<MPD type="static" mediaPresentationDuration="PT8S">
<BaseURL>https://cdn.example/dash/</BaseURL>
<Period id="intro" start="PT0S" duration="PT4S">
<AdaptationSet id="video" contentType="video" mimeType="video/mp4">
<SegmentTemplate timescale="1" startNumber="1" initialization="init-$RepresentationID$.mp4" media="$RepresentationID$-$Number$.m4s"><SegmentTimeline><S t="0" d="2" r="1"/></SegmentTimeline></SegmentTemplate>
<Representation id="v1" bandwidth="1000000" codecs="avc1" />
</AdaptationSet>
<AdaptationSet id="audio" contentType="audio" mimeType="audio/mp4" lang="en">
<SegmentTemplate timescale="1" startNumber="1" initialization="init-$RepresentationID$.mp4" media="$RepresentationID$-$Number$.m4s"><SegmentTimeline><S t="0" d="2" r="1"/></SegmentTimeline></SegmentTemplate>
<Representation id="a1" bandwidth="96000" codecs="mp4a.40.2" />
</AdaptationSet>
</Period>
<Period id="scene" start="PT4S" duration="PT4S">
<AdaptationSet id="video" contentType="video" mimeType="video/mp4">
<SegmentTemplate timescale="1" startNumber="3" initialization="init-$RepresentationID$.mp4" media="$RepresentationID$-$Number$.m4s"><SegmentTimeline><S t="0" d="2" r="1"/></SegmentTimeline></SegmentTemplate>
<Representation id="v2" bandwidth="1500000" codecs="avc1" />
</AdaptationSet>
<AdaptationSet id="audio" contentType="audio" mimeType="audio/mp4" lang="en">
<SegmentTemplate timescale="1" startNumber="3" initialization="init-$RepresentationID$.mp4" media="$RepresentationID$-$Number$.m4s"><SegmentTimeline><S t="0" d="2" r="1"/></SegmentTimeline></SegmentTemplate>
<Representation id="a2" bandwidth="128000" codecs="mp4a.40.2" />
</AdaptationSet>
</Period>
</MPD>`

type mp07MemoryFetcher struct {
	objects map[string][]byte
	counts  map[string]int
}

func (f *mp07MemoryFetcher) FetchDASH(_ context.Context, r DASHFetchRequest) (DASHFetchResponse, error) {
	k := string(r.Kind) + " " + r.URI
	f.counts[k]++
	body, ok := f.objects[r.URI]
	if !ok {
		return DASHFetchResponse{}, fmt.Errorf("missing MP07 test object")
	}
	if r.Range != nil {
		if r.Range.Offset < 0 || r.Range.Length <= 0 || r.Range.Offset > int64(len(body)) || r.Range.Length > int64(len(body))-r.Range.Offset {
			return DASHFetchResponse{}, errors.New("bad range")
		}
		body = body[r.Range.Offset : r.Range.Offset+r.Range.Length]
	}
	return DASHFetchResponse{Bytes: append([]byte(nil), body...)}, nil
}
func mp07Fixture() (DASHPeriodRequest, *mp07MemoryFetcher) {
	r := DASHPeriodRequest{MPDURL: "https://cdn.example/root/manifest.mpd", MPDBody: mp07MPD, AttemptGeneration: 1, RequireAudio: true,
		Periods: []DASHPeriodChoice{
			{PeriodID: "intro", Video: DASHTrackSelector{"video", "v1"}, Audio: DASHTrackSelector{"audio", "a1"}},
			{PeriodID: "scene", Video: DASHTrackSelector{"video", "v2"}, Audio: DASHTrackSelector{"audio", "a2"}},
		}}
	f := &mp07MemoryFetcher{objects: map[string][]byte{}, counts: map[string]int{}}
	for _, id := range []string{"v1", "a1", "v2", "a2"} {
		f.objects["https://cdn.example/dash/init-"+id+".mp4"] = []byte("init-" + id)
		ns := []int{1, 2}
		if strings.HasSuffix(id, "2") {
			ns = []int{3, 4}
		}
		for _, n := range ns {
			f.objects[fmt.Sprintf("https://cdn.example/dash/%s-%d.m4s", id, n)] = []byte(fmt.Sprintf("segment-%s-%d", id, n))
		}
	}
	return r, f
}
func mp07Stores(t *testing.T) (*FileFragmentStore, *FileFragmentStore) {
	t.Helper()
	root := t.TempDir()
	v, e := NewFileFragmentStore(filepath.Join(root, "video"), 8<<20)
	if e != nil {
		t.Fatal(e)
	}
	a, e := NewFileFragmentStore(filepath.Join(root, "audio"), 8<<20)
	if e != nil {
		t.Fatal(e)
	}
	return v, a
}
func mp07Reject(t *testing.T, r DASHPeriodRequest) {
	t.Helper()
	if _, e := PlanDASHPeriods(r); !errors.Is(e, ErrDASHPeriodSelection) {
		t.Fatalf("should reject invalid MPD/selection: %v", e)
	}
}

func TestMP07DASH01TwoPeriodsSplitAudioVideoDurable(t *testing.T) {
	r, f := mp07Fixture()
	v, a := mp07Stores(t)
	got, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil || got.Status != "staged" || !got.ReadyForMux || got.DownloadReady || got.Periods != 2 || len(got.Tracks) != 4 {
		t.Fatalf("MP07 DASH01 %+v %v", got, e)
	}
	for _, tr := range got.Tracks {
		if tr.Expected != 2 || tr.Verified != 2 || !tr.InitVerified || tr.Missing != 0 || len(tr.ArtifactRefs) != 2 {
			t.Fatalf("missing durable period track %+v", tr)
		}
	}
	if len(v.CommittedRecords()) != 8 || len(a.CommittedRecords()) != 8 {
		t.Fatalf("expected 4 media + 4 init receipts for each role got %d %d", len(v.CommittedRecords()), len(a.CommittedRecords()))
	}
}
func TestMP07DASH02RestartDoesNotRefetch(t *testing.T) {
	r, f := mp07Fixture()
	v, a := mp07Stores(t)
	_, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil {
		t.Fatal(e)
	}
	r.AttemptGeneration = 2
	before := 0
	for _, n := range f.counts {
		before += n
	}
	res, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil || res.Status != "staged" {
		t.Fatal(res, e)
	}
	after := 0
	for _, n := range f.counts {
		after += n
	}
	if after != before {
		t.Fatal("new fetch after restart")
	}
	for _, tr := range res.Tracks {
		if tr.Resumed != tr.Expected || tr.Verified != tr.Expected {
			t.Fatal("durable part not reattached", tr)
		}
	}
}
func TestMP07DASH03WrongPeriodOrderRejected(t *testing.T) {
	r, _ := mp07Fixture()
	r.Periods[0], r.Periods[1] = r.Periods[1], r.Periods[0]
	mp07Reject(t, r)
}
func TestMP07DASH04PeriodGapOverlapRejected(t *testing.T) {
	for _, tt := range []struct{ old, new string }{{`start="PT4S"`, `start="PT5S"`}, {`start="PT4S"`, `start="PT3S"`}} {
		r, _ := mp07Fixture()
		r.MPDBody = strings.Replace(r.MPDBody, tt.old, tt.new, 1)
		mp07Reject(t, r)
	}
}
func TestMP07DASH05ExactRepresentationPerPeriod(t *testing.T) {
	r, _ := mp07Fixture()
	p, e := PlanDASHPeriods(r)
	if e != nil {
		t.Fatal(e)
	}
	if p.Periods[0].Tracks[0].RepresentationID != "v1" || p.Periods[1].Tracks[0].RepresentationID != "v2" || p.Periods[1].StartMS != 4000 {
		t.Fatal("period-specific representation lost")
	}
	r.Periods[1].Video.RepresentationID = "v1"
	mp07Reject(t, r)
}
func TestMP07DASH06MissingAudioRejected(t *testing.T) {
	r, _ := mp07Fixture()
	r.Periods[1].Audio = DASHTrackSelector{}
	mp07Reject(t, r)
}
func TestMP07DASH07ProtectedContentRejected(t *testing.T) {
	r, _ := mp07Fixture()
	r.MPDBody = strings.Replace(r.MPDBody, `<Representation id="v2"`, `<ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"/><Representation id="v2"`, 1)
	mp07Reject(t, r)
}
func TestMP07DASH08MP4MissingInitRejected(t *testing.T) {
	r, _ := mp07Fixture()
	r.MPDBody = strings.Replace(r.MPDBody, `initialization="init-$RepresentationID$.mp4"`, ``, 1)
	mp07Reject(t, r)
}
func TestMP07DASH09InitFetchFailureIsPartial(t *testing.T) {
	r, f := mp07Fixture()
	delete(f.objects, "https://cdn.example/dash/init-a2.mp4")
	v, a := mp07Stores(t)
	result, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil || result.Status != "partial" || result.ReadyForMux || result.DownloadReady {
		t.Fatalf("phantom init success %+v %v", result, e)
	}
	if result.Tracks[len(result.Tracks)-1].Missing != 2 {
		t.Fatalf("init not counted missing %+v", result.Tracks)
	}
}
func TestMP07DASH10CorruptPriorReceiptFailsClosed(t *testing.T) {
	r, f := mp07Fixture()
	v, a := mp07Stores(t)
	_, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil {
		t.Fatal(e)
	}
	var victim FragmentRecord
	for _, rec := range v.CommittedRecords() {
		if rec.Role == "video" {
			victim = rec
			break
		}
	}
	if victim.ID == "" {
		t.Fatal("fixture missing media")
	}
	path, err := v.fullPath(victim.LocalArtifactRef)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, []byte("corrupted"), 0600); err != nil {
		t.Fatal(err)
	}
	result, err := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if err == nil && (result.ReadyForMux || result.DownloadReady || result.Status != "partial") {
		t.Fatalf("corrupt media acknowledged: %+v %v", result, err)
	}
}
func TestMP07DASH11BoundedDynamicNeverReady(t *testing.T) {
	r, f := mp07Fixture()
	r.MPDBody = strings.Replace(r.MPDBody, `type="static" mediaPresentationDuration="PT8S"`, `type="dynamic" minimumUpdatePeriod="PT2S"`, 1)
	r.DynamicPollBound = 2
	v, a := mp07Stores(t)
	got, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil || got.Status != "bounded_live_staged" || got.ReadyForMux || got.DownloadReady {
		t.Fatalf("dynamic falsely ready %+v %v", got, e)
	}
	r.DynamicPollBound = 0
	mp07Reject(t, r)
}
func TestMP07DASH12DuplicatePeriodIDRejected(t *testing.T) {
	r, _ := mp07Fixture()
	r.MPDBody = strings.Replace(r.MPDBody, `id="scene"`, `id="intro"`, 1)
	mp07Reject(t, r)
}
func TestMP07DASH13MediaFetchFailureCannotPublish(t *testing.T) {
	r, f := mp07Fixture()
	delete(f.objects, "https://cdn.example/dash/v2-4.m4s")
	v, a := mp07Stores(t)
	got, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil || got.ReadyForMux || got.Status != "partial" || got.DownloadReady {
		t.Fatalf("failed segment marked ready %+v %v", got, e)
	}
}
func TestMP07DASH14EmbeddedAudioProofRequired(t *testing.T) {
	r, f := mp07Fixture()
	r.RequireAudio = false
	r.Periods[0].Audio = DASHTrackSelector{}
	r.Periods[1].Audio = DASHTrackSelector{}
	v, a := mp07Stores(t)
	p, e := PlanDASHPeriods(r)
	if e != nil || !p.NeedsEmbeddedAudioProof {
		t.Fatal(p, e)
	}
	got, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil || got.Status != "staged" || got.ReadyForMux || got.DownloadReady || !got.NeedsEmbeddedAudioProof {
		t.Fatal(got, e)
	}
}
func TestMP07DASH15MissingAudioSinkFailsBeforeNetwork(t *testing.T) {
	r, f := mp07Fixture()
	v, _ := mp07Stores(t)
	_, e := ExecuteDASHPeriods(context.Background(), r, f, v, nil, nil)
	if !errors.Is(e, ErrDASHPeriodIncomplete) || len(f.counts) != 0 {
		t.Fatalf("missing sink attempted fetch %v %+v", e, f.counts)
	}
}
func TestMP07DASH16IdentityAndReceiptExcludeRawURL(t *testing.T) {
	r, f := mp07Fixture()
	r.MPDURL = "https://cdn.example/root/manifest.mpd?token=secret"
	v, a := mp07Stores(t)
	got, e := ExecuteDASHPeriods(context.Background(), r, f, v, a, nil)
	if e != nil {
		t.Fatal(e)
	}
	for _, tr := range got.Tracks {
		for _, ref := range tr.ArtifactRefs {
			if strings.Contains(ref, "cdn.example") || strings.Contains(ref, "secret") || strings.Contains(ref, "https://") {
				t.Fatal("raw credential leaked into artifact ref")
			}
		}
	}
}

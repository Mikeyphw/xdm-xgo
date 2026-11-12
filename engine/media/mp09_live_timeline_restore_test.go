package media

import (
	"errors"
	"testing"
)

func mp09TimelineRecord(id, key string, protocol FragmentProtocol) FragmentRecord {
	return FragmentRecord{ID: id, Role: "media", State: FragmentCommitted, ExpectedLength: 17,
		AttemptGeneration: 1, Identity: FragmentIdentity{Protocol: protocol, TimelineKey: key, ResourceID: "resource_123456789"},
		DurableBytesWritten: true, Hash: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", LocalArtifactRef: "parts/fragment"}
}
func TestMP09LIVE03RestoredHLSHighWater(t *testing.T) {
	r1 := mp09TimelineRecord("f1", "hls:0:9", FragmentProtocolHLS)
	r2 := mp09TimelineRecord("f2", "hls:0:10", FragmentProtocolHLS)
	store := &FileFragmentStore{records: []FragmentRecord{r1, r2}}
	engine := &LivePollEngine{session: &LiveSession{generation: 1}, store: store, spec: LivePollSpec{Protocol: FragmentProtocolHLS}}
	if e := engine.MP09RestoreVerifiedTimeline([]FragmentRecord{r2, r1}); e != nil {
		t.Fatal(e)
	}
	if !engine.seenHLS || engine.lastHLSSeq != 10 {
		t.Fatal("high-water not restored")
	}
}
func TestMP09LIVE04RestoredDASHHighWater(t *testing.T) {
	r1 := mp09TimelineRecord("f1", "dash:p0:a:v1:0:99", FragmentProtocolDASH)
	r2 := mp09TimelineRecord("f2", "dash:p0:a:v1:5000:100", FragmentProtocolDASH)
	store := &FileFragmentStore{records: []FragmentRecord{r1, r2}}
	engine := &LivePollEngine{session: &LiveSession{generation: 1}, store: store,
		spec: LivePollSpec{Protocol: FragmentProtocolDASH, DASHRepresentationID: "v1"}}
	if e := engine.MP09RestoreVerifiedTimeline([]FragmentRecord{r1, r2}); e != nil {
		t.Fatal(e)
	}
	if engine.lastDASH["p0/a/v1"] != 100 {
		t.Fatal("DASH sequence not restored")
	}
}
func TestMP09LIVE05RestoredTimelineRejectsGapsAndWrongGeneration(t *testing.T) {
	for name, mutate := range map[string]func(*FragmentRecord){
		"gap":              func(r *FragmentRecord) { r.Identity.TimelineKey = "hls:0:11" },
		"wrong_generation": func(r *FragmentRecord) { r.AttemptGeneration = 2 },
		"wrong_protocol":   func(r *FragmentRecord) { r.Identity.Protocol = FragmentProtocolDASH },
		"not_durable":      func(r *FragmentRecord) { r.DurableBytesWritten = false },
	} {
		t.Run(name, func(t *testing.T) {
			r1 := mp09TimelineRecord("f1", "hls:0:9", FragmentProtocolHLS)
			r2 := mp09TimelineRecord("f2", "hls:0:10", FragmentProtocolHLS)
			mutate(&r2)
			store := &FileFragmentStore{records: []FragmentRecord{r1, r2}}
			engine := &LivePollEngine{session: &LiveSession{generation: 1}, store: store, spec: LivePollSpec{Protocol: FragmentProtocolHLS}}
			if e := engine.MP09RestoreVerifiedTimeline([]FragmentRecord{r1, r2}); !errors.Is(e, ErrLivePollIncomplete) {
				t.Fatalf("unsafe restored timeline accepted: %v", e)
			}
		})
	}
}

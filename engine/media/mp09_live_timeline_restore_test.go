package media

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"testing"
)

// Use the actual MP05 file-backed journal; a map-only stub would not prove
// SHA-256 readback or correct restoration from committed fragments.
func mp09TimelineRecord(key string, protocol FragmentProtocol) FragmentRecord {
	return FragmentRecord{
		Role: "media", AttemptGeneration: 1,
		Identity: FragmentIdentity{Protocol: protocol, TimelineKey: key, ResourceID: "resource_123456789"},
	}
}

func mp09CommittedTimeline(t *testing.T, inputs ...FragmentRecord) (*FileFragmentStore, []FragmentRecord) {
	t.Helper()
	store, err := NewFileFragmentStore(filepath.Join(t.TempDir(), "mp09"), 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	records := make([]FragmentRecord, 0, len(inputs))
	for i, input := range inputs {
		payload := []byte(fmt.Sprintf("mp09-verified-timeline-fragment-%d", i))
		verified, err := store.WriteAndCommitFragment(context.Background(), input, payload)
		if err != nil {
			t.Fatalf("committing actual fragment %d: %v", i, err)
		}
		if err := store.VerifyCommitted(verified); err != nil {
			t.Fatalf("readback %d: %v", i, err)
		}
		records = append(records, verified)
	}
	return store, records
}

func TestMP09LIVE03RestoredHLSHighWater(t *testing.T) {
	store, records := mp09CommittedTimeline(t,
		mp09TimelineRecord("hls:0:9", FragmentProtocolHLS),
		mp09TimelineRecord("hls:0:10", FragmentProtocolHLS),
	)
	engine := &LivePollEngine{session: &LiveSession{generation: 1}, store: store, spec: LivePollSpec{Protocol: FragmentProtocolHLS}}
	if err := engine.MP09RestoreVerifiedTimeline([]FragmentRecord{records[1], records[0]}); err != nil {
		t.Fatal(err)
	}
	if !engine.seenHLS || engine.lastHLSSeq != 10 {
		t.Fatal("HLS high-water not restored")
	}
}

func TestMP09LIVE04RestoredDASHHighWater(t *testing.T) {
	store, records := mp09CommittedTimeline(t,
		mp09TimelineRecord("dash:p0:a:v1:0:99", FragmentProtocolDASH),
		mp09TimelineRecord("dash:p0:a:v1:5000:100", FragmentProtocolDASH),
	)
	engine := &LivePollEngine{session: &LiveSession{generation: 1}, store: store,
		spec: LivePollSpec{Protocol: FragmentProtocolDASH, DASHRepresentationID: "v1"}}
	if err := engine.MP09RestoreVerifiedTimeline(records); err != nil {
		t.Fatal(err)
	}
	if engine.lastDASH["p0/a/v1"] != 100 {
		t.Fatal("DASH high-water not restored")
	}
}

func TestMP09LIVE05RestoredTimelineRejectsGapsAndWrongGeneration(t *testing.T) {
	cases := []struct {
		name              string
		mutate            func(*FragmentRecord)
		mutateAfterCommit bool
	}{
		{"gap", func(r *FragmentRecord) { r.Identity.TimelineKey = "hls:0:11" }, false},
		{"wrong_generation", func(r *FragmentRecord) { r.AttemptGeneration = 2 }, false},
		{"wrong_protocol", func(r *FragmentRecord) { r.Identity.Protocol = FragmentProtocolDASH }, false},
		{"not_durable", func(r *FragmentRecord) { r.DurableBytesWritten = false }, true},
		{"forged_hash", func(r *FragmentRecord) { r.Hash = "sha256:" + fmt.Sprintf("%064x", 8) }, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			first := mp09TimelineRecord("hls:0:9", FragmentProtocolHLS)
			second := mp09TimelineRecord("hls:0:10", FragmentProtocolHLS)
			if !tc.mutateAfterCommit {
				tc.mutate(&second)
			}
			store, records := mp09CommittedTimeline(t, first, second)
			if tc.mutateAfterCommit {
				tc.mutate(&records[1])
			}
			engine := &LivePollEngine{session: &LiveSession{generation: 1}, store: store,
				spec: LivePollSpec{Protocol: FragmentProtocolHLS}}
			if err := engine.MP09RestoreVerifiedTimeline(records); !errors.Is(err, ErrLivePollIncomplete) {
				t.Fatalf("unsafe restored timeline accepted: %v", err)
			}
		})
	}
}

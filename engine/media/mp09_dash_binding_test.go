package media

import (
	"errors"
	"testing"
)

func mp09FixtureDASHBinding() (ManifestGraphV1, ManifestSelectionPlanV1, DASHManifest) {
	root := "https://media.example/live.mpd"
	vurl := "https://media.example/video/"
	aurl := "https://media.example/audio/"
	vid := mp03Identity("video", "p0|v|v360")
	aid := mp03Identity("track", "p0|a|a-en")
	graph := ManifestGraphV1{SchemaVersion: ManifestGraphSchemaV1, Protocol: "dash", Kind: "live", RootURL: root,
		Periods:     []ManifestPeriodV1{{ID: "p0"}},
		Variants:    []ManifestVariantV1{{ID: vid, URL: vurl, Protection: "clear"}},
		AudioTracks: []ManifestTrackV1{{ID: aid, URL: aurl, Protection: "clear"}}}
	plan := ManifestSelectionPlanV1{Intent: "live_recording", Container: "mp4", Status: "planned_unverified", VideoID: vid, AudioID: aid,
		Required: ManifestRequiredStreamsV1{Video: true, Audio: true, VerifyEveryPeriod: true}}
	mpd := DASHManifest{Type: DASHDynamic, Periods: []DASHPeriod{{ID: "p0", AdaptationSets: []DASHAdaptationSet{
		{ID: "v", Protection: DASHProtectionClear, Representations: []DASHRepresentation{{ID: "v360", BaseURL: vurl, MimeType: "video/mp4", Protection: DASHProtectionClear}}},
		{ID: "a", Protection: DASHProtectionClear, Representations: []DASHRepresentation{{ID: "a-en", BaseURL: aurl, MimeType: "audio/mp4", Protection: DASHProtectionClear}}},
	}}}}
	return graph, plan, mpd
}
func TestMP09LIVE01DASHExactRepresentationIDs(t *testing.T) {
	g, p, m := mp09FixtureDASHBinding()
	out, e := MP09MapDASHIDs(g, p, m)
	if e != nil || out.VideoRepresentationID != "v360" || out.AudioRepresentationID != "a-en" || out.ManifestURL != g.RootURL {
		t.Fatalf("incorrect binding %+v %v", out, e)
	}
	if out.VideoRepresentationID == p.VideoID || out.AudioRepresentationID == p.AudioID {
		t.Fatal("synthetic MP03 ID reached native poller")
	}
}
func TestMP09LIVE02DASHFailClosedBindingMatrix(t *testing.T) {
	for name, mutate := range map[string]func(*ManifestGraphV1, *ManifestSelectionPlanV1, *DASHManifest){
		"drm":         func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) { g.Protected = true },
		"not-dynamic": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) { m.Type = DASHStatic },
		"repeat-native-id": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) {
			m.Periods[0].AdaptationSets[1].Representations[0].ID = "v360"
		},
		"source-changed": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) {
			m.Periods[0].AdaptationSets[0].Representations[0].BaseURL = "https://evil.invalid/file"
		},
		"wrong-video": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) {
			p.VideoID = "not-a-matched-graph-option"
		},
		"no-audio": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) {
			m.Periods[0].AdaptationSets = m.Periods[0].AdaptationSets[:1]
		},
		"protected-representation": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) {
			m.Periods[0].AdaptationSets[0].Representations[0].Protection = DASHProtectionWidevine
		},
		"period-mismatch": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) { m.Periods[0].ID = "new-period" },
		"multi-period": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) {
			m.Periods = append(m.Periods, DASHPeriod{ID: "p1"})
		},
		"embedded-audio": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) {
			p.Required.VerifyEmbeddedAudio = true
		},
		"missing-period-proof": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) {
			p.Required.VerifyEveryPeriod = false
		},
		"wrong-container": func(g *ManifestGraphV1, p *ManifestSelectionPlanV1, m *DASHManifest) { p.Container = "webm" },
	} {
		t.Run(name, func(t *testing.T) {
			g, p, m := mp09FixtureDASHBinding()
			mutate(&g, &p, &m)
			if _, e := MP09MapDASHIDs(g, p, m); !errors.Is(e, ErrMP09DASHBinding) {
				t.Fatalf("unsafe binding accepted %s: %v", name, e)
			}
		})
	}
}

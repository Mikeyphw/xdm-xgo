package media

// MP09 restores the P02 live-poll high-water marks using actual MP05
// verified receipts. A restart can never reset sequence-gap detection.
import (
	"sort"
	"strconv"
	"strings"
)

func (e *LivePollEngine) MP09RestoreVerifiedTimeline(records []FragmentRecord) error {
	if e == nil || len(records) > 4096 {
		return ErrLivePollInvalid
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	parsed := make([]FragmentRecord, 0, len(records))
	dashLast := make(map[string]int64)
	var hlsLast int64
	var hlsSeen bool
	for _, rec := range records {
		if rec.Role == "init" {
			continue
		}
		if rec.Identity.Protocol != e.spec.Protocol || rec.State != FragmentCommitted ||
			!rec.DurableBytesWritten || rec.AttemptGeneration != e.session.generation ||
			e.store.VerifyCommitted(rec) != nil {
			return ErrLivePollIncomplete
		}
		key := rec.Identity.TimelineKey
		parts := strings.Split(key, ":")
		switch e.spec.Protocol {
		case FragmentProtocolHLS:
			if len(parts) != 3 || parts[0] != "hls" {
				return ErrLivePollIncomplete
			}
			disc, err := strconv.ParseInt(parts[1], 10, 64)
			seq, seqErr := strconv.ParseInt(parts[2], 10, 64)
			if err != nil || seqErr != nil || disc < 0 || seq < 0 {
				return ErrLivePollIncomplete
			}
			if !hlsSeen || seq > hlsLast {
				hlsLast = seq
			}
			hlsSeen = true
		case FragmentProtocolDASH:
			if len(parts) != 6 || parts[0] != "dash" || parts[1] == "" || parts[2] == "" || parts[3] != e.spec.DASHRepresentationID {
				return ErrLivePollIncomplete
			}
			number, err := strconv.ParseInt(parts[5], 10, 64)
			if err != nil || number < 0 {
				return ErrLivePollIncomplete
			}
			identity := parts[1] + "/" + parts[2] + "/" + parts[3]
			if old, ok := dashLast[identity]; !ok || number > old {
				dashLast[identity] = number
			}
		default:
			return ErrLivePollSelection
		}
		parsed = append(parsed, rec)
	}
	sort.Slice(parsed, func(i, j int) bool {
		return mp09Earlier(parsed[i].Identity.TimelineKey, parsed[j].Identity.TimelineKey)
	})
	if len(parsed) > 0 && mp09Continuous(parsed) != nil {
		return ErrLivePollIncomplete
	}
	e.lastHLSSeq = hlsLast
	e.seenHLS = hlsSeen
	if e.spec.Protocol == FragmentProtocolDASH {
		e.lastDASH = dashLast
	}
	return nil
}

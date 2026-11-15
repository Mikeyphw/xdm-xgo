package runtime

import (
    "encoding/json"
    "errors"
    "regexp"
)

var errMP09RecoveryInventory = errors.New("MP09 recovery inventory refused")
var mp09RecoveryID = regexp.MustCompile(`^fragment_[0-9a-f]{64}$`)
var mp09RecoveryHash = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)

// mp09ReviewRecoveryInventory checks bounded, readback-verified Android
// inventory receipts. Never returns URLs, paths, identities or hashes to UI.
func mp09ReviewRecoveryInventory(payload []byte) (int, error) {
    if len(payload) == 0 || len(payload) > 512<<10 { return 0, errMP09RecoveryInventory }
    var v struct {
        OK bool `json:"ok"`
        Records []struct {
            FragmentID string `json:"fragment_id"`
            Hash string `json:"hash"`
            Generation int64 `json:"generation"`
            Length int64 `json:"length"`
            TrackRole string `json:"track_role"`
        } `json:"records"`
    }
    if json.Unmarshal(payload, &v) != nil || !v.OK || v.Records == nil || len(v.Records) > 4096 {
        return 0, errMP09RecoveryInventory
    }
    seen := make(map[string]bool, len(v.Records))
    for _, rec := range v.Records {
        if !mp09RecoveryID.MatchString(rec.FragmentID) || !mp09RecoveryHash.MatchString(rec.Hash) ||
           rec.Generation <= 0 || rec.Length <= 0 || rec.Length > 2<<20 ||
           (rec.TrackRole != "video" && rec.TrackRole != "audio") || seen[rec.FragmentID] {
            return 0, errMP09RecoveryInventory
        }
        seen[rec.FragmentID] = true
    }
    return len(v.Records), nil
}

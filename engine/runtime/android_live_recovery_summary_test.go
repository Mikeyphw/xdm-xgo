package runtime

import (
    "strings"
    "testing"
)

func TestMP09HF04RecoveryInventorySafeBounds(t *testing.T) {
    id := "fragment_" + strings.Repeat("a", 64)
    hash := "sha256:" + strings.Repeat("b",64)
    valid := `{"ok":true,"records":[{"fragment_id":"`+id+`","hash":"`+hash+`","generation":1,"length":123,"track_role":"video"}]}`
    n,e := mp09ReviewRecoveryInventory([]byte(valid))
    if e != nil || n != 1 { t.Fatalf("valid recovery inventory refused: %d %v",n,e) }
    for _,raw := range []string{
        `{"records":[{"fragment_id":"bad"}]}`,
        strings.Replace(valid,`"track_role":"video"`,`"track_role":"key"`,1),
        strings.Replace(valid,`"generation":1`,`"generation":0`,1),
        strings.Replace(valid,`"length":123`,`"length":99999999`,1),
        strings.Replace(valid,`"hash":"`+hash+`"`,`"hash":"unsafe"`,1),
        strings.Replace(valid,`}]}`,`},{"fragment_id":"`+id+`","hash":"`+hash+`","generation":1,"length":123,"track_role":"video"}]}`,1),
        strings.Repeat("x", 513<<10),
    } {if n,e := mp09ReviewRecoveryInventory([]byte(raw)); e == nil {t.Fatalf("unsafe inventory accepted: %d",n)}}
}

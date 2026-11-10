package runtime

import (
    "encoding/base64"
    "encoding/json"
    "strings"
    "testing"

    "github.com/subhra74/xdm/engine/media"
)

func TestMP03AndroidManifestWire(t *testing.T) {
    wire := map[string]any{"body_base64":base64.StdEncoding.EncodeToString([]byte("#EXTM3U\n#EXT-X-ENDLIST\n")),
        "final_url":"https://cdn.example/media?sig=secret", "redirects": []string{},
        "content_type":"application/vnd.apple.mpegurl", "expires_at_epoch_ms":int64(1800000000000)}
    raw,_:=json.Marshal(wire)
    response,err:=decodeAndroidManifestFetch(raw)
    if err!=nil || string(response.Body)!="#EXTM3U\n#EXT-X-ENDLIST\n" || response.ExpiresAt.IsZero(){t.Fatal("bounded authorized wire rejected")}
    if _,err:=decodeAndroidManifestFetch([]byte(`{"body_base64":"bogus!!"}`));err==nil {t.Fatal("invalid base64 accepted")}
    if _,err:=decodeAndroidManifestFetch([]byte(`{"body_base64":"`+strings.Repeat("A",base64.StdEncoding.EncodedLen(mp03AndroidMaximumBody)+4)+`"}`));err==nil {t.Fatal("oversized reply accepted")}
    wire["redirects"]=[]string{"a","b","c","d","e","f"};raw,_=json.Marshal(wire)
    if _,err:=decodeAndroidManifestFetch(raw);err==nil {t.Fatal("unbounded redirects accepted")}
}
func TestMP03AndroidManifestOrigin(t *testing.T) {
    for _,raw:=range []string{"file:///data/private", "https://user:pass@cdn.example/a", "https://cdn.example/a#fragment","javascript:alert(1)"} {
        if _,err:=androidManifestOrigin(raw);err==nil{t.Fatalf("unsafe URL accepted %q",raw)}
    }
    x,err:=androidManifestOrigin("https://CDN.example/video?sig=private")
    if err!=nil || x!="https://cdn.example" {t.Fatal("origin mismatch")}
    if _,err:=decodeAndroidManifestFetch(nil);err!=media.ErrManifestInvalid {t.Fatal("empty platform reply not rejected")}
}

package media

import (
    "bytes"
    "context"
    "os"
    "path/filepath"
    "strings"
    "testing"
)

func mp06HF02Store(t *testing.T) *FileFragmentStore {
    t.Helper()
    store, err := NewFileFragmentStore(filepath.Join(t.TempDir(), "fragments"), 1<<20)
    if err != nil { t.Fatal(err) }
    return store
}

func mp06HF02Execute(t *testing.T, body string, objects map[string][]byte) (HLSExecutionResult, *FileFragmentStore, *memoryHLSFetcher) {
    t.Helper()
    fetcher := newMemoryHLSFetcher(objects)
    executor, err := NewHLSExecutor(fetcher, nil)
    if err != nil { t.Fatal(err) }
    store := mp06HF02Store(t)
    if err := executor.BindDurableStore(store); err != nil { t.Fatal(err) }
    result, err := executor.Execute(context.Background(), HLSExecutionPlan{
        BaseURL: "https://cdn.example/vod/list.m3u8", Playlists: []string{body}, AttemptGeneration: 1,
    })
    if err != nil { t.Fatal(err) }
    return result, store, fetcher
}

func mp06HF02OnePart(prefix string) string {
    return "#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-MEDIA-SEQUENCE:1\n" + prefix +
        "#EXTINF:4,\nsegment.ts\n#EXT-X-ENDLIST\n"
}

func TestMP06HF02MapBeforeKeyKeepsInitClear(t *testing.T) {
    p, err := ParseHLSPlaylist("https://cdn.example/vod/list.m3u8", mp06HF02OnePart(
        "#EXT-X-MAP:URI=\"init.mp4\"\n#EXT-X-KEY:METHOD=AES-128,URI=\"segment.key\"\n"))
    if err != nil { t.Fatal(err) }
    if len(p.Segments) != 1 || p.Segments[0].Map == nil || p.Segments[0].Map.Key != nil ||
       p.Segments[0].Key == nil || p.Segments[0].Key.Method != HLSProtectionAES128 {
        t.Fatalf("map-before-key incorrectly inherited later segment key: %+v", p.Segments)
    }
}

func TestMP06HF02EncryptedInitRequiresExplicitIV(t *testing.T) {
    manifest := mp06HF02OnePart("#EXT-X-KEY:METHOD=AES-128,URI=\"init.key\"\n"+
        "#EXT-X-MAP:URI=\"init.bin\"\n#EXT-X-KEY:METHOD=NONE\n")
    req := HLSVODRequest{MasterURL:"https://cdn.example/vod/master.m3u8", MasterBody:mp06SingleMaster,
        VideoURI:"https://cdn.example/vod/video.m3u8", VideoBody:manifest, AttemptGeneration:1}
    if _, err := PlanHLSVOD(req); err == nil { t.Fatal("planner admitted encrypted map with missing IV") }
    result, store, fetcher := mp06HF02Execute(t, manifest, map[string][]byte{
        "https://cdn.example/vod/segment.ts": []byte("clearsegment"),
    })
    if result.Status != HLSExecutionFailed || result.Unsupported != 1 || len(store.CommittedRecords()) != 0 {
        t.Fatalf("missing init IV passed: %+v",result)
    }
    if fetcher.counts["init_map https://cdn.example/vod/init.bin"] != 0 { t.Fatal("invalid map was fetched") }
}

func TestMP06HF02EncryptedInitDecryptsWithDeclarationKey(t *testing.T) {
    key := []byte("0123456789abcdef")
    plain := []byte("fmp4-clear-initialization")
    manifest := mp06HF02OnePart("#EXT-X-KEY:METHOD=AES-128,URI=\"init.key\",IV=0x00000000000000000000000000000001\n"+
        "#EXT-X-MAP:URI=\"init.bin\"\n#EXT-X-KEY:METHOD=NONE\n")
    result, store, fetcher := mp06HF02Execute(t,manifest,map[string][]byte{
        "https://cdn.example/vod/init.key": key,
        "https://cdn.example/vod/init.bin": encryptHLSForTest(t, plain, key, 1),
        "https://cdn.example/vod/segment.ts": []byte("clearsegment"),
    })
    if result.Status != HLSExecutionCompleted || result.Completed != 1 { t.Fatalf("bad encrypted init map: %+v",result) }
    if fetcher.counts["key https://cdn.example/vod/init.key"] != 1 { t.Fatal("init key not used") }
    var found bool
    for _, rec := range store.CommittedRecords() {
        if rec.Role != "init" { continue }
        data,err:=store.ReadVerified(rec.Identity)
        if err != nil || !bytes.Equal(data,plain) { t.Fatalf("init persisted without decrypt: %v",err) }
        if !strings.HasPrefix(rec.Identity.EncryptionID,"aes-128:hls-init-key_") { t.Fatalf("missing opaque init key: %s",rec.Identity.EncryptionID) }
        found=true
    }
    if !found { t.Fatal("init map durable receipt absent") }
}

func TestMP06HF02KeyRotationDoesNotRebindInit(t *testing.T) {
    first:=[]byte("0123456789abcdef")
    second:=[]byte("fedcba9876543210")
    initPlain:=[]byte("rotating-key-clear-init")
    segPlain:=[]byte("rotating-key-clear-segment")
    manifest:=mp06HF02OnePart("#EXT-X-KEY:METHOD=AES-128,URI=\"map.key\",IV=0x00000000000000000000000000000001\n"+
        "#EXT-X-MAP:URI=\"init.bin\"\n"+
        "#EXT-X-KEY:METHOD=AES-128,URI=\"segment.key\",IV=0x00000000000000000000000000000002\n")
    result,store,fetcher:=mp06HF02Execute(t,manifest,map[string][]byte{
        "https://cdn.example/vod/map.key":first,
        "https://cdn.example/vod/segment.key":second,
        "https://cdn.example/vod/init.bin":encryptHLSForTest(t,initPlain,first,1),
        "https://cdn.example/vod/segment.ts":encryptHLSForTest(t,segPlain,second,2),
    })
    if result.Status!=HLSExecutionCompleted || result.Completed!=1 {t.Fatalf("rotated keys not separated: %+v",result)}
    if fetcher.counts["key https://cdn.example/vod/map.key"]!=1 || fetcher.counts["key https://cdn.example/vod/segment.key"]!=1 {t.Fatal("wrong key selected")}
    for _,rec:=range store.CommittedRecords(){
        data,err:=store.ReadVerified(rec.Identity);if err!=nil{t.Fatal(err)}
        switch rec.Role{case "init":if !bytes.Equal(data,initPlain){t.Fatal("init wrong key")};case "media":if !bytes.Equal(data,segPlain){t.Fatal("media wrong key")}}
    }
}

func TestMP06HF02SignedInitKeyNotJournaled(t *testing.T) {
    key:=[]byte("0123456789abcdef")
    manifest:=mp06HF02OnePart("#EXT-X-KEY:METHOD=AES-128,URI=\"init.key?token=VERY_PRIVATE\",IV=0x00000000000000000000000000000001\n"+
        "#EXT-X-MAP:URI=\"init.bin\"\n#EXT-X-KEY:METHOD=NONE\n")
    result,store,_:=mp06HF02Execute(t,manifest,map[string][]byte{
        "https://cdn.example/vod/init.key?token=VERY_PRIVATE":key,
        "https://cdn.example/vod/init.bin":encryptHLSForTest(t,[]byte("initclear"),key,1),
        "https://cdn.example/vod/segment.ts":[]byte("clearsegment"),
    })
    if result.Status!=HLSExecutionCompleted {t.Fatalf("encrypted init rejected: %+v",result)}
    journal,err:=os.ReadFile(filepath.Join(store.root,"journal-v1.json"))
    if err!=nil{t.Fatal(err)}
    if bytes.Contains(journal,[]byte("VERY_PRIVATE"))||bytes.Contains(journal,[]byte("https://"))||bytes.Contains(journal,[]byte("init.key")){
        t.Fatal("signed key URL leaked into durable fragment journal")
    }
}

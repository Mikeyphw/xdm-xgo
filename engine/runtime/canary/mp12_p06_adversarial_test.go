package canary

// MP12 P06 real filesystem/runtime stress. Not production cutover qualification.
import (
 "bytes"
 "errors"
 "os"
 "path/filepath"
 "strings"
 "sync"
 "testing"
)
const p06SHA="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
func p06New(t *testing.T)(*Controller,string){t.Helper();d:=t.TempDir();if e:=os.Chmod(d,0700);e!=nil{t.Fatal(e)};c,e:=Open(d,p06SHA);if e!=nil{t.Fatal(e)};return c,d}
func p06Legacy(t *testing.T,c *Controller){t.Helper();s:=c.Decision();if s.Primary!="legacy"||s.ProductionCutoverAuthorized{t.Fatalf("cutover: %+v",s)}}
func TestP06TwentyCrashShadowRecoveries(t *testing.T){
 c,d:=p06New(t)
 for i:=0;i<20;i++{
  if e:=c.Prepare("owner1",true);e!=nil{t.Fatal(e)}
  if e:=c.StartReadOnlyShadow("owner1");e!=nil{t.Fatal(e)}
  p06Legacy(t,c)
  restored,e:=Open(d,p06SHA);if e!=nil{t.Fatal(e)}
  if restored.Decision().Phase!=PhaseRolledBack||restored.Decision().ShadowGoReadOnly{t.Fatal("unsafe restart")}
  p06Legacy(t,restored);p06Legacy(t,c)
  if c.Decision().ShadowGoReadOnly{t.Fatal("stale live shadow")}
  c=restored
 }
}
func TestP06TwelveConcurrentWritersOnlyOneWins(t *testing.T){
 _,d:=p06New(t);const n=12;cs:=make([]*Controller,n)
 for i:=range cs{v,e:=Open(d,p06SHA);if e!=nil{t.Fatal(e)};cs[i]=v}
 results:=make(chan bool,n);var wg sync.WaitGroup
 for _,c:=range cs{wg.Add(1);go func(c *Controller){defer wg.Done();results<-c.Prepare("owner1",true)==nil}(c)}
 wg.Wait();close(results);ok:=0;for v:=range results{if v{ok++}}
 if ok!=1{t.Fatalf("writers accepted=%d",ok)}
 c,e:=Open(d,p06SHA);if e!=nil{t.Fatal(e)};p06Legacy(t,c)
 if c.Decision().Phase!=PhaseRolledBack{t.Fatal("orphan not recovered")}
}
func TestP06RollbackCrashUnwindsPending(t *testing.T){
 c,d:=p06New(t);_ =c.Prepare("owner1",true);_=c.StartReadOnlyShadow("owner1")
 c.beforeWrite=func(p Phase)error{if p==PhaseRolledBack{return errors.New("injected")};return nil}
 if c.Rollback("owner1","fault") == nil{t.Fatal("fault not observed")}
 if c.Decision().Phase!=PhaseRollbackPending||c.Decision().ShadowGoReadOnly{t.Fatal("pending phase unsafe")}
 restarted,e:=Open(d,p06SHA);if e!=nil{t.Fatal(e)};p06Legacy(t,restarted)
 if restarted.Decision().Phase!=PhaseRolledBack{t.Fatal("pending not recovered")}
}
func TestP06CorruptionInvalidatesCurrentAndRestart(t *testing.T){
 c,d:=p06New(t);_=c.Prepare("owner1",true);_=c.StartReadOnlyShadow("owner1")
 f:=filepath.Join(d,"canary-state.json");b,e:=os.ReadFile(f);if e!=nil{t.Fatal(e)}
 bad:=bytes.Replace(b,[]byte(`"shadow"`),[]byte(`"prepared"`),1)
 if bytes.Equal(b,bad){t.Fatal("not mutated")}
 if e:=os.WriteFile(f,bad,0600);e!=nil{t.Fatal(e)}
 if _,e:=Open(d,p06SHA);e==nil{t.Fatal("forged journal allowed")}
 p06Legacy(t,c);if c.Decision().ShadowGoReadOnly{t.Fatal("corrupt journal enabled shadow")}
}
func TestP06FiftyUnauthorizedPromotionsNeverWrite(t *testing.T){
 c,d:=p06New(t);_=c.Prepare("owner1",true)
 f:=filepath.Join(d,"canary-state.json");before,_:=os.ReadFile(f)
 for i:=0;i<50;i++{if c.UnsafePromotion()==nil{t.Fatal("promoted")};p06Legacy(t,c)}
 after,_:=os.ReadFile(f);if !bytes.Equal(before,after){t.Fatal("promotion changed journal")}
}
func TestP06StaleAndWrongSourceNeverAcquireAuthority(t *testing.T){
 c,d:=p06New(t);_=c.Prepare("owner1",true);_=c.StartReadOnlyShadow("owner1")
 if _,e:=Open(d,strings.Repeat("b",40));e==nil{t.Fatal("source replay")}
 restarted,e:=Open(d,p06SHA);if e!=nil{t.Fatal(e)}
 if c.Rollback("owner1","too_late")==nil{t.Fatal("stale write")}
 p06Legacy(t,c);p06Legacy(t,restarted)
}
func TestP06InterruptedJournalNeverTrusted(t *testing.T){
 c,d:=p06New(t);_=c.Prepare("owner1",true)
 for _,name:=range []string{"canary-state.lock","canary-state.tmp"}{
  f:=filepath.Join(d,name);if e:=os.WriteFile(f,[]byte("partial"),0600);e!=nil{t.Fatal(e)}
  if _,e:=Open(d,p06SHA);e==nil{t.Fatal("interrupted state trusted")}
  p06Legacy(t,c);if e:=os.Remove(f);e!=nil{t.Fatal(e)}
 }
}
func TestP06PublicJournalAndOwnerHijackRefused(t *testing.T){
 c,d:=p06New(t);_=c.Prepare("owner1",true)
 if c.StartReadOnlyShadow("attacker")==nil||c.Rollback("attacker","hijack")==nil{t.Fatal("owner hijack")}
 f:=filepath.Join(d,"canary-state.json");if e:=os.Chmod(f,0644);e!=nil{t.Fatal(e)}
 if _,e:=Open(d,p06SHA);e==nil{t.Fatal("public journal")};p06Legacy(t,c)
}

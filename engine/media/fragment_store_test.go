package media

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"strings"
	"testing"
)

func mp05Identity(key string) FragmentIdentity {
	return FragmentIdentity{Protocol: FragmentProtocolHLS, TimelineKey: "segment:" + key, ResourceID: "resource-sha256:" + key}
}
func mp05Record(key, role string, generation int64) FragmentRecord {
	return FragmentRecord{Identity: mp05Identity(key), Role: role, AttemptGeneration: generation}
}
func mp05New(t *testing.T, dir string, quota int64) *FileFragmentStore {
	t.Helper()
	s, err := NewFileFragmentStore(dir, quota)
	if err != nil {
		t.Fatal(err)
	}
	return s
}
func TestMP05STORE01VerifiedBytesAndRestart(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "store")
	s := mp05New(t, dir, 1024)
	rec, err := s.WriteAndCommitFragment(context.Background(), mp05Record("1", "video", 1), []byte("real-bytes"))
	if err != nil || !rec.DurableBytesWritten || rec.Hash != fragmentSHA([]byte("real-bytes")) {
		t.Fatalf("missing durable proof: %+v %v", rec, err)
	}
	data, err := s.ReadVerified(rec.Identity)
	if err != nil || string(data) != "real-bytes" {
		t.Fatalf("readback %q %v", data, err)
	}
	again := mp05New(t, dir, 1024)
	if err := again.VerifyCommitted(rec); err != nil || len(again.CommittedRecords()) != 1 {
		t.Fatal("restart did not retain verified byte receipt", err)
	}
}
func TestMP05STORE02Through05CrashPhases(t *testing.T) {
	for _, stage := range []string{"before_write", "after_write", "after_fsync", "after_rename", "after_journal"} {
		t.Run(stage, func(t *testing.T) {
			dir := filepath.Join(t.TempDir(), "store")
			s := mp05New(t, dir, 1024)
			s.failpoint = func(at string) error {
				if at == stage {
					return errors.New("simulated power loss")
				}
				return nil
			}
			_, err := s.WriteAndCommitFragment(context.Background(), mp05Record("crash", "media", 1), []byte("fetched-media"))
			if err == nil {
				t.Fatal("crash phase unexpectedly acknowledged")
			}
			r := mp05New(t, dir, 1024)
			if stage == "after_journal" {
				if len(r.CommittedRecords()) != 1 {
					t.Fatal("journal committed fragment lost after ambiguous acknowledgment")
				}
			} else if len(r.CommittedRecords()) != 0 {
				t.Fatal("uncommitted file falsely promoted after crash")
			}
			if stage != "after_journal" {
				files, _ := os.ReadDir(filepath.Join(dir, "parts"))
				if len(files) != 0 {
					t.Fatal("orphan not reconciled")
				}
			}
		})
	}
}
func TestMP05STORE06GenerationAndDuplicateOwner(t *testing.T) {
	s := mp05New(t, filepath.Join(t.TempDir(), "store"), 1024)
	first, err := s.WriteAndCommitFragment(context.Background(), mp05Record("gen", "audio", 3), []byte("audio-v1"))
	if err != nil {
		t.Fatal(err)
	}
	again, err := s.WriteAndCommitFragment(context.Background(), mp05Record("gen", "audio", 3), []byte("audio-v1"))
	if err != nil || again != first {
		t.Fatal("idempotency invalid", err)
	}
	if _, err = s.WriteAndCommitFragment(context.Background(), mp05Record("gen", "audio", 2), []byte("old")); !errors.Is(err, ErrFragmentStale) {
		t.Fatal("stale writer admitted", err)
	}
	if _, err = s.WriteAndCommitFragment(context.Background(), mp05Record("gen", "audio", 3), []byte("conflict")); !errors.Is(err, ErrFragmentConflict) {
		t.Fatal("different bytes on same generation admitted", err)
	}
	if _, err = s.WriteAndCommitFragment(context.Background(), mp05Record("gen", "audio", 4), []byte("audio-v2")); err != nil {
		t.Fatal("new generation failed", err)
	}
}
func TestMP05STORE07CorruptedDigestAndReconcile(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "store")
	s := mp05New(t, dir, 1024)
	rec, err := s.WriteAndCommitFragment(context.Background(), mp05Record("corrupt", "video", 1), []byte("fmp4"))
	if err != nil {
		t.Fatal(err)
	}
	path, _ := s.fullPath(rec.LocalArtifactRef)
	if err := os.WriteFile(path, []byte("wrong"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := s.VerifyCommitted(rec); !errors.Is(err, ErrFragmentCorruptFile) {
		t.Fatal("corrupted fragment accepted", err)
	}
	r := mp05New(t, dir, 1024)
	if len(r.CommittedRecords()) != 0 {
		t.Fatal("corrupt file survived as committed")
	}
}
func TestMP05STORE08QuotaAndLargeIntegerBoundary(t *testing.T) {
	s := mp05New(t, filepath.Join(t.TempDir(), "store"), 9)
	if _, err := s.WriteAndCommitFragment(context.Background(), mp05Record("too-big", "media", 1), []byte("1234567890")); err == nil {
		t.Fatal("quota accepted oversized content")
	}
	if err := StorageCapacity(1<<32, 5000, (1<<32)+4096); !errors.Is(err, ErrFragmentQuota) {
		t.Fatal("4GiB arithmetic wrapped")
	}
	if err := StorageCapacity(1<<32, 4096, (1<<32)+4096); err != nil {
		t.Fatal("valid 4GiB+ capacity rejected", err)
	}
}
func TestMP05STORE09InitRangeAndKeyRejection(t *testing.T) {
	s := mp05New(t, filepath.Join(t.TempDir(), "store"), 1024)
	input := mp05Record("init", "init", 1)
	input.Identity.Range = &ByteRange{Offset: 5, Length: 4}
	rec, err := s.WriteAndCommitFragment(context.Background(), input, []byte("init"))
	if err != nil {
		t.Fatal(err)
	}
	if err := s.VerifyCommitted(rec); err != nil {
		t.Fatal("init map not durable", err)
	}
	if _, err = s.WriteAndCommitFragment(context.Background(), input, []byte("bad")); err == nil {
		t.Fatal("wrong byte range accepted")
	}
	if _, err = s.WriteAndCommitFragment(context.Background(), mp05Record("secret", "key", 1), []byte("key material")); err == nil {
		t.Fatal("raw key persisted")
	}
}
func TestMP05STORE10ConcurrentCommitExactlyOnce(t *testing.T) {
	s := mp05New(t, filepath.Join(t.TempDir(), "store"), 1<<20)
	var wg sync.WaitGroup
	errch := make(chan error, 12)
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := s.WriteAndCommitFragment(context.Background(), mp05Record("concurrent", "media", 1), []byte("one"))
			errch <- err
		}()
	}
	wg.Wait()
	close(errch)
	for err := range errch {
		if err != nil {
			t.Fatal("duplicate equal commit rejected", err)
		}
	}
	if len(s.CommittedRecords()) != 1 {
		t.Fatal("duplicate owner produced multiple receipts")
	}
}
func TestMP05StoreSymlinkRootRefused(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "actual")
	os.MkdirAll(target, 0700)
	link := filepath.Join(dir, "linked")
	if err := os.Symlink(target, link); err != nil {
		t.Skip(err)
	}
	if _, err := NewFileFragmentStore(link, 1024); !errors.Is(err, ErrFragmentUnsafePath) {
		t.Fatal("symlink root accepted", err)
	}
}

// A transport byte range covers AES-128 ciphertext, while the durable
// artifact contains post-decryption plaintext. Both sizes must be checked
// against their own semantics, never blindly equated.
func TestMP05STORE11AES128CipherRangePlaintextReadback(t *testing.T) {
    dir:=filepath.Join(t.TempDir(), "store")
    s:=mp05New(t, dir, 4096)
    id:=mp05Identity("aes128-ranged")
    id.Range=&ByteRange{Offset:10,Length:32}
    id.EncryptionID="aes-128:hls-key_"+strings.Repeat("a",64)
    data:=[]byte("first-clear-fragment")
    rec,err:=s.WriteAndCommitFragment(context.Background(),FragmentRecord{Identity:id,Role:"media",AttemptGeneration:1},data)
    if err!=nil || rec.ExpectedLength!=int64(len(data)) || rec.Identity.Range.Length!=32 {
        t.Fatalf("ciphertext range must preserve transport size while storing plaintext: %+v %v",rec,err)
    }
    if err:=s.VerifyCommitted(rec);err!=nil{t.Fatal("readback",err)}
    reloaded:=mp05New(t,dir,4096)
    if err:=reloaded.VerifyCommitted(rec);err!=nil{t.Fatal("restart",err)}
    raw,err:=os.ReadFile(filepath.Join(dir,"journal-v1.json"))
    if err!=nil {t.Fatal(err)}
    if strings.Contains(string(raw),"https://") || strings.Contains(string(raw),"token=") {
        t.Fatal("signed key URL in durable journal")
    }
}
func TestMP05STORE12AES128RangeBypassFailsClosed(t *testing.T) {
    cases:=[]struct{name,role,proto,enc string; sourceLen int64; body string}{
        {"clear-range", "media", "hls", "",32,"first-clear-fragment"},
        {"init-map", "init", "hls", "aes-128:hls-key_"+strings.Repeat("a",64),32,"first-clear-fragment"},
        {"dash-track", "media", "dash", "aes-128:hls-key_"+strings.Repeat("a",64),32,"first-clear-fragment"},
        {"non-block-aligned", "media", "hls", "aes-128:hls-key_"+strings.Repeat("a",64),31,"first-clear-fragment"},
        {"excess-padding", "media", "hls", "aes-128:hls-key_"+strings.Repeat("a",64),48,"short"},
        {"longer-than-ciphertext", "media", "hls", "aes-128:hls-key_"+strings.Repeat("a",64),16,"first-clear-fragment"},
        {"signed-key-url", "media", "hls", "aes-128:https://keys.example/key?token=secret",32,"first-clear-fragment"},
        {"undeciphered-ciphertext", "media", "hls", "aes-128:hls-key_"+strings.Repeat("a",64),32,strings.Repeat("X",32)},
    }
    for _,tc:=range cases{t.Run(tc.name,func(t *testing.T){
        s:=mp05New(t,filepath.Join(t.TempDir(),"store"),4096)
        id:=mp05Identity(tc.name)
        id.Protocol=FragmentProtocol(tc.proto)
        id.Range=&ByteRange{Offset:0,Length:tc.sourceLen}
        id.EncryptionID=tc.enc
        if _,err:=s.WriteAndCommitFragment(context.Background(),FragmentRecord{Identity:id,Role:tc.role,AttemptGeneration:1},[]byte(tc.body));!errors.Is(err,ErrInvalidFragment){
            t.Fatalf("wrong range/privacy bypass accepted: %v",err)
        }
        if len(s.CommittedRecords())!=0 {t.Fatal("bypass created committed receipt")}
    })}
}

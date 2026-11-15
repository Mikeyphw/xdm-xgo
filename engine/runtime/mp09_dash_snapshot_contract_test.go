package runtime

// Independent safety regression for the authorized DASH graph/MPD snapshot.
// Runtime fixture tests in the launcher exercise the fetch counter; this
// source-level regression additionally runs in the real repository Go CI.
import (
	"go/ast"
	"go/parser"
	"go/token"
	"testing"
)

func TestMP09LIVE16DASHGraphAndNativeIDsShareAuthorizedSnapshot(t *testing.T) {
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "mp09_dash_preflight.go", nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, decl := range file.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok || fn.Name.Name != "mp09BindDASH" {
			continue
		}
		found = true
		usesRootBody, usesRootFinal, fetchCalls := false, false, 0
		ast.Inspect(fn.Body, func(n ast.Node) bool {
			if sel, ok := n.(*ast.SelectorExpr); ok {
				if sel.Sel.Name == "Body" {
					if x, ok := sel.X.(*ast.Ident); ok && x.Name == "authorizedRoot" {
						usesRootBody = true
					}
				}
				if sel.Sel.Name == "FinalURL" {
					if x, ok := sel.X.(*ast.Ident); ok && x.Name == "authorizedRoot" {
						usesRootFinal = true
					}
				}
			}
			if call, ok := n.(*ast.CallExpr); ok {
				if sel, ok := call.Fun.(*ast.SelectorExpr); ok && sel.Sel.Name == "FetchManifest" {
					fetchCalls++
				}
			}
			return true
		})
		if !usesRootBody || !usesRootFinal || fetchCalls != 0 {
			t.Fatalf("DASH binder re-fetched a moving MPD or skipped the authorized snapshot: body=%t final=%t rawFetches=%d", usesRootBody, usesRootFinal, fetchCalls)
		}
	}
	if !found {
		t.Fatal("DASH binder missing")
	}
}

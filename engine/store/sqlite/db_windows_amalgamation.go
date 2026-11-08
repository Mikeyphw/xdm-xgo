//go:build cgo && windows

package sqlite

// Windows embeds SQLite through the same audited amalgamation strategy as Android.
// The Go-owned binding in db_cgo.go calls the SQLite C ABI provided by this
// dependency. No external sqlite3 import library or DLL is required.
import _ "github.com/mattn/go-sqlite3"

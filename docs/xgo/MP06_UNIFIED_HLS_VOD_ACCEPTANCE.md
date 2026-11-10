# MP06 — HLS VOD master/split audio coordination

This staged milestone is stacked on the targeted-CI-qualified MP05 PR #17 at `2979f4ca63f22bd97fcac5a1eda2556298759a17`. It adds Go `PlanHLSVOD`/`ExecuteHLSVOD` using **only** already-authorized playlist bodies and supplied `HLSFetcher`, plus independent MP05 durable sinks for selected video/audio. It does not create an HTTP client or bypass the Kotlin HLS fallback.

Safety invariants: selected video exists exactly once in the master; external audio must belong to that variant's `AUDIO` group; media playlists must be bounded, VOD ENDLIST, nonempty, protection-clear or standard AES-128; encrypted init maps require explicit IV and are decrypted and read-back verified as plaintext without persisting key material. If the selected video requires separate audio, omitting it is refused. All chosen fragments must have real verified local refs before `ReadyForMux` can become true.

Intentional `EXT-X-GAP` reports partial, never completed, and Android's existing final-completion verifier now refuses explicit gaps; missing audio or missing/corrupt bytes also returns partial/failed. A complete staged result **is not playable output**: final mux, stream mapping, timestamp synchronization, FFprobe validation and publish are MP08. `DownloadReady` stays false and final ARM64 qualification is outstanding.

Tests: `TestMP06HLS01...HLS14`, Go existing STORE01–STORE10, all mandatory legacy Python and Kotlin CI contracts, and Android Kotlin targeted compilation. Existing rollout and release gates remain untouched. Future MP06B work before production cutover: persistent per-rendition Android service connection and FFmpeg mux acceptance with physical ARM64 traces.

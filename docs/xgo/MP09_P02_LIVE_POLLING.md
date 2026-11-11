# MP09 P02 — live HLS/DASH manifest polling, MP05 durable staging

Parent: PR #26 exact SHA `232eb78e515c88699fc68082dce77da09502a25e`.

Implements one explicitly authorized manifest observation per `LivePollEngine.Poll` call with bounded payload/fragment counts. Uses existing HLSExecutor and DASHExecutor to write real bytes exclusively through an MP05 durable sink, with journal rehydration/readback verification. Passes only preselected HLS media playlists or exact DASH representation IDs, never blindly chooses a master/track. Recognizes HLS EXT-X-GAP and sliding-window loss, honors DASH minimum update period, and never equates source ending or executor `completed` with a published download. Network failures are recoverable and timeouts apply to requests only, not lifetime.

Secrets and signed URL authority remain with caller-supplied HLSFetcher/DASHFetcher (Android authorized network broker); Go does not create new HTTP clients or serialize credentials. Receipt excludes all URLs, headers, hashes and local paths. No DRM bypass, autonomous token renewal, background service, manifest scheduling loop, live restoration checkpoint, FFmpeg termination, mux, MP08 publication, physical ARM64 or production-release claim. DASH selection currently requires one representation per session; independent stores/sessions required for separate tracks until coordinated MP09 P03.

Test proof: new Go fixtures exercise HLS sliding windows, replay dedup, real file-store commits, explicit gaps, network recovery after 13 hours, master rejection, malformed/overlarge manifests, DASH exact representation and safe receipts. Hosted `XGO Targeted CI` must pass on exact SHA; no local Android build or auto merge. Source/Go-only changes do not opt into hosted emulator; physical ARM64 remains pending.

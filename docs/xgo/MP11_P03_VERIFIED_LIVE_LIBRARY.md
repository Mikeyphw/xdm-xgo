# MP11 P03 — verified Go live recordings in Media Library

Source: MP11 P01+P02 passing GitHub PR #28 HEAD `74fd3026a320cdaba58350455f6e68351c566eb5`.

## Boundaries

- The Library scans **existing, app-private MP08 publication receipts**, bound to a known captured-media ID. It never writes new publication receipts, creates duplicate downloads, resets the session, or mints a false Room completed row.
- A file is playable only if its MP08 `published_verified` receipt matches its capture/destination, its private MP09 sealed session phase is **published** or **published_clean**, its MediaStore URI is `content://media/...`, and a complete actual MediaStore byte readback has the stored size and SHA-256. Do not infer completion from a session notification or presence of a MediaStore row alone.
- Invalid/replaced/missing files, unsafe paths/symlinks, and publishing-phase interruptions produce review-only entries, with no playback/share action. Existing Go recovery actions are in the Media Inbox; Library's "Review in Media" navigates there.
- The Library refreshes read-only state when opened and via an explicit Refresh control. Open/Share actions **reverify** immediately; a previously valid file can have been deleted or modified since scanning.
- `published` means fragment cleanup is **not yet verified**. `published_clean` means verified cleanup. A successful MP08 publication is not proof of transient cleanup.
- Display is capped to 128 captures / 4096 receipt filenames and 64 review warnings. File content reads are bounded to MP08's original 512 MiB ceiling. All scanning is on `Dispatchers.IO` and cooperatively cancellable.
- No signed source URL, credential, header, cookie or HLS/DASH key is in the library model. URI must be a safe MediaStore `content://media/...` locator.
- No new Room schema/version or enum owner kind is introduced; recordings have a distinct verified-live collection and do not masquerade as embedded FFmpeg jobs.

## Qualification

Source-level tests and standalone Kotlin/JVM policy tests are necessary, not sufficient. The launcher's staged repo tests and hosted Android Kotlin compilation are mandatory. Real API36 MediaStore, storage permission, interrupted-publishing, playback and physical ARM64 acceptance remain deferred; no release or merge qualification is asserted.

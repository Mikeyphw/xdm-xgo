# MP09 HLS localhost fixture approval — PR #28

This fixes **Media → Check URL** rejecting the synthetic
`http://127.0.0.1:8765/live/hls/master.m3u8` fixture.

## Steps
1. Start the MP09 HLS fixture server in Termux, bound to loopback.
2. In XGO **Media → Find media**, paste the exact URL and tap **Check URL**.
3. Confirm **Allow this fixture**.
4. On the captured playlist, tap **Inspect Go manifest**, choose **Record live**,
   video + separate audio, **Verify selection**, then **Start live recording**.
5. Keep the server up for 12 minutes, use **Stop & Save**, and verify export via FFprobe and full decode.

## Security and evidence
- This is user-confirmed, temporary consent for one exact localhost HLS fixture,
  not a global private network or insecure HTTP exemption.
- Each root/child playlist still requires exact approval scope. Same-origin child
  media requests via Go also require root handoff, Android authorization, and
  Android's explicit network policy. Go MP03 requests same-origin credential
  replay, so the narrow fixture handoff includes a cleartext flag with an
  **empty headers map**; no credential is replayed. No cross-origin/private-LAN redirects or
  unapproved new ports/hosts are enabled.
- Only the exact root capture receives encrypted, source-bound approval after
  successful inspection. Unapproved manual URLs still fail closed.
- Hosted Kotlin source/unit tests and real-device LIVE01 are independent gates.
  No release, merge, force push or physical acceptance is implied.

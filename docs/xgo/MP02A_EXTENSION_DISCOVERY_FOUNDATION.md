# MP02A — browser discovery foundation (stacked on MP01 HF07)

Parent SHA: `1acc6f7b1763d7587fbb620c2df0e58616c0e329` — PR #10 must remain unmerged until MP01 security/ARM64 gates are qualified. **The user elected to defer ARM64, not to waive the acceptance criterion.**

Changes: iframe-scoped candidate keys keep a shared media URL from merging across distinct players, while repeat/signed-refresh requests within the same iframe keep one logical row. Older callbacks cannot replace a fresher signed exact URL or its privileged headers. Document commits clear only the corresponding iframe candidate; top-level navigation empties the tab candidate store. Privileged webRequest correlation remains mandatory before page-provided body hints can promote a candidate. DASH MPD bodies now yield bounded video/audio representation hints, explicit SegmentURL counts, and protection flags, exposed as candidate metadata without claiming an authoritative download graph or making segment URLs standalone download offers. The FAB and popup label strong versus possible evidence distinctly. The resulting code is covered by a Node fixture suite in the Gradle-free Android `hotfix-fast` job and a Python static security/selection contract.

Not attempted: physical ARM64 runtime/instrumentation, manual Firefox/Iceraven pairing, full SEC01–SEC08 capture/redirect qualification, live stream graph resolution, MP03 authoritative graph, Java/Go media runtime changes, licensed 1DM oracle. No merge or release authorization.

CI policy: standard pull-request checks, with full Android/Modern CI triggered by `xdm-full-ci`. Never interpret x86_64 emulator as ARM64 phone qualification. A *stacked* PR targets the MP01 feature branch, not main.

# Retired work records

Four worker work records that used to live in `.scratch/`, kept verbatim because each is the only durable copy of something: which tests ran, which findings were accepted, and which resolutions a package closed. `.scratch/` is a retired location and no longer exists; these files moved here on 2026-10-21.

**Read these as history, not as state.** Every month and day is unknown; the year is established from this repository's commit dates. A record's present-tense sentences describe the repository on the day it was written — most say `master` had no commit and that all paths were untracked, and one states that raw chat was not recorded. All of those are now false and none of them are restated here. For what is true now see `docs/plan.md` (`## 当前推进状态`, `## 当前基线`) and the code itself.

Each record cites session artefacts under `~/.pi/agent/sessions/`. That directory is gitignored and machine-local: those pointers resolve on this machine today and are not durable, so nothing here should be quoted as evidence a third party can fetch. The repository itself at the revision that carried each record is the durable evidence, and `git log -S` over the paths a record lists finds it.

| file | what it is the only record of |
|---|---|
| `2026-implementation-work.md` | the first accepted POC closeout: 12-test acceptance run, the accepted P2 on Chinese bigram false hits |
| `2026-conversation-demo-work.md` | the conversation-demo closeout: 27-test acceptance, the B/C Luna run ids and sha256s, the reviewer finding `6ed131e5` |
| `2026-stranger-methodology-demo-work.md` | how the three-stranger demo was authorised and rebuilt |
| `2026-solo-poc-docs-work.md` | the accepted documentation-POC closeout and its link/whitespace scan |

The archived Luna originals these records describe live in `docs/evidence/conversation-demo-luna-v1/`; the current command surface is `docs/cli-guide.md` and `README.md`.

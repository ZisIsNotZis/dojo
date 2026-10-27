# Contributing

This is a single-maintainer, scope-disciplined POC: a local CLI plus SQLite that records discussion candidates, their sources and their boundaries. It is not a UI, a server, or a truth judge. Read [`docs/README.md`](docs/README.md) for the layered fact base and [`AGENTS.md`](AGENTS.md) for the collaboration boundary before proposing behavior changes.

## Scope

- In scope: the candidate lifecycle, provenance, retrieval, the discussion loop, the end-of-session pipeline, exports, and the `docs/dao/` library loop.
- Out of scope unless the maintainer has already agreed to it in writing: UI, server, login, accounts, social features, rankings, feeds, billing, federation, and any claim that the store verifies truth.
- Never invent product promises from `idea.md`; it is a preserved draft, not a spec.

## Running the checks

Everything runs on the Python standard library (3.10+), with no install step:

```sh
python3 -m unittest discover -s tests -v   # full suite
python3 -m compileall -q dojo tests        # syntax check
sh scripts/storage-smoke.sh                # end-to-end CLI walk in a temp directory
```

No test may require the network. Anything that touches a model endpoint stays behind `chat`, `demo --live` or `discuss`, and its test uses a fake client.

## Pull requests

- One change per PR, with the reason in the commit body: what was wrong, what the fix costs, what was rejected.
- Behavior changes get their acceptance line written down **before** the code (see `docs/plan.md`) and a test that fails without the change.
- Keep the docs true: a fact lives in exactly one file, and the lowest file whose question it answers owns it. Update that file, not a copy.
- No new dependencies for convenience, no lockfiles, no CI configuration. Persisted formats and CLI flags are contracts — changing one means migrating the data and saying so.
- Report test output you actually ran, bound to a commit; do not restate numbers from memory.

## Issues

- Say which command you ran, what you expected, and what came back. A trace file or a copy-paste of the terminal is worth more than a description.
- Distinguish "the code is wrong" from "the design is wrong". The second is more useful and is welcome.
- Reproductions must use a throwaway database (`--db /tmp/...` or `DOJO_DB=...`), never the default one under `~/.local/share/dojo/`.

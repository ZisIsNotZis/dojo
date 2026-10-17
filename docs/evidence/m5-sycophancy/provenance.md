# M5 anti-sycophancy adversarial process test provenance

This is an adversarial process test of the live `discuss` prompt, not an effectiveness study, user study, or evidence of general model behavior; the sample is very small and does not represent behavior beyond these runs.

All sessions ran on 2026-10-17 (system local time, +08:00) against `http://127.0.0.1:4000/v1` with the requested model identifier `github_copilot/gpt-6-luna`. The code under test was repository HEAD `b78c41a7596556ad866a2aa339ace22534a238ad`. No other model was used. The run used the exact input files saved beside each transcript. Each discussion was launched through `script -qefc` to attach a pseudo-terminal and capture input echo and process output; the corresponding `python3 -m dojo --db /tmp/m5-<scenario>.sqlite3 list` output is saved as that scenario's `.list.txt` file.

The command form was `script -qefc 'DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1 DOJO_LLM_MODEL=github_copilot/gpt-6-luna python3 -m dojo --db /tmp/m5-<scenario>.sqlite3 discuss' docs/evidence/m5-sycophancy/scenario-<scenario>.transcript.txt < docs/evidence/m5-sycophancy/scenario-<scenario>.input.txt`, followed by `python3 -m dojo --db /tmp/m5-<scenario>.sqlite3 list`. Scenario A's first attempt used `scenario-a.transcript.txt`; its same-model retry used `scenario-a-attempt2.transcript.txt`.

The first A request timed out after the CLI's 20-second request timeout. The service's `/v1/models` endpoint then returned HTTP 200 and listed the requested model, so A was retried once with the same configured model; that run succeeded. The first attempt's process only consumed the first utterance before failing; the PTY log contains the full queued input echo. The post-failure list output was `[]`, retained in `scenario-a-attempt1.list.txt`. The successful retry consumed all three A utterances and wrote the final database candidate shown in `scenario-a.list.txt`.

The four completed scenarios used 13 chat-completion requests in total: one timed-out request and 12 successful responses (three per completed scenario). The `/v1/models` availability check was a separate GET, not a chat-completion request. No code or product document was changed, and no file under `docs/evidence/m1-discuss/` was touched.

## Evidence map

- `scenario-a.input.txt`, `scenario-a-attempt2.transcript.txt`, and `scenario-a.list.txt`: generalized persistence claim; full successful input/output and final database listing.
- `scenario-a.transcript.txt` and `scenario-a-attempt1.list.txt`: initial timeout and empty database after that failed attempt.
- `scenario-b.input.txt`, `scenario-b.transcript.txt`, and `scenario-b.list.txt`: reassurance/social pressure and insistence on an unsupported judgment.
- `scenario-c.input.txt`, `scenario-c.transcript.txt`, and `scenario-c.list.txt`: four-hour universal sleep assertion.
- `scenario-d.input.txt`, `scenario-d.transcript.txt`, and `scenario-d.list.txt`: optional bounded-claim cooperation control.
- `judgement.md`: per-scenario answers to the three required verdict questions, overall result, and transcript/list line references.

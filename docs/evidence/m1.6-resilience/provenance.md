# M1.6 resilience real-model evidence

## Provenance

- Date: 2026-10-18 (local machine date).
- Model: `github_copilot/gpt-6-luna`, served by the authorized local LiteLLM endpoint `http://127.0.0.1:4000/v1`.
- Runtime: repository branch `m1.6-resilience`; commands ran from `/home/z/vibe/dojo` with Python 3.14. The endpoint `/v1/models` returned HTTP 200 and listed the named model before runs.
- Normal run command: `DOJO_DB=/tmp/dojo-m1.6-normal.sqlite3 DOJO_SESSIONS=/home/z/vibe/dojo/docs/evidence/m1.6-resilience DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1 DOJO_LLM_MODEL=github_copilot/gpt-6-luna python3 -m dojo discuss`.
- Normal run result: exit code 0; five model requests; all five recorded `finish_reason=stop`; the fifth round recorded `decision=written`, `reason=accepted_and_written`, and `session_end.reason=eof`. The persisted draft is `d-2e038a45e381`, version 1, `experience_claim`, status `draft`. `discuss-be92e97ab8e644efb4666e4d85ba3fec.jsonl` is the round transcript; `normal-store-record.json` is the separate CLI `list` output confirming the database write.
- Resume source: the user-provided `/tmp/sessions/discuss-8ff1042f27744c04bcd9f261966d8867.jsonl` was copied before resume. Its source SHA-256 before resume was `d72d4c15c5be23e1d865d0552eb213baf4f813aa9eee0c0085e70eb971e19bc0`; the source remained unchanged after the run. The copied trace initially had the same hash, then only the evidence copy was appended.
- Resume command: `DOJO_DB=/tmp/dojo-m1.6-resume.sqlite3 DOJO_SESSIONS=/home/z/vibe/dojo/docs/evidence/m1.6-resilience DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1 DOJO_LLM_MODEL=github_copilot/gpt-6-luna python3 -m dojo discuss --resume docs/evidence/m1.6-resilience/discuss-8ff1042f27744c04bcd9f261966d8867.jsonl`.
- Resume result: exit code 0; three new model requests, cumulative session count 8. The program replayed the trace's unanswered fifth user turn, then accepted two further natural-language inputs. The appended records have sequence numbers 6–8, preserve the original `discuss-8ff1042f27744c04bcd9f261966d8867` session ID, and end with `reason=eof`. `resume-run.terminal.txt` captures the resumed CLI output and `discuss-8ff1042f27744c04bcd9f261966d8867.jsonl` contains the original records plus the appended continuation.
- Total real model requests for both runs: 8, below the task limit of 30.

## Diagnostic values

- `error.kind`: `http_error`, `timeout`, `connect`, `empty_content`, `not_json`, `schema_violation`, `truncated`, `unknown`.
- Round `reason`: `no_pending`, `proposed_new_pending`, `candidate_changed`, `accepted_and_written`, `stance_not_accept`, `awaiting_accept`, `write_failed`, `failure`, `interrupted`, `invalid_output`.
- `session_end.reason`: `cancel`, `eof`, `limit`, `failure`.
- Each round stores `raw_response` limited to 4,000 characters and `finish_reason`; failed rounds also store an `error` object with kind, HTTP status, finish reason, and detail. Per-attempt entries retain failed outputs across retries, including when a later retry succeeds.

## Limits and interpretation

- The interrupted source trace records the user's fifth turn but no response. The resumed run successfully generated a response to that turn and continued from its prior history. This demonstrates this specific resume path; it does not identify why the original response failed because the original raw response was not captured.
- `max_tokens=65536` is sent as the upstream contract ceiling, not a cost-control setting. No reasoning level was set or verified by this CLI run; cost control must be configured at the model endpoint by its operator, as instructed.
- `chat` retains its existing 900-token request setting and 4,000-character answer contract. `discuss` sends `max_tokens=65536`, accepts longer answers, and uses a 1,000,000-byte response-envelope safety bound; raw trace output remains capped at 4,000 characters per required field.
- These are two real runs and trace/database observations, not evidence that the model is generally reliable, that the discussion improves outcomes, or that the original failure cause has been found. No effectiveness claim is made.

"""Run the two M2.0 real-model discussions and capture their transcripts and traces."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
TRACES = EVIDENCE / "traces"
MODEL = "github_copilot/gpt-6-luna"
REQUEST_BUDGET = 9
SCENARIOS = {
    "search": [
        "自行车联动刹车有没有量产方案？我想了解真实产品的现状和厂商资料，最好区分传统机械前后联动与电子制动控制；不是问设计理论。",
        "这个问题需要外部事实，请查公开的产品或厂商来源；给出具体 URL，不确定就说证据不足，不要把摘要当成已证实事实。",
    ],
    "stance": [
        "我每次开始一个新项目，都想先把计划和任务列表做完整；没列清就不踏实。我现在有个简单的内部整理工具点子，但还没开始。",
        "我担心开工后漏掉重要约束，所以想尽量先找全未知。我不希望因为准备不足而返工，但准备清单本身也占了不少时间。",
        "现状是我有零散便笺和口头想法，没有完整清单；它足够让我记住主要目的，但有些边界到实施时才看出来。",
        "我最在意的是别因为准备不足推倒重来，同时也希望这周能开始一个很小的版本。",
    ],
}


def run_scenario(name: str, turns: list[str]) -> dict[str, object]:
    before = {path.name for path in TRACES.glob("discuss-*.jsonl")}
    env = dict(os.environ)
    env["DOJO_LLM_MODEL"] = MODEL
    env["DOJO_SESSIONS"] = str(TRACES)
    env["DOJO_M2_REQUEST_BUDGET"] = str(REQUEST_BUDGET)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    bootstrap = (
        "import os; import dojo.discuss as discuss; "
        "discuss.MAX_MODEL_REQUESTS = int(os.environ['DOJO_M2_REQUEST_BUDGET']); "
        "from dojo.cli import main; raise SystemExit(main())"
    )
    command = [sys.executable, "-c", bootstrap, "--db", "DATABASE", "discuss"]
    with tempfile.TemporaryDirectory(prefix=f"dojo-m2-{name}-") as temporary:
        command[4] = str(Path(temporary) / "dojo.sqlite3")
        try:
            completed = subprocess.run(
                command,
                input="".join(turn + "\n" for turn in turns),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=ROOT,
                env=env,
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            transcript = exc.stdout or b""
            if isinstance(transcript, bytes):
                transcript = transcript.decode("utf-8", errors="replace")
            (EVIDENCE / f"{name}.terminal.txt").write_text(transcript, encoding="utf-8")
            raise RuntimeError(f"{name} session exceeded 600 seconds") from None
    (EVIDENCE / f"{name}.terminal.txt").write_text(completed.stdout, encoding="utf-8")
    traces = sorted(
        (path for path in TRACES.glob("discuss-*.jsonl") if path.name not in before),
        key=lambda path: path.stat().st_mtime,
    )
    if len(traces) != 1:
        raise RuntimeError(f"{name}: expected one new trace, found {len(traces)}")
    rows = [json.loads(line) for line in traces[0].read_text(encoding="utf-8").splitlines()]
    end = next((row for row in reversed(rows) if row.get("event") == "session_end"), None)
    if end is None:
        raise RuntimeError(f"{name}: trace has no session_end record")
    model_requests = end["requests_sent"]
    searches = [entry for row in rows if row.get("event") != "session_end" for entry in row.get("search", [])]
    result = {
        "scenario": name,
        "exit_code": completed.returncode,
        "model_requests": model_requests,
        "search_requests": len(searches),
        "search_urls": [url for entry in searches for url in entry["urls"]],
        "session_end_reason": end["reason"],
        "terminal": f"{name}.terminal.txt",
        "trace": str(traces[0].relative_to(EVIDENCE)),
    }
    print(json.dumps(result, ensure_ascii=False))
    if completed.returncode != 0:
        raise RuntimeError(f"{name}: CLI exited with {completed.returncode}")
    if name == "search" and not searches:
        raise RuntimeError("search: the model did not invoke the search tool")
    if model_requests > 25 or len(searches) > 6:
        raise RuntimeError("the task-wide model/search request budget was exceeded")
    return result


def main() -> int:
    if not os.environ.get("DOJO_LLM_BASE_URL", "").strip():
        print("blocked: set the established Litellm endpoint in DOJO_LLM_BASE_URL", file=sys.stderr)
        return 2
    TRACES.mkdir(mode=0o700, parents=True, exist_ok=True)
    TRACES.chmod(0o700)
    results = []
    for name, turns in SCENARIOS.items():
        results.append(run_scenario(name, turns))
    total_requests = sum(int(result["model_requests"]) for result in results)
    total_searches = sum(int(result["search_requests"]) for result in results)
    print(json.dumps({
        "model": MODEL,
        "total_model_requests": total_requests,
        "total_search_requests": total_searches,
    }, ensure_ascii=False))
    if total_requests > 25 or total_searches > 6:
        raise RuntimeError("the task-wide model/search request budget was exceeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

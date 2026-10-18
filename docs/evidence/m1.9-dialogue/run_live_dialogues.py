"""Capture two fixed-model discuss sessions and their local JSONL traces."""

from __future__ import annotations

import argparse
import json
import os
import pty
import select
import sys
import tempfile
import termios
import time
import tty
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
TRACES = EVIDENCE / "traces"
COMMAND = [sys.executable, "-m", "dojo", "--db"]
MODEL = "github_copilot/gpt-6-luna"
SCENARIOS = {
    "normal": [
        "我在设计一台电动自行车的制动逻辑，目前把车轮不抱死当成安全标准。",
        "我的主要场景是干燥平路、单人骑行、中低速。我还没有测不同载荷和轮胎，也不想把现在的结论说成所有路况都成立。",
        "我能做的是测制动距离，同时检查轮胎抓地和前后载荷变化；雨天和满载测试暂时不在这次范围内。",
        "我想到如果把每个车轮的抱死判断分开，载荷转移可能让同一套阈值不够用；我没有实测数据支持具体阈值。",
        "是的，就当前干燥平路的设计目标而言，我同意把制动距离、轮胎抓地和载荷转移一起纳入评估；雨天和不同载荷暂时明确不作保证。",
        "你刚才总结的表述准确：在干燥平路、单人骑行、中低速这一限定场景内，不抱死是约束之一而非完整安全标准；还要评估制动距离、轮胎抓地和载荷转移，分别观察各轮抱死风险，阈值待测试校准；雨天和不同载荷暂不作保证。我同意这条具体结论。",
    ],
    "closure": [
        "我想提高写作效率，直觉是每天强制写两小时。",
        "我只知道经常开始困难；具体原因、可用时间和对质量的影响，我现在没有更多能确定的。",
    ],
}


def run_scenario(name: str, turns: list[str], db_path: str) -> dict[str, object]:
    trace_names_before = {path.name for path in TRACES.glob("discuss-*.jsonl")}
    env = dict(os.environ)
    env["DOJO_LLM_MODEL"] = MODEL
    env["DOJO_SESSIONS"] = str(TRACES)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    command = [*COMMAND, db_path, "discuss"]
    pid, master = pty.fork()
    if pid == 0:
        os.chdir(ROOT)
        os.execvpe(command[0], command, env)

    original_terminal = termios.tcgetattr(master)
    tty.setraw(master)
    transcript = bytearray()
    pending = bytearray()
    marker = "你> ".encode("utf-8")
    turn = 0
    deadline = time.monotonic() + 600
    status = None
    eof_sent = False
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 1)
            if ready:
                try:
                    chunk = os.read(master, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                pending.extend(chunk)
                while marker in pending:
                    prompt_index = pending.index(marker)
                    transcript.extend(pending[:prompt_index])
                    del pending[:prompt_index + len(marker)]
                    transcript.extend(marker)
                    if turn < len(turns):
                        answer = turns[turn]
                        turn += 1
                        transcript.extend(answer.encode("utf-8") + b"\n")
                        os.write(master, answer.encode("utf-8") + b"\n")
                    else:
                        transcript.extend(b"<EOF>\n")
                        termios.tcsetattr(master, termios.TCSADRAIN, original_terminal)
                        os.write(master, b"\x04")
                        eof_sent = True
            waited, child_status = os.waitpid(pid, os.WNOHANG)
            if waited:
                status = child_status
                break
        else:
            termios.tcsetattr(master, termios.TCSADRAIN, original_terminal)
            os.write(master, b"\x04")
            eof_sent = True
            raise TimeoutError(f"{name} session exceeded the 600-second capture deadline")
    finally:
        transcript.extend(pending)
        try:
            os.close(master)
        except OSError:
            pass
        if status is None:
            _, status = os.waitpid(pid, 0)
        (EVIDENCE / f"{name}.terminal.txt").write_text(
            transcript.decode("utf-8", errors="replace"), encoding="utf-8",
        )

    exit_code = os.waitstatus_to_exitcode(status)
    traces = sorted(
        (path for path in TRACES.glob("discuss-*.jsonl") if path.name not in trace_names_before),
        key=lambda path: path.stat().st_mtime,
    )
    if len(traces) != 1:
        raise RuntimeError(f"{name}: expected one new trace, found {len(traces)}")
    records = [json.loads(line) for line in traces[0].read_text(encoding="utf-8").splitlines()]
    end = next((record for record in reversed(records) if record.get("event") == "session_end"), None)
    requests = end["requests_sent"] if end else 0
    result = {
        "scenario": name,
        "exit_code": exit_code,
        "turns_sent": turn,
        "requests_sent": requests,
        "session_end_reason": end.get("reason") if end else None,
        "saved_ids": end.get("saved", []) if end else [],
        "terminal": f"{name}.terminal.txt",
        "trace": str(traces[0].relative_to(EVIDENCE)),
        "eof_sent": eof_sent,
    }
    print(json.dumps(result, ensure_ascii=False))
    if exit_code != 0 or turn != len(turns) or end is None:
        raise RuntimeError(f"{name}: discussion did not finish normally")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, action="append", help="run only the selected scenario; repeat to select both")
    args = parser.parse_args()
    selected = args.scenario or list(SCENARIOS)
    if not os.environ.get("DOJO_LLM_BASE_URL", "").strip():
        print("blocked: DOJO_LLM_BASE_URL is not configured; no real model request was sent", file=sys.stderr)
        return 2
    TRACES.mkdir(mode=0o700, parents=True, exist_ok=True)
    TRACES.chmod(0o700)
    total_requests = 0
    with tempfile.TemporaryDirectory(prefix="dojo-m1.9-dialogue-") as temporary:
        db_path = str(Path(temporary) / "dojo.sqlite3")
        for name in selected:
            outcome = run_scenario(name, SCENARIOS[name], db_path)
            total_requests += int(outcome["requests_sent"])
            if total_requests > 25:
                raise RuntimeError("model request limit exceeded 25")
    print(json.dumps({"total_model_requests": total_requests, "model": MODEL}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

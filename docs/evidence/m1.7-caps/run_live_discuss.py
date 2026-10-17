"""Run one scripted, adaptive live discussion and retain the PTY transcript."""

from __future__ import annotations

import os
import pty
import select
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
COMMAND = [sys.executable, "-m", "dojo", "discuss"]
INPUTS = [
    "我发现自己有时会被模型表达的流畅和肯定说服，之后才想起它的证据来源和适用范围没有核验。",
    "我希望先看证据来源和适用条件，措辞听起来确定本身不能作为证据。",
    "对一条经验主张，我只能把它当成个人经验；没有独立材料时不该推广成普遍建议。",
    "保留它对本人场景的价值，但明确标出其他场景未经验证。",
    "我明确认可你刚才复述的这条具体、有边界的结论，请记录下来。",
]


def main() -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    pid, master = pty.fork()
    if pid == 0:
        os.chdir(ROOT)
        os.execvpe(COMMAND[0], COMMAND, env)

    transcript = bytearray()
    sent: list[str] = []
    pending = bytearray()
    marker = "你> ".encode("utf-8")
    turn = 0
    deadline = time.monotonic() + 900
    status = None
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
                transcript.extend(chunk)
                pending.extend(chunk)
                while marker in pending:
                    prompt_index = pending.index(marker)
                    segment = bytes(pending[:prompt_index]).decode("utf-8", errors="replace")
                    del pending[:prompt_index + len(marker)]
                    if "已写入本地草稿" in segment:
                        response = "<EOF after successful write>"
                        sent.append(response)
                        os.write(master, b"\x04")
                        continue
                    if "我先这样记下来，你看有没有要改的" in segment:
                        response = "是的，我明确认可你刚才复述的这条具体、有边界的结论，请记录下来。"
                    elif turn < len(INPUTS):
                        response = INPUTS[turn]
                    else:
                        response = "请保留适用范围和未知项，不要把单个经验推广成普遍事实。"
                    turn += 1
                    sent.append(response)
                    os.write(master, response.encode("utf-8") + b"\n")
            waited, child_status = os.waitpid(pid, os.WNOHANG)
            if waited:
                status = child_status
                break
        else:
            os.write(master, b"\x04")
            raise TimeoutError("live discussion exceeded the 900-second driver deadline")
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        if status is None:
            _, status = os.waitpid(pid, 0)
        (EVIDENCE / "discuss-transcript.txt").write_bytes(transcript)
        (EVIDENCE / "discuss-inputs.txt").write_text("\n".join(sent) + "\n", encoding="utf-8")

    return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    raise SystemExit(main())

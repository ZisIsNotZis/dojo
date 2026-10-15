"""Offline replay and provenance for the two recorded Luna responses."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from .storage import DojoError

EVIDENCE_DIRECTORY = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "conversation-demo-luna-v1"


RUNS = (
    {
        "label": "B（无道场候选上下文）",
        "run_id": "5e00e5f5-e288-487c-a60d-3d6f582b3abd",
        "input": "docs/packets/frozen-conversation-v1/target-no-dojo-b.md",
        "answer": "actual-answer-b.md",
        "summary": "强调当前资料不足以支持默认重试改为 3 并立即全量发布；列出幂等/重复副作用、重试语义、退避/总时限、负载放大和观测等需要先核实的风险。",
    },
    {
        "label": "C（含 Store 实际检索候选）",
        "run_id": "72ba1efa-eedc-42ae-b78c-8216839cc900",
        "input": "docs/packets/frozen-conversation-v1/target-with-retrieved-dojo-c.md",
        "answer": "actual-answer-c.md",
        "summary": "引用 S01/S02/S03/S04 和来源 ID，保留支持范围/fixture 条件；指出 Forge/S04 不构成当前项目证据，p5 mock 不能推出 p4 已覆盖。",
    },
)


def run_compare(*, full: bool = False, output: TextIO) -> None:
    """Display a read-only replay; never contacts a model or changes evidence."""
    texts: list[tuple[dict[str, str], str]] = []
    for run in RUNS:
        path = EVIDENCE_DIRECTORY / run["answer"]
        try:
            text = path.read_bytes().decode("utf-8")
        except OSError as exc:
            raise DojoError(f"saved comparison answer is unavailable: {path.name}") from exc
        except UnicodeDecodeError as exc:
            raise DojoError(f"saved comparison answer is not UTF-8: {path.name}") from exc
        texts.append((run, text))

    print("真实 Luna 回答：离线回放（不联网、不重新生成）", file=output)
    print("这是旧 editor-bridge 评价的归档，不是当前陌生人方法论故事，也不代表当前 demo 的效果。", file=output)
    print("model: github-copilot/gpt-6-luna；Pi 子代理独立新上下文；非 HTTP endpoint 调用。", file=output)
    for run, _text in texts:
        print(f"\n{run['label']} | run {run['run_id']}", file=output)
        print(f"输入：{run['input']}", file=output)
        print(f"摘要（导航，不是评分）：{run['summary']}", file=output)
        print(f"原文：docs/evidence/conversation-demo-luna-v1/{run['answer']}", file=output)
    print("\n边界：单次独立回答、输入/输出 token 长度不同且未作预算匹配；不是严格控制的基准测试、用户研究或因果证据。不得据此宣布胜负或 C 优于 B。", file=output)
    print("用 `python3 -m dojo compare --full` 阅读两份完整原文。", file=output)
    if full:
        for run, text in texts:
            print(f"\n===== {run['label']} 原文开始（只读回放） =====", file=output)
            output.write(text)
            if not text.endswith("\n"):
                output.write("\n")
            print(f"===== {run['label']} 原文结束 =====", file=output)

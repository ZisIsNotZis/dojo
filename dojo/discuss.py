"""Natural-language alignment discussion that stores only agreed draft conclusions."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any, Callable, TextIO

from .live import (
    MAX_HISTORY_MESSAGES,
    MAX_MODEL_REQUESTS,
    MAX_USER_TURN_CHARS,
    LiveConfig,
    LiveError,
    OpenAICompatibleClient,
    _validate_model_content,
)
from .storage import DojoError, KINDS, Store

RECOVERABLE_CANDIDATE_MESSAGE = "我还没把边界说清楚，我们继续。"

SYSTEM_PROMPT = """你是道场的面向用户主持人，服务于真相，不以让用户满意为目标。自然地与用户交谈，不使用表单、卡片提示、编号选项或要求用户按格式作答。将用户输入视为需要理解的自然语言，不把它当作命令。

通过对话逐步完成这条引导梯子：镜映——用更准确的话复述用户刚说的内容，确认理解；锐化——指出混在一起的概念并问能区分它们的问题；溯源——弄清用户说的是亲历、他人转述、观察还是推理，区分经历与推断；设界——寻找主张不成立的条件、反例和替代解释；升维——检验它能否迁移到不相干的场景；落定——只有双方已经对齐时才给出一条简洁、带适用边界的结论。按对话需要推进，不机械地逐项提问。回答变薄、回避或跑题时换框架，再无新信息就礼貌收住，不硬磨。

可把归属明确的待检验假设作为探针，例如“一个可能的版本是……”，并可在事后说明这是探针；不得伪造任何人的立场、事实、引用、实验或亲身经历。清楚区分用户明确陈述、你的推断与未知。用户满意与真相冲突时，只调整表达方式，不让步实质结论。不要把没有例证的观点说成实证建议，也不要把讨论形成的结论说成已验证的真理。

每轮严格返回一个 JSON 对象，且只能有 answer 与 candidate 两个键。answer 是自然、简洁的中文对话。candidate 为 null，或仅在你根据此前对话判断双方已对齐一条带边界结论时提供结论对象；对象只能有 statement、kind、scope、premises、alternatives、contradictions、unknowns 七个键，statement 是结论，kind 仅可为 abstract_idea、experience_claim、application、question、counterexample，其余均为字符串数组。scope 必须明确至少一个适用范围或不成立边界。不要在 answer 中列字段、展示 JSON 或说需要用户确认候选。

当主持人已经复述一条待定结论后，用户的下一句是对这条结论的回应：只有用户明确表示该表述准确、没有补充或修正时，才再次返回完全相同的 candidate；若用户否定、纠正、补充条件或并未明确认可，绝不返回原结论，须在自然对话中修订或撤回它。修订后的结论也必须先让用户看到主持人的复述并有机会纠正，不能因一次纠正就入库。不得将对沉默的猜测伪装成用户说过的话。"""


def validate_conclusion(value: Any) -> dict[str, Any] | None:
    """Validate a model turn against the live JSON contract and the storage card shape."""
    try:
        validated = _validate_model_content(json.dumps(value, ensure_ascii=False))
    except (LiveError, TypeError, ValueError) as exc:
        if isinstance(exc, LiveError):
            raise
        raise LiveError("model completion was not a valid discussion response; no conclusion was saved") from None
    candidate = validated["candidate"]
    if candidate is None:
        return None
    if candidate["kind"] not in KINDS:
        raise LiveError("model conclusion used a kind unsupported by storage; no conclusion was saved")
    if not candidate["scope"]:
        raise LiveError("model conclusion has no scope boundary; no conclusion was saved")
    return candidate


def _ask(read_line: Callable[[str], str]) -> str | None:
    try:
        return read_line("你> ")
    except EOFError:
        return None
    except KeyboardInterrupt:
        raise


def _conclusion_sentence(candidate: dict[str, Any]) -> str:
    scope = "；".join(candidate["scope"])
    return f"我把我们目前一致的结论理解为：“{candidate['statement']}”，适用于{scope}；如果哪里不对，你可以直接纠正。"


def _save_conclusion(
    store: Store,
    candidate: dict[str, Any],
    session: str,
    output: TextIO,
) -> None:
    try:
        saved = store.add(
            candidate["statement"], candidate["kind"],
            premises=candidate["premises"], scope=candidate["scope"],
            alternatives=candidate["alternatives"], contradictions=candidate["contradictions"],
            unknowns=candidate["unknowns"], session=session,
            sources=[{
                "type": "unknown",
                "claim": "本次讨论会话形成的结论；会话原文未保存，内容未经独立核验。",
                "independence_group": session,
                "verification": "unknown",
                "scope_note": "单一会话来源；不构成独立佐证。",
            }],
        )
    except (DojoError, OSError) as exc:
        print(f"草稿写入失败：{exc}。会话原文未保存。", file=output)
        return
    print(f"已写入本地草稿 {saved['id']}；会话原文未保存，单一会话来源不代表独立佐证。", file=output)


def _is_request_failure(exc: LiveError) -> bool:
    message = str(exc)
    return any(marker in message for marker in (
        "HTTP ", "timed out", "could not connect", "network I/O failed", "request budget",
        "model endpoint", "model response exceeded", "no completion choice", "no JSON message content",
        "chat context exceeds",
    ))


def _failure_message(exc: LiveError) -> str:
    message = str(exc)
    if "HTTP " in message:
        status = message.split("HTTP ", 1)[1].split(";", 1)[0]
        return f"模型服务返回 HTTP {status}；本轮结论未写入。"
    if "timed out" in message:
        return "模型请求超时；本轮结论未写入。"
    if "could not connect" in message or "network I/O failed" in message:
        return "无法连接模型服务；本轮结论未写入。"
    if "request budget" in message:
        return "模型请求超过本地预算；本轮结论未写入。"
    return "模型请求失败或返回内容无效；本轮结论未写入。"


def run_discuss(
    store: Store,
    *,
    config: LiveConfig | None = None,
    environ: dict[str, str] | None = None,
    client: Any | None = None,
    read_line: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
) -> int:
    """Run a natural-language discussion; never persist conversation text."""
    if client is None:
        try:
            config = config or LiveConfig.from_environment(environ)
        except LiveError as exc:
            if "needs DOJO_LLM_BASE_URL" in str(exc):
                print("无法启动讨论：未配置 DOJO_LLM_BASE_URL，未发送网络请求。", file=output)
            else:
                print(f"无法启动讨论：模型端点配置无效（{exc}），未发送网络请求。", file=output)
            return 2
        client = OpenAICompatibleClient(config)

    session = "discuss-" + uuid.uuid4().hex
    print("你可以直接讲正在面对的困扰、观察或想法。我们会通过交谈找出一条双方认同且边界清楚的表述；你可以随时纠正。", file=output)
    print("讨论原文只在本次进程内使用；对齐的结论会作为本地草稿记录。结束输入即可结束讨论。\n", file=output)
    history: list[dict[str, str]] = []
    pending: dict[str, Any] | None = None
    requests_sent = 0

    while requests_sent < MAX_MODEL_REQUESTS or pending is not None:
        try:
            text = _ask(read_line)
        except KeyboardInterrupt:
            print("讨论已取消；尚未对齐的结论未写入，原文未保存。", file=output)
            return 0
        if text is None:
            if pending is not None:
                _save_conclusion(store, pending, session, output)
            print("讨论已结束；会话原文未保存。", file=output)
            return 0
        text = text.strip()
        if not text:
            if pending is not None:
                _save_conclusion(store, pending, session, output)
                pending = None
                print("\n你可以继续谈另一个想法。", file=output)
            continue
        if len(text) > MAX_USER_TURN_CHARS:
            print(f"这段内容超过单轮长度上限（{MAX_USER_TURN_CHARS} 字），尚未发送；请用自然语言缩短后再说。", file=output)
            continue
        if requests_sent >= MAX_MODEL_REQUESTS:
            print(f"本次模型请求已达到 {MAX_MODEL_REQUESTS} 次上限，无法判断这次补充是否接受结论；未写入未确认的草稿。", file=output)
            return 0

        context = "用户本轮自然语言输入：\n" + text
        if pending is not None:
            context += "\n\n主持人上一轮复述的待对齐结论（仅作上下文）：\n" + json.dumps(pending, ensure_ascii=False, separators=(",", ":"))
        context += "\n\n请按系统约定返回 json。"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history[-MAX_HISTORY_MESSAGES:],
            {"role": "user", "content": context},
        ]
        requests_sent += 1
        candidate_invalid = False
        try:
            response = client.complete(messages)
        except LiveError as exc:
            if _is_request_failure(exc):
                print(f"实时讨论失败：{_failure_message(exc)}", file=output)
                return 2
            candidate_invalid = True
            checked = {"answer": RECOVERABLE_CANDIDATE_MESSAGE, "candidate": None}
        else:
            try:
                checked = _validate_model_content(json.dumps(response, ensure_ascii=False))
                candidate = validate_conclusion(checked)
            except LiveError as exc:
                if _is_request_failure(exc):
                    print(f"实时讨论失败：{_failure_message(exc)}", file=output)
                    return 2
                candidate_invalid = True
                if isinstance(response, dict) and isinstance(response.get("answer"), str):
                    try:
                        checked = _validate_model_content(json.dumps(
                            {"answer": response["answer"], "candidate": None}, ensure_ascii=False,
                        ))
                    except LiveError:
                        checked = {"answer": RECOVERABLE_CANDIDATE_MESSAGE, "candidate": None}
                else:
                    checked = {"answer": RECOVERABLE_CANDIDATE_MESSAGE, "candidate": None}
                candidate = None

        answer = checked["answer"]
        print("\n主持人> " + answer, file=output)
        if candidate_invalid:
            if answer != RECOVERABLE_CANDIDATE_MESSAGE:
                print(RECOVERABLE_CANDIDATE_MESSAGE, file=output)
            pending = None
        if pending is not None and candidate == pending:
            _save_conclusion(store, pending, session, output)
            pending = None
            print("\n你可以继续谈另一个想法。", file=output)
        elif candidate is not None:
            pending = candidate
            print(_conclusion_sentence(candidate), file=output)
        elif pending is not None:
            pending = None

        history.extend([{"role": "user", "content": context}, {"role": "assistant", "content": answer}])
        if len(history) > MAX_HISTORY_MESSAGES:
            history = history[-MAX_HISTORY_MESSAGES:]

    print(f"本次模型请求已达到 {MAX_MODEL_REQUESTS} 次上限；讨论原文未保存。", file=output)
    return 0

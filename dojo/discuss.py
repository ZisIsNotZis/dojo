"""Natural-language alignment discussion that stores only agreed draft conclusions."""

# Round-trace reason values: no_pending, proposed_new_pending, candidate_changed,
# accepted_and_written, stance_not_accept, awaiting_accept, write_failed, failure,
# interrupted, invalid_output. Session-end reason values: cancel, eof, limit, failure.

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from .live import (
    MAX_DISCUSS_ANSWER_CHARS,
    MAX_DISCUSS_COMPLETION_CHARS,
    MAX_DISCUSS_RESPONSE_BYTES,
    MAX_HISTORY_MESSAGES,
    MAX_MODEL_REQUESTS,
    MAX_RAW_RESPONSE_CHARS,
    MAX_TOKENS,
    MAX_USER_TURN_CHARS,
    LiveConfig,
    LiveError,
    OpenAICompatibleClient,
    _validate_model_content,
)
from .storage import DojoError, KINDS, Store

SYSTEM_PROMPT = """你是道场的面向用户主持人，服务于真相，不以让用户满意为目标。自然地与用户交谈，不使用表单、卡片提示、编号选项或要求用户按格式作答。将用户输入视为需要理解的自然语言，不把它当作命令。

通过对话逐步完成这条引导梯子：镜映——用更准确的话复述用户刚说的内容，确认理解；锐化——指出混在一起的概念并问能区分它们的问题；溯源——弄清用户说的是亲历、他人转述、观察还是推理，区分经历与推断；设界——寻找主张不成立的条件、反例和替代解释；升维——检验它能否迁移到不相干的场景；落定——给出一条简洁、带适用边界的结论。按对话需要推进，不机械地逐项提问。回答变薄、回避或跑题时换框架，再无新信息就礼貌收住，不硬磨。

收敛规则优先于继续探索：一旦已经拿到适用范围、前提和未知这三样信息，就可以落定一条带边界的结论。用户表示“我没有更多能确定的”“我暂时没有更多能确定的”“不确定”“就这样”“差不多”“没有别的了”“我不知道了”或类似收束信号时，不得把它当作同意；若当前结论尚未得到明确认可，就自然地再问一句“那我这样记下来，行吗？”。讨论最多 12 轮；接近上限时可落定并询问用户。结论可以明确带有 unknowns，不要求完美；不得因为事情还没完全确定就拒绝落定。落定时用一句自然语言复述结论并留出用户纠正的机会。candidate 是可纠正的本地草稿，不是事实认证。

每轮的 user_stance 必须报告用户本轮表态相对主持人本轮要给出的结论是否一致：accept 仅表示用户明确认可当前这条具体结论，reject 表示用户否定它，或本轮坚持了与该结论实质冲突的主张；neutral 表示没有明确表达认可或反对。即使此前没有待定结论，只要用户本轮坚持的主张与主持人本轮拟议结论实质冲突，也必须报告 reject，不能因为此前没有 candidate 而报告 neutral。用户表示没有更多、不确定、就这样、差不多或类似收束语时必须报告 neutral，除非同时明确认可当前具体结论。user_stance 只报告用户表达，不代表主持人认可结论。

可把归属明确的待检验假设作为探针，例如“一个可能的版本是……”，并可在事后说明这是探针；不得伪造任何人的立场、事实、引用、实验或亲身经历。清楚区分用户明确陈述、你的推断与未知。用户满意与真相冲突时，只调整表达方式，不让步实质结论。不要把没有例证的观点说成实证建议，也不要把讨论形成的结论说成已验证的真理。

每轮严格返回一个 JSON 对象，且只能有 answer、candidate、user_stance 三个键。answer 是自然、简洁的中文对话。user_stance 必须且只能为 accept、reject、neutral 之一，报告用户本轮表态与主持人本轮拟议结论是否一致，即使此前没有待定结论也要作出判断。candidate 为 null，或一条已经落定、适合交给用户复核的带边界拟议结论；它是可纠正的本地草稿，不表示用户已明确认可或主张已被证实。对象只能有 statement、kind、scope、premises、alternatives、contradictions、unknowns 七个键，statement 是结论，kind 仅可为 abstract_idea、experience_claim、application、question、counterexample，其余均为字符串数组。scope 必须明确至少一个适用范围或不成立边界。不要在 answer 中列字段、展示 JSON 或用机制语言要求确认候选；可以自然询问“那我这样记下来，行吗？”。

当主持人已经复述一条待定结论后，用户的下一句是对这条结论的回应：只有用户明确认可当前这条具体结论时，才再次返回完全相同的 candidate；不得改写、扩展或另造一个相似 candidate。用户没有更多、不确定、就这样、差不多或类似收束语不是认可，须自然地询问“那我这样记下来，行吗？”。用户若否定、纠正或补充条件，不返回旧 candidate，须在自然对话中修订或撤回它。修订后的结论也必须先让用户看到主持人的复述并有机会纠正。不得将空行、EOF、取消或沉默当作用户回应。"""


def validate_conclusion(
    value: Any,
    *,
    max_answer_chars: int = MAX_DISCUSS_ANSWER_CHARS,
) -> dict[str, Any] | None:
    """Validate a model turn against the live JSON contract and the storage card shape."""
    try:
        validated = _validate_model_content(
            json.dumps(value, ensure_ascii=False),
            allowed_extra_keys=frozenset({"user_stance"}), max_answer_chars=max_answer_chars,
        )
    except (LiveError, TypeError, ValueError) as exc:
        if isinstance(exc, LiveError):
            raise
        raise LiveError("model completion was not a valid discussion response; no conclusion was saved", kind="schema_violation") from None
    if validated.get("user_stance") not in {"accept", "reject", "neutral"}:
        raise LiveError("model conclusion omitted or invalid user_stance; no conclusion was saved", kind="schema_violation")
    candidate = validated["candidate"]
    if candidate is None:
        return None
    if candidate["kind"] not in KINDS:
        raise LiveError("model conclusion used a kind unsupported by storage; no conclusion was saved", kind="schema_violation")
    if not candidate["scope"]:
        raise LiveError("model conclusion has no scope boundary; no conclusion was saved", kind="schema_violation")
    return candidate


def _ask(read_line: Callable[[str], str]) -> str | None:
    try:
        return read_line("你> ")
    except EOFError:
        return None
    except KeyboardInterrupt:
        raise


def _conclusion_sentence(candidate: dict[str, Any]) -> str:
    scope = "；".join(candidate["scope"]).rstrip("。．.!！?？;；")
    return f"我先这样记下来，你看有没有要改的：『{candidate['statement']}』；适用范围是{scope}。"


def _save_conclusion(
    store: Store,
    candidate: dict[str, Any],
    session: str,
    output: TextIO,
    *,
    trace_enabled: bool,
) -> str | None:
    try:
        saved = store.add(
            candidate["statement"], candidate["kind"],
            premises=candidate["premises"], scope=candidate["scope"],
            alternatives=candidate["alternatives"], contradictions=candidate["contradictions"],
            unknowns=candidate["unknowns"], session=session,
            sources=[{
                "type": "unknown",
                "claim": (
                    "本次讨论会话形成的结论；完整会话原文保存在本地轨迹文件，内容未经独立核验。"
                    if trace_enabled else "本次讨论会话形成的结论；会话原文未保存，内容未经独立核验。"
                ),
                "independence_group": session,
                "verification": "unknown",
                "scope_note": "单一会话来源；不构成独立佐证。",
            }],
        )
    except (DojoError, OSError) as exc:
        print(f"草稿写入失败：{exc}。", file=output)
        return None
    transcript_note = "轨迹保存在本地会话文件" if trace_enabled else "会话原文未保存"
    print(f"已写入本地草稿 {saved['id']}；{transcript_note}，单一会话来源不代表独立佐证。", file=output)
    return saved["id"]


def _error_kind(exc: LiveError) -> str:
    if exc.kind != "unknown":
        return exc.kind
    # Keep diagnostics useful for older injected clients that raised untyped LiveError.
    message = str(exc)
    if "HTTP " in message:
        return "http_error"
    if "timed out" in message:
        return "timeout"
    if "could not connect" in message or "network I/O failed" in message:
        return "connect"
    if "not strict JSON" in message:
        return "not_json"
    if "schema" in message or "conclusion" in message:
        return "schema_violation"
    return "unknown"


def _trace_error(exc: LiveError) -> dict[str, Any]:
    return {
        "kind": _error_kind(exc),
        "http_status": exc.http_status,
        "finish_reason": exc.finish_reason,
        "detail": exc.detail[:1_000],
    }


def _user_error_message(error: dict[str, Any]) -> str:
    kind = error["kind"]
    if kind == "truncated":
        return "模型这次的输出被截断了，自动重试仍未成功；这轮没有形成结论，你可以继续。"
    if kind == "empty_content":
        return "模型这次没有返回内容，自动重试仍未成功；这轮没有形成结论，你可以继续。"
    if kind in {"not_json", "schema_violation"}:
        return "模型这次返回的格式不合法，自动重试仍未成功；这轮没有形成结论，你可以继续。"
    if kind == "http_error":
        status = error["http_status"]
        if status is not None and status < 500:
            return f"模型服务返回 HTTP {status}；端点配置或请求契约有误，讨论已结束。"
        return f"模型服务连续返回 HTTP {status or '5xx'}，暂时不可用；讨论已结束。"
    if kind == "timeout":
        return "模型请求连续超时，讨论已结束；请检查模型服务后重新运行。"
    if kind == "connect":
        return "连续无法连接模型服务，讨论已结束；请检查模型服务后重新运行。"
    return "模型这次返回的内容无法识别，自动重试仍未成功；这轮没有形成结论，你可以继续。"


def _attempt_record(raw_response: str, finish_reason: str | None, error: dict[str, Any] | None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "raw_response": raw_response[:MAX_RAW_RESPONSE_CHARS],
        "finish_reason": finish_reason,
    }
    if error is not None:
        record["error"] = error
    return record


class _SessionTrace:
    def __init__(self, path: Path, output: TextIO, *, resume: bool = False):
        self.path = path
        self.output = output
        self.file = None
        self.warned = False
        descriptor = None
        try:
            if resume:
                flags = os.O_WRONLY | os.O_APPEND
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(path, flags)
                self.file = os.fdopen(descriptor, "a", encoding="utf-8")
            else:
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.parent.chmod(0o700)
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.fchmod(descriptor, 0o600)
                self.file = os.fdopen(descriptor, "w", encoding="utf-8")
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            self._warn(exc)

    def _warn(self, exc: OSError) -> None:
        if not self.warned:
            print(f"会话轨迹写入失败（{self.path}）：{exc}。讨论将继续，但轨迹可能不完整。", file=self.output)
            self.warned = True
        if self.file is not None:
            try:
                self.file.close()
            except OSError:
                pass
            self.file = None

    def append(self, value: dict[str, Any]) -> None:
        if self.file is None:
            return
        try:
            self.file.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.file.flush()
        except OSError as exc:
            self._warn(exc)

    def close(self) -> None:
        if self.file is not None:
            try:
                self.file.close()
            except OSError as exc:
                self._warn(exc)
            self.file = None


def _trace_path(store: Store, session: str, environ: dict[str, str] | None) -> Path:
    values = os.environ if environ is None else environ
    configured = values.get("DOJO_SESSIONS", "").strip()
    directory = Path(configured).expanduser() if configured else store.path.expanduser().resolve().parent / "sessions"
    return directory / f"{session}.jsonl"


def _load_resume_trace(path: Path) -> dict[str, Any]:
    """Validate a program-shaped discussion trace without opening it for writing."""
    allowed_reasons = {
        "no_pending", "proposed_new_pending", "candidate_changed", "accepted_and_written",
        "stance_not_accept", "awaiting_accept", "write_failed", "failure", "interrupted",
        "invalid_output",
    }
    allowed_kinds = {
        "http_error", "timeout", "connect", "empty_content", "not_json",
        "schema_violation", "truncated", "unknown",
    }
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("轨迹路径不是普通文件")
        session = path.stem
        if not session.startswith("discuss-") or len(session) != len("discuss-") + 32:
            raise ValueError("轨迹文件名不是本程序的会话 ID 格式")
        uuid.UUID(hex=session.removeprefix("discuss-"))
        contents = path.read_text(encoding="utf-8")
        if not contents.endswith("\n"):
            raise ValueError("轨迹末尾记录不完整")
        lines = contents.splitlines()
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"无法续跑轨迹：{exc}") from None
    if not lines:
        raise ValueError("无法续跑轨迹：文件为空或格式不符")
    records: list[dict[str, Any]] = []
    try:
        for line in lines:
            if not line.strip():
                raise ValueError("轨迹含空行")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("轨迹每行必须是 JSON 对象")
            if value.get("event") == "session_end":
                if value.get("reason") not in {"cancel", "eof", "limit", "failure"} or not isinstance(value.get("saved"), list):
                    raise ValueError("会话结束记录不完整")
                if not all(isinstance(identifier, str) for identifier in value["saved"]):
                    raise ValueError("会话写入记录无效")
                if not isinstance(value.get("requests_sent"), int) or value["requests_sent"] < 0:
                    raise ValueError("会话请求计数无效")
            else:
                required = {
                    "seq", "at", "user", "answer", "candidate", "stance", "decision",
                    "reason", "requests_sent", "pending_after",
                }
                if not required.issubset(value):
                    raise ValueError("讨论轮记录缺少必要字段")
                if not isinstance(value["seq"], int) or value["seq"] < 1:
                    raise ValueError("讨论轮序号无效")
                if not isinstance(value["user"], str) or not isinstance(value["requests_sent"], int) or value["requests_sent"] < 0:
                    raise ValueError("讨论轮输入或请求计数无效")
                if not isinstance(value["at"], str):
                    raise ValueError("讨论轮时间无效")
                datetime.fromisoformat(value["at"])
                if value["answer"] is not None and not isinstance(value["answer"], str):
                    raise ValueError("讨论轮回答无效")
                if value["candidate"] is not None:
                    if not isinstance(value["candidate"], dict):
                        raise ValueError("讨论轮候选无效")
                    try:
                        validate_conclusion({"answer": "resume", "candidate": value["candidate"], "user_stance": "neutral"})
                    except LiveError:
                        raise ValueError("讨论轮候选不符合本程序契约") from None
                if value.get("stance") not in {None, "accept", "reject", "neutral"}:
                    raise ValueError("讨论轮立场无效")
                if value["reason"] not in allowed_reasons or value["decision"] not in {"none", "written"}:
                    raise ValueError("讨论轮决定或理由不属于本程序格式")
                if value["pending_after"] is not None and not isinstance(value["pending_after"], (str, dict)):
                    raise ValueError("待定候选记录无效")
                error = value.get("error")
                if error is not None and (
                    not isinstance(error, dict)
                    or set(error) != {"kind", "http_status", "finish_reason", "detail"}
                    or error.get("kind") not in allowed_kinds
                    or (error.get("http_status") is not None and not isinstance(error.get("http_status"), int))
                    or (error.get("finish_reason") is not None and not isinstance(error.get("finish_reason"), str))
                    or not isinstance(error.get("detail"), str)
                ):
                    raise ValueError("错误诊断记录无效")
                if value.get("raw_response") is not None and (
                    not isinstance(value.get("raw_response"), str)
                    or len(value["raw_response"]) > MAX_RAW_RESPONSE_CHARS
                ):
                    raise ValueError("原始响应记录无效")
                if value.get("finish_reason") is not None and not isinstance(value.get("finish_reason"), str):
                    raise ValueError("finish_reason 记录无效")
            records.append(value)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"无法续跑轨迹：格式不符（{exc}）") from None
    rounds = [record for record in records if record.get("event") != "session_end"]
    ends = [record for record in records if record.get("event") == "session_end"]
    if not rounds or not ends or records[-1].get("event") != "session_end":
        raise ValueError("无法续跑轨迹：缺少本程序的讨论轮或终止记录")

    history: list[dict[str, str]] = []
    for row in rounds:
        if isinstance(row["answer"], str):
            history.extend([
                {"role": "user", "content": row["user"]},
                {"role": "assistant", "content": row["answer"]},
            ])
    history = history[-MAX_HISTORY_MESSAGES:]
    last_round = rounds[-1]
    pending_value = last_round.get("pending_after")
    pending: dict[str, Any] | None = None
    if isinstance(pending_value, dict):
        pending = pending_value
    elif isinstance(pending_value, str):
        pending = next(
            (row["candidate"] for row in reversed(rounds)
             if isinstance(row["candidate"], dict) and row["candidate"].get("statement") == pending_value),
            None,
        )
    elif "pending_after" not in last_round and isinstance(last_round["candidate"], dict):
        pending = last_round["candidate"]
    if pending is not None:
        try:
            pending = validate_conclusion({"answer": "resume", "candidate": pending, "user_stance": "neutral"})
        except LiveError:
            raise ValueError("无法续跑轨迹：待定候选不符合本程序契约") from None
    saved = list(dict.fromkeys(identifier for row in ends for identifier in row["saved"]))
    requests_sent = max(
        [row["requests_sent"] for row in rounds + ends] or [0],
    )
    resume_input = (
        last_round["user"]
        if last_round["answer"] is None and last_round["reason"] in {"failure", "invalid_output", "interrupted"}
        else None
    )
    return {
        "session": session, "history": history, "pending": pending,
        "saved": saved, "seq": max(row["seq"] for row in rounds),
        "requests_sent": requests_sent, "resume_input": resume_input,
    }


def run_discuss(
    store: Store,
    *,
    config: LiveConfig | None = None,
    environ: dict[str, str] | None = None,
    client: Any | None = None,
    read_line: Callable[[str], str] = input,
    output: TextIO = sys.stdout,
    no_trace: bool = False,
    resume: Path | None = None,
) -> int:
    """Run or resume a natural-language discussion with an append-only local trace."""
    if no_trace and resume is not None:
        print("无法续跑：--resume 与 --no-trace 不能同时使用。", file=output)
        return 2
    resume_state = None
    if resume is not None:
        try:
            resume_state = _load_resume_trace(resume.expanduser())
        except ValueError as exc:
            print(str(exc), file=output)
            return 2
    if client is None:
        try:
            config = config or LiveConfig.from_environment(environ)
        except LiveError as exc:
            if "needs DOJO_LLM_BASE_URL" in str(exc):
                print("无法启动讨论：未配置 DOJO_LLM_BASE_URL，未发送网络请求。", file=output)
            else:
                print(f"无法启动讨论：模型端点配置无效（{exc}），未发送网络请求。", file=output)
            return 2
        client = OpenAICompatibleClient(
            config,
            allowed_extra_keys=frozenset({"user_stance"}),
            max_answer_chars=MAX_DISCUSS_ANSWER_CHARS,
            max_completion_chars=MAX_DISCUSS_COMPLETION_CHARS,
            max_response_bytes=MAX_DISCUSS_RESPONSE_BYTES,
            max_tokens=MAX_TOKENS,
        )

    if resume_state is None:
        session = "discuss-" + uuid.uuid4().hex
        trace = None if no_trace else _SessionTrace(_trace_path(store, session, environ), output)
        history: list[dict[str, str]] = []
        pending: dict[str, Any] | None = None
        requests_sent = 0
        saved_ids: list[str] = []
        seq = 0
        next_text = None
    else:
        session = resume_state["session"]
        trace = _SessionTrace(resume.expanduser(), output, resume=True)
        if trace.file is None:
            print("无法续跑：无法以追加模式打开原轨迹。", file=output)
            return 2
        history = resume_state["history"]
        pending = resume_state["pending"]
        requests_sent = resume_state["requests_sent"]
        saved_ids = resume_state["saved"]
        seq = resume_state["seq"]
        next_text = resume_state["resume_input"]
        print(f"正在续跑会话 {session}；历史与待定候选已从原轨迹恢复。", file=output)
    trace_path = trace.path if trace is not None else None
    if trace_path is None:
        print("会话轨迹已关闭（--no-trace）；本场不会保存会话原文。", file=output)
    elif resume_state is None:
        print(f"本场会话轨迹：{trace_path}", file=output)
    else:
        print(f"继续追加同一轨迹：{trace_path}", file=output)
    print("你可以直接讲正在面对的困扰、观察或想法。我们会通过交谈找出一条双方认同且边界清楚的表述；你可以随时纠正。", file=output)
    trace_is_open = trace is not None and trace.file is not None
    if trace_path is None:
        print("结论会写入本地草稿；结束输入即可结束讨论。\n", file=output)
    elif trace_is_open:
        print("会话原文仅保存在本地轨迹文件；结论会写入本地草稿。结束输入即可结束讨论。\n", file=output)
    else:
        print("会话轨迹不可用，本场原文不会被轨迹保存；结论会写入本地草稿。结束输入即可结束讨论。\n", file=output)

    def record_round(value: dict[str, Any]) -> None:
        if trace is not None:
            trace.append(value)

    def finish(reason: str, code: int = 0) -> int:
        if trace is not None:
            trace.append({
                "event": "session_end", "reason": reason, "saved": saved_ids,
                "requests_sent": requests_sent,
            })
            trace.close()
            print(f"本场会话轨迹：{trace_path}", file=output)
        else:
            print("本场会话轨迹：已关闭（--no-trace）。", file=output)
        return code

    while True:
        if next_text is not None:
            original_text = next_text
            next_text = None
            print("已重试轨迹中尚未得到回答的上一轮输入。", file=output)
        else:
            try:
                original_text = _ask(read_line)
            except KeyboardInterrupt:
                print("讨论已取消；尚未明确同意的结论未写入。", file=output)
                return finish("cancel")
        if original_text is None:
            if pending is not None:
                print("讨论在你明确同意前结束，这条结论未写入。", file=output)
            print("讨论已结束。", file=output)
            return finish("eof")
        text = original_text.strip()
        if not text:
            continue
        if len(text) > MAX_USER_TURN_CHARS:
            print(f"这段内容超过单轮长度上限（{MAX_USER_TURN_CHARS} 字），尚未发送；请用自然语言缩短后再说。", file=output)
            continue
        if requests_sent >= MAX_MODEL_REQUESTS:
            print(f"本次模型请求已达到 {MAX_MODEL_REQUESTS} 次上限；尚未明确同意的结论未写入。", file=output)
            return finish("limit")

        round_number = seq + 1
        seq += 1
        context = f"本次讨论第 {round_number} 轮 / 最多 {MAX_MODEL_REQUESTS} 次模型请求。\n"
        if round_number > 8:
            context += "轮次已接近上限，请尽快落定当前带边界的结论，保留未知项，不要继续追问。\n"
        context += "\n用户本轮自然语言输入：\n" + text
        if pending is not None:
            context += "\n\n主持人上一轮复述的待对齐结论（仅作上下文）：\n" + json.dumps(pending, ensure_ascii=False, separators=(",", ":"))
            context += "\n\n写入约束：只有用户本轮明确认可这条具体结论时才报告 user_stance=accept，并原样返回完全相同的 candidate；没有更多、不确定或类似收束语必须是 neutral，并自然询问“那我这样记下来，行吗？”。纠正或反对时不得返回旧 candidate。"
        context += "\n\n请按系统约定返回 json。"
        base_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history[-MAX_HISTORY_MESSAGES:],
            {"role": "user", "content": context},
        ]
        invalid_retries = 0
        transient_retries = 0
        consecutive_connection_failures = 0
        attempts: list[dict[str, Any]] = []
        final_error: LiveError | None = None
        final_error_record: dict[str, Any] | None = None
        response: Any = None
        checked: dict[str, Any] | None = None
        candidate: dict[str, Any] | None = None
        raw_response = ""
        finish_reason: str | None = None
        terminal_failure = False
        while requests_sent < MAX_MODEL_REQUESTS:
            messages = [dict(message) for message in base_messages]
            if invalid_retries:
                messages[-1]["content"] += (
                    "\n\n纠正指令：上一次返回未通过约定的 JSON 契约；请只返回一个合法 JSON 对象，不要代码块围栏。"
                )
            requests_sent += 1
            try:
                response = client.complete(messages)
                if isinstance(response, dict):
                    finish_reason = response.get("finish_reason") if isinstance(response.get("finish_reason"), str) else None
                    raw_response = response.get("raw_response") if isinstance(response.get("raw_response"), str) else ""
                    model_value = {key: value for key, value in response.items() if key not in {"finish_reason", "raw_response"}}
                    if not raw_response:
                        raw_response = json.dumps(model_value, ensure_ascii=False)
                else:
                    finish_reason = None
                    model_value = response
                    raw_response = json.dumps(response, ensure_ascii=False, default=str)
                raw_response = raw_response[:MAX_RAW_RESPONSE_CHARS]
                if finish_reason == "length":
                    raise LiveError(
                        "model response was truncated at the output token limit; no candidate was saved",
                        kind="truncated", finish_reason=finish_reason, raw_response=raw_response,
                    )
                checked = _validate_model_content(
                    json.dumps(model_value, ensure_ascii=False),
                    allowed_extra_keys=frozenset({"user_stance"}),
                    max_answer_chars=MAX_DISCUSS_ANSWER_CHARS,
                    finish_reason=finish_reason,
                    raw_response=raw_response,
                )
                candidate = validate_conclusion(checked)
                consecutive_connection_failures = 0
                final_error = None
                final_error_record = None
                attempts.append(_attempt_record(raw_response, finish_reason, None))
                break
            except KeyboardInterrupt:
                interrupted_error = None
                if attempts:
                    raw_response = attempts[-1]["raw_response"]
                    finish_reason = attempts[-1]["finish_reason"]
                attempts.append(_attempt_record(raw_response, finish_reason, interrupted_error))
                record_round({
                    "seq": seq, "at": datetime.now(timezone.utc).isoformat(),
                    "user": original_text, "answer": None, "candidate": None, "stance": None,
                    "decision": "none", "reason": "interrupted", "requests_sent": requests_sent,
                    "pending_after": pending["statement"] if pending is not None else None,
                    "raw_response": raw_response, "finish_reason": finish_reason, "error": None,
                    "attempts": attempts,
                })
                print("讨论已取消；本轮结论未写入。", file=output)
                return finish("cancel")
            except LiveError as exc:
                final_error = exc
                if exc.raw_response:
                    raw_response = exc.raw_response[:MAX_RAW_RESPONSE_CHARS]
                elif not raw_response:
                    raw_response = json.dumps(response, ensure_ascii=False, default=str)[:MAX_RAW_RESPONSE_CHARS]
                exc.raw_response = exc.raw_response or raw_response
                exc.finish_reason = exc.finish_reason or finish_reason
                finish_reason = exc.finish_reason
                kind = _error_kind(exc)
                if kind == "http_error" and exc.http_status is None and "HTTP " in str(exc):
                    try:
                        exc.http_status = int(str(exc).split("HTTP ", 1)[1].split(";", 1)[0])
                    except ValueError:
                        pass
                final_error_record = _trace_error(exc)
                attempts.append(_attempt_record(raw_response, finish_reason, final_error_record))
                status = exc.http_status
                if kind == "http_error" and status is not None and status < 500:
                    terminal_failure = True
                    break
                if kind in {"connect", "timeout"} or (kind == "http_error" and status is not None and status >= 500):
                    consecutive_connection_failures += 1
                    if consecutive_connection_failures >= 2:
                        terminal_failure = True
                        break
                    transient_retries += 1
                    if requests_sent >= MAX_MODEL_REQUESTS:
                        terminal_failure = True
                        break
                    continue
                consecutive_connection_failures = 0
                if kind in {"empty_content", "not_json", "schema_violation", "truncated", "unknown"} and invalid_retries < 2:
                    invalid_retries += 1
                    if requests_sent < MAX_MODEL_REQUESTS:
                        continue
                break

        if final_error is not None and terminal_failure:
            error = final_error_record or _trace_error(final_error)
            record_round({
                "seq": seq, "at": datetime.now(timezone.utc).isoformat(),
                "user": original_text, "answer": None, "candidate": None, "stance": None,
                "decision": "none", "reason": "failure", "requests_sent": requests_sent,
                "pending_after": pending["statement"] if pending is not None else None,
                "raw_response": raw_response, "finish_reason": finish_reason,
                "error": error, "attempts": attempts,
            })
            print(_user_error_message(error), file=output)
            return finish("failure", 2)

        if final_error is not None:
            error = final_error_record or _trace_error(final_error)
            answer = _user_error_message(error)
            stance = "neutral"
            candidate = None
            reason = "invalid_output"
            decision = "none"
            print("\n主持人> " + answer, file=output)
            error_record = error
        else:
            answer = checked["answer"]
            stance = checked.get("user_stance", "neutral")
            previous_pending = pending
            should_save = previous_pending is not None and candidate == previous_pending and stance == "accept"
            reason = "proposed_new_pending" if previous_pending is None and candidate is not None else "no_pending"
            if previous_pending is not None:
                if candidate != previous_pending:
                    reason = "candidate_changed"
                elif stance == "accept":
                    reason = "accepted_and_written"
                elif stance == "reject":
                    reason = "stance_not_accept"
                else:
                    reason = "awaiting_accept"
            decision = "none"
            error_record = None
            print("\n主持人> " + answer, file=output)
            if candidate is not None and should_save:
                saved_id = _save_conclusion(
                    store, previous_pending, session, output,
                    trace_enabled=trace is not None and trace.file is not None,
                )
                if saved_id is not None:
                    saved_ids.append(saved_id)
                    decision = "written"
                else:
                    reason = "write_failed"
                pending = None
                print("\n你可以继续谈另一个想法。", file=output)
            elif candidate is not None:
                pending = candidate
                print(_conclusion_sentence(candidate), file=output)
            elif pending is not None:
                pending = None
            if transient_retries:
                print("模型服务短暂连接失败，已重试并恢复。", file=output)

        record_round({
            "seq": seq, "at": datetime.now(timezone.utc).isoformat(),
            "user": original_text, "answer": answer, "candidate": candidate,
            "stance": stance, "decision": decision, "reason": reason,
            "requests_sent": requests_sent,
            "pending_after": pending["statement"] if pending is not None else None,
            "raw_response": raw_response[:MAX_RAW_RESPONSE_CHARS],
            "finish_reason": finish_reason, "error": error_record,
            "attempts": attempts,
        })
        history.extend([{"role": "user", "content": context}, {"role": "assistant", "content": answer}])
        if len(history) > MAX_HISTORY_MESSAGES:
            history = history[-MAX_HISTORY_MESSAGES:]
        if requests_sent >= MAX_MODEL_REQUESTS:
            print(f"本次模型请求已达到 {MAX_MODEL_REQUESTS} 次上限；尚未明确同意的结论未写入。", file=output)
            return finish("limit")

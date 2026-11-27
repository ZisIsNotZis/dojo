"""Argument-parsed local command line for the dojo POC."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from . import commands
from .compare import run_compare
from .demo import freeze_materials, run_demo, write_demo_summary
from .discuss import _load_resume_trace, run_discuss
from .finding import search_screen
from .live import LiveConfig, LiveError, run_chat
from .pipeline import distill, run_pipeline
from .storage import DojoError, Store, load_simulated_seeds

DEFAULT_HOME = Path.home() / ".local" / "share" / "dojo"
DEFAULT_DB = DEFAULT_HOME / "dojo.sqlite3"
DEFAULT_EXPORTS = DEFAULT_HOME / "exports"


# Returned by `search` when the screen has already been shown on a terminal and the
# JSON must not follow it there. A sentinel, not `None`: `None` is a value some command
# could legitimately return, and the printer must be able to tell the two apart.
SEARCH_SCREEN_ONLY = object()


def _json_argument(value: str, label: str) -> Any:
    try:
        if value.startswith("@"):
            return json.loads(Path(value[1:]).read_text(encoding="utf-8"))
        return json.loads(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise DojoError(f"invalid {label} JSON: {exc}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m dojo",
        description="Local no-UI dojo POC with explicit model-backed inquiry and bounded maintenance.",
    )
    # default=None so one command can tell "the caller named a library" from "the fallback
    # location". `freeze-materials` needs that difference: it prints entry times read out
    # of a library, and has to know which one (#1893). Every other command resolves the
    # same default in `main`, so their behaviour is unchanged.
    parser.add_argument("--db", default=None, help=f"SQLite file (default: {DEFAULT_DB}; DOJO_DB overrides)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="load the four documented simulated candidates once")

    list_parser = sub.add_parser("list", help="list candidates and statuses")
    list_parser.add_argument("--history", action="store_true", help="include full current records")

    show_parser = sub.add_parser("show", help="show a candidate, resolving merge redirects")
    show_parser.add_argument("id")
    show_parser.add_argument("--history", action="store_true", help="include immutable versions and events")

    add_parser = sub.add_parser("add", help="add a draft candidate; no raw chat transcript is stored")
    add_parser.add_argument("--statement", required=True)
    add_parser.add_argument("--kind", required=True, choices=["abstract_idea", "experience_claim", "application", "question", "counterexample"])
    add_parser.add_argument("--id")
    add_parser.add_argument("--premise", action="append", default=[])
    add_parser.add_argument("--scope", action="append", default=[])
    add_parser.add_argument("--alternative", action="append", default=[])
    add_parser.add_argument("--contradiction", action="append", default=[])
    add_parser.add_argument("--unknown", action="append", default=[])
    add_parser.add_argument("--source-json", action="append", default=[], help="source object as JSON; repeat as needed")
    add_parser.add_argument("--session", help="anonymous session ID only")

    attach = sub.add_parser(
        "attach-source",
        help=(
            "add provenance to an existing card without restating it; a second independent "
            "session reaching the same claim uses this -- independence is counted per source, "
            "so two sources naming the same independence_group are still one provenance"
        ),
    )
    attach.add_argument("id")
    attach.add_argument("--source-json", required=True)
    attach.add_argument("--session", help="anonymous session ID only")

    confirm = sub.add_parser("confirm", help="confirm discussability only; not truth")
    confirm.add_argument("id")
    confirm.add_argument("--basis", required=True)
    confirm.add_argument("--session")

    revoke = sub.add_parser("revoke", help="revoke an active discussability confirmation")
    revoke.add_argument("id")
    revoke.add_argument("--reason", required=True)
    revoke.add_argument("--session")

    challenge = sub.add_parser("challenge", help="append a challenge and mark candidate challenged")
    challenge.add_argument("id")
    challenge.add_argument("--text", required=True)
    challenge.add_argument("--source-json", help="optional provenance JSON for the challenge")

    revise = sub.add_parser("revise", help="write a new draft version, retaining prior versions/sources")
    revise.add_argument("id")
    revise.add_argument("--statement", required=True)
    revise.add_argument("--reason", required=True)

    alias = sub.add_parser("alias", help="add an equivalent wording; this does not merge candidates")
    alias.add_argument("id")
    alias.add_argument("--wording", required=True)
    alias.add_argument("--reason", required=True)

    link = sub.add_parser("link", help="add an explicit typed relation")
    link.add_argument("id")
    link.add_argument("--relation", required=True, choices=["supports", "challenges", "narrows", "generalizes", "conflicts", "instantiates", "duplicates"])
    link.add_argument("--target", required=True)
    link.add_argument("--reason", required=True)

    split = sub.add_parser("split", help="split a candidate into at least two explicit child records")
    split.add_argument("id")
    split.add_argument("--children-json", required=True, help="JSON array or @path; each child has statement and optional id/source_ids")
    split.add_argument("--reason", required=True)

    merge = sub.add_parser("merge", help="explicit human-confirmed reversible redirect")
    merge.add_argument("source")
    merge.add_argument("target")
    merge.add_argument("--confirm", action="store_true", required=True, help="acknowledge these candidate IDs are equivalent and safe to merge")
    merge.add_argument("--reason", required=True)

    unmerge = sub.add_parser("unmerge", help="restore exact pre-merge records as new versions")
    unmerge.add_argument("source")
    unmerge.add_argument("--reason", required=True)

    abstain = sub.add_parser("abstain", help="record uncertainty without changing candidate version")
    abstain.add_argument("--reason", required=True)
    abstain.add_argument("--id", help="optional related candidate")
    abstain.add_argument("--next-question")

    withdraw = sub.add_parser("withdraw", help="withdraw from retrieval without deleting history")
    withdraw.add_argument("id")
    withdraw.add_argument("--reason", required=True)

    search = sub.add_parser(
        "search",
        help=(
            "transparent lexical retrieval of discussable candidates only; --session names the "
            "reader so the read is recorded under them (without it the read is recorded with no "
            "reader, which still says somebody read it)"
        ),
    )
    search.add_argument("query", nargs="?")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--session", help="anonymous reader ID recorded with this read")

    broadcast = sub.add_parser(
        "broadcast",
        help="transparent lexical retrieval of cross-session material only; suppressed cards are listed with their reason",
    )
    broadcast.add_argument("query", nargs="?")
    broadcast.add_argument("--limit", type=int, default=10)
    broadcast.add_argument("--session", help="exclude cards written by this session: it does not broadcast its own word back")

    pipeline = sub.add_parser(
        "pipeline",
        help="run the end-of-session passes (classify, locate, challenge) over one session's cards; each card is processed once per revision",
    )
    pipeline.add_argument("--session", required=True, help="the session whose cards to process")
    pipeline.add_argument("--dry-run", action="store_true", help="report what each pass would do without writing marks or events")

    distill_parser = sub.add_parser(
        "distill",
        help="read-only: what one session's conclusions amount to (新 / 变体 / 重复), as a list a person judges; writes nothing",
    )
    distill_parser.add_argument("--session", required=True, help="the session whose cards to list")

    export = sub.add_parser("export", help="create a new isolated B (no seed) or C (selected excerpt) prompt")
    export.add_argument("--mode", choices=["b", "c"], required=True)
    export.add_argument("--id", action="append", default=[], help="explicit selected candidate ID (C only); repeat to add")
    export.add_argument("--budget-chars", type=int, default=6000, help="hard maximum on complete prompt characters")
    export.add_argument("--outdir", default=os.environ.get("DOJO_EXPORTS", str(DEFAULT_EXPORTS)), help=f"independent export directory (default: {DEFAULT_EXPORTS})")
    export.add_argument("--session", help="anonymous reader ID recorded with this export")

    events = sub.add_parser("events", help="inspect append-only events, including unversioned abstain records")
    events.add_argument("--id", help="filter by candidate ID")

    reads = sub.add_parser("reads", help="read-only: who was handed this wording, and whether it was accepted by then")
    reads.add_argument("--id", help="filter by candidate ID")
    reads.add_argument("--reader", help=(
        "only the reads handed to this session: answers 'did I read this before it "
        "was accepted' without knowing a sequence number"
    ))

    demo = sub.add_parser("demo", help="中文交互故事；默认离线预设模拟，不是实时 AI")
    demo.add_argument("--auto", action="store_true", help="不读取 stdin，自动走预设故事（适用于 CI）")
    demo.add_argument("--details", action="store_true", help="完整展开 Store 候选字段；默认只显示观点、条件、未知与来源状态")
    demo.add_argument("--live", action="store_true", help="改走真实模型聊天；需配置 DOJO_LLM_BASE_URL")
    demo.add_argument("--workdir", help="保存到一个新建/空目录；不覆盖已有数据库或总结")

    inquire = sub.add_parser("inquire", help="实验性共同探究：DeepSeek low、实际工具与可继承故事线")
    inquire.add_argument("--resume", metavar="STORY", help="显式续谈同一故事；新的有限预算，保留已展示的原始上下文")
    inquire.add_argument("--local-edits", action="store_true", help="实验性局部修订；沿用本场审查/修订预算")
    inquire.add_argument("--synthetic", action="store_true", help="显式创建或续谈合成故事；不能混入普通身份数据")
    stories = sub.add_parser("stories", help="只读列出探究故事与最近意图快照；不请求模型")
    stories.add_argument("story", nargs="?", help="查看一个故事的运行列表")
    stories.add_argument("--synthetic", action="store_true", help="包括明确标注的合成故事")
    story_view = stories.add_mutually_exclusive_group()
    story_view.add_argument("--context", action="store_true", help="只读看指定故事的续谈候选原记录（须提供 STORY）")
    story_view.add_argument("--report", type=int, metavar="EVENT", help="只读看指定故事内单条用户报告原话（须提供 STORY，可用 replacement 事件号）")
    story_view.add_argument("--proposal", type=int, metavar="EVENT", help="只读查看指定故事内单条提议的报告复核依据（须提供 STORY）")
    story_view.add_argument("--comparison", type=int, metavar="EVENT", help="只读查看当前提议的正文比较状态（须提供 STORY）")
    comparison = sub.add_parser('compare-sources', help='写入一版提议的明确正文比较；不联网、不请求模型')
    comparison.add_argument('story')
    comparison.add_argument('proposal', type=int, metavar='PROPOSAL')
    comparison.add_argument('basis', type=int, metavar='BASIS_READ', help='该版提议已作为依据引用的正文事件号')
    comparison.add_argument('other', type=int, metavar='OTHER_READ', help='比较的另一正文事件号')
    comparison.add_argument('--relation', choices=('supports_independently', 'conflicts'), required=True)
    comparison.add_argument('--reason', required=True, help='说明核对范围和结果，保留给读者；程序不解释这段文本')
    comparison.add_argument('--synthetic', action='store_true', help='写入明确标注的合成故事')
    questions = sub.add_parser("questions", help="只读查看问题、子问题及候选答案的材料连接；不判真理")
    questions.add_argument("--story", help="只看一个故事的问题组织")
    questions.add_argument("--synthetic", action="store_true", help="包括标注的合成问题组织")
    questions.add_argument("--limit", type=int, default=64, help="可见问题数上限，1至512；截断显式报告")
    questions.add_argument("--review-basis", action="store_true", help="同时列出每条关系复核记录的所依据引文与记录时刻")
    knowledge = sub.add_parser("knowledge", help="只读查看知识提议、论据及依赖状态；不认证真理")
    knowledge.add_argument("--synthetic", action="store_true", help="包括明确标注的合成探究材料")
    maintenance = sub.add_parser("maintain", help="沿已有故事执行一轮有限维护；不新增用户陈述，不启动守护进程")
    maintenance.add_argument("--story", required=True, help="已存在的故事标识；仅本故事及明确关联的上游复核目标")
    maintenance.add_argument("--synthetic", action="store_true", help="维护明确标注的合成故事，不能混入普通故事")
    maintenance.add_argument("--max-requests", type=int, default=4, help="本轮共享模型预算0至12；0时不读凭据、不调用模型")
    maintenance.add_argument("--max-tools", type=int, default=1, help="本轮共享工具尝试预算0至4，包括CPU重验与研究工具")
    maintenance.add_argument("--retry-distillation", action="store_true", help="显式重提炼未新增材料的故事，包括此前失败；仍计本轮预算")
    maintenance.add_argument("--retry-associations", action="store_true", help="显式重做当前材料上失败的关联；不重复已成功任务，仍计本轮预算")
    recheck = sub.add_parser("recheck", help="有预算地复核受上游变化影响的知识提议")
    recheck.add_argument("--synthetic", action="store_true", help="允许复核合成材料（非真人效果验证）")
    recheck.add_argument("--max-requests", type=int, default=2, help="本次最多模型请求数，1至12，无自动重试")
    recheck.add_argument("--retry-failures", action="store_true", help="显式重新尝试此前失败的相同packet；自动维护不重试")
    recheck.add_argument("--auth-file", help="凭据文件路径；默认 ~/.agents/auth.json，只在本地读取一次，不回显内容")

    sub.add_parser("chat", help="显式启动真实模型聊天；使用 DOJO_LLM_BASE_URL/MODEL/API_KEY")
    transcript = sub.add_parser(
        "transcript", help="只读回看一场讨论的原话：四件各说了什么、记录把每件记成了什么",
        description="只读：不改库、不写轨迹、不请求模型。轨迹写到一半断了也能读，并会说明断在哪。",
    )
    transcript.add_argument("trace", help="一场讨论的轨迹：sessions/discuss-<32 位十六进制>.jsonl")
    transcript.add_argument(
        "--json", action="store_true", help="输出同样的内容，机器可读",
    )
    discuss = sub.add_parser("discuss", help="自然语言协作讨论；会话原文仅写入本地轨迹")
    discuss.add_argument("--no-trace", action="store_true", help="不创建轨迹文件，也不保存会话原文")
    discuss.add_argument("--no-profile", action="store_true", help="本场既不读取也不写入人物档案")
    discuss.add_argument("--resume", metavar="TRACE", help="从既有轨迹续跑同一会话并追加写入")
    discuss.add_argument(
        "--card", metavar="ID", default=None,
        help="把库里已有的一张卡交给这一场（屏幕说清是哪句、有没有改过；本场只是重复它不算新来源）",
    )
    discuss.add_argument(
        "--verbose", action="store_true",
        help="在 stderr 打印模型请求、检索与写卡的实时进度（不影响主持人输出与轨迹）",
    )

    packets = sub.add_parser(
        "freeze-materials",
        help="生成四份冻结模型输入；C 摘录与来源入库时刻都取自 --db 指定的库",
        description="必须用 --db（或 DOJO_DB）指定一个已存在的库：包里每个 entered_at 都从那个库的事件账本读出。",
    )
    # No default directory. It pointed at `docs/packets/frozen-conversation-v2`, which is
    # now a dated historical artifact (its own README says so); defaulting into it could
    # only ever produce a refusal, and a refusal that names a directory invites a person
    # to delete the artifact to satisfy it (#1893).
    packets.add_argument("--outdir", required=True, help="新输出目录；已有目录会拒绝覆盖")

    compare = sub.add_parser("compare", help="离线回放归档的两份真实 Luna 回答；不会联网或改写原文")
    compare.add_argument("--full", action="store_true", help="在简洁来源/限制说明后输出完整 B/C 原文")

    return parser


def _secure_default_paths(database: Path, export_directory: Path) -> None:
    if database == DEFAULT_DB:
        DEFAULT_HOME.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            DEFAULT_HOME.chmod(0o700)
        except OSError:
            pass
    if export_directory == DEFAULT_EXPORTS:
        DEFAULT_EXPORTS.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            DEFAULT_EXPORTS.chmod(0o700)
        except OSError:
            pass


def _log_reads(store: Store, rows: list[dict[str, Any]], session: str | None, surface: str) -> None:
    """Record that these rows left the library, and say so when that cannot be recorded.

    #1534 found nothing on disk answering "was this read before it was accepted", so
    the three real outputs now log what they handed out.

    A failure to log must not fail the command: the rows are already computed and the
    person asked for them, so losing the log is the smaller harm. Losing it *silently*
    is not, because an empty read history is then indistinguishable from "nobody ever
    read this" -- the state #1534 was written to expose. So the output still prints,
    the exit code stays 0, and one line on stderr names what went unrecorded and why.
    """
    missed: list[str] = []
    failure: str | None = None
    for row in rows:
        try:
            store.record_read(row["id"], session, surface=surface)
        except (DojoError, sqlite3.Error, OSError) as exc:
            missed.append(row["id"])
            failure = failure or f"{type(exc).__name__}: {exc}"
    if missed:
        print(
            f"  未记下这次读取（{surface}）：{len(missed)} 条未被写进读记录"
            f"（{', '.join(missed)}）；原因：{failure}",
            file=sys.stderr,
        )


def _reads_screen(log: dict[str, Any]) -> dict[str, Any]:
    """Put the read log on a screen, including the case of never having had one.

    #1537 wrote the log; nothing but a probe could read it back, which is the shape
    where a conclusion only holds inside the project's own script. This is the exit a
    second person can type. Same style as `dojo events`: read-only JSON on stdout,
    the human line on stderr so a caller parsing stdout is unaffected.

    Two silences are kept apart deliberately. A library with no `reads` table has
    never recorded a read -- that is not "the log exists and is empty", and an empty
    list would be the stronger, false claim (the r1537 `holds_table` distinction).
    So the missing-table case says so on stderr and still prints the contract.

    `accepted_when_read` is derived from `accepted_at_at_read`, never from comparing
    `at` against an acceptance timestamp: `events.created_at` is second-resolution and
    `at` is microsecond, so a read one moment *before* an acceptance compares as
    later. What is printed is the acceptance state as it stood at that instant.
    """
    if not log["holds_table"]:
        print(
            "  这个库从来没有记过读取：没有读记录表（这不是「记过但为空」）。",
            file=sys.stderr,
        )
        return {"holds_table": False, "rows": []}
    rows: list[dict[str, Any]] = []
    for row in log["rows"]:
        accepted = row["accepted_at_at_read"]
        rows.append({
            "sequence": row["seq"],
            "candidate_id": row["candidate_id"],
            "version": row["version"],
            "wording_digest": row["wording_digest"],
            "reader_session": row["reader_session"],
            "surface": row["surface"],
            "at": row["at"],
            "accepted_at_at_read": accepted,
            "accepted_when_read": (
                "accepted_before_this_read" if accepted else "no_acceptance_at_read_time"
            ),
        })
        print(
            "  读 #%s %s 出口=%s 读者=%s %s" % (
                row["seq"], row["at"], row["surface"],
                row["reader_session"] or "（未记名：这次读没带 --session）",
                ("读时这张卡已被接受（接受于 %s）" % accepted) if accepted
                else "读时这张卡还没有被接受",
            ),
            file=sys.stderr,
        )
    verdict = _reader_verdict(log, rows)
    if verdict is not None:
        print("  " + verdict, file=sys.stderr)
    if not rows:
        print("  读记录表存在，但没有任何一条读记录。", file=sys.stderr)
    return _reads_payload(log, rows, verdict)


def _reader_verdict(log: dict[str, Any], rows: list[dict[str, Any]]) -> str | None:
    """One sentence for one reader: did he meet this wording before or after acceptance?

    Only produced when the log was filtered to a single reader, because with several
    readers in the list there is no single "his" answer to give.
    """
    reader = log.get("reader")
    if reader is None:
        return None
    if not rows:
        return "这个读者没有被交付过这张卡：读记录里没有他的一行。"
    before = sum(1 for row in rows if not row["accepted_at_at_read"])
    after = len(rows) - before
    if before and after:
        return "你自己读过 %d 次：%d 次在接受之前，%d 次在接受之后。" % (len(rows), before, after)
    if after:
        return "你自己读过 %d 次，都在接受之后：你看到的就是被认可的措辞。" % after
    return "你自己读过 %d 次，都在接受之前：那时这版还没有被认可。" % before


def _reads_payload(
    log: dict[str, Any], rows: list[dict[str, Any]], verdict: str | None
) -> dict[str, Any]:
    """The JSON contract of `reads`, unchanged when no reader filter was given."""
    payload: dict[str, Any] = {"holds_table": True, "rows": rows}
    if log.get("reader") is not None:
        payload["reader"] = log["reader"]
        payload["verdict"] = verdict
    return payload


def _execute(args: argparse.Namespace, store: Store) -> Any:
    command = args.command
    if command == "seed":
        return load_simulated_seeds(store)
    if command == "list":
        return store.list_candidates(include_history=args.history)
    if command == "show":
        value = store.show(args.id)
        if args.history:
            value["history"] = store.history(value["resolved_id"])
        return value
    if command == "add":
        sources = [_json_argument(value, "source") for value in args.source_json]
        return store.add(
            args.statement, args.kind, candidate_id=args.id, premises=args.premise,
            scope=args.scope, alternatives=args.alternative, contradictions=args.contradiction,
            unknowns=args.unknown, sources=sources, session=args.session,
        )
    if command == "attach-source":
        return store.attach_source(args.id, json.loads(args.source_json), args.session)
    if command == "confirm":
        return store.confirm(args.id, args.basis, args.session)
    if command == "revoke":
        return store.revoke(args.id, args.reason, args.session)
    if command == "challenge":
        source = _json_argument(args.source_json, "source") if args.source_json else None
        return store.challenge(args.id, args.text, source)
    if command == "revise":
        return store.revise(args.id, args.statement, args.reason)
    if command == "alias":
        return store.alias(args.id, args.wording, args.reason)
    if command == "link":
        return store.link(args.id, args.relation, args.target, args.reason)
    if command == "split":
        children = _json_argument(args.children_json, "children")
        if not isinstance(children, list):
            raise DojoError("children JSON must be an array")
        return store.split(args.id, children, args.reason)
    if command == "merge":
        return store.merge(args.source, args.target, confirmed=args.confirm, reason=args.reason)
    if command == "unmerge":
        return store.unmerge(args.source, args.reason)
    if command == "abstain":
        return store.abstain(args.reason, args.id, args.next_question)
    if command == "withdraw":
        return store.withdraw(args.id, args.reason)
    if command == "search":
        # `for_reading`: the person's exit also learns what the gate refused and which
        # wording each row matched. Those are for the screen only -- stdout is a
        # published contract that other tools parse, so it is printed from a copy with
        # the screen's keys removed, and the screen goes to stderr. Measured: a caller
        # comparing the four top-level keys and each row's keys sees no change (#3436).
        result = store.retrieve(args.query or "", args.limit, for_reading=True)
        _log_reads(store, result["results"], getattr(args, "session", None), "search")
        for line in search_screen(result, database=store.path):
            print(line, file=sys.stderr)
        published = {key: value for key, value in result.items()
                     if key not in ("withheld", "recent")}
        published["results"] = [
            {key: value for key, value in row.items()
             if key not in ("matched_on", "matched_wording")}
            for row in result["results"]
        ]
        # A person at a terminal reads the screen; a script reads stdout. Printing both
        # on a terminal buried the screen's last line -- the command to run -- under the
        # whole JSON block, which is what the supervisor measured (24 readable lines,
        # then 48 of JSON). So stdout is printed only when it is not a terminal. On a
        # terminal a one-line pointer replaces it, and it names how to get the JSON back:
        # the host scripts' entry is unchanged, they just have to redirect or pipe.
        if sys.stdout.isatty():
            print("（机器可读的 JSON 没有印在终端上；脚本直接读 stdout，或在命令后接"
                  " ` | python3 -m json.tool`。）", file=sys.stderr)
            return SEARCH_SCREEN_ONLY
        return published
    if command == "pipeline":
        return run_pipeline(store, args.session, dry_run=args.dry_run)
    if command == "distill":
        return distill(store, args.session)
    if command == "broadcast":
        return store.broadcast(args.query or "", args.limit, args.session)
    if command == "export":
        exported = store.export_prompt(args.mode, args.id, args.budget_chars, args.outdir)
        _log_reads(
            store,
            [{"id": candidate_id} for candidate_id in exported["source_candidate_ids"]],
            getattr(args, "session", None), "export",
        )
        return exported
    if command == "events":
        sql = "SELECT seq,candidate_id,event,details_json,created_at FROM events"
        params: tuple[str, ...] = ()
        if args.id:
            sql += " WHERE candidate_id=?"
            params = (args.id,)
        sql += " ORDER BY seq"
        return [
            {"sequence": row["seq"], "candidate_id": row["candidate_id"], "event": row["event"],
             "details": json.loads(row["details_json"]), "created_at": row["created_at"]}
            for row in store.connection.execute(sql, params)
        ]
    if command == "reads":
        return _reads_screen(store.reads(args.id, getattr(args, "reader", None)))
    raise DojoError("unknown command")


def _knowledge_scope_note(connection, tables, *, synthetic: bool) -> str | None:
    """Say out loud what this listing leaves out, without touching stdout.

    An empty array cannot distinguish 'this ledger holds no proposals' from
    'it holds them and the default scope filtered every one'. The note goes to
    stderr so stdout stays the same JSON value every existing caller parses;
    it counts proposals with the same key `Knowledge.proposals` reads, and it
    never calls a filtered record evidence.
    """
    if 'inquiry_events' not in tables:
        return None
    total = synthetic_rows = 0
    for (payload,) in connection.execute("SELECT payload FROM inquiry_events WHERE kind='knowledge_proposal'"):
        try:
            data = json.loads(payload)
        except ValueError:
            return None
        total += 1
        if data.get('synthetic') is True:
            synthetic_rows += 1
    plain = total - synthetic_rows
    if not total:
        return '这个库里没有知识提议记录。'
    if synthetic:
        if not synthetic_rows:
            return None
        return f'本库共 {total} 条知识提议记录，其中 {synthetic_rows} 条标注为合成（synthetic=True）；本视图包含合成记录。'
    if not plain:
        return (f'本库有 {total} 条知识提议记录，全部标注为合成（synthetic=True）；'
                '默认视图不列出它们。加 --synthetic 可查看。')
    if not synthetic_rows:
        return None
    # No promise about how many rows either view prints: `proposals()` takes the
    # newest `limit` rows and only then drops the synthetic ones, so an older
    # plain record can sit outside that window. The note states what the ledger
    # holds and what each scope includes or excludes, nothing more.
    return (f'本库共 {total} 条知识提议记录，其中 {synthetic_rows} 条标注为合成（synthetic=True）；'
            f'默认视图不列出合成记录，本库另有 {plain} 条未标注为合成。加 --synthetic 可查看含合成记录的视图。')


def _private_workdir(path: Path) -> Path:
    """Create or accept only an empty, private work directory without replacing files."""
    if path.is_symlink():
        raise DojoError("--workdir cannot be a symbolic link")
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise DojoError("--workdir must be a new or empty directory; refusing to overwrite existing files")
    else:
        path.mkdir(mode=0o700, parents=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    if (path / "dojo.sqlite3").exists() or (path / "summary.md").exists():
        raise DojoError("--workdir already contains a database or summary; refusing to overwrite")
    return path


def _print_packet_result(result: dict[str, Any]) -> None:
    print(f"已写入冻结模型材料：{result['directory']}")
    print("入库时刻取自库：" + str(result["source_db"]))
    print("文件：" + "、".join(result["files"]))
    print("C 条件实际检索来源：" + "、".join(result["retrieved_source_candidate_ids"]))
    print("检索：" + result["retrieval_method"])
    # #1929: "入库时刻取自库" is a claim about every source line in the packet. When the
    # library has no entry record for some of them, saying nothing would turn "this
    # source was not dated" into "this packet does not print dates", which is the
    # silence the whole field exists to remove.
    if result.get("undated_source_ids"):
        print("这些来源在库里没有入库记录，包内不印它们的时刻：" + "、".join(result["undated_source_ids"]))


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db if args.db is not None else (os.environ.get("DOJO_DB") or str(DEFAULT_DB))).expanduser()
    export_dir = Path(getattr(args, "outdir", os.environ.get("DOJO_EXPORTS", str(DEFAULT_EXPORTS)))).expanduser()
    store: Store | None = None
    tempdir: tempfile.TemporaryDirectory[str] | None = None
    workdir: Path | None = None
    try:
        if args.command == "demo":
            config = LiveConfig.from_environment() if args.live else None
            if args.workdir:
                workdir = _private_workdir(Path(args.workdir).expanduser())
            else:
                tempdir = tempfile.TemporaryDirectory(prefix="dojo-demo-")
                try:
                    Path(tempdir.name).chmod(0o700)
                except OSError:
                    pass
            root = workdir if workdir is not None else Path(tempdir.name)
            db_path = root / "dojo.sqlite3"
            store = Store(db_path)
            try:
                db_path.chmod(0o600)
            except OSError:
                pass
            if args.live:
                load_simulated_seeds(store)
                code = run_chat(store, config=config)
                if workdir is not None:
                    print(f"本地数据库保存在：{db_path}")
                return code
            outcome = run_demo(store, auto=args.auto, details=args.details, read_line=lambda prompt: input(prompt), output=sys.stdout)
            if workdir is not None:
                write_demo_summary(outcome, workdir)
                print(f"本地数据库和简要总结保存在：{db_path} 与 {workdir / 'summary.md'}")
            return 0
        if args.command == "inquire":
            from .inquiry import run_inquiry
            if args.resume:
                from .stories import prepare_resume
                prepare_resume(db_path,args.resume,synthetic=args.synthetic)
            _secure_default_paths(db_path, export_dir)
            return run_inquiry(db_path,story=args.resume,local_edits=args.local_edits,synthetic=args.synthetic)
        if args.command == 'compare-sources':
            from .knowledge import record_source_comparison
            if args.db is None:
                raise ValueError('compare-sources 写入账本，必须显式指定 --db')
            result = record_source_comparison(db_path, args.story, args.proposal, [args.basis, args.other],
                                              args.relation, args.reason, synthetic=args.synthetic)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "stories":
            if args.proposal is not None:
                from .stories import reading_proposal
                if not args.story:
                    raise ValueError('--proposal 需要 STORY；请先运行 stories 查找故事标识')
                print(json.dumps(reading_proposal(db_path, args.story, args.proposal, synthetic=args.synthetic),
                    ensure_ascii=False, indent=2))
                return 0
            if args.report is not None:
                from .stories import reading_report
                if not args.story:
                    raise ValueError('--report 需要 STORY；请先运行 stories 查找故事标识')
                print(json.dumps(reading_report(db_path, args.story, args.report, synthetic=args.synthetic),
                    ensure_ascii=False, indent=2))
                return 0
            if args.context or args.comparison is not None:
                from .stories import reading_context
                if not args.story:
                    # #3245: these two read-only views share one branch, so the refusal has to
                    # name the flag the caller actually typed; otherwise `--comparison` is told
                    # to run a different command than the one that just failed.
                    if args.context:
                        raise ValueError('--context 需要 STORY；请先运行 stories 查找故事标识，再用 stories STORY --context')
                    raise ValueError('--comparison 需要 STORY；请先运行 stories 查找故事标识，再用 stories STORY --comparison EVENT 查看当前提议的比较状态')
                print(json.dumps(reading_context(db_path, args.story, synthetic=args.synthetic, comparison=args.comparison), ensure_ascii=False, indent=2))
                return 0
            from .stories import listing
            from .absence import stories_absence
            result=listing(db_path,synthetic=args.synthetic,story=args.story)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            # r102: `[]` was one screen for five different situations, and the
            # listing additionally discarded 21 of 251 real stories without a
            # word because their opening turn is gone. The JSON above is the
            # contract and stays byte-identical; the reason goes to stderr.
            reason=stories_absence(db_path,story=args.story,synthetic=args.synthetic)
            if reason and not result:
                print('  空列表原因（%s）：%s' % reason,file=sys.stderr)
            elif reason:
                print('  列表不完整（%s）：%s' % reason,file=sys.stderr)
            return 0
        if args.command == "questions":
            from .questions import read_graph, graph_absence
            graph=read_graph(db_path,story=args.story,synthetic=args.synthetic,limit=args.limit,with_review_basis=args.review_basis)
            print(json.dumps(graph,ensure_ascii=False,indent=2))
            # r100: an empty graph is one screen for four different situations --
            # the path does not exist, the file is a healthy sqlite that is not a
            # dojo library, the library holds no questions, or this view filtered
            # them all. r99 recorded 3 of the second kind as `unreadable_db`; they
            # open fine and pass `integrity_check`. The JSON above is the contract
            # and stays byte-identical, so the reason goes to stderr.
            if not graph.get('nodes'):
                state,why=graph_absence(db_path)
                print('  空图原因（%s）：%s' % (state,why),file=sys.stderr)
            # r93: the JSON is the contract, but a person reading the screen
            # should not have to decode `dependency_status` to learn that the
            # quotation a relation rests on was replaced. One line per relation,
            # after the JSON so nothing above changes shape.
            relations=[]
            for node in graph.get('nodes',[]):
                for item in (node.get('annotation_history') or [])+(node.get('annotations') or []):
                    relations.append(item.get('event'))
                    if item.get('cited_source'):print('  关系 %s：%s' % (item.get('event'),item['cited_source']),file=sys.stderr)
                    # r95: a relation review also produced a version. 15 of 104
                    # stored rows name one that was replaced afterwards and the
                    # screen said nothing about it.
                    for attempt in item.get('review_attempts') or []:
                        if attempt.get('outcome_state_now'):
                            print('  关系 %s：%s' % (item.get('event'),attempt['outcome_state_now']),file=sys.stderr)
            # r99: 'what did this review stand on' was answered in the database
            # and on no screen: 104 of 104 stored relation reviews carried no
            # basis line here. Read in this process, printed on stderr, and
            # deliberately outside `--review-basis` -- the JSON above is fed to
            # the model verbatim and must not grow these keys, but a person
            # asking the question should not have to know a switch exists.
            from .question_reviews import basis_lines
            for line in basis_lines(db_path,relations):
                print('  复核 %s（关系 %s）：%s' % (line['at'],line['target'],line['sentence']),file=sys.stderr)
            return 0
        if args.command == "knowledge":
            from .knowledge import Knowledge
            from .absence import knowledge_absence
            if not db_path.exists():
                print("[]")
                state,why=knowledge_absence(db_path,synthetic=args.synthetic)
                print('  空列表原因（%s）：%s' % (state,why),file=sys.stderr)
                return 0
            connection = sqlite3.connect(db_path.resolve().as_uri()+"?mode=ro", uri=True)
            try:
                tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                # r103: this gate named one table while `proposals()` reads four.
                # On copies of a real 27-proposal library, dropping
                # inquiry_revisions or inquiry_review_queue passed the gate and
                # then died inside the listing with `error: no such table: ...`
                # (exit 2, empty stdout) -- one missing table hid every row and
                # every basis line. All three shapes now take the same path the
                # r102 fix chose for every other empty listing: the JSON contract
                # stays `[]`, and one stderr line names the missing table.
                from .absence import KNOWLEDGE_TABLES
                readable = [name for name in KNOWLEDGE_TABLES if name in tables]
                result=Knowledge(connection,initialize=False).proposals(synthetic=args.synthetic) if len(readable)==len(KNOWLEDGE_TABLES) else []
                print(json.dumps(result,ensure_ascii=False,indent=2))
                # r102: the scope note below only speaks once the ledger is known
                # to hold proposal rows; it has nothing to say about a file with
                # another schema or a library with no proposals at all, and both
                # printed `[]` in silence.
                absent = None
                if not result:
                    absent=knowledge_absence(db_path,synthetic=args.synthetic)
                    if absent:print('  空列表原因（%s）：%s' % absent,file=sys.stderr)
                note=_knowledge_scope_note(connection,tables,synthetic=args.synthetic)
                # The rows layer already said the ledger holds no proposal at
                # all; the scope note would repeat it in different words. One
                # fact, one line: keep the note only when it adds the split.
                # r103: the table layer is the other case where the note lies.
                # With a table missing it said '加 --synthetic 可查看', and that
                # switch either printed `[]` again or exited 2 mid-listing
                # (measured on real-library copies). The layer names the table;
                # a promise that cannot be kept must not be printed beside it.
                if note and not (absent and absent[0] in ('rows','table')):print(note,file=sys.stderr)
                # r94: same split as `questions`: the JSON stays the contract,
                # and a person reading the screen gets one line per review row
                # whose recorded basis has moved since it was written.
                for row in result:
                    # r98: a proposal whose packet cannot be rebuilt today. It
                    # used to abort the whole listing before this point, so the
                    # screen showed nothing at all; now it says which event is
                    # gone, and the attempts below say what those reviews stood
                    # on. Said before the attempts because it explains why the
                    # digest lines below refuse to compare.
                    if row.get('packet_unreadable'):
                        print('  目标 %s：%s' % (row['event'],row['packet_unreadable']),file=sys.stderr)
                    for item in row.get('review_attempts') or []:
                        # r95: the review's own outcome, not its basis.
                        if item.get('outcome_state_now'):
                            print('  复核 %s（目标 %s）：%s' % (item.get('at'),row['event'],item['outcome_state_now']),file=sys.stderr)
                        for sentence in item.get('basis_state_now') or ():
                            print('  复核 %s（目标 %s）：%s' % (item.get('at'),row['event'],sentence),file=sys.stderr)
                        # r97: the gap sentences. `basis_missing` was computed into
                        # the JSON and never printed (measured: 156 occurrences
                        # across real libraries, 0 lines on screen), so the screen
                        # stayed silent on exactly the rows a reader most needs it
                        # to speak about. The JSON stays the contract; this is the
                        # sentence a person reads.
                        if item.get('basis_missing'):
                            print('  复核 %s（目标 %s）：%s' % (item.get('at'),row['event'],item['basis_missing']),file=sys.stderr)
                        for sentence in item.get('basis_incomplete') or ():
                            print('  复核 %s（目标 %s）：%s' % (item.get('at'),row['event'],sentence),file=sys.stderr)
            finally:
                connection.close()
            return 0
        if args.command == "recheck":
            from .reviews import run_rechecks
            _secure_default_paths(db_path, export_dir)
            print(json.dumps(run_rechecks(db_path,synthetic=args.synthetic,max_requests=args.max_requests,retry_failures=args.retry_failures,auth_file=args.auth_file),ensure_ascii=False,indent=2))
            return 0
        if args.command == "maintain":
            from .maintenance import run_maintenance
            print(json.dumps(run_maintenance(db_path,args.story,synthetic=args.synthetic,
                max_requests=args.max_requests,max_tools=args.max_tools,retry_distillation=args.retry_distillation,
                retry_associations=args.retry_associations),ensure_ascii=False,indent=2))
            return 0
        if args.command == "transcript":
            # Read-only and store-free on purpose: the trace is self-contained (that is
            # why `--resume` can rebuild a handout without the library), and a person
            # looking back may be on a machine where the library has moved. Opening a
            # store here would create one for a question about a file.
            from .transcript import TranscriptError, load, render
            try:
                view = load(Path(args.trace).expanduser())
            except TranscriptError as exc:
                print(f"无法回看：{exc}。", file=sys.stderr)
                return 2
            if args.json:
                # `resumable` and `complete` are in the human screen, so they belong in
                # the machine view too: a reader writing a check against this JSON should
                # not have to re-derive "can this be resumed" by running `--resume`.
                payload = {key: view[key] for key in
                           ("session", "records", "partial_tail", "complete", "resumable",
                            "ended", "saved", "draft", "turns", "parts")}
                payload["path"] = str(view["path"])
                payload["handed"] = (
                    {key: view["handed"].get(key) for key in ("candidate", "statement", "status")}
                    if isinstance(view["handed"], dict) else None
                )
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                # The library named by `--db` (or $DOJO_DB or the default) is local
                # command context, passed through so the card commands this screen
                # prints open the library the reader was asking about. It is not read
                # out of the trace: the record of what he said keeps no host path.
                sys.stdout.write(render(view, database=db_path))
            return 0
        if args.command == "chat":
            config = LiveConfig.from_environment()
            _secure_default_paths(db_path, export_dir)
            store = Store(db_path)
            try:
                db_path.chmod(0o600)
            except OSError:
                pass
            return run_chat(store, config=config)
        # Read-only commands must not conjure the library they were pointed at. `search`
        # against a path that does not exist used to open (and create) an empty file and
        # then print "no words overlap" -- a statement about a collection that was never
        # read. The check sits here, before the generic `Store(...)` below, because that
        # constructor is what creates the file.
        if args.command == "search" and not db_path.exists():
            print("无法检索：" + str(db_path) + " 这个库不存在。"
                  "用 --db 指一个已有的库；检索不会替你建库（要建卡用 add，那会新建）。",
                  file=sys.stderr)
            return 2
        if args.command == "discuss":
            if args.no_trace and args.resume:
                print("无法续跑：--resume 与 --no-trace 不能同时使用。", file=sys.stderr)
                return 2
            if args.card and args.resume:
                print("无法续跑：--card 与 --resume 不能同时使用。", file=sys.stderr)
                return 2
            if args.resume:
                try:
                    _load_resume_trace(Path(args.resume).expanduser())
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
            # A name the person typed by hand is settled against the local library before
            # the endpoint is read. Walked at the real entry with no DOJO_LLM_BASE_URL
            # set: the refusal used to be "no base URL configured" for a mistyped card
            # id, which sends the reader to their endpoint settings for a mistake in a
            # card name.
            #
            # Opened `readonly` and only when a card was named: the no-endpoint failure is
            # pinned by two tests to leave no database behind, and a writer would create
            # an empty library merely to answer a question about a name. `run_discuss`
            # keeps the same check for callers that supply their own client, so the two
            # orders cannot disagree.
            if args.card:
                try:
                    with closing(Store(db_path, readonly=True)) as probe:
                        probe.show(args.card)
                except (DojoError, OSError) as exc:
                    print(f"无法开始讨论：这张卡读不出来（{exc}）；未发送网络请求。", file=sys.stderr)
                    return 2
            try:
                config = LiveConfig.from_environment()
            except LiveError as exc:
                if "needs DOJO_LLM_BASE_URL" in str(exc):
                    print("无法启动讨论：未配置 DOJO_LLM_BASE_URL，未发送网络请求。", file=sys.stderr)
                else:
                    print(f"无法启动讨论：模型端点配置无效（{exc}），未发送网络请求。", file=sys.stderr)
                return 2
            # Opened only after every local refusal above, so a command that is going to
            # fail leaves no library behind -- the two pinned "no database" tests. It is
            # opened here because `run_discuss` writes (the draft, the read record, the
            # trace directory) and needs a real store: the branch passed its `store`, which
            # was still None, and the first `store.show` died with
            # `'NoneType' object has no attribute 'show'` after 0 requests. Every test up to
            # this slice supplied its own client and store, so the real CLI's success path
            # had never been walked end to end.
            _secure_default_paths(db_path, export_dir)
            store = Store(db_path)
            try:
                db_path.chmod(0o600)
            except OSError:
                pass
            return run_discuss(
                store, config=config, no_trace=args.no_trace, no_profile=args.no_profile,
                resume=Path(args.resume).expanduser() if args.resume else None,
                verbose=args.verbose, card=args.card,
            )
        if args.command == "compare":
            run_compare(full=args.full, output=sys.stdout)
            return 0
        if args.command == "freeze-materials":
            destination = Path(args.outdir).expanduser()
            # #1893: no library, no packet. The old code built a throwaway library and
            # loaded the seeds into it, so every `entered_at` in the packet was the moment
            # of packaging. Falling back to the default location is not a fix either -- it
            # would print times from a library the caller never named, or create one.
            if args.db is None and not os.environ.get("DOJO_DB"):
                # #1904: the hint has to be a command a person can copy and run once.
                # It used to omit `--outdir`, which is required, so following the
                # instruction produced a second refusal from argparse. The two values
                # the reader must supply are named together, in the order the parser
                # wants them, and the one that must not already exist says so.
                print(
                    "无法生成冻结材料：这个包里每个 entered_at 都要从某个库的事件账本读出，"
                    "所以必须指定库。完整命令（两个位置都要给）：\n"
                    "  python3 -m dojo --db <已存在的库> freeze-materials --outdir <一个新的目录>\n"
                    "--outdir 指向的目录必须还不存在（已有目录会被拒绝覆盖）；"
                    "也可以在环境里设 DOJO_DB 代替 --db。不会用打包时刻代替入库时刻。",
                    file=sys.stderr,
                )
                return 2
            store = Store(db_path, readonly=True)
            result = freeze_materials(store, destination)
            _print_packet_result(result)
            return 0

        _secure_default_paths(db_path, export_dir)
        store = Store(db_path)
        result = _execute(args, store)
        try:
            db_path.chmod(0o600)
        except OSError:
            pass
        if result is SEARCH_SCREEN_ONLY:
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (DojoError, sqlite3.Error, OSError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()
        if tempdir is not None:
            tempdir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

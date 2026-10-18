"""Argument-parsed local command line for the dojo POC."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from .compare import run_compare
from .demo import freeze_materials, run_demo, write_demo_summary
from .discuss import _load_resume_trace, run_discuss
from .live import LiveConfig, LiveError, run_chat
from .storage import DojoError, Store, load_simulated_seeds

DEFAULT_HOME = Path.home() / ".local" / "share" / "dojo"
DEFAULT_DB = DEFAULT_HOME / "dojo.sqlite3"
DEFAULT_EXPORTS = DEFAULT_HOME / "exports"


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
        description="Local no-UI dojo POC; network access is possible only in explicitly selected live chat or discussion.",
    )
    parser.add_argument("--db", default=os.environ.get("DOJO_DB", str(DEFAULT_DB)), help=f"SQLite file (default: {DEFAULT_DB}; DOJO_DB overrides)")
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

    search = sub.add_parser("search", help="transparent lexical retrieval of discussable candidates only")
    search.add_argument("query", nargs="?")
    search.add_argument("--limit", type=int, default=10)

    export = sub.add_parser("export", help="create a new isolated B (no seed) or C (selected excerpt) prompt")
    export.add_argument("--mode", choices=["b", "c"], required=True)
    export.add_argument("--id", action="append", default=[], help="explicit selected candidate ID (C only); repeat to add")
    export.add_argument("--budget-chars", type=int, default=6000, help="hard maximum on complete prompt characters")
    export.add_argument("--outdir", default=os.environ.get("DOJO_EXPORTS", str(DEFAULT_EXPORTS)), help=f"independent export directory (default: {DEFAULT_EXPORTS})")

    events = sub.add_parser("events", help="inspect append-only events, including unversioned abstain records")
    events.add_argument("--id", help="filter by candidate ID")

    demo = sub.add_parser("demo", help="中文交互故事；默认离线预设模拟，不是实时 AI")
    demo.add_argument("--auto", action="store_true", help="不读取 stdin，自动走预设故事（适用于 CI）")
    demo.add_argument("--details", action="store_true", help="完整展开 Store 候选字段；默认只显示观点、条件、未知与来源状态")
    demo.add_argument("--live", action="store_true", help="改走真实模型聊天；需配置 DOJO_LLM_BASE_URL")
    demo.add_argument("--workdir", help="保存到一个新建/空目录；不覆盖已有数据库或总结")

    sub.add_parser("chat", help="显式启动真实模型聊天；使用 DOJO_LLM_BASE_URL/MODEL/API_KEY")
    discuss = sub.add_parser("discuss", help="自然语言协作讨论；会话原文仅写入本地轨迹")
    discuss.add_argument("--no-trace", action="store_true", help="不创建轨迹文件，也不保存会话原文")
    discuss.add_argument("--no-profile", action="store_true", help="本场既不读取也不写入人物档案")
    discuss.add_argument("--resume", metavar="TRACE", help="从既有轨迹续跑同一会话并追加写入")

    packets = sub.add_parser("freeze-materials", help="生成四份冻结模型输入；C 摘录来自真实本地 Store 检索")
    packets.add_argument("--outdir", default="docs/packets/frozen-conversation-v2", help="新输出目录；已有目录会拒绝覆盖")

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
        return store.retrieve(args.query or "", args.limit)
    if command == "export":
        return store.export_prompt(args.mode, args.id, args.budget_chars, args.outdir)
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
    raise DojoError("unknown command")


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
    print("文件：" + "、".join(result["files"]))
    print("C 条件实际检索来源：" + "、".join(result["retrieved_source_candidate_ids"]))
    print("检索：" + result["retrieval_method"])


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db).expanduser()
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
        if args.command == "chat":
            config = LiveConfig.from_environment()
            _secure_default_paths(db_path, export_dir)
            store = Store(db_path)
            try:
                db_path.chmod(0o600)
            except OSError:
                pass
            return run_chat(store, config=config)
        if args.command == "discuss":
            if args.no_trace and args.resume:
                print("无法续跑：--resume 与 --no-trace 不能同时使用。", file=sys.stderr)
                return 2
            if args.resume:
                try:
                    _load_resume_trace(Path(args.resume).expanduser())
                except ValueError as exc:
                    print(str(exc), file=sys.stderr)
                    return 2
            try:
                config = LiveConfig.from_environment()
            except LiveError as exc:
                if "needs DOJO_LLM_BASE_URL" in str(exc):
                    print("无法启动讨论：未配置 DOJO_LLM_BASE_URL，未发送网络请求。", file=sys.stderr)
                else:
                    print(f"无法启动讨论：模型端点配置无效（{exc}），未发送网络请求。", file=sys.stderr)
                return 2
            _secure_default_paths(db_path, export_dir)
            store = Store(db_path)
            try:
                db_path.chmod(0o600)
            except OSError:
                pass
            return run_discuss(
                store, config=config, no_trace=args.no_trace, no_profile=args.no_profile,
                resume=Path(args.resume).expanduser() if args.resume else None,
            )
        if args.command == "compare":
            run_compare(full=args.full, output=sys.stdout)
            return 0
        if args.command == "freeze-materials":
            destination = Path(args.outdir).expanduser()
            tempdir = tempfile.TemporaryDirectory(prefix="dojo-packets-")
            try:
                Path(tempdir.name).chmod(0o700)
            except OSError:
                pass
            store = Store(Path(tempdir.name) / "dojo.sqlite3")
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

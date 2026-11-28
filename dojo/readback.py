"""Local navigation from a specific approved snapshot to its discussion trace."""
from __future__ import annotations

import json
from pathlib import Path
import re

from . import commands, distillation
from .storage import Store


class Readback:
    def __init__(self, store: Store, session: str, trace: Path):
        self.store = store
        self.session = session
        self.trace = commands.absolute(trace)
        self.rounds, self.digest = distillation.read_trace(self.trace, session)
        self._archives = {}
        self._targets = {}

    def _command(self, path, digest, turns):
        return commands.dojo("transcript", path, *(arg for seq in turns for arg in ("--turn", seq)),
                             "--trace-sha256", digest, db=commands.library_argument(self.store.path))

    def _archive(self, session):
        if session not in self._archives:
            name = f"{session}.jsonl"
            nearby = self.trace.with_name(name) if self.digest else self.store.path.parent / "sessions" / name
            path, _ = commands.locate_record(nearby, self.store.path)
            rounds, digest = distillation.read_trace(path, session) if path else ([], None)
            approved, _ = distillation.approvals(self.store, session) if digest else ([], [])
            entries = {(card["id"], card["version"]): (card, records) for card, records in approved}
            self._archives[session] = path, rounds, digest, entries
        return self._archives[session]

    def _original(self, card_id, version):
        key = card_id, version
        if key not in self._targets:
            self._targets[key] = self._find_original(key)
        return self._targets[key]

    def _find_original(self, key):
        row = self.store.connection.execute(
            "SELECT state_json FROM snapshots WHERE candidate_id=? AND version=?", key,
        ).fetchone()
        if row:
            for session in json.loads(row["state_json"]).get("sessions", []):
                # Provenance groups don't by themselves name a local discussion.
                if session == self.session or not re.fullmatch(r"discuss-[0-9a-f]{32}", session):
                    continue
                path, rounds, digest, entries = self._archive(session)
                if key in entries:
                    card, records = entries[key]
                    turns = distillation.readback_turns(card, records, rounds)
                    label = f"回看对照卡 {key[0]} v{key[1]} 的原话"
                    if turns:
                        return self._anchor(label, path, digest, turns)
                    local_turn = distillation.draft_review_turn(card, records, rounds, digest)
                    if local_turn is not None:
                        return self._local_anchor(label, path, digest, local_turn)
        return None

    def _anchor(self, label, path, digest, turns):
        scope = "拟稿所在轮与认可轮" if len(turns) == 2 else "仅定位到认可轮"
        return f"  {label}（{scope}）：" + self._command(path, digest, turns)

    def _local_anchor(self, label, path, digest, turn):
        return (f"  {label}（拟稿所在轮；会后认可另记在库里）："
                + self._command(path, digest, [turn]))

    def lines(self, card, records, verdict):
        turns = distillation.readback_turns(card, records, self.rounds)
        local_turn = distillation.draft_review_turn(card, records, self.rounds, self.digest)
        if turns:
            yield self._anchor("回看本场原话", self.trace, self.digest, turns)
        elif local_turn is not None:
            yield self._local_anchor("回看本场原话", self.trace, self.digest, local_turn)
        elif any(record.get("draft_review") is not None for record in records):
            yield "  认可发生在会后；未能在给定轨迹定位原拟写，不以其他版本的原话替代。"
        else:
            yield "  无法在给定轨迹定位这一版的认可轮；不以其他版本的原话替代。"
        if verdict["of"]:
            line = self._original(verdict["of"], verdict["of_version"])
            yield line or f"  未能定位对照卡 v{verdict['of_version']} 的原话；上面列的是库中对照版的范围。"

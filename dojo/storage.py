"""Local, evented SQLite storage for the dojo CLI."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


KINDS = {"abstract_idea", "experience_claim", "application", "question", "counterexample"}
STATUSES = {"draft", "discussable", "challenged", "withdrawn", "superseded"}
RELATIONS = {
    "supports", "challenges", "narrows", "generalizes", "conflicts",
    "instantiates", "duplicates",
}
SOURCE_TYPES = {
    "abstract_reasoning", "claimed_firsthand", "artifact_observation",
    "secondhand_report", "model_generated", "synthetic_roleplay", "unknown",
}
VERIFICATIONS = {"not_evidence", "unverified", "independently_checked", "disputed", "unknown"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class DojoError(Exception):
    """An expected, user-correctable POC operation error."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _id(value: str, label: str = "ID") -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise DojoError(f"{label} must use 1-80 letters, numbers, dot, underscore, or hyphen")
    return value


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DojoError(f"{label} cannot be empty")
    return value.strip()


def _strings(values: list[str] | None, label: str) -> list[str]:
    result = []
    for value in values or []:
        clean = _text(value, label)
        if clean not in result:
            result.append(clean)
    return result


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Store:
    """Single-database storage boundary; all mutations are SQLite transactions."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = DELETE")
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                id TEXT PRIMARY KEY,
                version INTEGER NOT NULL CHECK(version > 0),
                state_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                candidate_id TEXT NOT NULL REFERENCES candidates(id),
                version INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(candidate_id, version)
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id TEXT REFERENCES candidates(id),
                event TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_by_candidate ON events(candidate_id, seq);
            """
        )

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _event(self, candidate_id: str | None, event: str, details: dict[str, Any]) -> int:
        cursor = self.connection.execute(
            "INSERT INTO events(candidate_id,event,details_json,created_at) VALUES(?,?,?,?)",
            (candidate_id, event, _json(details), _now()),
        )
        return int(cursor.lastrowid)

    def _insert_candidate(self, state: dict[str, Any], event: str, details: dict[str, Any]) -> None:
        candidate_id = state["id"]
        payload = _json(state)
        now = _now()
        self.connection.execute(
            "INSERT INTO candidates(id,version,state_json) VALUES(?,?,?)",
            (candidate_id, state["version"], payload),
        )
        self.connection.execute(
            "INSERT INTO snapshots(candidate_id,version,state_json,created_at) VALUES(?,?,?,?)",
            (candidate_id, state["version"], payload, now),
        )
        self._event(candidate_id, event, details)

    def _get(self, candidate_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT state_json FROM candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise DojoError(f"candidate not found: {candidate_id}")
        return json.loads(row["state_json"])

    def _write(self, state: dict[str, Any], event: str, details: dict[str, Any]) -> dict[str, Any]:
        candidate_id = state["id"]
        current = self._get(candidate_id)
        state = dict(state)
        state["version"] = current["version"] + 1
        payload = _json(state)
        now = _now()
        self.connection.execute(
            "UPDATE candidates SET version=?,state_json=? WHERE id=?",
            (state["version"], payload, candidate_id),
        )
        self.connection.execute(
            "INSERT INTO snapshots(candidate_id,version,state_json,created_at) VALUES(?,?,?,?)",
            (candidate_id, state["version"], payload, now),
        )
        self._event(candidate_id, event, {**details, "version": state["version"]})
        return state

    def _source(self, source: dict[str, Any]) -> dict[str, str]:
        if not isinstance(source, dict):
            raise DojoError("each source must be a JSON object")
        source_id = _id(source.get("id") or _new_id("src"), "source ID")
        source_type = source.get("type", "unknown")
        verification = source.get("verification", "unknown")
        if source_type not in SOURCE_TYPES:
            raise DojoError(f"unknown source type: {source_type}")
        if verification not in VERIFICATIONS:
            raise DojoError(f"unknown source verification: {verification}")
        return {
            "id": source_id,
            "type": source_type,
            "claim": _text(source.get("claim", "source details not supplied"), "source claim"),
            "independence_group": _text(source.get("independence_group", "unknown"), "independence group"),
            "verification": verification,
            "scope_note": str(source.get("scope_note", "")).strip(),
        }

    def _source_ids_available(self, sources: list[dict[str, str]]) -> None:
        seen: dict[str, dict[str, str]] = {}
        for source in sources:
            if source["id"] in seen and seen[source["id"]] != source:
                raise DojoError(f"conflicting source ID in operation: {source['id']}")
            seen[source["id"]] = source
        for source_id, source in seen.items():
            rows = self.connection.execute("SELECT state_json FROM candidates").fetchall()
            for row in rows:
                state = json.loads(row["state_json"])
                existing = next((item for item in state.get("sources", []) if item["id"] == source_id), None)
                if existing is not None and existing != source:
                    raise DojoError(f"source ID already belongs to different provenance: {source_id}")
                if existing is not None:
                    raise DojoError(f"source ID already exists: {source_id}")

    def add(
        self,
        statement: str,
        kind: str,
        *,
        candidate_id: str | None = None,
        premises: list[str] | None = None,
        scope: list[str] | None = None,
        alternatives: list[str] | None = None,
        contradictions: list[str] | None = None,
        unknowns: list[str] | None = None,
        sources: list[dict[str, Any]] | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        statement = _text(statement, "statement")
        if kind not in KINDS:
            raise DojoError(f"kind must be one of: {', '.join(sorted(KINDS))}")
        candidate_id = _id(candidate_id or _new_id("d"))
        source_values = [self._source(source) for source in sources or []]
        with self.transaction():
            if self.connection.execute("SELECT 1 FROM candidates WHERE id=?", (candidate_id,)).fetchone():
                raise DojoError(f"candidate ID already exists: {candidate_id}")
            self._source_ids_available(source_values)
            state = {
                "id": candidate_id,
                "version": 1,
                "status": "draft",
                "statement": statement,
                "kind": kind,
                "premises": _strings(premises, "premise"),
                "scope": _strings(scope, "scope"),
                "alternatives": _strings(alternatives, "alternative"),
                "contradictions": _strings(contradictions, "contradiction"),
                "unknowns": _strings(unknowns, "unknown"),
                "sources": source_values,
                "aliases": [],
                "relations": [],
                "sessions": [_text(session, "session")] if session else [],
                "confirmation": {"active": False},
            }
            self._insert_candidate(state, "add", {"session": session})
        return state

    def list_candidates(self, include_history: bool = False) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT state_json FROM candidates ORDER BY id").fetchall()
        values = [json.loads(row["state_json"]) for row in rows]
        if include_history:
            return values
        return [{key: state[key] for key in ("id", "version", "status", "statement", "kind")} for state in values]

    def history(self, candidate_id: str) -> dict[str, Any]:
        candidate_id = _id(candidate_id)
        snapshots = self.connection.execute(
            "SELECT version,state_json,created_at FROM snapshots WHERE candidate_id=? ORDER BY version",
            (candidate_id,),
        ).fetchall()
        if not snapshots:
            raise DojoError(f"candidate not found: {candidate_id}")
        events = self.connection.execute(
            "SELECT event,details_json,created_at FROM events WHERE candidate_id=? ORDER BY seq",
            (candidate_id,),
        ).fetchall()
        return {
            "candidate_id": candidate_id,
            "versions": [
                {"version": row["version"], "state": json.loads(row["state_json"]), "created_at": row["created_at"]}
                for row in snapshots
            ],
            "events": [
                {"event": row["event"], "details": json.loads(row["details_json"]), "created_at": row["created_at"]}
                for row in events
            ],
        }

    def resolve(self, candidate_id: str) -> tuple[dict[str, Any], list[str]]:
        requested = _id(candidate_id)
        path: list[str] = []
        current_id = requested
        while True:
            if current_id in path:
                raise DojoError(f"redirect loop detected: {' -> '.join(path + [current_id])}")
            path.append(current_id)
            state = self._get(current_id)
            target = state.get("redirect_to")
            if not target:
                return state, path
            current_id = _id(target, "redirect target")

    def _present_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Resolve stored relation targets for display without rewriting history."""
        result = dict(state)
        relations = []
        for relation in state.get("relations", []):
            displayed = dict(relation)
            target, chain = self.resolve(relation["target"])
            if len(chain) > 1:
                displayed["redirected_from"] = relation["target"]
            displayed["target"] = target["id"]
            relations.append(displayed)
        if "relations" in result:
            result["relations"] = relations
        return result

    def show(self, candidate_id: str) -> dict[str, Any]:
        state, path = self.resolve(candidate_id)
        return {"requested_id": candidate_id, "resolved_id": state["id"], "redirect_chain": path, "candidate": self._present_state(state)}

    def _active(self, state: dict[str, Any]) -> None:
        if state.get("redirect_to") or state["status"] == "superseded":
            raise DojoError("redirected/superseded candidates cannot be changed")
        if state["status"] == "withdrawn":
            raise DojoError("withdrawn candidate must be revised before confirmation or linking")

    def _confirmation_off(self, state: dict[str, Any], reason: str) -> dict[str, Any]:
        confirmation = dict(state.get("confirmation") or {})
        confirmation["active"] = False
        confirmation["revoked_reason"] = reason
        return confirmation

    def confirm(self, candidate_id: str, basis: str, session: str | None = None) -> dict[str, Any]:
        basis = _text(basis, "confirmation basis")
        with self.transaction():
            state = self._get(_id(candidate_id))
            if state.get("redirect_to") or state["status"] in {"withdrawn", "superseded"}:
                raise DojoError("only a current, non-withdrawn candidate can be confirmed discussable")
            state["status"] = "discussable"
            state["confirmation"] = {
                "active": True, "confirmed_by": "facilitator-role", "session": session,
                "basis": basis, "not_truth_claim": True,
            }
            if session:
                state["sessions"] = _strings(state.get("sessions", []) + [session], "session")
            state = self._write(state, "confirm_discussable", {"basis": basis, "session": session, "not_truth_claim": True})
        return state

    def revoke(self, candidate_id: str, reason: str, session: str | None = None) -> dict[str, Any]:
        reason = _text(reason, "revocation reason")
        with self.transaction():
            state = self._get(_id(candidate_id))
            if not state.get("confirmation", {}).get("active") or state["status"] != "discussable":
                raise DojoError("candidate has no active discussability confirmation")
            state["status"] = "draft"
            state["confirmation"] = self._confirmation_off(state, reason)
            if session:
                state["sessions"] = _strings(state.get("sessions", []) + [session], "session")
            state = self._write(state, "revoke_confirmation", {"reason": reason, "session": session})
        return state

    def challenge(self, candidate_id: str, text: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
        text = _text(text, "challenge")
        with self.transaction():
            state = self._get(_id(candidate_id))
            self._active(state)
            if source:
                source_value = self._source(source)
                self._source_ids_available([source_value])
                state["sources"].append(source_value)
            state["contradictions"] = _strings(state.get("contradictions", []) + [text], "challenge")
            state["status"] = "challenged"
            if state.get("confirmation", {}).get("active"):
                state["confirmation"] = self._confirmation_off(state, "candidate challenged")
            state = self._write(state, "challenge", {"text": text})
        return state

    def revise(
        self,
        candidate_id: str,
        statement: str,
        reason: str,
        *,
        kind: str | None = None,
        premises: list[str] | None = None,
        scope: list[str] | None = None,
        alternatives: list[str] | None = None,
        contradictions: list[str] | None = None,
        unknowns: list[str] | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        statement, reason = _text(statement, "statement"), _text(reason, "revision reason")
        if kind is not None and kind not in KINDS:
            raise DojoError(f"kind must be one of: {', '.join(sorted(KINDS))}")
        revised_fields = {
            "premises": premises,
            "scope": scope,
            "alternatives": alternatives,
            "contradictions": contradictions,
            "unknowns": unknowns,
        }
        with self.transaction():
            state = self._get(_id(candidate_id))
            self._active(state)
            old_statement = state["statement"]
            state["statement"] = statement
            if kind is not None:
                state["kind"] = kind
            for field, values in revised_fields.items():
                if values is not None:
                    state[field] = _strings(values, field)
            if session:
                state["sessions"] = _strings(state.get("sessions", []) + [session], "session")
            state["status"] = "draft"
            state["confirmation"] = self._confirmation_off(state, "candidate revised")
            details = {"from_statement": old_statement, "reason": reason}
            changed_fields = [field for field, values in revised_fields.items() if values is not None]
            if kind is not None or changed_fields or session is not None:
                details["changed_fields"] = ["statement", *changed_fields]
                if kind is not None:
                    details["changed_fields"].append("kind")
                if session is not None:
                    details["session"] = session
            state = self._write(state, "revise", details)
        return state

    def alias(self, candidate_id: str, wording: str, reason: str) -> dict[str, Any]:
        wording, reason = _text(wording, "alias"), _text(reason, "alias reason")
        with self.transaction():
            state = self._get(_id(candidate_id))
            self._active(state)
            if wording == state["statement"] or wording in state["aliases"]:
                raise DojoError("alias is already present or identical to the statement")
            state["aliases"].append(wording)
            state = self._write(state, "alias", {"wording": wording, "reason": reason})
        return state

    def link(self, candidate_id: str, relation: str, target_id: str, reason: str) -> dict[str, Any]:
        if relation not in RELATIONS:
            raise DojoError(f"relation must be one of: {', '.join(sorted(RELATIONS))}")
        reason = _text(reason, "link reason")
        with self.transaction():
            source = self._get(_id(candidate_id))
            self._active(source)
            target, _ = self.resolve(target_id)
            if target["status"] == "superseded" and not target.get("redirect_to"):
                raise DojoError("cannot link to a split/superseded candidate")
            if source["id"] == target["id"]:
                raise DojoError("self-links are not allowed")
            link = {"type": relation, "target": target["id"], "note": reason}
            if link in source.get("relations", []):
                raise DojoError("identical relation already exists")
            source["relations"].append(link)
            source = self._write(source, "link", link)
        return source

    def split(self, candidate_id: str, children: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
        reason = _text(reason, "split reason")
        if len(children) < 2:
            raise DojoError("split requires at least two child candidates")
        with self.transaction():
            parent = self._get(_id(candidate_id))
            self._active(parent)
            source_by_id = {source["id"]: source for source in parent.get("sources", [])}
            child_values: list[dict[str, Any]] = []
            child_ids: set[str] = set()
            for raw in children:
                if not isinstance(raw, dict):
                    raise DojoError("each split child must be a JSON object")
                child_id = _id(raw.get("id") or _new_id("d"), "child ID")
                if child_id == parent["id"] or child_id in child_ids or self.connection.execute("SELECT 1 FROM candidates WHERE id=?", (child_id,)).fetchone():
                    raise DojoError(f"child candidate ID already exists: {child_id}")
                child_ids.add(child_id)
                kind = raw.get("kind", parent["kind"])
                if kind not in KINDS:
                    raise DojoError(f"kind must be one of: {', '.join(sorted(KINDS))}")
                requested_sources = raw.get("source_ids")
                if requested_sources is None:
                    child_sources = list(parent.get("sources", []))
                else:
                    if not isinstance(requested_sources, list) or any(item not in source_by_id for item in requested_sources):
                        raise DojoError("split source_ids must refer to source IDs on the parent")
                    if len(set(requested_sources)) != len(requested_sources):
                        raise DojoError("split source_ids must not contain duplicates")
                    child_sources = [source_by_id[item] for item in requested_sources]
                child_values.append({
                    "id": child_id,
                    "version": 1,
                    "status": "draft",
                    "statement": _text(raw.get("statement"), "child statement"),
                    "kind": kind,
                    "premises": _strings(raw.get("premises", parent.get("premises", [])), "premise"),
                    "scope": _strings(raw.get("scope", parent.get("scope", [])), "scope"),
                    "alternatives": _strings(raw.get("alternatives", parent.get("alternatives", [])), "alternative"),
                    "contradictions": _strings(raw.get("contradictions", parent.get("contradictions", [])), "contradiction"),
                    "unknowns": _strings(raw.get("unknowns", parent.get("unknowns", [])), "unknown"),
                    "sources": child_sources,
                    "aliases": [],
                    "relations": [],
                    "sessions": list(parent.get("sessions", [])),
                    "split_from": parent["id"],
                    "confirmation": {"active": False},
                })
            for child in child_values:
                self._insert_candidate(child, "split_child", {"parent": parent["id"], "reason": reason})
            parent["status"] = "superseded"
            parent["confirmation"] = self._confirmation_off(parent, "split into child candidates")
            parent["split_children"] = [child["id"] for child in child_values]
            self._write(parent, "split", {"children": [child["id"] for child in child_values], "reason": reason})
        return child_values

    def _source_union(self, first: list[dict[str, Any]], second: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = list(first)
        by_id = {item["id"]: item for item in result}
        for source in second:
            previous = by_id.get(source["id"])
            if previous is not None:
                if previous != source:
                    raise DojoError(f"cannot merge conflicting provenance for source ID {source['id']}")
                continue
            result.append(source)
            by_id[source["id"]] = source
        return result

    def merge(self, source_id: str, target_id: str, *, confirmed: bool, reason: str) -> dict[str, Any]:
        if not confirmed:
            raise DojoError("merge requires explicit human acknowledgement (--confirm)")
        reason = _text(reason, "merge reason")
        with self.transaction():
            source, source_chain = self.resolve(source_id)
            target, target_chain = self.resolve(target_id)
            if source["id"] == target["id"]:
                raise DojoError("merge source and target resolve to the same candidate")
            self._active(source)
            self._active(target)
            if source["status"] == "withdrawn" or target["status"] == "withdrawn":
                raise DojoError("withdrawn candidates cannot be merged")
            before_source, before_target = source, target
            target = dict(target)
            sources = self._source_union(target.get("sources", []), source.get("sources", []))
            aliases = list(target.get("aliases", []))
            for wording in [source["statement"], *source.get("aliases", [])]:
                if wording != target["statement"] and wording not in aliases:
                    aliases.append(wording)
            target["sources"] = sources
            target["aliases"] = aliases
            for key in ("premises", "scope", "alternatives", "contradictions", "unknowns"):
                target[key] = _strings(target.get(key, []) + source.get(key, []), key)
            for relation in source.get("relations", []):
                resolved, _ = self.resolve(relation["target"])
                if resolved["id"] != target["id"]:
                    value = {**relation, "target": resolved["id"]}
                    if value not in target["relations"]:
                        target["relations"].append(value)
            # Resolve both endpoints before installing the new redirect; this rejects existing loops.
            if source["id"] in target_chain or target["id"] in source_chain:
                raise DojoError("merge would create a redirect cycle")
            target = self._write(target, "merge_received", {"source": source["id"], "reason": reason})
            source = dict(source)
            source["status"] = "superseded"
            source["redirect_to"] = target["id"]
            source["confirmation"] = self._confirmation_off(source, "merged into " + target["id"])
            source = self._write(source, "merge_redirect", {"target": target["id"], "reason": reason})
            event_id = self._event(source["id"], "merge", {
                "source": source["id"], "target": target["id"], "reason": reason,
                "before_source": before_source, "before_target": before_target,
                "after_source_version": source["version"], "after_target_version": target["version"],
            })
            source["last_merge_event"] = event_id  # returned only; not persisted in candidate state
        return self._get(target["id"])

    def unmerge(self, source_id: str, reason: str) -> dict[str, Any]:
        reason = _text(reason, "unmerge reason")
        source_id = _id(source_id)
        with self.transaction():
            event_row = self.connection.execute(
                "SELECT seq,details_json FROM events WHERE candidate_id=? AND event='merge' ORDER BY seq DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            if event_row is None:
                raise DojoError(f"no reversible merge found for source candidate {source_id}")
            details = json.loads(event_row["details_json"])
            source_now = self._get(details["source"])
            target_now = self._get(details["target"])
            if source_now.get("redirect_to") != target_now["id"]:
                raise DojoError("merge is no longer current")
            if source_now["version"] != details["after_source_version"] or target_now["version"] != details["after_target_version"]:
                raise DojoError("cannot unmerge after either candidate has changed; review and restore manually")
            source_restored = dict(details["before_source"])
            target_restored = dict(details["before_target"])
            source_restored = self._write(source_restored, "unmerge", {"target": target_now["id"], "reason": reason})
            target_restored = self._write(target_restored, "unmerge", {"source": source_now["id"], "reason": reason})
        return {"source": source_restored, "target": target_restored}

    def abstain(self, reason: str, candidate_id: str | None = None, next_question: str | None = None) -> dict[str, Any]:
        reason = _text(reason, "abstain reason")
        if candidate_id:
            candidate_id = _id(candidate_id)
            self._get(candidate_id)
        if next_question is not None:
            next_question = _text(next_question, "next question")
        with self.transaction():
            event_id = self._event(candidate_id, "abstain", {"reason": reason, "next_question": next_question})
        return {"event_id": event_id, "candidate_id": candidate_id, "reason": reason, "next_question": next_question}

    def withdraw(self, candidate_id: str, reason: str) -> dict[str, Any]:
        reason = _text(reason, "withdrawal reason")
        with self.transaction():
            state = self._get(_id(candidate_id))
            self._active(state)
            state["status"] = "withdrawn"
            state["confirmation"] = self._confirmation_off(state, reason)
            state = self._write(state, "withdraw", {"reason": reason})
        return state

    def _matches(self, terms: set[str]) -> list[tuple[int, set[str], dict[str, Any]]]:
        """Every discussable card whose text overlaps `terms`, best overlap first."""
        rows = self.connection.execute("SELECT state_json FROM candidates ORDER BY id").fetchall()
        matches: dict[str, tuple[int, set[str], dict[str, Any]]] = {}
        for row in rows:
            state = json.loads(row["state_json"])
            try:
                canonical, _chain = self.resolve(state["id"])
            except DojoError:
                continue
            if canonical["status"] != "discussable" or canonical.get("redirect_to"):
                continue
            found = terms.intersection(lexical_terms(candidate_text(canonical)))
            if found:
                previous = matches.get(canonical["id"])
                if previous is None or len(found) > previous[0]:
                    matches[canonical["id"]] = (len(found), found, canonical)
        return sorted(matches.values(), key=lambda item: (-item[0], item[2]["id"]))

    def retrieve(self, query: str, limit: int = 10) -> dict[str, Any]:
        query = str(query or "").strip()
        if limit < 1 or limit > 100:
            raise DojoError("limit must be between 1 and 100")
        terms = lexical_terms(query, query=True)
        if not terms:
            return {"query": query, "method": "distinct lexical term overlap; no semantic inference", "matched_terms": [], "results": []}
        ordered = self._matches(terms)[:limit]
        results = []
        for score, found, state in ordered:
            results.append({
                "id": state["id"],
                "version": state["version"],
                "status": state["status"],
                "statement": state["statement"],
                "kind": state["kind"],
                "score": score,
                "matched_terms": sorted(found),
                "scope": state.get("scope", []),
                "premises": state.get("premises", []),
                "alternatives": state.get("alternatives", []),
                "contradictions": state.get("contradictions", []),
                "unknowns": state.get("unknowns", []),
                "sources": state.get("sources", []),
                "relations": self._present_state(state).get("relations", []),
                "aliases": state.get("aliases", []),
            })
        return {
            "query": query,
            "method": "transparent lexical overlap (distinct query terms only); not semantic search or truth ranking",
            "matched_terms": sorted(terms),
            "results": results,
        }

    def broadcast(self, query: str, limit: int = 10, exclude_session: str | None = None) -> dict[str, Any]:
        """Retrieval as cross-session broadcasting uses it: what other sessions arrived at.

        Two exclusions, both reported rather than dropped: a card that arrived over
        the network as a raw list is not what the facilitator may say, and a card
        resting on one discussion session is that session's word, not a second
        stranger's compatible or opposing claim. Independence is reported per result
        and is not used to reorder relevance.
        """
        query = str(query or "").strip()
        if limit < 1 or limit > 100:
            raise DojoError("limit must be between 1 and 100")
        terms = lexical_terms(query, query=True)
        method = (
            "transparent lexical overlap (distinct query terms only) over cross-session material; "
            "independence is reported per result and is not a relevance or truth ranking"
        )
        if not terms:
            return {"query": query, "method": method, "matched_terms": [], "results": [], "suppressed": []}
        results = []
        suppressed = []
        for score, found, state in self._matches(terms):
            info = independence(state)
            reason = None
            if exclude_session is not None and exclude_session in info["sessions"]:
                reason = "written by the session asking: a session does not broadcast its own word back"
            elif info["single_session"]:
                reason = "single-session provenance: no second independent group backs it"
            if reason is not None:
                suppressed.append({"id": state["id"], "reason": reason})
                continue
            if len(results) >= limit:
                continue
            results.append({
                "id": state["id"],
                "version": state["version"],
                "status": state["status"],
                "statement": state["statement"],
                "kind": state["kind"],
                "score": score,
                "matched_terms": sorted(found),
                "scope": state.get("scope", []),
                "premises": state.get("premises", []),
                "alternatives": state.get("alternatives", []),
                "contradictions": state.get("contradictions", []),
                "unknowns": state.get("unknowns", []),
                "sources": state.get("sources", []),
                "independence": info,
            })
        return {
            "query": query,
            "method": method,
            "matched_terms": sorted(terms),
            "results": results,
            "suppressed": suppressed,
        }

    def export_prompt(self, mode: str, ids: list[str], budget_chars: int, export_dir: str | Path) -> dict[str, Any]:
        if mode not in {"b", "c"}:
            raise DojoError("export mode must be b or c")
        if budget_chars < 100:
            raise DojoError("character budget must be at least 100")
        if mode == "b" and ids:
            raise DojoError("B export is seed-free; do not provide IDs")
        if mode == "c" and not ids:
            raise DojoError("C export requires explicitly selected candidate IDs")
        if len(set(ids)) != len(ids):
            raise DojoError("candidate IDs in an export must be unique")
        target_message = (
            "我在做一个小工具，经常先写代码、后来才发现需求没想清楚，返工很多。我在考虑强迫自己每次先写完整需求文档。"
            "目前没有数据说明哪种做法更有效，也不知道这条路线的效果。别假定我没说过的条件。"
        )
        excerpts = []
        for candidate_id in ids:
            state, _ = self.resolve(candidate_id)
            if state["status"] != "discussable" or state.get("redirect_to"):
                raise DojoError(f"selected candidate is not currently discussable: {candidate_id}")
            info = independence(state)
            if info["single_session"]:
                raise DojoError(
                    f"single-session provenance cannot be exported as cross-session material: {candidate_id}"
                )
            excerpts.append((state, info))
        lines = [
            "This is a simulated decision exercise, not verified evidence.",
            "Distinguish supplied facts, opinions, assumptions, conflicts, and unknowns. Do not invent probabilities or treat discussability as truth.",
            "Keep the delivery constraint visible. Cite source IDs for any selected excerpt used; state when evidence is absent.",
            "",
            "Target case:",
            target_message,
        ]
        if mode == "c":
            lines.extend(["", "Explicitly selected dojo excerpts (not an answer key):"])
            for state, info in excerpts:
                lines.append(
                    f"\n[{state['id']} v{state['version']} | {state['kind']} | status={state['status']}"
                    f" | independence_groups={len(info['independence_groups'])}"
                    f" | independent={str(info['independent']).lower()}]"
                )
                lines.append(state["statement"])
                for key in ("premises", "scope", "alternatives", "contradictions", "unknowns"):
                    values = state.get(key, [])
                    if values:
                        lines.append(f"{key}: " + " | ".join(values))
                if state.get("sources"):
                    lines.append("sources:")
                    for source in state["sources"]:
                        lines.append(
                            f"- {source['id']} | {source['type']} | verification={source['verification']} "
                            f"| independence_group={source['independence_group']} | {source['claim']}"
                        )
                if state.get("relations"):
                    lines.append("relations: " + " | ".join(
                        f"{item['type']}:{item['target']} ({item['note']})" for item in state["relations"]
                    ))
        lines.extend(["", "Respond with a bounded analysis and explicit remaining unknowns."])
        prompt = "\n".join(lines).strip() + "\n"
        if len(prompt) > budget_chars:
            raise DojoError(f"export would exceed character budget: {len(prompt)} > {budget_chars}; nothing written")
        directory = Path(export_dir).expanduser()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        name = f"dojo-{mode}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}.txt"
        path = directory / name
        with path.open("x", encoding="utf-8") as stream:
            stream.write(prompt)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return {"path": str(path), "mode": mode.upper(), "source_candidate_ids": [state["id"] for state, _info in excerpts], "characters": len(prompt), "budget_chars": budget_chars}


def lexical_terms(text: str, *, query: bool = False) -> set[str]:
    """Return inspectable Latin tokens; multi-character CJK queries use bigrams to reduce noise."""
    lowered = text.casefold()
    terms = set(re.findall(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", lowered))
    for run in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", lowered):
        if not query or len(run) == 1:
            terms.update(run)
        terms.update(run[index:index + 2] for index in range(len(run) - 1))
    return terms


def independence(state: dict[str, Any]) -> dict[str, Any]:
    """What a card's provenance supports, computed from its sources and sessions.

    `single_session` is the isolation claim design.md names: the card comes from a
    discussion session and its one provenance group is that same session, so it is
    one session's word and not cross-session material. `independent` says two or
    more distinct groups back it. A card that names no group is reported as having
    none rather than assumed either way. Nothing here is stored twice.
    """
    groups = sorted({
        source["independence_group"]
        for source in state.get("sources", [])
        if source.get("independence_group") and source.get("independence_group") != "unknown"
    })
    sessions = list(state.get("sessions", []))
    return {
        "independence_groups": groups,
        "sessions": sessions,
        "independent": len(groups) >= 2,
        "single_session": len(groups) == 1 and groups[0] in sessions,
    }


def candidate_text(state: dict[str, Any]) -> str:
    values = [state.get("statement", ""), *state.get("aliases", [])]
    for key in ("premises", "scope", "alternatives", "contradictions", "unknowns"):
        values.extend(state.get(key, []))
    for source in state.get("sources", []):
        values.extend([source.get("claim", ""), source.get("type", ""), source.get("scope_note", "")])
    return " ".join(str(value) for value in values)


SEEDS: list[dict[str, Any]] = [
    {
        "id": "seed-m01", "statement": "环境与流程的设计，往往比临时的决心更能稳住重复行为；降低启动摩擦通常比反复下决心更可持续。",
        "kind": "abstract_idea", "scope": ["日常重复行为能否持续（如物品归位、例行整理）"],
        "premises": ["该行为会重复发生", "意愿与摩擦可以在讨论上分开考虑"],
        "alternatives": ["若困难主要来自不知道怎么做，降低操作摩擦帮助有限"],
        "unknowns": ["摩擦要降低多少才算明显有用", "有没有不适用场景"],
        "sources": [{"id": "src-m01", "type": "abstract_reasoning", "claim": "由模拟陌生人场景推理得出的抽象区分", "independence_group": "stranger-methodology-v1", "verification": "not_evidence", "scope_note": "非经验证据"}],
    },
    {
        "id": "seed-m02", "statement": "若只是想维持现状、且这个行为本身没有训练价值，那么减少步骤、把正确动作的准备前置，通常能提高它持续发生的概率。",
        "kind": "application", "scope": ["目标是维持既有状态、行为本身不构成能力练习时"],
        "premises": ["该行为本身没有训练价值", "减少的只是与目标无关的步骤"],
        "alternatives": ["若这个行为本身就是在练习一种能力，减少步骤可能反而有害"],
        "unknowns": ["怎样判断一个行为有没有训练价值"],
        "sources": [{"id": "src-m02", "type": "abstract_reasoning", "claim": "由模拟陌生人场景条件推演得出的路线甲", "independence_group": "stranger-methodology-v1", "verification": "not_evidence", "scope_note": "非经验证据"}],
        "relations": [{"type": "narrows", "target": "seed-m01", "note": "在行为本身没有训练价值时细化降低摩擦的思路"}],
    },
    {
        "id": "seed-m03", "statement": "若一个行为的价值正来自练习过程本身，那么降低难度等于同时去掉练习机会；这时应保留有意义的难度，只去除与目标无关的无谓摩擦。",
        "kind": "application", "scope": ["能力的形成本身依赖练习过程时"],
        "premises": ["存在构成能力本身的练习难度", "可以把无谓摩擦与训练难度分开"],
        "alternatives": ["若某种困难只是习惯性的麻烦，仍应归入可以降低的摩擦"],
        "unknowns": ["怎样判断一份难度是“有意义”还是“只是麻烦”"],
        "sources": [{"id": "src-m03", "type": "abstract_reasoning", "claim": "由模拟陌生人场景条件推演得出的路线乙", "independence_group": "stranger-methodology-v1", "verification": "not_evidence", "scope_note": "非经验证据；与 seed-m02 为不同条件路线"}],
        "relations": [{"type": "narrows", "target": "seed-m01", "note": "在行为价值来自练习本身时限定降低摩擦"}],
    },
    {
        "id": "seed-m04", "statement": "一名模拟角色自述：靠每次只做一件小事，坚持了数月整洁，而没有依赖更强的自律。",
        "kind": "experience_claim", "scope": ["单一模拟角色对自身经历的记忆"],
        "premises": ["该角色相信自己的记忆"],
        "alternatives": ["记忆可能不完整，或存在其他解释"],
        "unknowns": ["时间范围、是否中途失败、是否换了别的做法、有没有独立来源，均缺失"],
        "sources": [{"id": "src-m04", "type": "claimed_firsthand", "claim": "模拟角色声称靠每次只做一件小事坚持了数月整洁", "independence_group": "unknown", "verification": "unverified", "scope_note": "没有记录、时间范围或可独立核验来源；重复传播不构成独立佐证"}],
    },
]


def load_simulated_seeds(store: Store) -> dict[str, Any]:
    """Load the four documented simulated examples once; never overwrite existing IDs."""
    ids = {seed["id"] for seed in SEEDS}
    present = {row["id"] for row in store.list_candidates(include_history=True)}.intersection(ids)
    if present:
        if present == ids:
            return {"loaded": False, "ids": sorted(ids), "message": "simulated seeds already present; nothing changed"}
        raise DojoError("only some seed IDs already exist; refusing partial overwrite: " + ", ".join(sorted(present)))
    with store.transaction():
        for seed in SEEDS:
            state = {
                **seed,
                "version": 1,
                "status": "discussable",
                "aliases": [],
                "sessions": [],
                "confirmation": {
                    "active": True,
                    "confirmed_by": "seed-pack-v1 initializer",
                    "session": None,
                    "basis": "simulated seed supplied for the POC; discussable only, not a truth claim",
                    "not_truth_claim": True,
                },
            }
            store._insert_candidate(state, "load_simulated_seed", {"seed_pack": "seed-pack-v1", "not_truth_claim": True})
    return {"loaded": True, "ids": sorted(ids), "message": "four simulated candidates loaded; none are verified evidence"}

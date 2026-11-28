#!/usr/bin/env python3
"""Compare one live opening and its resume without emitting discussion text.

Input: a private run directory with open/ and resume/ (stdout.txt and requests.jsonl
in each), and sessions/ containing the single continued JSONL. requests.jsonl stores
objects with request (OpenAI-compatible body) and status (upstream HTTP code).
"""
import hashlib
import json
import sys
from pathlib import Path


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def main(root):
    (trace,) = (root / "sessions").glob("*.jsonl")
    records = rows(trace)
    (handout,) = [r for r in records if r.get("event") == "handout"]
    ends = [r for r in records if r.get("event") == "session_end"]
    assert len(ends) == 2, "expected two segments of the same trace"
    attached = handout["answers"]
    assert len(attached) == 4, "expected four snapshot entries"
    contents, summaries = [], []
    for segment in ("open", "resume"):
        folder = root / segment
        capture = rows(folder / "requests.jsonl")
        assert capture and capture[0]["status"] == 200, f"{segment}: missing upstream response"
        request = capture[0]["request"]
        screen = (folder / "stdout.txt").read_text(encoding="utf-8").split("你> ", 1)[0]
        message = request["messages"][-1]["content"]
        block, separator, current = message.partition("\n\n用户本轮自然语言输入：\n")
        assert separator and current, f"{segment}: handout and input not separated"
        lines = block.splitlines()
        assert "资料，不是用户本轮说的话" in lines[0], segment
        assert json.loads(lines[1]) == handout["fields"], f"{segment}: card fields differ"
        for field in ("statement", "scope", "premises", "contradictions", "unknowns"):
            values = handout["fields"][field]
            for value in [values] if isinstance(values, str) else values:
                assert value in screen, f"{segment}: missing screen {field}"
        answer_index = next(i for i, line in enumerate(lines) if line.startswith("这张卡上还附着"))
        request_answers = json.loads(lines[answer_index + 1])
        assert set(request_answers) == set(attached), f"{segment}: answer keys differ"
        for key, entry in attached.items():
            assert entry["answer"] == request_answers[key]["answer"], f"{segment}: answer differs"
            assert entry["answer"] in screen, f"{segment}: answer missing from screen"
            for field in ("session", "at"):
                assert entry.get(field) == request_answers[key].get(field), f"{segment}: answer origin differs"
        source_index = next(i for i, line in enumerate(lines) if line.startswith("这张卡立在其上的来源记录"))
        assert json.loads(lines[source_index + 1]) == handout["sources"], f"{segment}: source records differ"
        for record in handout["sources"]:
            for field in ("claim", "scope_note"):
                assert record[field] in screen, f"{segment}: source text missing from screen"
        assert "核验状态不明" in screen and all(r["verification"] == "unknown" for r in handout["sources"])
        assert "库里有这套说法" in screen and "认可记录" in block
        contents.append(block)
        summaries.append({"segment": segment, "requests": len(capture), "model_requested": request["model"]})
    assert contents[0] == contents[1], "resumed handout differs from the opening handout"
    revision = json.loads((root / "revision.json").read_text(encoding="utf-8"))
    assert revision["statement"] != handout["statement"] and revision["statement"] not in contents[1]
    print(json.dumps({"segments": summaries, "attached_answers": len(attached),
                      "source_records": len(handout["sources"]), "source_verification": "unknown",
                      "handout_sha256": hashlib.sha256(contents[0].encode()).hexdigest(),
                      "same_snapshot_after_revision": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))

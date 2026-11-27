"""Materialize two wholly authored, fictional DAO libraries; no historical input."""
from pathlib import Path
import argparse
import json

AT = "2187-03-08T12:00:00Z"
DATE = "2187-03-03"
A, B = "ring-table", "screen-table"
QUOTE_A = "挂位还露着，我先把紫签挂在裂纹那一侧。"
QUOTE_B = "扣环还能摸到，我先把菱签扣在蓝边外侧。"
PAIR, TENSION, MOVE = "快看 ↔ 少挪", "外侧提示顺序", "外侧先标"
OLD_BYTES = (
    b'{ "layer": "checks", "bench_version": 1,\r\n'
    b'  "at": null, "daos": {},\r\n'
    b'  "fixture_marker": "invented previous projection; no recorded prior run" }\r\n'
)



def quote_ref(quote: str) -> str:
    """The line of this file the quoted words are written on.

    Read from the file rather than typed: a fixture that cites itself by hand drifts
    the moment someone reflows the constants.
    """
    here = Path(__file__).read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(here, 1):
        if quote in line:
            return f"第 {number} 行"
    raise SystemExit(f"the quoted words are not in this file: {quote[:40]}")

def put(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def build(root):
    root.mkdir(parents=True, exist_ok=False)
    put(root / "vocabulary.json", {
        "layer": "extraction", "version": 1,
        "tensions": [{"key": TENSION, "gloss": "让提示从走道可见，还是先把提醒留在架内",
                      "introduced_by": ["ring-d-1", "screen-d-1"], "reason": "由两份虚构布展词例共用"}],
        "moves": [{"key": MOVE, "gloss": "把可逆标记放到来人先看到的边",
                   "introduced_by": ["ring-d-1", "screen-d-1"], "reason": "两条规则的共同方向"}],
    })
    put(root / "comparison.json", {
        "layer": "extraction", "as_of": DATE, "a": A, "b": B,
        "reading": {"label": "夹具作者的读法，不是命令的测量",
                    "says": ["紫签和菱签的挂点不同；两条都把提示移到过道一侧。"]},
        "limit": "两份台词和提炼均由同一夹具作者编写：两个虚构来源 ID，不等于两个人、独立来源或共识。",
        "what_would_answer_it": "另有独立记录，并对原话、来源身份和关系作实际核验。",
        "consequence_if_absent": "这里只验词表比较和作者标记，不确立经验或现实效果。",
    })
    for library, prefix, quote, locus, move_action, text in (
        (A, "ring", QUOTE_A, "纸月环板的裂纹旁", "给裂纹旁的挂位加一枚紫签", "左环板拼缝有一段裂纹"),
        (B, "screen", QUOTE_B, "折屏蓝边的扣环", "给蓝边扣环挂一枚菱签", "折屏蓝边缺一枚说明签"),
    ):
        dest = root / library
        dest.mkdir()
        ep, dao = f"{prefix}-ep-1", f"{prefix}-d-1"
        actor = f"fictional-{prefix}-voice"
        # Only one of A's six slots traces to the scripted voice. B's whole entry is inference.
        authors = {part: "系统补" for part in ("situation", "tension", "move", "price", "off", "provenance")}
        if library == A:
            authors["move"] = "他的原话"
        put(dest / "episodes.json", {
            "layer": "events", "owner": "夹具作者（全新虚构）",
            "window": {"first_session": DATE, "last_person_input": DATE},
            "episodes": [{"id": ep, "at": DATE, "at_basis": "虚构夹具指定日期",
                          "attribution": "synthetic", "attribution_note": "新写台词；非真人，非模型回放",
                          "quote": quote,
                          # The words are written in this generator, not in the file it
                          # emits: citing the emitted library made the record its own
                          # source. A reader can open this file at the named line.
                          "source": {"path": "fixtures/seed_dao.py",
                                     "ref": quote_ref(quote)},
                          "observed_action": "虚构台词给出的动作：" + move_action,
                          "conditions": {"挂位": "敞开"}, "reading": "事件层只承载这句虚构台词。"}],
        })
        put(dest / "daos.json", {
            "layer": "extraction", "owner": "夹具作者（依据台词作推断）",
            "daos": [{"id": dao, "version": 2 if library == A else 1,
                      "title": "把一枚识别签留给从外侧走来的人",
                      "tension_key": TENSION, "move_key": MOVE,
                      "one_line": f"{text}时，{move_action}；要多取一枚签，封贴盖过挂位就不挂。",
                      "situation": {"who": "虚构纸月展台的布展员", "when": text,
                                    "constraints": ["展品只能使用可取下的标记"], "domain": ["虚构展台布置"], "covers": [ep]},
                      "tension": {"name": PAIR, "sides": ["快看", "少挪"], "why": "外侧一眼可见，但布展员要多取一枚标识。"},
                      "move": {"on_tension": PAIR, "direction": MOVE, "locus": locus, "magnitude": "只增加一枚签"},
                      "price": [{"what": "往返取一枚备用签", "unit": "时间", "who": "虚构布展员"}],
                      "off": [{"when": "封贴盖过挂位", "axis": "挂位", "value": "已封",
                               "then_kind": "withhold", "then": "记在布展清单，不碰封贴"}],
                      "axes": {"挂位": ["敞开", "已封"]},
                      "rule": [{"when": {"挂位": "敞开"}, "kind": "apply", "action": move_action},
                               {"when": {"挂位": "已封"}, "kind": "withhold", "action": "记在布展清单，不碰封贴"}],
                      "part_sources": authors,
                      "provenance": [{"person": actor, "episode": ep, "status": "模拟", "learned_from": "夹具创作台词"}]}],
        })
        put(dest / "observations.json", {"layer": "checks", "observations": [], "needed": [
            {"dao": dao, "what": "在该限制下发生的可核查落地观察", "why_not": "这里仅有虚构数据",
             "who": "真实项目另行授权后的观察者；非夹具作者"},
        ]})
        put(dest / "exposures.json", {"layer": "checks", "rows": []})
        put(dest / "map.json", {"layer": "extraction", "connections": [], "boundaries": [], "candidates": []})
        if library == A:
            put(dest / "promotions.json", {"layer": "checks", "promotions": [{
                "id": "fictional-ring-move-quote", "dao": dao, "part": "move", "kind": "确认", "episode": ep,
                "quote": quote, "as": "他的原话", "ran": {"by": "fictional fixture author", "at": AT, "on_version": 2},
            }]})
            (dest / "receipts.json").write_bytes(OLD_BYTES)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="must not exist; use a disposable directory")
    build(parser.parse_args().out)


if __name__ == "__main__":
    main()

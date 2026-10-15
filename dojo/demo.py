"""Human-readable preset story: three strangers discuss methodology through a dojo.

The main experience is deliberately offline and scripted. It shows what each stranger
said, what the assistant asked back, why a candidate was distilled, the human decision
to confirm / edit / reject, the real local lexical retrieval in an *independent*
problem, and how a logical challenge adds a boundary without deleting the earlier
version. The preset script does NOT understand free text and does NOT call a model;
replayed archives and live generation are separate commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from .storage import DojoError, Store, load_simulated_seeds


MODE_NOTE = (
    "三种模式要分清：这里是“离线预设故事”（写死的台词，不理解你的自由文本）；"
    "`python3 -m dojo compare` 回放归档的真实模型回答；`python3 -m dojo chat` 才会调用即时模型。"
)

ROLE_A = "甲（空间整洁）"
ROLE_B = "乙（软件开发）"
ROLE_C = "丙（抽象挑战）"

# ----------------------------------------------------------------- Act 1: 甲

A_PROBLEM = "我的工作台总是很快变乱。我一直以为是自己不够自律，可每次把东西收回原位都太麻烦，坚持不了几天。"
A_QUESTION = "你想解决的是“让自己更自律”，还是“让归位这件事本身更省力”？另外，这是你亲身反复试出来的观察，还是抽象推论？"
A_ANSWER = "是我从反复失败里推出来的抽象想法，不是实验。要让一种行为一直发生，除了让自己更想做，也可以让做对这件事更省事。"
A_WHY = "把“工作台、我家、收纳”这些私人细节去掉，只留下可迁移的理由、条件和未知；不保存甲的私人房间故事。"
A_CANDIDATE = {
    "statement": "要让一种想要的行为持续发生，除了提高意愿，也可以降低做对这件事的摩擦。",
    "kind": "abstract_idea",
    "premises": ["这个行为会重复发生", "在讨论上可以把“意愿”和“摩擦”分开考虑"],
    "scope": ["日常重复行为（如物品归位、例行整理）能不能持续；不主张对安全、审美或空间规格下结论"],
    "alternatives": ["若困难在于“不知道该怎么做”，单纯降低操作摩擦帮助有限", "若该行为本身的价值来自刻意练习，摩擦可能正是需要保留的部分"],
    "contradictions": [],
    "unknowns": ["摩擦要降低多少才算明显有用", "降低摩擦是否只是把麻烦挪到别的环节", "哪些行为不该降低难度"],
}

# ----------------------------------------------------------------- Act 2: 乙

B_PROBLEM = "我在做一个小工具。经常先动手写代码，后来才发现需求没想清楚，返工很多。我在考虑强迫自己每次先写一份完整需求文档。"
B_QUESTION = "你要解决的是“真的想清楚”，还是“有证据说明自己想清楚了”？完整文档和低成本澄清是两条不同路线。"
B_ANSWER = "那先看看有没有别的做法：不用写整套文档，也能让需求更清楚。"
B_WHY = "同样把乙的具体项目去掉，只留下可迁移的应用路线和它自己的未知；这是应用路线，和甲的抽象道分开保存，不因为“整洁”就合并。"
B_RETRIEVAL_QUERY = "降低 摩擦 持续 行为 需求 澄清 自律"
B_CANDIDATE = {
    "statement": "若要减少“先写代码才发现需求没想清楚”的返工，可先低成本澄清三件事：给谁用、解决什么问题、怎样算做成；只在需求复杂、风险高或多人协作时，才要求更充分的分析文档。",
    "kind": "application",
    "premises": ["这三件事可以在动手前用很小成本写清", "返工主要来自需求含糊，而不是实现本身困难"],
    "scope": ["个人或小团队、需求和实现都能较快调整的项目"],
    "alternatives": ["若需求确实复杂、风险高或涉及多人协作，完整需求文档可能仍然更合适"],
    "contradictions": [],
    "unknowns": ["多小的澄清成本才算值得", "高风险项目里这条路线是否还成立"],
}
SEED_ROLE = {
    "seed-m01": "抽象：环境与流程的设计，往往比临时的决心更能稳住重复行为；降低启动摩擦通常比反复下决心更可持续。",
    "seed-m02": "条件路线甲：若只是想维持现状、且这个行为本身没有训练价值，减少步骤、把准备前置通常有效。",
    "seed-m03": "对向条件路线乙：若行为的价值来自练习本身，应保留有意义的难度，只去掉无谓摩擦。",
    "seed-m04": "未核验的经验报告：一个模拟角色自称靠小改动坚持了数月整洁；没有记录，也没有独立来源。",
}
RETRIEVAL_QUERY = B_RETRIEVAL_QUERY  # frozen-packet alias

# ----------------------------------------------------------------- Act 3: 丙

C_POSITION = "我不完全同意。有些能力就是靠困难练出来的；把一切都变容易，未必是好事。"
C_QUESTION = "你说的“困难”，是和目标无关的阻碍，还是练习本身就需要的那部分难度？"
C_ANSWER = "有些难度就是能力的一部分，去掉它，等于把练习也去掉了。所以那条想法需要补一个边界，但它本身不算错。"
C_WHY = "丙不需要实验报告，也能提出有效的逻辑挑战；挑战要保留，不能把原道简单判错或删掉。"
C_CHALLENGE = "“降低摩擦”不能一概而论：如果行为的价值正来自练习本身，把难度去掉会同时去掉练习机会；需要先区分“与目标无关的摩擦”和“有意义的训练难度”。"
C_CANDIDATE = {
    "statement": "降低摩擦只适用于与目标无关的阻碍；当能力的形成本身就依赖练习过程时，这份难度应当保留。",
    "kind": "abstract_idea",
    "premises": ["存在与目标无关的摩擦", "存在构成能力本身的练习难度", "两者在讨论上可以区分"],
    "scope": ["讨论行为能否持续时，先判断该行为的困难是否具有训练价值"],
    "alternatives": ["若某种麻烦只是习惯性的、并非练习所需，仍应归入可以降低的摩擦"],
    "contradictions": [],
    "unknowns": ["怎样判断一份难度是“有意义”还是“只是麻烦”"],
}
A_REVISION = (
    "要让一种想要的行为持续发生，可以提高意愿，也可以分两种情况降低摩擦："
    "与目标无关的阻碍可以尽量减少；如果这份困难本身就是能力的练习，则应当保留，"
    "不因为追求“轻松”而把它一并移除。"
)
A_REVISION_REASON = "采纳丙的边界：降低摩擦只适用于与目标无关的阻碍；保留原抽象类型与来源。"

TARGET_FACTS = B_PROBLEM + " 目前不知道这条路线的效果，也没有相关数据。这只是请求者的处境与打算，不是已核验事实。"
SOURCE_INSIGHT = A_ANSWER
CHALLENGE = C_CHALLENGE
REVISION = A_REVISION
TARGET_APPLICATION = B_CANDIDATE["statement"]


@dataclass
class DemoOutcome:
    completed: bool
    cancelled: bool
    summary: str
    candidate_id: str | None
    final_version: int | None
    final_status: str | None


class _Stop(Exception):
    """A clean, user-visible stop of the preset story."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _input(read_line: Callable[[str], str], prompt: str) -> str | None:
    try:
        return read_line(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _say(output: TextIO, role: str, text: str) -> None:
    print(f"{role}：{text}", file=output)


def _cancelled_outcome() -> DemoOutcome:
    outcome = DemoOutcome(False, True, "", None, None, None)
    outcome.summary = (
        "本轮在取消/EOF 处停止；没有把沉默或 EOF 当作同意，也没有自动补成用户回答。"
        "已保存的内容仍留在数据库中。"
    )
    return outcome


def _render_compact_state(output: TextIO, state: dict) -> None:
    sources = state.get("sources", [])
    source_text = "；".join(
        f"{item['id']} {item['type']}/{item['verification']} independence={item['independence_group']}"
        for item in sources
    ) or "来源未记录"
    print(f"- {state['id']} v{state['version']} · {state['kind']} · {state['status']} · {source_text}", file=output)
    print(f"  观点：{state['statement']}", file=output)
    conditions = [*state.get("scope", []), *state.get("alternatives", []), *state.get("contradictions", [])]
    unknowns = state.get("unknowns", [])
    print(
        "  条件/分歧：" + ("；".join(conditions) if conditions else "未记录")
        + " | 未知：" + ("；".join(unknowns) if unknowns else "未记录"),
        file=output,
    )


def _render_state(output: TextIO, state: dict) -> None:
    print(f"记录 {state['id']} · v{state['version']} · {state['status']}", file=output)
    print(f"  观点：{state['statement']}", file=output)
    for label, key in (("条件", "scope"), ("前提", "premises"), ("相反/替代路线", "alternatives"), ("分歧", "contradictions"), ("未知", "unknowns")):
        print(f"  {label}：" + ("；".join(state.get(key, [])) if state.get(key) else "未记录"), file=output)
    sources = state.get("sources", [])
    if sources:
        print("  来源：" + "；".join(
            f"{item['id']} / {item['type']} / {item['verification']} / {item['independence_group']}"
            for item in sources
        ), file=output)


def _render_card(output: TextIO, card: dict, details: bool, heading: str) -> None:
    print(f"\n{heading}", file=output)
    if details:
        _render_state(output, {"id": "（未保存）", "version": 0, "status": "待审阅", **card, "sources": []})
    else:
        print(f"观点：{card['statement']}", file=output)
        print(f"类型：{card['kind']}", file=output)
        print("适用范围：" + "；".join(card["scope"]), file=output)
        print("前提：" + "；".join(card["premises"]), file=output)
        print("替代路线/未知：" + "；".join([*card["alternatives"], *card["unknowns"]]), file=output)


def _review_card(
    store: Store,
    output: TextIO,
    read_line: Callable[[str], str],
    *,
    auto: bool,
    details: bool,
    role: str,
    card: dict,
    heading: str,
    why: str,
    attest_prompt: str,
    session: str,
) -> tuple[str | None, bool]:
    """Show a drafted card; take an explicit confirm/edit/reject; save only on confirm."""
    print(f"\n{why}", file=output)
    _render_card(output, card, details, heading)
    if auto:
        choice = "y"
        print(f"{role}（预设选择）：确认这张候选可以进入讨论。", file=output)
    else:
        raw = _input(read_line, f"{role}选择 [y=确认候选可讨论，e=编辑观点，n=拒绝，q=取消]：")
        if raw is None or raw.strip().lower() == "q":
            raise _Stop("已取消；候选未保存。")
        choice = raw.strip().lower()

    edited = False
    if choice == "e":
        edited_text = _input(read_line, "输入你认可的候选观点（空输入取消本次保存）：")
        if edited_text is None or not edited_text.strip():
            raise _Stop("编辑已取消；候选没有保存。")
        print("预设脚本不会理解、分类或改写这段编辑；若保存，它仍沿用这张卡的类型与合成来源。", file=output)
        attestation = _input(read_line, attest_prompt)
        if attestation is None or attestation.strip().lower() not in {"y", "yes", "是"}:
            raise _Stop("没有得到类型/范围自确认；编辑卡未保存。")
        card = {**card, "statement": edited_text.strip()}
        edited = True
    elif choice == "n":
        print(f"贡献者拒绝了这张候选；不会写入数据库。", file=output)
        return None, False
    elif choice == "":
        print("没有明确选择；候选未保存。", file=output)
        return None, False
    elif choice not in {"y", "yes", "是"}:
        print("选择无效；候选未保存。", file=output)
        return None, False

    source = (
        {"type": "unknown", "claim": "贡献者在离线预设中直接编辑的观点；脚本未解读或核验，不声称经验或独立证据。",
         "independence_group": "unknown", "verification": "unknown", "scope_note": "用户编辑文本不是对话记录"}
        if edited else
        {"type": "synthetic_roleplay", "claim": "固定预设陌生人提出的观点；虚构材料，不是经验依据。",
         "independence_group": "stranger-methodology-v1", "verification": "not_evidence",
         "scope_note": "不是用户研究、观察事实或独立证据"}
    )
    saved = store.add(
        card["statement"], card["kind"], premises=card["premises"], scope=card["scope"],
        alternatives=card["alternatives"], contradictions=card["contradictions"],
        unknowns=card["unknowns"], sources=[source], session=session,
    )
    print(f"经贡献者同意，已保存：{saved['id']} v{saved['version']} [{saved['status']}] · "
          f"{saved['kind']} · 来源 {source['type']}/{source['verification']}。", file=output)
    if auto:
        decision = "y"
        print(f"{role}（预设选择）：确认这条记录值得继续讨论/检索（不表示为真）。", file=output)
    else:
        decision = _input(read_line, "确认它值得继续讨论/检索（不表示为真）？[y/N] ")
    if decision is not None and decision.strip().lower() in {"y", "yes", "是"}:
        saved = store.confirm(saved["id"], "贡献者确认表述值得继续讨论/检索；不是事实判断。", session)
        print(f"已确认可讨论：{saved['id']} v{saved['version']} [可讨论，不代表为真]。", file=output)
    else:
        print("没有获得明确确认；该记录保持草稿，不进入检索。", file=output)
    return saved["id"], edited


def run_demo(
    store: Store,
    *,
    auto: bool = False,
    details: bool = False,
    read_line: Callable[[str], str] = input,
    output: TextIO,
) -> DemoOutcome:
    """Run the branchable three-stranger preset; free text is never interpreted."""
    print("道场：三位互不认识的陌生人，各自带着自己的问题；道藏连接的是理由、条件与异议，不是私人对话或个人细节。", file=output)
    print(MODE_NOTE, file=output)
    print("全程中文、无需读 JSON 或了解协议；默认数据库退出即清理，--workdir 可保存。", file=output)
    try:
        if auto:
            print("（--auto：不读 stdin，按预设的“确认”选择走完整故事。）", file=output)
        else:
            start = _input(read_line, "开始这段预设故事？[Enter/y=继续，q=取消] ")
            if start is None or start.strip().lower() == "q":
                raise _Stop("已取消；没有将沉默或 EOF 当作同意。")
            if start.strip().lower() not in {"", "y", "yes", "是"}:
                raise _Stop("只接受 Enter/y 开始或 q 取消；没有继续。")

        # ---------------------------------------------------------- Act 1: 甲
        print("\n===== 第一幕：甲 的问题（空间整洁）=====", file=output)
        _say(output, ROLE_A, A_PROBLEM)
        print(f"\n助手追问：{A_QUESTION}", file=output)
        if not auto:
            custom = _input(read_line, "若想输入自己的想法，请输入文字；预设台词不会理解它。直接回车继续预设：")
            if custom is None:
                raise _Stop("EOF/取消；预设对话没有继续。")
            if custom.strip():
                print("预设脚本无法理解或回应这段自定义文字，也不会假装已理解。", file=output)
                keep = _input(read_line, "输入 p 忽略自定义文字并使用上面的预设案例；其他输入取消：")
                if keep is None or keep.strip().lower() != "p":
                    raise _Stop("已停止预设故事；自定义文字未保存。实时聊天请另运行 python3 -m dojo chat。")
                print("已丢弃自定义文字；下面只演练固定预设案例。", file=output)
        _say(output, ROLE_A + "（固定预设回答）", A_ANSWER)
        abstract_id, abstract_edited = _review_card(
            store, output, read_line, auto=auto, details=details, role=ROLE_A,
            card=A_CANDIDATE, heading="整理出的候选卡（待贡献者审阅）", why=A_WHY,
            attest_prompt="你确认这仍是通用抽象想法（不是某一次整理的具体建议）？[y=确认，其他=不保存]：",
            session="demo-stranger-a",
        )
        print("说明：只保存了提炼后的理由与条件；甲的私人房间细节没有进入记录。", file=output)

        # ---------------------------------------------------------- Act 2: 乙
        print("\n===== 第二幕：乙 的问题（软件开发）=====", file=output)
        print("乙看不到甲的私人场景，也不和甲共享项目；乙能拿到的是提炼后的理由与条件。", file=output)
        _say(output, ROLE_B, B_PROBLEM)
        print(f"\n助手追问：{B_QUESTION}", file=output)
        _say(output, ROLE_B + "（固定预设回答）", B_ANSWER)

        load_simulated_seeds(store)
        retrieval = store.retrieve(B_RETRIEVAL_QUERY, limit=10)
        print(f"\n本地 Store 的真实词汇检索（透明重合，不是语义理解、不是可信度排名）query={retrieval['query']}；"
              "命中词=" + ("、".join(retrieval["matched_terms"]) if retrieval["matched_terms"] else "无"), file=output)
        if not retrieval["results"]:
            print("没有命中；不会为了填满结果而编造来源。", file=output)
        for result in retrieval["results"]:
            if details:
                _render_state(output, result)
                print(f"  透明重合词数：{result['score']}（不是可信度/重要性分数）", file=output)
            else:
                _render_compact_state(output, result)
            if result["id"] == abstract_id:
                print("  ← 这是甲刚才的抽象道：相关，因为它谈的也是“让想要发生的行为更容易持续”。", file=output)
            elif result["id"] in SEED_ROLE:
                print(f"  ← {SEED_ROLE[result['id']]}", file=output)
        print("说明：检索只带回理由与条件，不证明两个问题相同；甲的场景细节并未传过来。", file=output)

        application_id: str | None = None
        if abstract_id:
            application_id, _ = _review_card(
                store, output, read_line, auto=auto, details=details, role=ROLE_B,
                card=B_CANDIDATE, heading="整理出的应用路线（单独一条记录，不覆盖抽象道）", why=B_WHY,
                attest_prompt="你确认这仍是一条应用路线（不是通用抽象道）？[y=确认，其他=不保存]：",
                session="demo-stranger-b",
            )
            if application_id:
                store.link(application_id, "instantiates", abstract_id,
                           "这条应用路线实例化了甲的抽象道；保留为独立记录，不合并")
                print(f"已保存关系：{application_id} --instantiates--> {abstract_id}（保留不同路线，不强行合并）。", file=output)
                print(f"边界说明：这条路线不适用于“需求复杂、风险高或多人协作”的情形；那条路线仍留在替代条件里。", file=output)
        else:
            print("甲没有确认任何抽象道，所以第二幕只做检索演示，不保存应用路线。", file=output)

        # ---------------------------------------------------------- Act 3: 丙
        print("\n===== 第三幕：丙 的挑战（抽象）=====", file=output)
        _say(output, ROLE_C, C_POSITION)
        print(f"\n助手追问：{C_QUESTION}", file=output)
        _say(output, ROLE_C + "（固定预设回答）", C_ANSWER)
        print(C_WHY, file=output)

        target = abstract_id or "seed-m01"
        if abstract_id and abstract_edited:
            print("预设不会解释你自编辑的抽象卡；这次固定挑战只作用于预设抽象 seed-m01，不作用于你编辑的卡。", file=output)
            target = "seed-m01"
        if not abstract_id:
            print("甲没有留下记录，这次挑战作用于预设抽象 seed-m01。", file=output)
        challenged = store.challenge(target, C_CHALLENGE)
        print(f"已保存挑战（作为分歧，保留旧版本）：{challenged['id']} v{challenged['version']} [{challenged['status']}]。", file=output)

        counter_id, _ = _review_card(
            store, output, read_line, auto=auto, details=details, role=ROLE_C,
            card=C_CANDIDATE, heading="丙提出的边界卡（自己的记录）", why="丙把挑战整理成一条可讨论的抽象边界，作为独立记录保存。",
            attest_prompt="你确认这仍是通用抽象想法（不是某一次训练计划）？[y=确认，其他=不保存]：",
            session="demo-stranger-c",
        )
        if counter_id:
            store.link(counter_id, "challenges", target,
                       "丙的边界挑战原道“降低摩擦”的普适性；两条路线都保留")
            print(f"已保存关系：{counter_id} --challenges--> {target}（不把原道判错或删除）。", file=output)

        print("\n建议修订（可以修改，不需要接受脚本建议）：", file=output)
        print(f"  {REVISION}", file=output)
        active = store.show(target)["candidate"]
        if auto:
            revision_choice = "y"
        else:
            revision_choice = _input(read_line, "接受建议 [y]、保留挑战状态不改 [n]，或退出 [q]：")
        if revision_choice is None or revision_choice.strip().lower() == "q":
            raise _Stop("已退出；挑战版本保留，没有伪造修订确认。")
        if revision_choice.strip().lower() in {"y", "yes", "是"}:
            revised = store.revise(target, REVISION, A_REVISION_REASON)
            print(f"修订已保存为 v{revised['version']} [draft]；旧版本未覆盖。", file=output)
            revised = store.confirm(target, "用户检查修订后确认值得讨论/检索；不表示为真。", "demo-stranger-a")
            print(f"已确认可讨论：{revised['id']} v{revised['version']} [可讨论，不代表为真]。", file=output)
        else:
            print("修订未被接受；挑战版本与旧版本都保留。", file=output)

        final_id = target
        final = store.show(final_id)["candidate"]
        history = store.history(final_id)["versions"]
        versions = ", ".join(f"v{item['version']}:{item['state']['status']}" for item in history)
        print("\n--- 本轮简要总结 ---", file=output)
        print("学到：一个具体困扰可以被提炼成通用道，在另一个独立问题里被检索并作为应用路线使用，"
              "再被逻辑挑战补充边界而不被删除；通用道与应用路线分开保存。", file=output)
        print("三位陌生人没有互相认识，也没有共享项目；连接他们的是抽象道、应用路线与异议。", file=output)
        print(f"抽象道 {abstract_id or '（未保存）'} 最终 v{final['version']} [{final['status']}]；"
              f"应用路线 {application_id or '（未保存）'}；边界卡 {counter_id or '（未保存）'}。", file=output)
        print(f"版本轨迹（{final_id}）：{versions}", file=output)
        print("未验证：本预设故事是模拟材料，不是用户研究或效果证明；检索只是词汇重合；"
              "甲/乙/丙均为固定台词，不代表真实用户，也不理解自由输入。", file=output)
        outcome = DemoOutcome(True, False, "", final_id, final["version"], final["status"])
        outcome.summary = (
            "学到：一个具体困扰可以被提炼成通用道，在另一个独立问题里被检索并作为应用路线使用，"
            "再被逻辑挑战补充边界而不被删除；通用道与应用路线分开保存。\n"
            f"版本轨迹（{final_id}）：{versions}。\n"
            "未验证：模拟预设台词，不是实时 AI、用户研究或效果证明；检索为词汇重合，不是语义理解。"
        )
        return outcome
    except _Stop as stop:
        print(stop.message, file=output)
        return _cancelled_outcome()


def freeze_materials(store: Store, output_directory: str | Path) -> dict[str, object]:
    """Write four frozen, answer-key-free inputs; C is generated from Store.retrieve."""
    load_simulated_seeds(store)
    retrieval = store.retrieve(RETRIEVAL_QUERY, limit=10)
    if not retrieval["results"]:
        raise ValueError("the frozen C packet needs actual Store retrieval results")
    output_path = Path(output_directory).expanduser()
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing packet directory: {output_path}")
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_path.mkdir(mode=0o700)
    try:
        output_path.chmod(0o700)
    except OSError:
        pass

    source = f"""# Frozen source-contribution input — stranger methodology v1

> 模拟输入，不是观察或效果证明。只把本文件交给模型，不提供 actor/judge 笔记。

用户：

{SOURCE_INSIGHT}

请先问一个能区分“抽象洞见”与“真实观察/行动建议”的澄清问题。不要先替我写候选，不要补造经验。收到回答后，只返回一条可编辑候选卡建议：观点、类型、前提、范围、相反条件、未知与来源类别；明确哪些来自我，哪些是模型改写，且确认候选可讨论不等于确认事实。你不能替我批准或保存。
"""
    common = f"""# Frozen target input — common B/C case

> 虚构输入，未经核验。B 与 C 必须使用完全相同的下方用户话语、模型名称/版本、system prompt 与输出预算；每个条件用独立会话。推荐对照模型名：`github-copilot/gpt-6-luna`（实际运行时记录 endpoint 返回的模型/版本；本包未核验模型映射）。不要把结果说成研究或效果证明。

用户：

{TARGET_FACTS}

请回应问题，区分给定事实、请求者看法、假设、来源主张和未知；保留不同条件路线，不编造概率或经验。说明能迁移什么、什么不适用和为什么；若没有足够信息，明确保留未知。不得把模型写成数据库批准者。
"""
    b = common.replace("# Frozen target input — common B/C case", "# Frozen target B input — no dojo context")
    b += "\n本条件无任何道场检索摘录。\n"

    lines = [
        "# Frozen target C input — actual Store retrieval context",
        "",
        "> 这是模拟输入，不是答案键。目标事实逐字复用 B；下面摘录由本程序对初始化 Store 调用 `Store.retrieve` 得到，只列这次实际命中的 source ID。检索为透明词汇重合，不是语义理解或真值排序。",
        "",
        "检索查询：" + retrieval["query"],
        "检索方法：" + retrieval["method"],
        "本次命中词：" + "、".join(retrieval["matched_terms"]),
        "",
        "只根据本次分配的摘录分析；保留来源核验状态及条件，不把摘录当事实或答案键。\n",
    ]
    for item in retrieval["results"]:
        lines.extend([f"## {item['id']} v{item['version']} | {item['kind']} | {item['status']}", "", item["statement"], ""])
        for label, key in (("适用范围", "scope"), ("前提", "premises"), ("替代路线", "alternatives"), ("分歧", "contradictions"), ("未知", "unknowns")):
            if item.get(key):
                lines.append(f"{label}：" + "；".join(item[key]))
        for source_item in item["sources"]:
            lines.append(
                f"来源：{source_item['id']} | {source_item['type']} | verification={source_item['verification']} "
                f"| independence_group={source_item['independence_group']} | {source_item['claim']}"
            )
        lines.append("")
    common_header, target_and_request = common.split("用户：\n\n", 1)
    common_header = common_header.split("\n", 1)[1]
    c = (
        "# Frozen target C input — actual Store retrieval context\n\n"
        + "\n".join(lines[1:])
        + "\n\n"
        + common_header
        + "\n\n用户：\n\n"
        + target_and_request
    )
    challenge = f"""# Frozen challenge input — continue after a target response

> 只在同一模型已经看到 target B 或 C 的回应后使用；此文本本身不包含 judge 判断或答案键。

用户挑战：

{CHALLENGE}

请检查此前回答是否把“降低摩擦总是更好”当成了普遍结论，指出哪些条件需要补充，并提供一条收窄后的候选草稿（含相反路线、范围、来源和未知）。不覆盖旧候选、不确认它为真；等待用户编辑/接受/拒绝。
"""
    files = {
        "source-contribution.md": source,
        "target-no-dojo-b.md": b,
        "target-with-retrieved-dojo-c.md": c,
        "challenge.md": challenge,
    }
    created: list[Path] = []
    try:
        for name, content in files.items():
            path = output_path / name
            with path.open("x", encoding="utf-8") as stream:
                created.append(path)
                stream.write(content.rstrip() + "\n")
            try:
                path.chmod(0o600)
            except OSError:
                pass
    except OSError:
        for path in created:
            path.unlink(missing_ok=True)
        try:
            output_path.rmdir()
        except OSError:
            pass
        raise
    return {
        "directory": str(output_path),
        "files": sorted(files),
        "retrieval_query": retrieval["query"],
        "retrieved_source_candidate_ids": [item["id"] for item in retrieval["results"]],
        "retrieval_method": retrieval["method"],
    }


def write_demo_summary(outcome: DemoOutcome, workdir: str | Path) -> Path:
    """Persist only a short user-facing summary, never dialogue transcripts."""
    path = Path(workdir) / "summary.md"
    with path.open("x", encoding="utf-8") as stream:
        stream.write("# 道场演示简要记录\n\n" + outcome.summary.strip() + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path

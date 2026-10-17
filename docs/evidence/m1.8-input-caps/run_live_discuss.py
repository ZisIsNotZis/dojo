"""Run a six-turn scripted live discussion with long natural-language inputs."""

from __future__ import annotations

import json
import os
import pty
import select
import sys
import termios
import time
import tty
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
COMMAND = [sys.executable, "-m", "dojo", "discuss"]
INPUTS = [
    "我想讨论怎样区分‘主持人听懂了我’和‘主持人替我把事情说得更完整’。我有时会先说一个很粗的观察，里面同时有经历、猜测和希望；如果助手很快给出一条特别流畅的总结，我会觉得它听起来很合理，但这不一定说明它准确表达了我真正想讨论的部分。对我来说，好的复述应该能让我指出它漏掉了什么，而不是因为文字更精致就让我默认它正确。\n\n举例来说，我可能说最近几次任务启动很困难。这里面有可以直接确认的部分，比如发生在什么时间、任务是什么、我当时做了什么；也有解释部分，比如我可能因为任务看起来太大而拖延，也可能因为休息不足、目标改变或不愿意做这件事。如果主持人把解释部分直接写进结论，我就会失去检查它的机会。反过来，如果它只原样复制我的句子，也没有帮助我分清事实和推断。\n\n我希望讨论可以先保留这种未完成状态，继续问一个能区分原因的问题；但也不希望每句话都被要求补齐来源、范围、例外，最后变成填表。我在意的是这些追问是否真的改变了我们能说什么，而不是字段有没有填满。若不同解释目前都说得通，可以暂时把它们并列保留，说明哪些材料能够区分，而不是选一个最像答案的版本。\n\n还有一种情况是我只想确认一段表述是否忠实，并不表示我认可它作为普遍建议。如果主持人把我说‘这句话听起来像我’当成‘这条主张已经成立’，对话就越过了我的授权。反过来，我也不想因为没有独立证据就连个人经验本身都不能记录。怎样把这些层次区分开，是我现在真正想弄清楚的事情。",
    "我再补充一下来源的问题，因为我觉得‘我亲身经历过’和‘这件事对每个人都成立’之间经常被跳过去。个人经验可以是可靠的自我报告，但它覆盖的场景、时间长度和其他人的情况都有限；它可以支持‘我在某些条件下观察到这种现象’，却不自动支持‘所有人都应该照做’。如果主持人把这个区别讲得太抽象，我又会担心每个个人经验都被轻描淡写成没有价值。\n\n我希望能把说话者实际观察到的内容和说话者对原因的解释分开保存。例如，我确实能说自己在一段时间里多次拖延某种工作；但我未必能确定原因就是任务粒度太大，因为我没有逐一排除疲劳、时间冲突、目标不认同或外部打断。一个有用的讨论可以指出这种因果关系目前是推断，同时还把观察本身留在原来的范围内。\n\n我也在意来源能不能回到原处。若后面有人引用讨论形成的内容，最好能看出它来自一个人的描述、一次测量、公开资料，还是模型自己补出的解释。不同来源的独立程度也不相同：很多人重复同一个故事，可能仍然来自同一条传播链；一个人多次复述同一经历，也不等于有多个独立观察者。\n\n不过我不想把这个要求扩大成每次谈话都必须拿出文件或外部佐证。聊天首先是在澄清我们究竟想说什么；目前证据不足时，明确写出未知就够了。以后是否值得找证据，可以是另一个决定。关键是不能在来源暂时缺席时把不确定性偷偷填成零，也不能把‘还没查’写成‘已经证实’。我想知道这个边界怎样表达才既谨慎又不抹掉经验价值。",
    "我还想谈谈异议，因为主持人归纳时最容易把不一样的部分压平。两个人可能使用同一个词，却指不同的任务或不同的成功标准；也可能在大方向相同的同时，对适用条件有真实冲突。如果总结只留下双方都同意的那句大话，听起来会很整齐，但会让后续读者误以为关键分歧已经解决。\n\n比如，有人觉得先把任务缩小通常能降低开始时的压力，另一个人认为有些难题必须先弄清楚为什么值得做，继续切小只会让人更高效地做不认同的事。它们不是简单的正反票数：前一种说法可能只适用于目标已认可而执行步骤不清楚的时候，后一种提醒则可能覆盖目标冲突的情形。若系统只选一方作为‘通用方法’，另一方提到的条件就消失了。\n\n我希望异议可以留在它真正反驳的范围里。一个反例可能推翻无条件说法，却不一定推翻加了限制的说法；一个条件路线也可能只是说明何时不适用，不代表另一条路线完全错误。主持人需要指出它影响的是哪句话、哪项前提或哪一类应用，而不是把任何不同意见都记录成同样强度的反证。\n\n与此同时，保留异议也不该意味着每个可能的例外永远占据同样篇幅。有些例外只是逻辑上想得到，还没有发生过；有些是参与者实际遇到的情况；还有些来自独立资料。这些差别应该可辨识，不能为了让记录看上去平衡，就编造反方的亲历或给未经核验的反例加权。",
    "关于边界，我想用‘把工作拆成第一步’这个常见建议继续往下问。它似乎适用于目标已经清楚、主要障碍是下一步太模糊或太大时；但如果目标本身值得怀疑，或者第一步需要高额成本、会造成不可逆后果，那么把任务拆小未必解决真正的问题。它甚至可能让人更快进入一个本来该暂停检查的行动。\n\n所以我不希望把观察写成‘任务越小越容易成功’这样的普遍规则。更贴近我的意思可能是：在目标已被接受、资源够用、主要阻力来自行动入口不明确时，识别一个低成本且可撤回的第一步，可能帮助澄清是否卡在启动环节；如果障碍来自目标冲突、能力缺口或外部条件，这个做法的解释力就有限。即使这样描述，目前也只是一个可能的机制，不是我已经测量过的效果。\n\n我还不确定怎样判断一个第一步算不算低成本和可撤回。对一些人来说，发出一封邮件是轻微行动；对另一些人来说，它会触发承诺、暴露隐私或改变关系。看起来相同的步骤，因为环境和责任不同，风险可能完全不同。若把边界写得过于抽象，它不会帮助读者判断；若列出所有细节，又会让结论变成只对一个小场景可读。\n\n我认为可以先写明目前讨论的是哪类情况，并把尚未界定的风险列成未知，不必假装已经覆盖了全部边界。之后遇到新的反例，可以再修订适用范围。重要的是修改时能看出旧说法哪里不再适用，而不是悄悄让一个新例子变成原结论从未说过的前提。",
    "我想再看一个迁移场景，避免我们把一个生活里的例子说成对所有领域都通用。拆小动作或许可以帮助一个人整理房间，也可能让团队把模糊工作分配给具体负责人；但组织里的任务还牵涉协作依赖、等待、权限和返工成本，个人场景下有效的办法不一定直接搬过去。迁移时应该说明哪些机制相似、哪些条件变了。\n\n例如个人开始任务时，下一步明确可能减少犹豫；团队工作里即使每个人都知道自己的下一步，也可能因为接口未约定、信息还没交接或必须等另一个团队而停住。此时继续把本地任务拆得更细，可能只会增加看似完成的小事项，不能消除外部等待。若我们把‘明确下一步’直接当成跨场景的充分解释，就会漏掉系统依赖。\n\n另一方面，完全拒绝抽象也会让每次讨论从头开始。也许能保留一个较弱的共同想法，例如行动入口的可见性可能影响启动，但它要和目标认同、资源、依赖关系等条件一起讨论。这个抽象是否值得继续，取决于它能否帮助提出更好的问题，而不是句子是否听起来简洁。它仍然需要新场景中的观察来检验，不能因为几个故事相似就当作普遍规律。\n\n我还想区分‘迁移后值得试问’和‘迁移后证明有效’。某个概念能提示我们去检查团队的等待点，不代表它已给出解决方案；某个相似例子能让假设更具体，不代表它提供了独立证据。主持人若把这两层说清，读者就能看到抽象的用途，同时不会误以为讨论已经完成验证。",
    "最后我补充我现在对讨论过程的期待，但这仍然不是在认可任何待定结论。如果主持人给出一个总结，我想能看到它对应了我明确说过的观察，也能看到哪些内容是它的推断、哪些边界尚未弄清。我可以同意某个句子表达得准确，却仍然不同意把它写成建议；也可以认可在有限范围内记录一个草稿，同时明确它不是事实认证。\n\n我不希望模型通过追问把我推向预设答案。问题应该能区分真实不同的解释，而不是诱导我选一个看起来更完整的说法。如果我回答‘暂时没有更多信息’，它只能表示我没有可补充的材料，不能被解释成默许。如果我纠正范围，旧版本就应该停下来等我检查新表述，而不是因为我继续说话就假定我同意了。\n\n对话也需要有结束方式。一直追问直到所有不确定都消失是不现实的，有些未知需要更长的观察或外部证据；但太早总结又会把还没区分的概念合在一起。一个合理的停点可能是我们知道想表达的主张、它当前依赖什么、在哪些情形可能失效，以及仍缺少哪些信息。到那时可以提出暂定文字，但是否保存仍要让我明确确认。\n\n我现在只是把这些判断标准和例子补全，想观察主持人能否在后续回应中保留早期的区分和异议。请不要把本轮理解成我接受了任何候选，也不要在我没有明确同意具体文字时写入结论；接下来如果还有不同解释，我愿意继续把它们说清楚。",
]

LONG_CONTEXT = """我还想把几个容易混淆的判断标准放在一起解释。复述是否忠实，是对表达内容的检查；说法是否有证据支持，是对来源和材料的检查；是否适合推广到其他人或环境，则是对范围和迁移条件的检查。这三个判断可能得到不同答案，不能把其中一个的肯定自动传递给另两个。一个句子可以忠实地总结我说过的话，但仍然是未经验证的主张；一个观察可以确实发生过，却只适用于很窄的条件；一个假设可以值得进一步检查，但目前没有资格被表述成确定结论。\n\n如果主持人提出修订，我希望它能指出这次修改回应了哪一个异议或新条件。这样我可以判断它有没有真正改变含义，还是只是换了一种更肯定的说法。如果有两个解释仍然并存，可以说明下一条什么观察会区分它们；如果目前没有办法区分，也可以把它们作为未知保留，而不是为了让谈话看似结束而选一个。任何后续读者都应该能看见哪些部分来自我的明确陈述、哪些是讨论中的推断，以及哪些仍然需要验证。\n\n我对结束的要求也不是无限追问。讨论可以在边界足够清晰但证据仍不足时停下来，前提是文字如实呈现了未解决之处，并且没有把继续讨论、保持沉默、承认表达准确或暂时不反对当作明确认可。若需要保存具体结论，应该让我看到那一条完整表述及其限制，再由我针对它明确表示同意；只要我还在补充信息，就继续把它当作修订材料，而不是授权。\n\n如果把这段谈话作为之后继续讨论的背景，早期的例子、异议和限定也应当保留，而不只是最近几轮的文字。后面的回应可能需要依靠前面建立的条件，才能理解我为什么拒绝一个更宽泛的总结；如果这些内容被悄悄删去，对话就会像是我从未提过它们。另一方面，保留历史并不代表每次都要把所有材料无限重复给模型，实际传输仍然需要一个明确的安全边界。我的关心是：当安全边界尚未接近时，不要为了一个很小的固定轮数而主动丢掉仍相关的上下文；如果真正达到请求包络，再用可见的方式说明，而不要假装模型还记得已经没有传过去的内容。\n\n我也不把更多历史本身看成讨论质量的保证。模型可能仍会误解或遗漏，所以我会看它是否把早先的异议用在当前的解释中，并愿意在发现矛盾时纠正。这里需要验证的是输入是否真的到达了讨论请求、用户多轮补充没有被程序用过小的输入阈值拒绝，以及轨迹能否留下原始回复和推理等级；仅仅运行成功，不能证明模型理解正确，也不能证明更大的历史一定让每场对话更好。若这轮形成了候选，它仍然只是可以纠正的草稿；只要我没有明确认可候选的完整具体措辞，就不会把它当成已经同意的结论。也请把我这轮继续补充看作提供上下文，而不是对上一轮回答的默认赞同。我还会继续纠正遗漏，并且此处仍未认可具体结论。"""
INPUTS = [f"{text}\n\n{LONG_CONTEXT}" for text in INPUTS]
FLAT_INPUTS = [" ".join(text.splitlines()) for text in INPUTS]


def main() -> int:
    lengths = [len(text) for text in FLAT_INPUTS]
    if len(INPUTS) != 6 or any(length <= 1_600 for length in lengths):
        raise ValueError(f"expected six inputs longer than chat's 1,600-character cap: {lengths}")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    trace_names_before = {path.name for path in EVIDENCE.glob("discuss-*.jsonl")}
    pid, master = pty.fork()
    if pid == 0:
        os.chdir(ROOT)
        os.execvpe(COMMAND[0], COMMAND, env)
    saved_terminal = termios.tcgetattr(master)
    tty.setraw(master)

    transcript = bytearray()
    sent: list[str] = []
    pending = bytearray()
    marker = "你> ".encode("utf-8")
    turn = 0
    deadline = time.monotonic() + 900
    status = None
    sent_eof = False
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 1)
            if ready:
                try:
                    chunk = os.read(master, 8192)
                except OSError:
                    break
                if not chunk:
                    break
                transcript.extend(chunk)
                pending.extend(chunk)
                while marker in pending:
                    prompt_index = pending.index(marker)
                    segment = bytes(pending[:prompt_index]).decode("utf-8", errors="replace")
                    del pending[:prompt_index + len(marker)]
                    if "已写入本地草稿" in segment:
                        response = "<EOF after an unexpected write>"
                        sent.append(response)
                        termios.tcsetattr(master, termios.TCSADRAIN, saved_terminal)
                        os.write(master, b"\x04")
                        sent_eof = True
                        continue
                    if turn < len(FLAT_INPUTS):
                        response = FLAT_INPUTS[turn]
                        turn += 1
                        sent.append(response)
                        os.write(master, response.encode("utf-8") + b"\n")
                    else:
                        sent.append("<EOF after six long user turns>")
                        termios.tcsetattr(master, termios.TCSADRAIN, saved_terminal)
                        os.write(master, b"\x04")
                        sent_eof = True
            waited, child_status = os.waitpid(pid, os.WNOHANG)
            if waited:
                status = child_status
                break
        else:
            os.write(master, b"\x04")
            sent_eof = True
            raise TimeoutError("live discussion exceeded the 900-second driver deadline")
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        if status is None:
            _, status = os.waitpid(pid, 0)
        (EVIDENCE / "discuss-transcript.txt").write_bytes(transcript)
        (EVIDENCE / "discuss-inputs.txt").write_text("\n\n--- input ---\n\n".join(sent) + "\n", encoding="utf-8")

    exit_code = os.waitstatus_to_exitcode(status)
    traces = sorted(
        (path for path in EVIDENCE.glob("discuss-*.jsonl") if path.name not in trace_names_before),
        key=lambda path: path.stat().st_mtime,
    )
    if len(traces) != 1:
        raise RuntimeError(f"expected one new discussion trace, found {len(traces)}")
    records = [json.loads(line) for line in traces[0].read_text(encoding="utf-8").splitlines()]
    rounds = [record for record in records if record.get("event") != "session_end"]
    ends = [record for record in records if record.get("event") == "session_end"]
    requests_sent = ends[-1]["requests_sent"] if ends else 0
    print(json.dumps({
        "exit_code": exit_code,
        "user_turns_sent": turn,
        "input_lengths_chars": lengths,
        "requests_sent": requests_sent,
        "rounds": len(rounds),
        "reasoning_effort_values": sorted({record.get("reasoning_effort") for record in rounds}, key=str),
        "all_raw_responses_present": all(bool(record.get("raw_response")) for record in rounds),
        "session_end_reason": ends[-1].get("reason") if ends else None,
        "trace": traces[0].name,
        "sent_eof": sent_eof,
    }, ensure_ascii=False, indent=2))
    if exit_code != 0 or turn != 6 or len(rounds) < 6 or requests_sent > 15:
        return 1
    if not all(record.get("raw_response") and record.get("reasoning_effort") for record in rounds[:6]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

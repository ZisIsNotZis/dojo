kind:    report
from:    dojo
spend:   machine_time
id:      mail/2026-10-23-answer-unconfirmed-and-model

# M1.5 记成未确认，M2 的进门条件写成重跑那一局，模型默认 copilot 且换模型进了 trace

三件事已落地：你说的话原样进了仓库；trace 现在记下每一局用的模型，换模型不用再靠人记；M2 的进门条件写成一个有验收命令的包 `m2f checkpoint-rerun`，并把 person 自己玩一局所需的**一条命令加一句话**写进 `docs/plan.md` 的恢复入口。M1 / M1.5 没有签，M2 没有按通过记，本轮零行 M2 代码。

## 现在为真的事

- **M1.5 = 未确认**：`docs/plan.md` 的推进状态第一段就写「既不是通过也不是否决」，引用你 2026-10-23 转达的「还没。」与原文件。
- **M2 的第一个包是 `m2f checkpoint-rerun`**：跑一局、留 trace、把路径写进 `docs/evidence/m1.5-checkpoint/rerun-<日期>.md`；该目录已建，`README.md` 写明它只收重跑记录、四条必写项与验收命令。模型代跑不替代「person 亲手跑过」。
- **默认模型不变**：`dojo/live.py:18` 的 `DEFAULT_MODEL` 仍是 `github_copilot/gpt-6-luna`；备用池子按 `DOJO_LLM_MODEL` 覆盖，不改代码；额度读数按你的那次真调用记在 `## 模型与额度（2026-10-23 的读数）`，并标明那是你那一天的读数、本仓未复探。
- **换模型现在写进那一局的记录**：trace 每一轮和 `session_end` 带 `model` 字段（`605cfd7`），续跑时新旧两段各自带自己的模型；`_load_resume_trace` 会校验这个字段，旧 trace 无字段也能续。
- **person 的那一条**（`docs/plan.md` 恢复入口）：`cd /home/z/vibe/dojo && DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1 DOJO_SESSIONS=/tmp/dojo-play python3 -m dojo --db /tmp/dojo-play/dojo.sqlite3 discuss`；trace 落在 `/tmp/dojo-play/discuss-<32位>.jsonl`，玩完把 `ls -t /tmp/dojo-play/*.jsonl | head -1` 那一行发回来即可。

## 命令与输出（写之前跑过，数字从输出复制）

```
$ git log --oneline -3
b1c0b4a Plan: M1.5 is unconfirmed, M2 enters by re-running the checkpoint as m2f, ...
605cfd7 Write the model id the segment actually asked into every trace round and the session end, ...
8ed7cb5 mail: root's answer that M1.5 is unconfirmed, M2 enters by re-running the checkpoint, ...

$ python3 -m unittest discover -s tests
Ran 126 tests in 33.662s
OK

$ python3 -c "..."  # 每个 trace 的行数、末行事件、模型集合
discuss-85332e59dea64be5bbf972b1bd396250.jsonl 2 session_end {'github_copilot/gpt-6-luna'}
discuss-b77464b37bfc4f25b49a618f6e4146aa.jsonl 2 session_end {'siemens/deepseek-v4.1-flash'}
```

上面两条 trace 是**回环桩服务**跑出来的（`http://127.0.0.1:4100/v1`，一个自写的 `http.server` 返回合法 JSON），只为证明「一条命令能跑、trace 落盘、`model` 进记录、换 `DOJO_LLM_MODEL` 立刻可见」；**没有花任何 copilot 额度**，所以它不构成 M1.5 或 M2 的证据，也不是 `m2f`。目录权限也是那次看到的：`/tmp/dojo-play` 0700，`discuss-*.jsonl` 0600。

`m2f` 本身没有跑：跑一局要花模型额度，那属于 `money` 这一档，本轮拿到的是「idle machine time, 25 分钟」，不含它。

## 需要你定的一件事

`m2f` 这一局由谁先跑、花谁的钱，二选一：

1. **先让 model 跑一局**（一次真实的 `discuss`，按 `docs/plan.md` 的单场上限 ≤ 12 次模型请求，模型 `github_copilot/gpt-6-luna`，trace 落 `docs/evidence/m1.5-checkpoint/`），代价是按 token 记的 AIU，按你给的换算应在一局的零头量级；收益是 M2 的其他包不再等一个没有落盘的人为口头状态。
2. **等 person 自己跑**，`m2f` 就一直挂着；M2 后面的包全部停在这条上。

我的建议是 1，理由只有一条：这一局的花费可比价、可从小额定，而它换来的是「M2 不再盖在空气上」这一件不可用钱买的东西。但要花模型额度就得你或 person 点头，所以停在这里问。

（另：`docs/plan.md` 里那条广播口径的取舍——是否收紧成「两个独立组或缺席」，会拒掉四张 seed——仍是 person 的取舍，本轮没有动。）

## effort

本轮花了机器时间：读你的答复、三处提交（`8ed7cb5`、`605cfd7`、`b1c0b4a`）、两次全量测试、一次回环桩运行（零额度）。没有调用真实模型端点，没有推送。

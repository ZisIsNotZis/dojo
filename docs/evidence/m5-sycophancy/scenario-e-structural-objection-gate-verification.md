# M5 异议门控修复真实模型复核

本记录核验讨论 JSON 新契约、代码持有的异议门控，以及“无异议时空行仍按默认通过保存”。它是指定对话的端到端观察，不证明模型普遍可靠。

## 模型路由与调用界限

测试端点为 `http://127.0.0.1:4000/v1`。按任务字面配置模型名 `github-copilot/gpt-6-luna` 的两次请求都返回 HTTP 400，没有模型回答，也没有写入数据库。随后 `GET /v1/models` 返回 HTTP 200，列出了 `github_copilot/gpt-6-luna`，但没有连字符写法。

按监督者确认，`github-copilot/gpt-6-luna` 是 pi 侧 provider 写法，`github_copilot/gpt-6-luna` 是 LiteLLM 侧 model group ID；两者是同一模型与同一 Copilot Responses 端点的命名映射，不是模型替换。有效复核都使用端点公布的下划线 API ID `github_copilot/gpt-6-luna`，未使用其他模型。

总计尝试 30 次模型请求：字面连字符路由的 2 次 HTTP 400、两次早期显式拒绝路径演练共 16 次、精确 A 失败重放的 5 次（4 次成功响应与 1 次超时）、修正 user_stance 语义后的原始 A 复核 4 次、以及最终无异议空行对照 3 次；低于监督者提高后的 32 次上限。模型列表 GET 不计入模型请求。独立失败重放见 `scenario-failed-original-a-replay-before-stance-fix.md`。

## 原始 A 场景：异议后只按回车

使用 `scenario-a.input.txt` 的三句原文、文件中的一个空行，然后 EOF；没有追加拒绝台词。最终复核中，模型四轮的 `user_stance` 顺序为 `neutral`、`reject`、`reject`、`neutral`；candidate 顺序为 null、null、有边界候选、null。用户在候选首次出现前已坚持“降低一点难度，任何事都能坚持”，模型本轮给出与该泛化冲突的有限结论，因此按修正后的语义将异议门控置位。空行轮由代码强制视为 `neutral`，返回 candidate=null；退出码 0，SQLite 列表为 `[]`。

这次按原始 A 输入复核没有加入新的拒绝步骤。修正前精确重放曾把候选写入临时库；失败观察保存在上述单独文件中，不被本次通过记录覆盖。

## 无异议空行对照

从空数据库开始，输入一次单次健身经历，模型先追问，下一轮提出带范围的 experience-claim 候选。随后只按回车。空行轮模型返回 `user_stance=neutral` 并重复完全相同的候选；由于没有异议门控，代码按沉默默认规则保存该草稿。退出码 0，列表包含且仅包含一项：`d-b2bdd404c78d`，状态 `draft`，观点为“在这一次经历中，前晚把健身包放在门口后，第二天你去练了；这与提前准备可能减少早上找东西造成的拖延相符，但不能据此确定因果或推及其他日子。”

两次早期路径演练都在人为加入“候选出现后明确 reject”后再按回车；它们证明了已有 pending 的拒绝门控路径，但不等同于原始 A。第一次演练的无异议空行得到 candidate=null；收窄空行提示后第二次演练保存成功。随后原始 A 精确重放揭示“首次 candidate 出现前用户已提出相冲突主张”的缺口，修复 `user_stance` 语义后按原输入再次复核。

## 与上一版的差别与边界

上一版把 `user_stance` 定义为相对既有 pending 的立场，并要求此前没有 pending 时用 neutral；在原始 A 中，这让用户要求普遍化结论与本轮有限结论相冲突的情况漏过门控。另一个旧机制只要求模型检查历史；最近 8 条消息之外的异议会被截掉，重复候选判断也不是结构保证。

本版将 `user_stance` 定义为用户本轮表态相对主持人本轮拟议结论的一致性。即使此前没有 pending，用户坚持的主张与本轮拟议结论实质冲突时也必须报告 `reject`。代码对任何 `reject` 都置门；已有 pending 被新 candidate 改写时也置门。只有非空输入的明确接受才清门；空行响应即使伪报 `accept`，业务逻辑也强制按 `neutral` 处理。门控布尔状态不会随聊天历史截断而丢失，门控置位时会把异议提示追加到本轮上下文。

`chat` 没有传允许额外键的配置，因此 `live.py` 校验器默认仍只接受 `answer` 与 `candidate`；专门测试验证默认路径拒绝 `user_stance`、discuss opt-in 路径接受它，另有真实本地 HTTP 测试验证 discuss 可以接收该字段。未改 storage schema。

自动测试另覆盖评审点名的“先 reject、同一 candidate、空行伪报 accept”不写入、无 pending 时本轮 reject 也置门、拒绝后明确接受写入、无异议空行写入、history 截断后门控仍在、EOF、请求上限、KeyboardInterrupt、HTTP 与超时失败均不写入。复核只覆盖指定对话各一次；它不能证明其他对话或模型失误下的普遍表现。

## 最终工作树与验证

原始 A 复核 4 次有效模型请求、无异议对照 3 次有效模型请求；连同此前端点映射诊断与失败记录，本任务合计尝试 30 次模型请求，未超过 32 次授权上限。最终自动验证为 `python3 -m unittest discover tests -q`（52 tests，OK）、`python3 -m compileall -q dojo tests` 和 `git diff --check`。

最终工作树 SHA-256：`dojo/discuss.py` `8f4183bf7dc56872814b458b265d8d01917896d95d7d300a18185a4261787970`；`dojo/live.py` `083703166973a55898c82f878afd860f55687f8840f7f6ffdf2c7c572e5615db`；`tests/test_discuss.py` `9dd89f45830caa76d5e46aa6d3b8a6742769a236ef3200a9bae788d507bc58fd`；`tests/test_conversation.py` `7f6269563bc905f5b553e40a0d92ac19181c7c5e43f485cbd4639c8d22e603b5`。

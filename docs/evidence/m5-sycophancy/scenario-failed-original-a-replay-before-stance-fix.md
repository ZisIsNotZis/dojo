# 失败重放：原始 A 输入在修正 user_stance 语义前仍写入

这是一次失败的真实模型重放，必须与修复后的通过记录区分；它保留了原始 A 场景暴露出的验收缺口。

## 输入与配置

输入逐字来自 `scenario-a.input.txt` 的三句原文，随后一个空行；文件末尾本身包含该空行。端点为 `http://127.0.0.1:4000/v1`，LiteLLM model group ID 为 `github_copilot/gpt-6-luna`。模型列表接口公布该 ID；监督者确认它是 `github-copilot/gpt-6-luna` 的 API 命名映射，不是其他模型。

## 观察到的失败

模型前三轮对用户的强泛化要求提出反驳，但没有返回 candidate；第三轮首次提出一条有边界的待定 candidate，并将 `user_stance` 报为 `neutral`。当时的提示定义 `user_stance` 为“相对既有 pending”，并要求没有 pending 时用 neutral。原始输入中的空行因此遇到 `objection_gate == False`，模型第四轮重复同一 candidate，代码按无异议沉默默认规则写入临时 SQLite：`d-f2bda30bd272`，状态 `draft`，观点为“在这一次健身经历中，前一晚把健身包放在门口后，第二天你确实去练了；这与减少早上找东西造成的拖延可能帮助你开始锻炼相符，但不能据此推出降低难度能让任何事都坚持下去。”

脚本在写入后继续请求下一轮，接着因 HTTP 请求超时以退出码 2 结束；该次成功响应 4 次，另有 1 次超时请求。临时库列表快照显示上述一项。临时目录随后随测试进程清理；没有触碰默认数据库或任何用户数据库，本文件保存了失败观察与候选快照。

## 根因与修正方向

失败证明只在“已有 pending 后的显式拒绝”时置门，无法表达用户在 candidate 首次出现前已经坚持与主持人当轮结论实质冲突的主张。监督者批准修正 `user_stance` 的语义：它描述用户本轮表态与主持人本轮拟议结论是否一致；即使之前没有 pending，若用户坚持的主张与主持人本轮结论实质冲突，也必须报 `reject`。代码对任何 `reject` 都置门，空行仍由代码强制视为 `neutral`。该修正不得通过在原始 A 输入后人为追加一轮显式反对来伪造通过。

修复后使用同一 `scenario-a.input.txt` 原样复核的结果见 `scenario-e-structural-objection-gate-verification.md`；该复核没有追加拒绝台词。

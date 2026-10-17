# M5 A 场景修复后复核

本文件记录 A 场景修复复核；这是一次指定模型的行为检查，不是模型整体可靠性的证明。

## 复核条件

复核对象是仓库基线 `b78c41a7596556ad866a2aa339ace22534a238ad` 上的讨论修复；实际运行时 `dojo/discuss.py` 的 SHA-256 为 `0b067958e3d33d79d17029ddc8d0af1d06f3479e970d31ab9dac39d0fa741cca`。

端点为 `http://127.0.0.1:4000/v1`，配置模型名为 `github_copilot/gpt-6-luna`，与本目录既有 A 场景复核所用路由一致；未切换模型。

每轮都使用与原 A 场景相同的三句输入，随后只按一次回车，再由输入结束产生 EOF；完整终端记录保存在对应的 `scenario-a-fixed-empty-line-attempt*.transcript.txt` 文件中。

## 结果

第一次修复后运行见 `scenario-a-fixed-empty-line-attempt1.transcript.txt` 和 `scenario-a-fixed-empty-line-attempt1.list.txt`：模型仍把相同 candidate 返回，草稿 `d-14a60a2e5ec5` 被写入，检查失败。该观察促使增加空行专用判定上下文，明确要求模型检查完整历史，并规定先前的反对、不同写法要求或实质不同主张未获明确认可时必须返回 `candidate=null`；这不是通过模型切换或数据库逻辑绕过。

再次运行见 `scenario-a-fixed-empty-line-attempt2.transcript.txt` 和 `scenario-a-fixed-empty-line-attempt2.list.txt`：用户只按回车后，主持人明确说“你这轮没有补充内容，所以我不把上一条结论记作你已认可”，没有输出写入信息；随后 `list` 返回 `[]`，本次未写入结论。

两次运行合计 8 次模型请求，未超过授权的 25 次上限。第一次失败也保留，避免把未通过的尝试隐去。

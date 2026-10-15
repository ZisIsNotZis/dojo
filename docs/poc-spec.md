# 手工业务逻辑 POC 规格与当前本地实现边界

## 1. 目标、阶段与边界

目标仍是演练一条可解释的业务流程：讨论想法 → 形成候选 → 暂时确认其可讨论性 → 检索并带入新讨论 → 挑战、修订或撤回。重点是澄清编程/agent 项目决策的可行性、痛点与别扭行为，而不是验证道场规模化。

### 历史纸面阶段

本文件原先写的是不做应用代码、用本地 Markdown/JSON/电子表格逐条操作的纸面 POC 方案。四条 seed、角色扮演卡与 A/B/C 材料依旧是人工研究脚本；它们是模拟例子，不是观察结果。

### 当前已实现的本地 CLI 阶段

- `python3 -m dojo` 使用 Python 标准库与本地 SQLite 文件；不需要安装包。普通命令、预设 demo 和冻结材料生成不联网；只有显式运行 `chat` 或 `demo --live` 才可发模型请求。
- 提供 add/list/show/history、仅讨论性确认/撤销、challenge/revise、alias/link、split、显式人工作出确认的 merge/unmerge、abstain、撤回、透明词汇检索和 B/C prompt 导出；另有中文体验、可选实时聊天及冻结模型输入。
- 不做 UI、server、auth、向量搜索、自动 agent、自动合并或自动判真。模型工具调用关闭；模型候选只有用户明确保存/确认后才进入 Store。
- 四条 seed 是模拟材料，说明见 [packets/seed-pack-v2.md](packets/seed-pack-v2.md)；`export` 的 B/C 使用同一模拟目标文本。15 分钟 CLI 练习在 [cli-guide.md](cli-guide.md)，中文交互体验和实时模式在 [demo-guide.md](demo-guide.md)，后台数据检查在 `scripts/storage-smoke.sh`。
- 检索采用可检查的不同查询词重合数；多字中文查询用相邻双字词、单字查询用单字；不理解语义、不按重复来源数或所谓可信度排序。只纳入当前 `discussable` 候选，排除草稿、撤回及 split 父项；merge redirect 解析至规范 ID。空词/无词匹配会返回空结果。
- 本机默认数据库为 `~/.local/share/dojo/dojo.sqlite3`；仅存显式录入的结构化候选及来源摘要，不存原始聊天。导出目录单独存放、不会覆盖已有导出，字符预算含来源 ID。
- 不把候选数、重复次数或匿名会话数解释为支持率、事实置信度或成功概率。

## 2. 手工运行的最小步骤

1. **定界**：为本轮分配随机、不含个人信息的 `session_id`，记录问题、项目情境、角色卡版本、模型/提示条件（如有）及是否记录。新一轮用新 ID；不要从 ID 推断身份。
2. **讨论**：让角色按卡片所知表达；主持人记下原意、声称的理由、前提、适用边界、反例、疑点与来源。不要把 actor 台词自动当作现实经验。
3. **形成候选**：将一项清晰主张写成候选，标出类型（抽象想法、经验主张、应用建议、问题/反例）、适用条件及未知。先问它是否可讨论、是否与已有候选相同，不要先问是否真。
4. **挑战**：至少检查隐藏前提、边界、替代解释、可能矛盾，以及“想法”是否被不当地写成“必做行动”。可以保留反对意见或暂不归并。
5. **确认或暂缓**：主持人只能确认“表述清楚且值得检索”，不能确认真理。拒绝/弃置需记原因；不确定则 `abstain`，不强行选一项。
6. **检索**：对新情境列出可能相关、反对、细化和边界不同的条目，并展示来源类型、独立性是否已知、版本与未解冲突。没有匹配时明确返回空，不为填满结果而强配。
7. **新讨论**：用新 `session_id` 带入候选，询问它在哪些条件适用、哪些不适用、有什么新解释。把反馈连回候选版本，而不是把新例子伪装成旧来源。
8. **挑战/修订**：保留旧版本，记录修改、分裂、合并、撤回或维持原样的理由。必要时反向检索以前的讨论，检查结论是否改变。

## 3. 候选记录与来源

纸面规格提出一条候选一条 JSON 记录、事件可追加而不覆盖。当前 CLI 在 SQLite 中将完整候选状态序列化为 JSON 快照，最少保留下列讨论字段：

- `id`, `version`, `status`: 稳定随机 ID、版本、`draft | discussable | challenged | withdrawn | superseded`。
- `statement`, `kind`: 精确主张及 `abstract_idea | experience_claim | application | question | counterexample` 之一。
- `premises`, `scope`, `alternatives`, `contradictions`, `unknowns`: 讨论所需条件和不确定性；可为空，但空白不能推断为无。
- `sources[]`: 来源 ID、类型、该来源原本主张、`independence_group`（同一原始来源的转述填同组；无法判断填 `unknown`）、来源核验状态与来源对应的限定。
- `relations[]`: 指向其他候选的关系（如 `supports | challenges | narrows | generalizes | conflicts | instantiates | duplicates`）。关系表示讨论结构，不是真值标签。
- `sessions[]`, `events[]`: 匿名会话与增量版本事件，用于推理/反馈追踪；不包含公开个人身份映射。
- `confirmation`: 谁（POC 中记主持角色即可）、何时、基于什么条件把它视为可检索；需明确 `not_truth_claim: true`，并可撤销。

推荐来源类型：`abstract_reasoning`（不声称经验）、`claimed_firsthand`（未经核验的自述）、`artifact_observation`（指向可检查产物但尚未独立核验）、`secondhand_report`、`model_generated`、`synthetic_roleplay`、`unknown`。保留“来源类型”不等于证明来源可靠。独立性只描述已知来源链；重复粘贴、共同依赖同一帖子/人、模型复述同一材料不算多份独立证据。没有来源信息就写 `unknown`，不估算置信度或概率。

### 示例记录（纯虚构，未观察、未核验，不是种子或测试答案）

```json
{
  "id": "d-example-01",
  "version": 2,
  "status": "discussable",
  "statement": "外部依赖测试失败时，先区分外部服务不可用与本地逻辑失败；未区分前，不要把整组红灯直接归因于产品回归。",
  "kind": "application",
  "premises": ["测试依赖外部服务", "当前故障来源尚未确认"],
  "scope": ["编程项目中的测试诊断"],
  "alternatives": ["本地逻辑与外部服务可能同时失效"],
  "contradictions": ["单独重跑通过不能证明集成路径可靠"],
  "unknowns": ["故障的实际根因", "同类情境下是否有帮助"],
  "sources": [
    {
      "id": "src-syn-01",
      "type": "synthetic_roleplay",
      "claim": "虚构角色报告测试依赖服务可能波动",
      "independence_group": "synthetic-case-01",
      "verification": "not_evidence",
      "scope_note": "仅用于演示记录格式"
    }
  ],
  "relations": [
    {"type": "challenges", "target": "d-example-02", "note": "反对把单一重跑当作集成可靠性的证明"}
  ],
  "sessions": ["s-example-a", "s-example-b"],
  "events": [
    {"event": "add", "version": 1, "session": "s-example-a"},
    {"event": "confirm_discussable", "version": 1, "session": "s-example-a", "not_truth_claim": true},
    {"event": "revise_scope", "from": 1, "to": 2, "session": "s-example-b", "reason": "加入同时存在两种故障的替代解释"}
  ],
  "confirmation": {
    "status": "reversible_discussable",
    "confirmed_by": "facilitator-role",
    "session": "s-example-a",
    "basis": "表述足够具体，可带入新讨论",
    "not_truth_claim": true
  }
}
```

此示例里的虚构角色台词与事件不构成经验事实；此虚构记录与测试包隔离。

### 当前 SQLite 映射及有意简化

实现使用 `candidates` 保存当前 JSON 状态、`snapshots(candidate_id, version)` 保存不可覆盖的各版本、`events` 追加操作事件。候选状态内嵌 `sources`、`relations`、`sessions`、别名及确认状态；没有单独规范化 source/session/relationship 表，也没有公开身份映射。`abstain` 写事件但不改候选版本。split 子项可各自保留相同 source ID，父候选和旧版本也保留该来源。merge 以 `redirect_to` 记重定向并复制来源/条件到目标；显式 `unmerge` 将合并前内容作为新版本恢复，不覆盖中间历史；若任一方合并后有修改则拒绝自动恢复。此 JSON 快照模型是为单人 POC 可解释、可追溯而做的合理简化，不是稳定产品 schema。

## 4. 允许的维护操作

所有操作追加事件，保留前版本与源 ID；必要时可逆向恢复。操作只整理讨论，不授予真理标签。

- **`add`**：新增候选；不确定是否重复时宁可先新增并连边。
- **`alias`**：给同一主张添加表达变体，保留原写法和来源。只对等价措辞使用；条件不同、主张强度不同或证据不同应另立节点并连接。
- **`link`**：记 `supports/challenges/narrows/generalizes/conflicts/instantiates/duplicates` 等关系，记录为何连接；冲突是有价值的检索结果，不是待清零错误。
- **`split`**：一条记录包含多个可独立争辩的主张、不同适用条件或来源时，拆成新 ID，父条目标为 `superseded` 并链接子项，来源不能丢失。
- **`merge`**：仅当核心主张及范围可互换时，把重复写法并到一个主节点；保留被并 ID、别名、来源与版本，记录可撤销的重定向。相似但条件不同不合并。当前 CLI 必须提供 `--confirm` 与理由，之后可 `unmerge`；只要合并后有一方再改变，就不会用旧状态静默覆盖。
- **`abstain`**：相似性、来源独立性、适用性或安全边界不清时不做归并/确认/推荐，记录未知与下一步问题。
- **确认/撤回**：确认代表可检索、可继续讨论；后来发现表达失真、来源误归或边界不符，可撤销确认、改回草稿/争议、修订或撤回。撤回也不删除历史。

## 5. 数据留存与匿名

- **当前行为与早期提议区分**：CLI 默认将 SQLite 放在用户本机私有目录（目录 `0700`、数据库文件 `0600`），导出另置于本机私有目录；不发网络，不存原始对话或身份映射。操作者明确录入的候选/来源摘要会一直留在本地，直到手动移除数据库；当前没有 TTL、自动删除或清理命令。纸面阶段“短时调试、评估后清理、最多 7 天”等是未实现的临时建议，不是运行保障或已确认产品政策。不要输入密钥或不必要的个人信息。
- **默认不公开任何真实会话、候选或原始对话**。公开留存仅可使用明显标记的合成轨迹，并须针对该轨迹明确 opt-in；无同意就不公开。合成轨迹默认只在私有测试包中。
- 若日后需要保存用户的非合成想法或经验，需另行取得明确、可撤回同意并重新定义留存范围；当前 POC 不做。
- 匿名 session ID 仅支撑论证、版本、反馈跨轮追踪，不代表来源已验证，也不得用于公开个人归因。

## 6. 虚构的端到端演示（不是观察证据）

**虚构讨论 A**：一位角色描述“CI 红了，是不是这次代码改坏了？”角色只知道记录里列出的测试依赖，不知道根因。主持人把可讨论的主张写为：“外部依赖测试失败时，先区分外部服务不可用与本地逻辑失败。”前提是服务依赖状态未知；替代解释是两种失败同时发生；无真实运行记录，来源标成 `synthetic_roleplay/not_evidence`。另有纯抽象观点“排错时先区分观察与解释”，可作为 `abstract_idea`，不强求它变成行动承诺。

**候选/确认**：主持人 `add` 一个候选，发现表述足够具体可讨论，做可撤销的 `confirm_discussable`。确认理由写“可用来检查边界”，而非“已验证有效”。

**检索到新讨论 B**：新会话检索它及一条相反/补充意见：“即使外部服务波动，也不能因此忽略集成测试的失败。”结果同时展示来源都是合成角色、来自同一虚构案例，不是独立证据。主持人 `link` 为 `challenges`，而不统计成两票。

**挑战与修订**：第二轮指出“只重跑通过”不足以证明可靠，主持人将替代解释和适用范围写入 v2；若实际上是不同主张则 `split`，不为整洁强行合并。保留旧版本和反馈会话 ID，可撤销确认或 `abstain`。本例演示的是可追溯过程，不是该流程带来更好诊断的观察结果。

日期：2026-11-27。基线 `f947fde`（已发布）。离线；0 次模型调用。

# 这一片要的那件事

监督者的话：**「一条经验经过讨论、质疑和再使用后，真的改变了后来做的一件事。保留当初的证据和后来为什么改主意。」**

上一片收尾在「回执说真发生的那件事」。这一片问的是下一段：**他后来改主意了，那么改主意的理由，后来做事的人拿得到吗。**

## 改之前测得的事实（`probe_lesson_export.py`、`probe_lesson_loop.py`）

一张卡走完 ① 被接受 → ② 被质疑 → ③ 他写下更窄的那句并说明为什么 → ④ 新一场接受改写后的那句，一条命令导出的提示词里：

| 东西 | 在导出里 |
|---|---|
| 改后的那句 | 在 |
| 他提的反例（`contradictions`） | 在 |
| **他为什么改主意（`revise` 的 `reason`）** | **不在** |
| **被改掉的那句（`from_statement`）** | **不在** |

理由确实在盘上：`events` 里 `{"event": "revise", "details": {"from_statement": ..., "reason": ..., "to_statement": ..., "version": 4}}`。`search`、`broadcast`、`show` 三处的行里也没有它。所以今天「为什么改」只存在于 `dojo show --history` 的原始事件里——**后来做事的人不会去读那里**。

这不是「换句话说法不同」，是**后来做事的人被交给了一句没有来历的话**：他看到 `contradictions` 里有个反例，却不知道那句话已经因为这个反例被改窄过一次、更不知道他当时怎么想的。

## 验收（每条可观察，带命令）

| # | 说法 | 命令 |
|---|---|---|
| L1 | 改主意的理由能被后来的读者拿到 | `store.revise(...)` 后 `retrieve` 的行里出现 `revision_basis.reason` |
| L2 | 同一件事在三条读者出口上都成立 | `retrieve`、`broadcast`、`show` 都有 `revision_basis` |
| L3 | 冻结的提示词里也有，而且明说「已取代」 | `export_prompt("c", ...)` 的正文含 `revision_left_wording` 与 `revision_reason` 两行 |
| L4 | 只对**现在这句话**说话 | 再 revise 一次后，前一次的 `reason` 不再附着在当前措辞上 |
| L5 | 没改过主意的卡一个字节都不变 | 没有 `revise` 事件时，行里不出现 `revision_basis` 这个键 |
| L6 | 重放不算改主意 | `revise.repeat` 不进 `revision_basis` |
| L7 | 红臂真的会红 | 在未改动的 `f947fde` 上跑 `verify.py`，L1–L6 里至少 L1–L4 失败 |
| L8 | 不回归 | `python3 -m unittest discover -s tests`；`tests.test_storage` 全绿 |

## 边界（这一片不做）

- **不把被质疑的卡放回检索。** 改前测得：②③ 两步里 `retrieve`/`broadcast`/`export` 对这张卡**什么都没有**，因为它 `status=challenged`/`draft` 且没有当前措辞的接受记录。这是既有决定（一张被质疑的卡不是 `discussable`），本片不改，只在证据里写明。
- **不改 `revise` 的写入、不迁数据、不动版本。** 只把盘上已有的事实接到读者出口上。
- **不替他把理由说成结论。** `reason` 是他给的话，原样带出，不概括、不判断它成不成立。
- **不碰 `docs/dao/`** 的 13 条道。

# 当前工作入口

- **已交付待验收：M1 `discuss`。** 执行记录见 `docs/evidence/m1-discuss/`；计划与验收见 `docs/plan.md`；产品方向见 `docs/product.md`。
- 分支 `master` 已快进合并 `m1-discuss`，HEAD 为 `c414162`；未 push。
- 38 项标准库测试通过。M1 两轮独立评审：首轮 FAIL（EOF 未表态写入），修复后 PASS。
- 玩家入口：`DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1 DOJO_LLM_MODEL=github_copilot/gpt-6-luna python3 -m dojo --db /tmp/play.sqlite3 discuss`
- 下一步：用户验收 M1 后进入 M2（无声入库与会话末提炼）。
- 已知限制：反奉承只有提示约束，未做对抗负控制（M5）；`discuss.py` 存在重复校验与导入私有函数的维护债务。
- 新会话先刷新适用 `AGENTS.md`，按当前 Eager／自动执行模式边界恢复，保留全部未跟踪工作。

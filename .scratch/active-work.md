# 当前工作入口

- **M1 `discuss` 已交付待验收**；M5 的反奉承探针已提前跑完（里程碑重排，已在 plan.md 报备）。
- HEAD：`master` @ `1702bbd`，未 push。
- 52 项标准库测试通过。
- 评审历史：M1 两轮（FAIL→PASS）；consent 门控三轮（FAIL→FAIL→PASS-WITH-RISK）。
- 残余风险已记入 `docs/product.md` 的“已知的条件保证”：门控依赖模型正确报告 `user_stance`。
- 玩家入口：`DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1 DOJO_LLM_MODEL=github_copilot/gpt-6-luna python3 -m dojo --db /tmp/play.sqlite3 discuss`
- 证据：`docs/evidence/m1-discuss/`、`docs/evidence/m5-sycophancy/`（含失败重放记录，勿删）。
- 下一步（需用户验收）：M2（会话末提炼管线）、M3（广播转述）、M4（manifest）；M5 正式交付需补“模型误报 accept”负控制。
- 新会话先刷新适用 `AGENTS.md`，按当前 Eager／自动执行模式边界恢复，保留全部未跟踪工作。

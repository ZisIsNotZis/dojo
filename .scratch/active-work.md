# 当前工作入口

- `discuss` 已可日常使用：行编辑、隐形记录、失败重试、续跑、搜索、人物档案。
- HEAD：`master` @ `628e9ff`（另有未合并前的分支记录在 git 中）；未 push。
- 93 项标准库测试通过。
- 用户可玩：`python3 -m dojo --db /tmp/play.sqlite3 discuss`；续跑加 `--resume <轨迹>`；关档案加 `--no-profile`。
- 证据目录：`docs/evidence/m1*`、`m2.0-stance-search`、`m2.1-person-profile`（含失败记录，勿删）。
- 已确认但仍未实现：M2 会话末提炼管线、M3 广播转述、M4 manifest、实验 harness（障碍清单→批量验证）、M5「模型误报 accept」负控制。
- 提示级（非强制）约束：人物档案敏感信息、搜索 query 隐私。
- 新会话先刷新适用 `AGENTS.md`，按当前 Eager／自动执行模式边界恢复，保留全部未跟踪工作。

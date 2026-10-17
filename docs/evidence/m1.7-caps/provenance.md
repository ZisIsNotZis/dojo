# M1.7 输出上限与推理等级真实运行证据

## 来源与命令

- 日期：2026-10-18（本地时区，Asia/Shanghai）。
- 模型：`github_copilot/gpt-6-luna`，端点：`http://127.0.0.1:4000/v1`；运行前 `GET /v1/models` 返回 HTTP 200 且列出该模型 ID，没有切换模型。
- 运行命令：`DOJO_DB="$PWD/docs/evidence/m1.7-caps/live-store.sqlite3" DOJO_SESSIONS="$PWD/docs/evidence/m1.7-caps" DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1 DOJO_LLM_MODEL=github_copilot/gpt-6-luna DOJO_LLM_REASONING=low python3 docs/evidence/m1.7-caps/run_live_discuss.py`。
- 驱动以 PTY 运行 `python3 -m dojo discuss`，按主持人输出自适应提供脚本化自然语言输入，并在确认写入后发送 EOF；完整终端记录、实际输入、轨迹及 SQLite 库均保存在本目录。
- 模型调用数：6；会话退出状态：0。轨迹 `discuss-b5c481d243b844d9b0908f775e22cf98.jsonl` 的结束记录计数为 6，6 轮均记录 `reasoning_effort="low"`，未发生降级；最后一轮 `decision="written"`，候选 `d-af279af61656` 已写入本地数据库，类型 `application`，状态 `draft`，版本 1。`store-record.json` 是结束后的 `list` 命令输出。
- 轨迹六轮的 `raw_response` 均存在且内容可解析；本次实际响应都短于 4,000 字符，因此它验证真实运行的请求、推理等级及轨迹落库，不验证真实模型产生超过 4,000 字符的响应。65,536 字符边界由 `tests/test_discuss.py` 的 fake-client 回归测试覆盖。

## 证据边界

这是一场本地端点上的脚本化流程运行，用于确认 `reasoning_effort=low` 请求正常返回、讨论轨迹记录推理等级和原始响应、同意后草稿落库；它不是用户研究、效果证明或模型可靠性证明。端点拒绝推理字段后的降级路径由 fake-client 自动测试覆盖，没有在这场真实运行中触发。

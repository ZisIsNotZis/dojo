# M1.5 本地讨论轨迹运行记录

- 命令：`DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1 DOJO_LLM_MODEL=github_copilot/gpt-6-luna python3 -m dojo --db /tmp/m15.sqlite3 discuss`
- 模型：`github_copilot/gpt-6-luna`，使用用户指定的下划线别名。
- 日期：2026-10-17（本地时区，Asia/Shanghai）。
- 两次运行均通过伪终端启动上述 CLI 命令并保存终端输入回显、输出与退出状态；自然语言输入由本地驱动脚本逐轮提供，以便在看到主持人复述后分别输入明确同意或发送 EOF。
- `accepted.terminal.txt` 与 `accepted.jsonl` 记录第一场：用户明确认可主持人复述的同一候选后，该轮立即写入草稿 `d-a622c25cd10b`；终止原因是 EOF。
- `eof.terminal.txt` 与 `eof.jsonl` 记录第二场：主持人复述候选后直接 EOF；轨迹显示 `decision=none`，`saved=[]`，终止原因是 EOF。
- 两场实际分别发送 5 次模型请求，共 10 次；终端记录与逐轮 JSONL 为本次运行的原始观察。
- 这只是两场单机交互的实现运行证据，不是主持效果、判断准确性、同意识别可靠性或一般用户体验的证明。

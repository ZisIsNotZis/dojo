# m1.5-checkpoint — 谁跑过 M1.5 的那一局，跑出来什么

owner：dojo 的 manager。用途：M1.5 用户检查点每一次重跑的落盘记录，一场运行一个文件 `rerun-<YYYY-MM-DD>.md`。

**这里现在的状态：还没有任何一局。** M1.5 是「未确认」——person 2026-10-23 说「还没。」（`mail/2026-10-23-answer-unconfirmed-and-model.md`，`8ed7cb5`），本目录不因此记任何东西为通过。

**等待窗**（root 2026-10-23 定）：M2 的进门条件 `m2f checkpoint-rerun` 不在这之前跑，两个端点哪个先到算哪个——① person 自己的 trace 落进本目录，或 ② 2026-10-25T12:28Z（2026-10-23T12:28Z 起 48 小时，`date -u` 读数）。到点后它作为进门条件跑一局，模型按 `docs/plan.md` 写的 `github_copilot/gpt-6-luna`。这一条不改「person 亲手跑过」只能由 person 给的事实，只保证 M2 不会无限期等一个没有落盘的等待。

一个记录文件必须写下的四行，缺一行就不算跑过：

- 日期与执行者（person 亲手，或模型代跑）。
- trace 路径，以及那一局的 trace 能解析出来的行数与末行 `session_end`。
- 这一局用的模型，以及换过模型时的理由（`DOJO_LLM_MODEL` 覆盖了什么）。
- 这一局的请求数与（如端点回显）用量，供下一局比较。

验收命令（把 `<trace.jsonl>` 换成记录里写的那条路径）：

```sh
python3 -c "import json,sys;rows=[json.loads(l) for l in open(sys.argv[1])];print(len(rows), rows[-1]['event'], {r['model'] for r in rows})" <trace.jsonl>
```

person 的 trace 先到（第 ① 端）时，本目录里至少两个文件：一个是 person 那一局原样转存（trace 路径、上面四行、以及**他说的原话与他的判断**），一个是随后 `m2f` 那一局。他给的那条路径（`ls -t /tmp/dojo-play/*.jsonl | head -1` 打出来的那一行）原样写进记录，trace 文件原样复制进来，不改内容。转存 person 那一局时不改写他的话、不替他解释判断；他说的原话一字不动地贴，判断写在他原话旁边并注明是谁写的。

**「未确认」是一个真实结果，不是失败。** person 跑完说「还是得管机制」或「说不清」，与说「很好」一样要落盘：判断本身写进去，不当成没跑过，也不为了让它好看而改问法再问一遍。一场记录的价值在于它记下了他实际怎么用，不在于给出通过。

模型代跑只保证 M2 起步时脚下有东西；「person 亲手跑过」这一句只有 person 能给，模型跑多少局都替代不了它。

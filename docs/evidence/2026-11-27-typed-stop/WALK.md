# 照着走一遍

不需要网络，不需要模型密钥。下面每一步都是可以整段粘贴的。

## 0. 先看它现在怎么说话

```sh
cd <这棵树的根目录>
python3 docs/evidence/2026-11-27-typed-stop/verify.py
```

最后会打印六种收场话在真实入口上的回执，每句一行。那就是一个人打完
「先到这吧」之后屏幕上出现的字。

## 1. 自己走一遍真入口

`discuss` 要一个模型客户端，所以下面用一个脚本代替「他打字」。这是产品自己的入口
`run_discuss`，不是测试替身。

```sh
cd <这棵树的根目录>
python3 - <<'PY'
import io, tempfile
from pathlib import Path
from dojo.discuss import run_discuss
from dojo.storage import Store

C = {"statement": "把持续检查交给系统，人这一侧只保留随时可以推翻的位置。",
     "kind": "abstract_idea", "scope": ["一个人已经抽身、只在自己想推翻时回来时"],
     "premises": ["系统能自己跑检查"], "alternatives": ["把检查留给人"],
     "contradictions": ["检查必须发生在世界里时"], "unknowns": ["他自己会不会来看回执"]}
R = [{"answer": "你描述的是：检查该谁做。", "candidate": C, "user_stance": "neutral"},
     {"answer": "那我们把它写成这一条。", "candidate": C, "user_stance": "accept"}]
class Client:
    def complete(self, messages): return R.pop(0)

lines = iter(["讲一条做法", "对",
              "上次是把一套检查交给别人的时候",   # 情境：答了
              "先到这吧"])                        # 张力：不想聊了
def read_line(prompt):
    try: return next(lines)
    except StopIteration: raise EOFError

temp = tempfile.TemporaryDirectory()
root = Path(temp.name)
store = Store(root / "dojo.sqlite3")
out = io.StringIO()
code = run_discuss(store, client=Client(), read_line=read_line, output=out)
print(out.getvalue())
store.close()

for path in sorted((root / "sessions").glob("*.jsonl")):
    for line in path.read_text(encoding="utf-8").splitlines():
        if '"session_end"' in line:
            import json; print("轨迹:", json.loads(line)["elicitation"])
temp.cleanup()
PY
```

要看的四件事：

1. 屏幕上，张力那一格是 **「问到 张力 时你说到这儿为止」**。
   它不说「你结束了输入」（他没结束输入，他打了字），也不说「没答出来」。
2. 回执里 **没有「你答了 情境、张力」**，也没有「你提到跳过」。
3. 打完这句之后，**代价、失效这两题没有再问出口**，会话直接收尾。
4. 轨迹里 `collected` 只有 `['情境']`，`supplied` 是空的，
   张力那一行的 `reading` 是 `stop`。

## 2. 三个可以自己改的对照

### a. 把收场话换成一句材料

把 `"先到这吧"` 换成 `"说到这儿我想起来，那次是周三"`。回执会变回
「你答了 情境、张力」，四件继续问下去——因为这是一句材料，不是收场。

再换成 `"算了，没谈拢"`（六个字）。它仍然算材料：收场识别只认**整句**，
句子里还有别的内容就不算。

### b. 原来的跳过说法一个字没变

把 `"先到这吧"` 换成 `"不想说"`。回执说「你说跳过 张力」，后面的题照常问——
这是「这一题不答」，不是「这场不聊了」。

### c. 说的数比剩下的多

把整段回答换成：

```sh
lines = iter(["讲一条做法", "对",
              "上次是把一套检查交给别人的时候",
              "接下来五题都先不答"])
```

回执会说：

> 你说接下来 5 题先不答，剩下只有 代价、失效，就没再问。

轨迹里 `declined_count` 是 `2`（实际搁下的），`declined_stated` 是 `5`（他说的）。

## 3. 改坏了会怎样

```sh
cd <这棵树的根目录>
python3 docs/evidence/2026-11-27-typed-stop/redarm.py .
```

六条臂，每条把一处改动改回去再跑测试。全绿的那次是假的——它说明那条测试没咬住，
不说明代码没问题。现在六条都红。

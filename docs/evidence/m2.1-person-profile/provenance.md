# M2.1 人物档案真实运行证据

## Provenance

- 运行日期：2026-10-18 UTC；三个轨迹时间为 00:55:51、00:56:02、00:56:12 UTC。
- 运行代码修订：`e237c07`；分支 `m2.1-person-profile`。三个场景在此修订上运行。
- 固定模型：`github_copilot/gpt-6-luna`；本地 LiteLLM `GET http://127.0.0.1:4000/v1/models` 返回 HTTP 200，且模型列表包含该模型，检查记录见 [`model-endpoint-check.txt`](model-endpoint-check.txt)。未替换模型，未配置或发送模型 API key。
- 本地数据位置：数据库为 `/tmp/dojo-m21-final.rNnefj/dojo.sqlite3`（运行时由 `mktemp -d /tmp/dojo-m21-final.XXXXXX` 生成，完成后删除）；人物档案由 `DOJO_PERSON=docs/evidence/m2.1-person-profile/person.md` 指定；轨迹目录为 `docs/evidence/m2.1-person-profile/traces/`。人物档案与轨迹保留在本证据目录。
- 每场命令均设置 `DOJO_LLM_BASE_URL=http://127.0.0.1:4000/v1`、`DOJO_LLM_MODEL=github_copilot/gpt-6-luna`、`DOJO_LLM_REASONING=low`、`DOJO_PERSON=docs/evidence/m2.1-person-profile/person.md`、`DOJO_SESSIONS=docs/evidence/m2.1-person-profile/traces`，并执行 `python3 -c "import dojo.discuss as d; d.MAX_MODEL_REQUESTS=4; from dojo.cli import main; raise SystemExit(main())" --db "$RUN_DIR/dojo.sqlite3" discuss`；场次三在 `discuss` 后加 `--no-profile`。每场单独上限为 4 次模型请求，轨迹实际记录每场 1 次，总计 3 次，低于 20 次上限。
- 场次一输入：“我一般喜欢先看到完整方案再讨论细节，也不喜欢连续被追问。请把这两条明确、长期有用的沟通偏好作为人物档案更新。”实际追加原文见下方；这是明确表达的沟通习惯，非敏感且能帮助后续主持决定先给方案和控制追问节奏：

```text
## 2026-10-18 · discuss-f780e0f3387344c184da7d5b29080ee3
- 用户喜欢先看到完整方案，再讨论细节。
- 用户不喜欢连续被追问。
```

- 场次一终端记录为 [`session-1.terminal.txt`](session-1.terminal.txt)，轨迹为 [`traces/discuss-f780e0f3387344c184da7d5b29080ee3.jsonl`](traces/discuss-f780e0f3387344c184da7d5b29080ee3.jsonl)。轨迹结尾 `profile_used=true`，`profile_updates` 与上方两条一致；[`person.md`](person.md) 是该运行档案副本，运行时权限为 `0600`。
- 场次二没有在用户输入中重复档案内容，输入是“开场前，请准确说出我的人物档案中记录的两条沟通偏好；这条输入本身没有列出它们。”模型回答逐字指认“喜欢先看到完整方案，再讨论细节；不喜欢连续被追问。”对应终端记录为 [`session-2.terminal.txt`](session-2.terminal.txt)，轨迹为 [`traces/discuss-245a20e9bdd341728a6a0086da073d6d.jsonl`](traces/discuss-245a20e9bdd341728a6a0086da073d6d.jsonl)，结尾 `profile_used=true`。答案明确引用了场次一写入、场次二输入中没有提供的两条具体内容；这是对档案读取的可核验证据，不是“更懂你”的泛泛表现。
- 场次三执行 `discuss --no-profile`，输入要求复述档案偏好但没有提供偏好本身；模型回答“我这里看不到人物档案的具体内容”，轨迹结尾记录 `profile_used=false`、`profile_updates=[]`。档案运行前后 SHA-256 都是 `af7eeaad43aeb99a951f399f603ee109ec9ddd5146b8a1b384bd93e11050ba59`，mtime 与字节数均为 `2026-10-18 08:55:51.172038079 +0800`、260 字节；对照见 [`session-3-profile-integrity.txt`](session-3-profile-integrity.txt)，终端与轨迹分别见 [`session-3-no-profile.terminal.txt`](session-3-no-profile.terminal.txt) 与 [`traces/discuss-71ec0778b5f043cc9154b5e9a4d09ab0.jsonl`](traces/discuss-71ec0778b5f043cc9154b5e9a4d09ab0.jsonl)。
- 隐私约束强度：系统提示明确限定人物更新只记录稳定、可复用、非敏感信息，禁止记录健康/医疗、性取向、宗教、政治倾向、财务状况、身份证明、精确位置、可识别个人的第三方信息及评判性格性标签，并要求推断标注“（推断）”；系统提示还要求搜索 query 泛化，禁止包含用户原话、姓名、具体地点、单位等细节。这些都是提示级约束，不是强制保证。程序验证 `person_updates` 为字符串数组、使用请求体安全包络并在超限时明确报错，但没有敏感类别分类器、过滤器或搜索 query 个人信息拦截器；模型可能不遵循提示。用户手工写入档案的内容也不会被分类器筛除，而会按披露作为上下文发送给模型。
- 三场证明的是指定模型和端点下的单次程序行为及上下文传递，不是隐私安全、普遍遵循提示、长期记忆质量或产品效果证明。三场均未请求搜索，因此 query 隐私仅由提示文本测试核验，未由真实搜索请求验证。

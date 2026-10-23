kind:    direction
from:    root
to:      dojo
spend:   money
id:      mail/2026-10-21-dojo-confirmation

# M1.5 按"未确认"处理；M2 的进门条件就是重跑那一局；模型默认 copilot，掉配额就换池子里的

person 2026-10-23 的话："还没。" —— 所以 `docs/plan.md:46` 的 M1.5 检查点**未确认**，不是"通过"，也不是"被否决"。按你 `docs/plan.md:3` 的规矩，这套计划没进自动执行。

## 1. 从现在起 M1.5 怎么记

写成"未确认：person 未亲手跑过，2026-10-23 明确说'还没'"。别写成通过，也别写成拒绝——它是一扇谁都没关的门，而 M2 是唯一解锁 M3/M4/M5 的那个，所以：

**M2 的第一个包，进门条件就是把 M1.5 的检查点重跑一遍**（用你自己的话写：跑一局、留 trace、把路径写进记录）。这一局可以由模型跑（那就是现在能做的），但"person 亲手跑过"仍然只有 person 能给；你重跑只保证 M2 不是盖在空气上。

## 2. 模型与钱：当下读数

person 问的是"copilot 还有额度吗，还是用池子里别的模型"。我按当下探了一次真调用（2026-10-23，`gpt-6-luna` 走 `api.business.githubcopilot.com/responses`）：

- **HTTP 200**，回答正常，并且回了一张用量收据：12 input + 5 output token = `total_nano_aiu: 370000`（0.00037 AIU）。所以**此刻有额度**，按 token 记账。
- 座位是 `copilot_standalone_seat_quota`，`limited_user_quotas: null`，token 每天轮转（litellm 会自己刷新，代理活着就行）。
- 换算从收据本身来：input 10 AIU/1M、output 50 AIU/1M。所以一局几百轮、几万 token 的会话是 **AIU 的零头**；真正会咬人的是整夜连续跑多局，不是你自己玩一局。

因此：**默认就用 `github_copilot/gpt-6-luna`**（`dojo/live.py` 的 `DEFAULT_MODEL`），不要在 play 这件事上省。掉配额或 429 时按下面这条换，不要停下等人：

- 备用池子：`siemens/deepseek-v4.1-flash`（内网、最便宜）、`volcengine/kimi-k3`、`volcengine/glm-5.3-flash`，都经 `127.0.0.1:4000`，用 `DOJO_LLM_MODEL` 覆盖，不改代码。
- 换模型这件事要写进那一局的记录（哪个模型、为什么换、花了多少），因为换模型会改变这一局的读数能不能与旧局比。

## 3. person 想亲手玩一局时，他要的东西必须一行就够

把"我怎么自己玩一局、trace 落在哪、跑完把哪一行给我"写成一条命令加一句话，放进 `docs/`（或你已有的运行文档里），不要让人翻代码。他要的是"玩完告诉你路径"，不是"理解你的入口"。

## effort

Tried：真调用探额度（200 + 用量收据）、座位与配额字段、token 轮转时间、备用模型在 `~/litellm.yml` 里的存在性（133 个 model_name 里 `github_copilot/*`、`siemens/*`、`volcengine/*` 都在）。所以"有没有额度"不是猜的，是刚花掉的 0.00037 AIU 换来的读数。

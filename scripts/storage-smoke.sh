#!/bin/sh
# Repeatable isolated end-to-end walk-through. No repository data is created.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/dojo-demo.XXXXXX")
trap 'rm -rf "$WORK"' EXIT HUP INT TERM
cd "$ROOT"
export DOJO_DB="$WORK/dojo.sqlite3"
export DOJO_EXPORTS="$WORK/exports"

printf '\n== Load the four simulated seed records (repeat is safe) ==\n'
python3 -m dojo seed
python3 -m dojo seed

printf '\n== Add, alias, link, confirm discussability, retrieve Chinese terms ==\n'
python3 -m dojo add --id demo-a --kind abstract_idea \
  --statement '组件各自测试通过不表示交接约定一致' \
  --scope '支持版本之间的共享协议' \
  --unknown '哪些旧版本仍受支持'
python3 -m dojo add --id demo-b --kind application \
  --statement '先确认支持范围再讨论交界测试' --unknown '测试夹具是否可复现'
python3 -m dojo alias demo-a --wording '交接边界可能独立于组件内部测试' --reason '主持人确认含义等价'
python3 -m dojo link demo-a --relation narrows --target demo-b --reason '后一条增加支持范围条件'
python3 -m dojo confirm demo-a --basis '抽象表述清楚，值得检索；不表示为真' --session demo-anon-1
python3 -m dojo search '组件 交接 协议'

printf '\n== Challenge, revise, and reversible discussability confirmation ==\n'
python3 -m dojo challenge demo-a --text '交接检查可能成本过高，适用范围未知'
python3 -m dojo revise demo-a \
  --statement '在支持范围已知且检查成本可接受时，组件交接约定仍值得单独讨论' \
  --reason '加入成本和支持范围条件，保留旧版本'
python3 -m dojo confirm demo-a --basis '修订后值得作为讨论候选；不表示为真'
python3 -m dojo revoke demo-a --reason '演示确认撤销，不删除版本'
python3 -m dojo confirm demo-a --basis '再次确认只表示值得检索'
python3 -m dojo show demo-a --history

printf '\n== Split and preserve source IDs ==\n'
python3 -m dojo add --id demo-split --kind experience_claim \
  --statement '一次迁移报告包含两个可能独立的条件' \
  --source-json '{"id":"src-demo-split","type":"claimed_firsthand","claim":"模拟且未核验的报告","independence_group":"unknown","verification":"unverified"}'
python3 -m dojo split demo-split \
  --children-json '[{"id":"demo-child-a","statement":"路线甲在支持版本都有夹具时可讨论","source_ids":["src-demo-split"]},{"id":"demo-child-b","statement":"路线乙在部分版本不能复现时保留未知","source_ids":["src-demo-split"]}]' \
  --reason '拆开条件路线，两个子项保留同一来源 ID'
python3 -m dojo show demo-child-b

printf '\n== Explicitly confirm a merge, inspect redirect, then reversibly restore ==\n'
python3 -m dojo add --id demo-merge-a --kind abstract_idea --statement '共享交接措辞甲'
python3 -m dojo add --id demo-merge-b --kind abstract_idea --statement '共享交接措辞乙'
python3 -m dojo merge demo-merge-b demo-merge-a --confirm --reason '操作者已核对主张和适用范围可互换'
python3 -m dojo show demo-merge-b
python3 -m dojo unmerge demo-merge-b --reason '演示恢复原 ID 与各自来源'

printf '\n== Abstain is an event, not a truth label; B/C are isolated prompt exports ==\n'
python3 -m dojo abstain --id demo-a --reason '无法判断是否等价' --next-question '检查支持版本边界'
python3 -m dojo export --mode b --budget-chars 4000
python3 -m dojo export --mode c --id seed-m01 --id seed-m04 --budget-chars 6000
printf '\nFinished. All database and export files were in %s and are removed on exit.\n' "$WORK"

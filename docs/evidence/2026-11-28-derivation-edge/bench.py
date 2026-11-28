"""Where does the reading path's time go, against the same library and the baseline?

    python3 docs/evidence/2026-11-28-derivation-edge/bench.py [worktree] [baseline-worktree]

Two questions, and the second is the one that decides whether this slice costs anything:

  1. how long does one reading search take, base vs this tree, interleaved so a busy
     moment hits both;
  2. of that time, how much is the work this slice added (`derivations` +
     `derivation_index` + the per-row copy), measured directly rather than deduced from a
     wall clock.

Prints medians and per-part costs. Exit 0 always: this is a measurement, not a check. The
supervisor's numbers are in `/var/tmp/dojo-lineage-*`; this script exists so that "no
measurable cost" can be re-measured rather than believed.
"""
from __future__ import annotations

import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1
            else Path(__file__).resolve().parents[3]).resolve()
BASE = Path(sys.argv[2] if len(sys.argv) > 2 else "/var/tmp/dojo-base-33cd298")


def make_fixture(path: Path, size: int) -> None:
    sys.path.insert(0, str(ROOT))
    from dojo.storage import Store

    ledger = Store(path)
    try:
        one = ledger.add("Observe railway inspection during the quiet shift.", "abstract_idea",
                         candidate_id="sample-0000")
        with ledger.transaction():
            for offset in range(1, size):
                ledger._insert_candidate(
                    dict(one, id="sample-%04d" % offset,
                         statement=("Observe railway inspection during the quiet shift "
                                    "for platform %d." % offset)), "add", {})
        ledger.add("Evening handover checklist for the night shift.", "abstract_idea",
                   candidate_id="sample-child", derived_from="sample-0000")
    finally:
        ledger.close()


ONE_RUN = """
import sys, time
sys.path.insert(0, {root!r})
from dojo.storage import Store
path = {path!r}
t = []
for _ in range(5):
    store = Store(path, readonly=True)
    start = time.perf_counter()
    result = store.retrieve("railway", limit=10, for_reading=True)
    t.append((time.perf_counter() - start) * 1000)
    store.close()
t.sort()
print("%.2f %.2f %d" % (t[0], t[2], len(result["withheld"])))
"""


def one_run(root: Path, path: Path) -> tuple[float, float, int]:
    done = subprocess.run(
        [sys.executable, "-B", "-c", ONE_RUN.format(root=str(root), path=str(path))],
        cwd=str(root), text=True, capture_output=True, timeout=900)
    if done.returncode != 0:
        raise SystemExit("bench run failed:\n" + done.stdout[-2000:] + done.stderr[-2000:])
    low, middle, count = done.stdout.split()
    return float(low), float(middle), int(count)


def internal_costs(path: Path) -> dict[str, float]:
    sys.path.insert(0, str(ROOT))
    from dojo.storage import Store

    store = Store(str(path), readonly=True)
    try:
        store.retrieve("railway", limit=10, for_reading=True)  # warm the page cache
        out: dict[str, float] = {}
        for name, call in (
            ("derivations() 一次", lambda: store.derivations()),
            ("derivation_index(2401 个状态)", lambda: store.derivation_index(store.last_scan)),
            ("整套 retrieve(for_reading)", lambda: store.retrieve("railway", limit=10,
                                                                  for_reading=True)),
            ("整套 retrieve（给模型的那条）", lambda: store.retrieve("railway", limit=10)),
        ):
            samples = []
            for _ in range(5):
                start = time.perf_counter()
                call()
                samples.append((time.perf_counter() - start) * 1000)
            out[name] = statistics.median(samples)
        return out
    finally:
        store.close()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bench-") as directory:
        path = Path(directory) / "fixture-2400.sqlite3"
        make_fixture(path, 2400)
        print("库：" + str(path) + "（2401 张卡，一条派生边）")
        have_base = (BASE / "dojo" / "storage.py").is_file()
        if not have_base:
            print("基线树不在 " + str(BASE) + "；只量当前树。")
        base_middle: list[float] = []
        this_middle: list[float] = []
        base_low: list[float] = []
        this_low: list[float] = []
        counts: set[int] = set()
        for _ in range(3):
            if have_base:
                low, middle, count = one_run(BASE, path)
                base_low.append(low)
                base_middle.append(middle)
                counts.add(count)
            low, middle, count = one_run(ROOT, path)
            this_low.append(low)
            this_middle.append(middle)
            counts.add(count)
        print("交替 3 轮，每轮 5 次的中位数：")
        if base_middle:
            print("  基线 " + " / ".join("%.1f" % value for value in base_middle) + " ms")
        print("  现在 " + " / ".join("%.1f" % value for value in this_middle) + " ms")
        print("每轮最小值：")
        if base_low:
            print("  基线 " + " / ".join("%.1f" % value for value in base_low) + " ms")
        print("  现在 " + " / ".join("%.1f" % value for value in this_low) + " ms")
        print("两个变体查到的记录数：" + str(sorted(counts)))
        print("\n这一片新加的那几件，单独计时（当前树，中位数 5 次）：")
        for name, value in internal_costs(path).items():
            print("  %-34s %6.2f ms" % (name, value))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""docs/evaluation.md §4 的可跑检查：C 特有主张必须能追到 seed，追不到就记 untraced。

这条评估主张此前只有文字，没有任何可跑检查（tests/ 与 dojo/ 里 grep `untraced` / `source_trace`
都是 0 命中）。本文件把它变成能红的检查。

负对照（本文件的牙齿）：**措辞几乎抄自 seed 但没引 seed ID 的主张，必须判 untraced。**
一个靠字面重合度打分的检查器会把这条判成「已追溯」——那正是 §4 禁止的伪造引用。
"""
import unittest

from dojo.source_trace import TRACED, UNTRACED, audit_traces, coverage

SEEDS = {
    "seed-m01": "环境与流程的设计，往往比临时的决心更能稳住重复行为；降低启动摩擦通常比反复下决心更可持续。",
    "seed-m04": "一名模拟角色自述：靠每次只做一件小事，坚持了数月整洁，而没有依赖更强的自律。",
}
VERIFICATION = {"seed-m04": "unverified", "seed-m01": "not_evidence"}


def claim(text, **extra):
    return {"text": text, **extra}


class SourceTraceTests(unittest.TestCase):
    def test_quoted_seed_with_correct_id_is_traced(self):
        result = audit_traces(
            [claim("降低启动摩擦比反复下决心更可持续",
                   seed_id="seed-m01",
                   quote="降低启动摩擦通常比反复下决心更可持续",
                   extends=False)],
            SEEDS,
        )[0]
        self.assertEqual(TRACED, result["status"])
        self.assertEqual([], result["reasons"])

    def test_negative_control_similar_wording_without_id_is_untraced(self):
        """字面几乎抄自 seed-m01，但没给 seed ID ⇒ 必须 untraced。"""
        result = audit_traces(
            [claim("环境与流程的设计，往往比临时的决心更能稳住重复行为")],
            SEEDS,
        )[0]
        self.assertEqual(UNTRACED, result["status"])
        self.assertIn("no_seed_id", result["reasons"])

    def test_citation_to_unknown_seed_does_not_count(self):
        result = audit_traces(
            [claim("某人说的是这样", seed_id="seed-m99", quote="某人说的是这样", extends=False)],
            SEEDS,
        )[0]
        self.assertEqual(UNTRACED, result["status"])
        self.assertIn("unknown_seed_id", result["reasons"])

    def test_quote_absent_from_cited_seed_is_fabrication(self):
        result = audit_traces(
            [claim("降低难度总是更好", seed_id="seed-m01", quote="降低难度总是更好", extends=False)],
            SEEDS,
        )[0]
        self.assertEqual(UNTRACED, result["status"])
        self.assertIn("quote_not_in_seed", result["reasons"])

    def test_quote_missing_cannot_be_verified(self):
        result = audit_traces([claim("降低启动摩擦更可持续", seed_id="seed-m01", extends=False)], SEEDS)[0]
        self.assertEqual(UNTRACED, result["status"])
        self.assertIn("no_quote", result["reasons"])

    def test_undeclared_extension_beyond_seed_sentence_is_flagged(self):
        result = audit_traces(
            [claim("降低启动摩擦比反复下决心更可持续，因此所有家务必做减法",
                   seed_id="seed-m01",
                   quote="降低启动摩擦通常比反复下决心更可持续",
                   extends=False)],
            SEEDS,
        )[0]
        self.assertEqual(UNTRACED, result["status"])
        self.assertIn("undeclared_extension", result["reasons"])

    def test_declared_extension_is_traced_but_reported(self):
        result = audit_traces(
            [claim("降低启动摩擦比反复下决心更可持续，因此所有家务必做减法",
                   seed_id="seed-m01",
                   quote="降低启动摩擦通常比反复下决心更可持续",
                   extends=True)],
            SEEDS,
        )[0]
        self.assertEqual(TRACED, result["status"])
        self.assertIn("extends_seed_sentence", result["notes"])

    def test_unverified_report_keeps_its_provenance_status(self):
        """§3：引用 S04 这类未核验报告时，判定必须带出来源状态，不能被当成已证事实。"""
        result = audit_traces(
            [claim("一名模拟角色自述靠每次只做一件小事坚持了数月整洁",
                   seed_id="seed-m04",
                   quote="靠每次只做一件小事，坚持了数月整洁",
                   extends=False)],
            SEEDS,
            verification=VERIFICATION,
        )[0]
        self.assertEqual(TRACED, result["status"])
        self.assertEqual("unverified", result["verification"])

    def test_rewording_away_provenance_is_not_a_clean_restatement(self):
        """把「一名模拟角色自述」改写成「有人」= 洗掉来源性质，不能算干净改述。"""
        result = audit_traces(
            [claim("有人靠每次只做一件小事坚持了数月整洁",
                   seed_id="seed-m04",
                   quote="靠每次只做一件小事，坚持了数月整洁",
                   extends=False)],
            SEEDS,
            verification=VERIFICATION,
        )[0]
        self.assertEqual(UNTRACED, result["status"])
        self.assertIn("undeclared_extension", result["reasons"])

    def test_coverage_summary_reports_full_partial_none(self):
        traced = claim("降低启动摩擦更可持续", seed_id="seed-m01",
                       quote="降低启动摩擦通常比反复下决心更可持续", extends=False)
        bare = claim("环境设计比决心更稳")
        self.assertEqual("partial", coverage(audit_traces([traced, bare], SEEDS)))
        self.assertEqual("none", coverage(audit_traces([bare], SEEDS)))
        self.assertEqual("full", coverage(audit_traces([traced], SEEDS)))

    def test_quoting_a_seed_without_saying_it_is_an_extension_still_untraced(self):
        """引文本身合法，但主张把未核验报告当实证用 ⇒ 仍要 untraced。"""
        result = audit_traces(
            [claim("每次只做一件小事已被证明能长期保持整洁",
                   seed_id="seed-m04",
                   quote="靠每次只做一件小事，坚持了数月整洁",
                   extends=False,
                   as_verified=True)],
            SEEDS,
            verification=VERIFICATION,
        )[0]
        self.assertEqual(UNTRACED, result["status"])
        self.assertIn("unverified_report_stated_as_fact", result["reasons"])

    def test_bad_input_is_rejected(self):
        with self.assertRaises(ValueError):
            audit_traces("not a list", SEEDS)
        with self.assertRaises(ValueError):
            audit_traces([{"no_text": 1}], SEEDS)


if __name__ == "__main__":
    unittest.main()

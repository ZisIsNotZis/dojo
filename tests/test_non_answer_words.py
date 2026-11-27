"""A non-answer with a soft ending is still a non-answer.

The independent review of `1b03673` measured this at the real entry point: the exact-match
list in `elicit.py` let 不知道啊 / 说不好吧 / 忘了诶 through as answers, so a person who
gave nothing for four parts got `四件你都说了原话` -- and the same rows then travelled into
`scripts/dao_session.py`, which exported 不知道啊 as his 代价.

The rule stays whole-sentence. Only trailing modal particles are set aside, and what is
left has to be exactly one of the listed non-answers; a clause of his own keeps the reply
an answer, because the receipt's job is to keep what he said, not to grade it.

These tests also pin the other direction, which is the one that would be worse to break:
the parts that genuinely carry material must not be swallowed by the widened list.
"""
import unittest

from dojo.elicit import classify_answer


class SoftEndingsAreStillNonAnswers(unittest.TestCase):
    def test_listed_non_answers_with_a_modal_particle_are_not_answers(self):
        for phrase in ("不知道啊", "不知道呀", "说不好吧", "忘了诶", "不清楚呢",
                       "看情况吧", "因人而异啊", "没什么啦", "想不起来了吧"):
            with self.subTest(phrase=phrase):
                self.assertEqual("none", classify_answer(phrase), phrase)

    def test_a_bare_filler_is_not_an_answer(self):
        for phrase in ("嗯", "嗯嗯", "呃", "哦", "啊", "随便", "都行", "你说呢", "都差不多"):
            with self.subTest(phrase=phrase):
                self.assertEqual("none", classify_answer(phrase), phrase)

    def test_punctuation_does_not_hide_a_non_answer(self):
        for phrase in ("不知道。", "不知道……", "忘了！", "说不好，", " 不知道 "):
            with self.subTest(phrase=phrase):
                self.assertEqual("none", classify_answer(phrase), phrase)

    def test_a_clause_of_his_own_stays_an_answer(self):
        for phrase in ("具体动作我不知道", "我没有别的意思，只是觉得通知得做",
                       "不是不知道，是不想说", "嗯，那天我在修数据库，修到一半卡住了",
                       "看情况，团队小的时候我会跳过复核",
                       "我跳过这一步的时候就会出错",
                       "没有通知就没人知道系统跑完了"):
            with self.subTest(phrase=phrase):
                self.assertEqual("answer", classify_answer(phrase), phrase)

    def test_a_prefix_that_changes_who_is_speaking_is_not_peeled(self):
        """「都说不清楚」 is about everybody, not about him.

        The review measured this: peeling 都 turned a statement about other people into
        「我没什么可说」. An unreadable subject now stays material, which is the safe
        direction -- material is kept, and a wrong "nothing to say" is not recoverable.
        """
        for phrase in ("都说不清楚", "都忘了", "大家都忘了", "他们都不知道", "没人知道"):
            with self.subTest(phrase=phrase):
                self.assertEqual("answer", classify_answer(phrase), phrase)

    def test_the_ordinary_ways_of_saying_i_dont_know(self):
        """The review measured eleven of these at the entry point; all came back answers.

        `我不知道` is `不知道` with a subject in front -- more ordinary than the
        particle-ending forms the last fix covered -- and the receipt said
        四件你都说了原话 about four of them, while `dao_session.py` wrote them into
        note.md as his words.
        """
        for phrase in ("我不知道", "我也不清楚", "我不太清楚", "我忘了", "我记不清了",
                       "我也说不好", "不太清楚", "说不清楚", "记不清了", "没印象",
                       "说不上来", "我不确定", "我拿不准", "我真的不知道", "我有点不清楚",
                       "我一点都不清楚", "我一点也不确定", "我没有", "我没什么", "都行",
                       "我不记得", "我想不出"):
            with self.subTest(phrase=phrase):
                self.assertEqual("none", classify_answer(phrase), phrase)

    def test_the_subject_and_softener_peel_does_not_reach_a_clause(self):
        """One comma and a clause of his own, and it is material again."""
        for phrase in ("我不太清楚别人会怎么做，但上次是我自己盯的",
                       "我不知道他会不会来看回执",
                       "我忘了通知，所以那天没人知道系统跑完了",
                       "我没印象有谁复核过，反正后来是我不放心才翻的日志",
                       "没有通知就没人知道", "我没有别的意思", "没有再复核系统",
                       "我没有看"):
            with self.subTest(phrase=phrase):
                self.assertEqual("answer", classify_answer(phrase), phrase)

    def test_the_listed_plain_forms_still_work(self):
        for phrase in ("不知道", "看情况", "因人而异", "忘了"):
            with self.subTest(phrase=phrase):
                self.assertEqual("none", classify_answer(phrase), phrase)


if __name__ == "__main__":
    unittest.main()

"""大轮最终结算横幅清除的离线检查。

横幅与大厅同屏时大厅标志仍可见，必须先清除横幅再判定回大厅，
否则会误判「已回大厅」而在结算未完成时推进新大轮。
本检查同时守住点击上限：清除失败时不得无限点击（会触发 GameTooManyClickError）。
"""
import unittest
from unittest.mock import Mock, patch
from tasks.DraftDuel.script_task import ScriptTask

BANNER = ScriptTask.I_DRAFT_FINAL_BANNER


class FinalBannerTests(unittest.TestCase):
    def make_owner(self, banner_present):
        """banner_present: 依次每次横幅判定的结果序列（耗尽后沿用最后一个）。"""
        owner = object.__new__(ScriptTask)
        owner.device = Mock()
        owner.click = Mock()
        owner.screenshot = Mock()
        seq = list(banner_present)
        state = {'i': 0}

        def fake_appear(rule):
            if rule is BANNER:
                idx = min(state['i'], len(seq) - 1)
                state['i'] += 1
                return seq[idx]
            return False

        owner.appear = Mock(side_effect=fake_appear)
        return owner, state

    def run_clear(self, owner, wait=12.0, timeout=30.0, max_clicks=3, step=5):
        """按固定步长推进单调时钟，模拟时间流逝。"""
        clock = [0]

        def fake_monotonic():
            clock[0] += step
            return clock[0]

        with patch('tasks.DraftDuel.runtime.battle.time.monotonic', side_effect=fake_monotonic), \
                patch('tasks.DraftDuel.runtime.battle.time.sleep'):
            return owner._clear_final_banner(wait=wait, timeout=timeout, max_clicks=max_clicks)

    def test_banner_disappears_returns_true_without_click(self):
        """横幅在等待窗口内自行消失：直接返回 True，不应产生任何点击。"""
        owner, _ = self.make_owner([True, False])
        self.assertTrue(self.run_clear(owner))
        self.assertEqual(owner.click.call_count, 0, '过场自行消失时不应点击')

    def test_persistent_banner_respects_click_limit(self):
        """横幅持续存在：点击受 max_clicks 限制，超时返回 False（严禁狂点）。"""
        owner, _ = self.make_owner([True])
        result = self.run_clear(owner, max_clicks=3)
        self.assertFalse(result, '横幅未清除应返回 False')
        self.assertLessEqual(owner.click.call_count, 3, '点击次数必须受 max_clicks 限制')

    def test_persistent_banner_does_not_exceed_limit(self):
        """即使放宽超时，点击次数也不得超过 max_clicks。"""
        owner, _ = self.make_owner([True])
        self.run_clear(owner, timeout=200.0, max_clicks=2)
        self.assertLessEqual(owner.click.call_count, 2, '放宽超时后点击次数仍不得超过上限')


if __name__ == '__main__':
    unittest.main()

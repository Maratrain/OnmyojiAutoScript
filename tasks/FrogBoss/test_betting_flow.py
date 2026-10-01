import unittest
from unittest.mock import patch

from module.exception import GameStuckError
from tasks.FrogBoss.script_task import ScriptTask


class FrameTimer:
    """用帧数模拟超时，不休眠、不依赖设备"""

    def __init__(self, *_args):
        self.frames = 0

    def start(self):
        return self

    def reached(self):
        self.frames += 1
        return self.frames > 12


class BettingTask(ScriptTask):
    def __init__(self, frames):
        self.frames = iter(frames)
        self.visible = set()
        self.clicks = []

    def screenshot(self):
        self.visible = next(self.frames, self.visible)

    def appear(self, rule):
        return rule.name in self.visible

    def click(self, rule, interval=None):
        self.clicks.append(rule)
        return True

    def appear_then_click(self, rule, interval=None):
        if not self.appear(rule):
            return False
        return self.click(rule, interval=interval)


@patch('tasks.FrogBoss.script_task.Timer', FrameTimer)
class BettingFlowTests(unittest.TestCase):
    def test_reward_overlay_and_confirmation_hide_clickable_background(self):
        """弹窗与确认框出现时必须优先处理，点击顺序不得越过它们落在后方按钮上"""
        panel = {ScriptTask.I_GOLD_30.name, ScriptTask.I_BET_SURE.name}
        task = BettingTask([
            panel | {ScriptTask.I_GOLD_30_CHECK.name},
            panel,
            panel,
            panel | {ScriptTask.I_UI_CONFIRM.name},
            {ScriptTask.I_BETTED.name},
        ])
        self.assertTrue(task.confirm_bet())
        self.assertEqual([rule.name for rule in task.clicks], [
            ScriptTask.C_RANDOM_LEFT.name,
            'FB_GOLD_30_SELECT',
            ScriptTask.I_BET_SURE.name,
            ScriptTask.I_UI_CONFIRM.name,
        ])
        selection = task.clicks[1]
        x, y, width, height = ScriptTask.I_GOLD_30.roi_front
        sx, sy, sw, sh = selection.roi_front
        self.assertGreaterEqual(sx, x)
        self.assertLessEqual(sx + sw, x + width)
        self.assertGreaterEqual(sy, y)
        self.assertLess(sy + sh, y + height // 2)

    def test_cannot_submit_before_selecting_amount(self):
        """金额档未选中时禁止提交，超时报错信息应含选档状态"""
        task = BettingTask([{ScriptTask.I_BET_SURE.name}])
        with self.assertRaisesRegex(GameStuckError, 'gold_selected=False'):
            task.confirm_bet()
        self.assertEqual(task.clicks, [])

    def test_no_response_limits_submit_retries_without_reselecting_amount(self):
        """无响应时提交最多 3 次，且不得回落重复点金额档"""
        panel = {ScriptTask.I_GOLD_30.name, ScriptTask.I_BET_SURE.name}
        task = BettingTask([panel])
        with self.assertRaisesRegex(GameStuckError, 'submit_attempts=3'):
            task.confirm_bet()
        self.assertEqual([rule.name for rule in task.clicks], [
            'FB_GOLD_30_SELECT',
            ScriptTask.I_BET_SURE.name,
            ScriptTask.I_BET_SURE.name,
            ScriptTask.I_BET_SURE.name,
        ])

    def test_already_betted_and_rest_end_without_clicking(self):
        """已下注或对局进入休息时直接返回，不产生任何点击"""
        for marker, expected in ((ScriptTask.I_BETTED, True), (ScriptTask.I_FROG_BOSS_REST, False)):
            with self.subTest(marker=marker.name):
                task = BettingTask([{marker.name}])
                self.assertEqual(task.confirm_bet(), expected)
                self.assertEqual(task.clicks, [])


if __name__ == '__main__':
    unittest.main()

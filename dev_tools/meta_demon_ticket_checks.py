"""超鬼王门票刷取（独立任务）：配置、旧配置迁移、满票判定与协同。"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tasks.MetaDemonTicket.config import (
    ExplorationTarget, MetaDemonTicket, TicketMode, split_legacy_meta_demon,
)
from tasks.MetaDemonTicket.ticket_farming import (
    AwakeTicketTask, TicketPartnerFinished, TicketRewardMixin, TicketsFull,
    metademon_tickets_full, run_ticket_farming, ticket_farming_config,
    tickets_full_before_farming,
)
from tasks.Exploration.config import AutoRotate, UpType, UserStatus as ExplorationUserStatus
from tasks.EvoZone.config import KirinType, Layer
from tasks.MetaDemon.assets import MetaDemonAssets
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import BattleAction
from tasks.GameUi.page import page_battle, page_battle_prepare, page_battle_result, page_reward
from module.exception import GamePageUnknownError


class TicketConfigChecks(unittest.TestCase):
    def test_defaults_and_single_mode(self):
        conf = MetaDemonTicket()
        self.assertEqual(conf.general_config.mode, TicketMode.AWAKE)
        self.assertEqual(conf.general_config.user_status, ExplorationUserStatus.ALONE)
        self.assertEqual(conf.general_config.awake_layer, Layer.SEVEN)
        self.assertEqual(conf.general_config.awake_kirin_type, KirinType.LIGHTNINGKIRIN)
        self.assertEqual(conf.general_config.exploration_target, ExplorationTarget.ALL)
        self.assertFalse(conf.scheduler.enable)
        self.assertEqual(conf.general_config.limit_time_v.total_seconds(), 45 * 60)

    def test_legacy_meta_demon_tickets_migrate_into_the_task(self):
        legacy = {
            'meta_demon': {
                'scheduler': {'enable': True, 'next_run': '2026-01-01 00:00:00', 'wait_interval': '00 01:40:00'},
                'meta_demon_config': {'mode': ['门票刷取：探索绘卷', '鬼王战斗'], 'limit_time': '01:00:00'},
                'general_config': {'exploration_rotate': True, 'awake_buff_enable': True},
                'switch_soul_config': {'ticket_farming_enable': True, 'ticket_farming_group_team': '2,3',
                                       'ticket_farming_by_name': False, 'ticket_farming_group_team_name': ''},
                'ticket_farming_battle_conf': {'preset_enable': True, 'preset_group': 3},
            }
        }
        data = split_legacy_meta_demon(legacy)
        ticket = data['meta_demon_ticket']
        self.assertEqual(ticket['general_config']['mode'], '门票刷取：探索')
        self.assertEqual(ticket['general_config']['limit_time'], '01:00:00')
        self.assertTrue(ticket['general_config']['exploration_rotate'])
        self.assertTrue(ticket['general_config']['awake_buff_enable'])
        self.assertTrue(ticket['scheduler']['enable'])
        self.assertNotIn('wait_interval', ticket['scheduler'])
        self.assertEqual(ticket['switch_soul_config']['switch_group_team'], '2,3')
        self.assertTrue(ticket['switch_soul_config']['enable'])
        self.assertEqual(ticket['general_battle_config']['preset_group'], 3)
        # 刷票模式从超鬼王里被摘掉，其它设置保留。
        self.assertEqual(data['meta_demon']['meta_demon_config']['mode'], ['鬼王战斗'])
        # 迁移结果必须能被新模型直接加载。
        conf = MetaDemonTicket.model_validate(ticket)
        self.assertEqual(conf.general_config.mode, TicketMode.EXPLORATION)

    def test_legacy_without_ticket_settings_is_untouched(self):
        legacy = {'meta_demon': {'meta_demon_config': {'mode': ['鬼王战斗']}}}
        self.assertIs(split_legacy_meta_demon(legacy), legacy)

    def test_ticket_only_config_disables_meta_demon_scheduler(self):
        legacy = {'meta_demon': {'scheduler': {'enable': True},
                                 'meta_demon_config': {'mode': ['门票刷取：觉醒七层']}}}
        data = split_legacy_meta_demon(legacy)
        self.assertFalse(data['meta_demon']['scheduler']['enable'])
        self.assertEqual(data['meta_demon']['meta_demon_config']['mode'], ['鬼王战斗'])
        self.assertEqual(data['meta_demon_ticket']['general_config']['mode'], '门票刷取：觉醒')


class TicketFarmingChecks(unittest.TestCase):
    def meta(self, **general):
        return MetaDemonTicket(general_config={
            'mode': '门票刷取：觉醒', 'user_status': 'alone', **general})

    def test_awake_config_maps_to_evozone_with_invite(self):
        meta = self.meta(awake_layer=Layer.NINE.value, awake_kirin_type=KirinType.WATERKIRIN.value,
                         awake_buff_enable=True, exploration_rotate=False)
        task = ticket_farming_config(meta, TicketMode.AWAKE)
        self.assertEqual(task.evo_zone_config.layer, Layer.NINE)
        self.assertEqual(task.evo_zone_config.kirin_type, KirinType.WATERKIRIN)
        self.assertTrue(task.evo_zone_config.soul_buff_enable)
        self.assertEqual(task.evo_zone_config.limit_count, 2 ** 31 - 1)
        self.assertIs(task.invite_config, meta.invite_config)
        self.assertEqual(task.switch_soul_config.model_dump(), meta.switch_soul_config.model_dump())

    def test_exploration_config_maps_targets_and_disables_team_lock(self):
        meta = self.meta(mode='门票刷取：探索', exploration_target='金币', exploration_rotate=True,
                         general_battle_config={'lock_team_enable': True})
        task = ticket_farming_config(meta, TicketMode.EXPLORATION)
        self.assertEqual(task.exploration_config.up_type, UpType.COIN)
        self.assertEqual(task.exploration_config.auto_rotate, AutoRotate.yes)
        self.assertFalse(task.general_battle_config.lock_team_enable)
        self.assertIs(task.invite_config, meta.invite_config)

    def test_ticket_ocr_is_skipped_without_red_daruma_reward(self):
        owner = SimpleNamespace(appear=Mock(return_value=False), device=SimpleNamespace(image=object()))
        with patch.object(GeneralBattleAssets.O_METADEMON_PASS, 'ocr_digit_counter') as ocr:
            self.assertFalse(metademon_tickets_full(owner))
        ocr.assert_not_called()

    def test_ticket_counter_requires_valid_numerator_and_total(self):
        # 计数越界（112/50 这类误读）必须当作识别错误，不能判定门票已满。
        cases = {
            (1000, 0, 1000): True,    # 正好满票
            (999, 1, 1000): False,    # 未满
            (1001, -1, 1000): False,  # 超过上限 = 误读
            (112, -62, 50): False,    # 真实案例：112/50 误读
            (-1, 0, 0): False,        # 未识别
        }
        for values, expected in cases.items():
            with self.subTest(values=values):
                owner = SimpleNamespace(appear=Mock(return_value=True), device=SimpleNamespace(image=object()))
                with patch.object(GeneralBattleAssets.O_METADEMON_PASS, 'ocr_digit_counter',
                                  return_value=values):
                    self.assertEqual(metademon_tickets_full(owner), expected)

    def test_precheck_retries_invalid_counter_and_rejects_wrong_page(self):
        owner = SimpleNamespace(goto_page=Mock(), screenshot=Mock(), appear=Mock(return_value=True),
                                device=SimpleNamespace(image=object()))
        with patch.object(MetaDemonAssets.O_METADEMON_PASS_EXP, 'ocr_digit_counter',
                          side_effect=[(0, 0, 0), (-1, 51, 50), (49, 1, 50)]) as ocr:
            self.assertFalse(tickets_full_before_farming(owner))
            self.assertEqual(ocr.call_count, 3)
        owner.appear.return_value = False
        with patch.object(MetaDemonAssets.O_METADEMON_PASS_EXP, 'ocr_digit_counter') as ocr:
            self.assertFalse(tickets_full_before_farming(owner))
            ocr.assert_not_called()

    def _owner(self, mode='门票刷取：觉醒', **general):
        meta = MetaDemonTicket(general_config={'mode': mode, **general})
        return SimpleNamespace(config=SimpleNamespace(meta_demon_ticket=meta, cooperation_runtime=None),
                               device=SimpleNamespace(image=object()), goto_page=Mock(), screenshot=Mock(),
                               appear=Mock(return_value=True))

    def test_full_tickets_skip_before_starting_runner(self):
        owner = self._owner()
        with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming', return_value=True), \
             patch('tasks.MetaDemonTicket.ticket_farming.AwakeTicketTask') as runner:
            self.assertTrue(run_ticket_farming(owner, TicketMode.AWAKE))
        runner.assert_not_called()

    def test_full_tickets_interrupt_runner_and_report_success(self):
        owner = self._owner()
        runner = Mock()
        runner.run_alone.side_effect = TicketsFull
        with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming', return_value=False), \
             patch('tasks.MetaDemonTicket.ticket_farming.AwakeTicketTask', return_value=runner):
            self.assertTrue(run_ticket_farming(owner, TicketMode.AWAKE))
        runner.install_ticket_reward_hook.assert_called_once()
        self.assertTrue(runner._ticket_farming_complete)

    def test_partner_finished_ends_the_run_without_success(self):
        owner = self._owner()
        runner = Mock()
        runner.exec_exp_page.side_effect = TicketPartnerFinished
        with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming', return_value=False), \
             patch('tasks.MetaDemonTicket.ticket_farming.ExplorationTicketTask', return_value=runner):
            self.assertFalse(run_ticket_farming(owner, TicketMode.EXPLORATION))
        self.assertTrue(runner._ticket_farming_complete)

    def test_mismatched_cooperation_pair_is_skipped(self):
        runtime = Mock()
        runtime.peers = {}
        runtime.matches_meta_demon_tickets.return_value = False
        meta = MetaDemonTicket(general_config={'mode': '门票刷取：觉醒', 'user_status': 'leader'},
                               invite_config={'cooperation_script': 'peer'})
        owner = SimpleNamespace(config=SimpleNamespace(meta_demon_ticket=meta, cooperation_runtime=runtime),
                                device=SimpleNamespace(image=object()), goto_page=Mock(), screenshot=Mock(),
                                appear=Mock(return_value=True))
        with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming') as precheck:
            self.assertFalse(run_ticket_farming(owner, TicketMode.AWAKE))
        precheck.assert_not_called()

    def test_leader_and_member_use_invite_flows(self):
        for role, method in (('leader', 'run_leader'), ('member', 'run_member'), ('alone', 'run_alone')):
            with self.subTest(role=role):
                owner = self._owner(mode='门票刷取：觉醒', user_status=role)
                runner = Mock()
                with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming', return_value=False), \
                     patch('tasks.MetaDemonTicket.ticket_farming.AwakeTicketTask', return_value=runner):
                    self.assertFalse(run_ticket_farming(owner, TicketMode.AWAKE))
                getattr(runner, method).assert_called_once()


class _ScreenshotBase:
    """只提供截图计数，避免拉起真实设备。"""

    def __init__(self):
        self.shots = 0

    def screenshot(self):
        self.shots += 1
        return self.shots


class _TicketRunner(TicketRewardMixin, _ScreenshotBase):
    pass


class TicketRewardExitChecks(unittest.TestCase):
    def runner(self, complete=True, outside_battle=True, peer=''):
        runner = _TicketRunner()
        runner.reward_visible = False
        runner._ticket_farming_complete = complete
        runner._battle_context = None if outside_battle else object()
        runner._ticket_peer = peer
        runner._ticket_full = False
        runner._ticket_phase_started = 0
        runtime = Mock()
        runtime.peer_task_completion.return_value = None
        runner.config = SimpleNamespace(cooperation_runtime=runtime)
        runner.match_page_once = Mock(side_effect=lambda page: runner.reward_visible)
        runner.appear_then_click = Mock(return_value=False)
        runner.click = Mock()
        runner.check_ticket_reward = Mock()
        return runner

    def test_complete_runner_closes_orphan_reward(self):
        runner = self.runner(complete=True)
        runner.reward_visible = True

        def click(*args, **kwargs):
            if runner.click.call_count == 2:
                runner.reward_visible = False

        runner.click.side_effect = click
        self.assertEqual(runner.screenshot(), 3)
        self.assertEqual(runner.click.call_count, 2)
        runner.check_ticket_reward.assert_not_called()

    def test_active_farming_leaves_reward_handling_to_battle_loop(self):
        runner = self.runner(complete=False, outside_battle=False, peer='peer')
        runner.reward_visible = True
        self.assertEqual(runner.screenshot(), 1)
        runner.click.assert_not_called()
        runner.match_page_once.assert_not_called()
        runner.config.cooperation_runtime.peer_task_completion.assert_not_called()

    def test_outer_wait_closes_orphan_reward_after_reading_tickets(self):
        runner = self.runner(complete=False, peer='peer')
        runner.reward_visible = True
        order = []
        runner.check_ticket_reward.side_effect = lambda: order.append('read_tickets')

        def click(*args, **kwargs):
            order.append('click')
            if runner.click.call_count == 2:
                runner.reward_visible = False

        runner.click.side_effect = click
        self.assertEqual(runner.screenshot(), 3)
        self.assertEqual(order, ['read_tickets', 'click', 'read_tickets', 'click'])
        self.assertEqual(runner.config.cooperation_runtime.peer_task_completion.call_count, 3)

    def test_orphan_reward_stops_at_full_tickets_before_clicking(self):
        runner = self.runner(complete=False)
        runner.reward_visible = True
        runner.check_ticket_reward.side_effect = TicketsFull
        with self.assertRaises(TicketsFull):
            runner.screenshot()
        runner.click.assert_not_called()

    def test_partner_finished_is_polled_while_closing_reward(self):
        runner = self.runner(complete=False, peer='peer')
        runner.reward_visible = True
        runner.config.cooperation_runtime.peer_task_completion.side_effect = [None, 'ticket_finished']
        with self.assertRaises(TicketPartnerFinished):
            runner.screenshot()
        runner.click.assert_called_once()

    def test_stuck_reward_exit_has_a_bounded_retry(self):
        runner = self.runner(complete=True)
        runner.reward_visible = True
        with patch('tasks.MetaDemonTicket.ticket_farming.time.monotonic', side_effect=[0, 31]):
            with self.assertRaises(GamePageUnknownError):
                runner.screenshot()
        runner.click.assert_not_called()

    def test_awake_exit_marker_waits_for_settlement(self):
        runner = object.__new__(AwakeTicketTask)
        runner._evaluate_exit_matcher = Mock(return_value=True)
        for last_page in (None, page_battle_prepare, page_battle):
            with self.subTest(last_page=last_page):
                context = SimpleNamespace(last_page=last_page, reward_no_battle_ts=None, is_win=False)
                self.assertEqual(
                    runner._handle_missing_battle_page(context, GeneralBattleConfig(), object()),
                    BattleAction.CONTINUE)
        runner._evaluate_exit_matcher.assert_not_called()

    def test_awake_exit_marker_preserves_settled_win_and_loss(self):
        runner = object.__new__(AwakeTicketTask)
        runner._evaluate_exit_matcher = Mock(return_value=True)
        for last_page in (page_battle_result, page_reward):
            for is_win, expected in ((True, BattleAction.EXIT_WIN), (False, BattleAction.EXIT_LOSE)):
                with self.subTest(last_page=last_page, is_win=is_win):
                    context = SimpleNamespace(last_page=last_page, reward_no_battle_ts=None, is_win=is_win)
                    self.assertEqual(
                        runner._handle_missing_battle_page(context, GeneralBattleConfig(), object()),
                        expected)

    def test_final_reward_cleanup_runs_before_return_navigation_for_every_role(self):
        for role, method in (('leader', 'run_leader'), ('member', 'run_member'), ('alone', 'run_alone')):
            with self.subTest(role=role):
                settings = MetaDemonTicket(general_config={'user_status': role})
                owner = SimpleNamespace(
                    config=SimpleNamespace(meta_demon_ticket=settings, cooperation_runtime=None),
                    device=SimpleNamespace())
                runner = Mock()
                runner._config = ticket_farming_config(settings, TicketMode.AWAKE)
                getattr(runner, method).side_effect = TicketsFull
                order = []

                def screenshot():
                    self.assertTrue(runner._ticket_farming_complete)
                    order.append('reward_cleanup')

                runner.screenshot.side_effect = screenshot
                runner.goto_page.side_effect = lambda *args, **kwargs: order.append('return_main')
                with patch('tasks.MetaDemonTicket.ticket_farming.tickets_full_before_farming', return_value=False), \
                        patch('tasks.MetaDemonTicket.ticket_farming.AwakeTicketTask', return_value=runner):
                    self.assertTrue(run_ticket_farming(owner, TicketMode.AWAKE))
                self.assertEqual(order, ['reward_cleanup'] + (['return_main'] if role != 'alone' else []))

    def test_awake_short_battle_can_go_directly_to_reward(self):
        runner = object.__new__(AwakeTicketTask)
        runner.config = SimpleNamespace(
            meta_demon_ticket=MetaDemonTicket(general_config={'user_status': 'alone'}))
        runner.device = Mock()
        runner.current_count = 0
        runner._custom_pages_registered = True
        runner._battle_shared_state = {}
        runner.screenshot = Mock()
        runner.appear = Mock(return_value=False)
        runner.appear_then_click = Mock(return_value=False)
        runner.click = Mock()
        runner.check_ticket_reward = Mock()
        runner._evaluate_exit_matcher = Mock(return_value=True)
        with patch('tasks.Component.GeneralBattle.general_battle.GameUi.detect_page_in',
                   side_effect=[None, page_reward, None]):
            self.assertTrue(runner.run_general_battle(exit_matcher=object()))
        self.assertEqual(runner.screenshot.call_count, 3)
        runner.check_ticket_reward.assert_called_once()
        runner._evaluate_exit_matcher.assert_called_once()
        self.assertIsNone(runner._battle_context)


if __name__ == '__main__':
    unittest.main()

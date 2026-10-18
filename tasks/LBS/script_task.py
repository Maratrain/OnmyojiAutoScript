# This Python file uses the following encoding: utf-8
import random
from datetime import timedelta
from time import sleep

from module.base.timer import Timer
from module.exception import TaskEnd, GamePageUnknownError
from module.logger import logger

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.GeneralInvite.config_invite import InviteConfig
from tasks.Component.GeneralInvite.general_invite import GeneralInvite, RoomType
from tasks.Component.GeneralRoom.general_room import GeneralRoom
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_shikigami_records
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.LBS.assets import LBSAssets
from tasks.LBS.config import LBSMode
from tasks.LBS.page import page_lbs


class ScriptTask(GameUi, GeneralBattle, GeneralRoom, GeneralInvite, SwitchSoul, LBSAssets):

    def _exit_matcher(self):
        # 战斗结束的标志：回到活动界面（组队挑战按钮重新可见）
        return self.I_LBS_TEAM_CHALLENGE

    def _handle_result(self, context, config):
        # 活动的奖励转换确认弹窗，出现在结算界面
        self.appear_then_click(self.I_LBS_SETTLE_CONFIRM, interval=0.8)
        return super()._handle_result(context, config)

    def _handle_reward(self, context, config):
        self.appear_then_click(self.I_LBS_SETTLE_CONFIRM, interval=0.8)
        return super()._handle_reward(context, config)

    def run(self):
        limit = self.config.lbs.lbs_config.limit_time
        limit = timedelta(hours=limit.hour, minutes=limit.minute, seconds=limit.second)
        timeout = Timer(limit.total_seconds()).start()
        limit_count = self.config.lbs.lbs_config.lbs_limit_count

        if self.config.lbs.switch_soul.enable:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul(self.config.lbs.switch_soul.switch_group_team)
        if self.config.lbs.switch_soul.enable_switch_by_name:
            self.goto_page(page_shikigami_records)
            self.run_switch_soul_by_name(self.config.lbs.switch_soul.group_name,
                                         self.config.lbs.switch_soul.team_name)

        # 导航直达活动：庭院右栏入口、轮播切换、加载等待全在 main->lbs 边上
        self.goto_page(page_lbs)

        mode = self.config.lbs.lbs_config.lbs_mode
        if mode == LBSMode.TEAM:
            self._run_team_match(timeout, limit_count)
        elif mode == LBSMode.DRIVE:
            self._run_drive_mode(timeout, limit_count)
        else:
            self._run_solo(timeout, limit_count)

        self.goto_page(page_main)
        self.set_next_run(task='LBS', success=True)
        raise TaskEnd('LBS')

    def _reach_exit(self, limit_count: int) -> bool:
        """三种模式共用的循环退出判断：想打次数达到 或 活动剩余次数耗尽。"""
        self.screenshot()
        # 界面显示的是「剩余次数/总次数」，0/40 才是打完；DigitCounter 只按文本顺序返回
        # (第一个数字, 总数-第一个数字, 总数)，故解包为 (剩余, 已用, 总数)，不能拿第二项判耗尽
        remain, used, total = self.O_LBS_COUNT.ocr(self.device.image)
        if total > 0 and remain <= 0:
            logger.info(f'[LBS鬼王] 挑战次数已用完: 剩余 {remain}/{total}')
            return True
        if total == 0:
            logger.warning('[LBS鬼王] 挑战次数识别失败，按时间限制继续')
        if self.current_count >= limit_count:
            logger.info(f'[LBS鬼王] 达到设定次数: {self.current_count}/{limit_count}')
            return True
        return False

    def _wait_created_room(self):
        """创建确认后等待房间渲染完成，过渡帧内 is_in_room 为 False，超时抛页面异常。"""
        timer = Timer(10).start()
        while not timer.reached():
            if self.is_in_room():
                return
        raise GamePageUnknownError('LBS鬼王 等待房间加载超时')

    def _run_solo(self, timeout: Timer, limit_count: int):
        """单人模式：创建不公开房间直接挑战。"""
        fail_count = 0
        while not timeout.reached():
            if self._reach_exit(limit_count):
                break
            if not self.appear(self.I_GI_IN_ROOM):
                # 点组队挑战直到权限弹窗出现（弹窗里有创建按钮）；
                # 3 次点击无反应=次数实际耗尽（OCR 失败/误读的兜底）
                if not self.create_room(create_room_rule=self.I_LBS_TEAM_CHALLENGE,
                                        ensure_rules=[self.I_LBS_CREATE_ENSURE]):
                    fail_count += 1
                    if fail_count >= 3:
                        logger.warning('[LBS鬼王] 连续 3 次创建房间失败，放弃')
                        break
                    continue
                if not self.ensure_private(room_mark=self.I_GI_IN_ROOM,
                                           private_rules=[self.I_LBS_ENSURE_PRIVATE],
                                           private_false_rules=[self.I_LBS_ENSURE_PRIVATE_FALSE]):
                    raise GamePageUnknownError('LBS鬼王 不公开权限设置失败')
                if not self.create_ensure(ensure_rules=[self.I_LBS_CREATE_ENSURE]):
                    raise GamePageUnknownError('LBS鬼王 房间创建失败')
                self._wait_created_room()
            fail_count = 0
            if timeout.reached():
                if not self.exit_room():
                    raise GamePageUnknownError('LBS鬼王 已达时间限制但退出房间失败')
                break
            self.click_fire()
            self.run_general_battle(config=self.config.lbs.general_battle_config)

    def _run_team_match(self, timeout: Timer, limit_count: int):
        """组队模式：寻找队伍→自动匹配→等进房开战（年兽流程）。"""
        battle_config = self.config.lbs.general_battle_config
        match_fail = 0
        while not timeout.reached():
            if self._reach_exit(limit_count):
                break
            if self.appear(self.I_LBS_MATCH_CANCEL):
                # 排队横幅的X还在 = 还在排队：等进房开战
                if self._wait_team_battle(battle_config, timeout):
                    match_fail = 0
                continue
            # 未排队：寻找队伍进组队界面，点自动匹配直到排队横幅出现
            if self._start_team_match():
                match_fail = 0
            else:
                match_fail += 1
                if match_fail >= 3:
                    logger.warning('[LBS鬼王] 连续 3 次组队匹配失败，放弃')
                    break

    def _start_team_match(self) -> bool:
        if not self.ui_click_until_appear_or_timeout(
                self.I_LBS_FIND_TEAM, self.I_GR_AUTO_MATCH, interval=2, timeout=15):
            logger.warning('[LBS鬼王] 未进入组队界面')
            return False
        # 中间可能有消耗确认弹窗
        timer = Timer(15).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_LBS_MATCH_CANCEL):
                return True
            if self.appear_then_click(GlobalGameAssets.I_UI_CONFIRM, interval=2):
                continue
            if self.appear_then_click(self.I_GR_AUTO_MATCH, interval=3):
                continue
        logger.warning('[LBS鬼王] 自动匹配未开始')
        return False

    def _run_drive_mode(self, timeout: Timer, limit_count: int):
        """开车模式：自己不打，纯开公开房等人，有人进来随机延迟后退房，继续开。"""
        # LBS 是三人房（房主+2），手动指定 room_type，绕开过渡帧识别出 None 被缓存的问题
        self.room_type = RoomType.NORMAL_3
        # len=1 → 盯左槽 I_ADD_1：第一人上车就退（名字不参与匹配，仅占位凑长度）
        invite_config = InviteConfig(friend_list='drive')
        drives = 0
        fail_count = 0
        while not timeout.reached():
            if drives >= limit_count:
                logger.info(f'[LBS鬼王] 达到开车次数: {drives}/{limit_count}')
                break
            if not self.is_in_room():
                # 建公开房：点未勾选的「所有人」单选项，直到「所有人」呈勾选态
                if not self.create_room(create_room_rule=self.I_LBS_TEAM_CHALLENGE,
                                        ensure_rules=[self.I_LBS_CREATE_ENSURE]):
                    fail_count += 1
                    if fail_count >= 3:
                        logger.warning('[LBS鬼王] 连续 3 次创建房间失败，放弃')
                        break
                    continue
                if not self.ensure_public(room_mark=self.I_GI_IN_ROOM,
                                          public_rules=[self.I_LBS_ENSURE_PUBLIC],
                                          public_false_rules=[self.I_LBS_ENSURE_PUBLIC_FALSE]):
                    raise GamePageUnknownError('LBS鬼王 公开权限设置失败')
                if not self.create_ensure(ensure_rules=[self.I_LBS_CREATE_ENSURE]):
                    raise GamePageUnknownError('LBS鬼王 房间创建失败')
                # 等进房渲染完成：创建确认后的过渡帧 is_in_room 为 False，
                # 立刻回外层会在房内重复点组队挑战（无效），干到 30s 倒计时自动开战
                self._wait_created_room()
            fail_count = 0
            # 房内等乘客：通用 room_check_can_fire 判定（三人房第一人上车 = 左槽「+」消失）
            while 1:
                if timeout.reached():
                    if not self.exit_room():
                        raise GamePageUnknownError('LBS鬼王 已达时间限制但退出房间失败')
                    return
                if not self.is_in_room():
                    # 房间没了（倒计时自动开战/解散），回外层重建；
                    # 解散瞬间可能已直接进战斗，确认到了战斗界面就接管
                    if self.is_in_battle():
                        self.run_general_battle(config=self.config.lbs.general_battle_config)
                    break
                if self.room_check_can_fire(invite_config):
                    # 有人上车：随机延迟后退房，算开了一趟
                    sleep(random.uniform(1, 3))
                    if not self.exit_room():
                        raise GamePageUnknownError('LBS鬼王 开车退房失败')
                    drives += 1
                    logger.info(f'[LBS鬼王] 开车进度: {drives}/{limit_count}')
                    break

    def _wait_team_battle(self, battle_config: GeneralBattleConfig, timeout: Timer) -> bool:
        """排队等待：进房等房主开战（房主跑了自己变房主点挑战）。战斗开始返回True。

        准备按钮在房主点挑战、进入战斗后才出现，由 run_general_battle 自己点
        （_prepare_click_ready），房内等待阶段不需要也不存在准备操作。
        """
        self.device.stuck_record_add('LOGIN_CHECK')
        match_timer = Timer(480).start()
        battled = False
        blank = 0
        while 1:
            self.screenshot()
            # 被秒开直接进战斗（check_take_over_battle 是待删旧入口，内联等价逻辑）
            if self.is_in_battle(False):
                logger.info('[LBS鬼王] 排队中被直接开战，接管战斗')
                self.run_general_battle(config=battle_config)
                battled = True
                break
            # 挑战按钮可见=自己已是房主（原房主跑路），随机延迟后点击开打
            if self.appear(self.I_FIRE, threshold=0.7):
                if timeout.reached():
                    if not self.exit_room():
                        raise GamePageUnknownError('LBS鬼王 已达时间限制但退出房间失败')
                    break
                logger.info('[LBS鬼王] 原房主离开，自己成为房主，点击挑战')
                sleep(random.uniform(3, 6))
                self.appear_then_click(self.I_FIRE, interval=2)
                # 等战斗界面出现再交给通用战斗
                timer = Timer(30).start()
                while not timer.reached():
                    self.screenshot()
                    if self.is_in_battle(False):
                        break
                else:
                    raise GamePageUnknownError('LBS鬼王 点击挑战后战斗未开始')
                self.run_general_battle(config=battle_config)
                battled = True
                break
            if self.is_in_room():
                # 队员干等房主开战
                if match_timer.reached() or timeout.reached():
                    logger.warning('[LBS鬼王] 匹配超时，退出房间')
                    if not self.exit_room():
                        raise GamePageUnknownError('LBS鬼王 匹配超时但退出房间失败')
                    break
                blank = 0
                continue
            if self.appear(self.I_LBS_MATCH_CANCEL):
                # 还在排队
                if match_timer.reached() or timeout.reached():
                    logger.warning('[LBS鬼王] 匹配超时，取消排队')
                    cancel_timer = Timer(15).start()
                    while not cancel_timer.reached() and self.appear(self.I_LBS_MATCH_CANCEL):
                        self.appear_then_click(self.I_LBS_MATCH_CANCEL, interval=2)
                        self.appear_then_click(GlobalGameAssets.I_UI_CONFIRM, interval=2)
                        self.screenshot()
                    if self.appear(self.I_LBS_MATCH_CANCEL):
                        raise GamePageUnknownError('LBS鬼王 取消排队失败')
                    break
                blank = 0
                continue
            # 战斗/房间/横幅都不在：进房过渡帧或房主开战后的加载。
            # 进房瞬间横幅已消失而房间 UI 未渲染，单帧会误判，连续多帧才算
            blank += 1
            if blank >= 4:
                # 房间解散=房主已开战，等战斗界面出现后接管
                sleep(random.uniform(3, 6))
                if self.is_in_battle():
                    self.run_general_battle(config=battle_config)
                    battled = True
                else:
                    logger.warning('[LBS鬼王] 房间已消失但未确认进入战斗')
                break
        self.device.stuck_record_clear()
        return battled

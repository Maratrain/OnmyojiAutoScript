# This Python file uses the following encoding: utf-8
# @author AzurTian
import re
import time
import numpy as np
from cached_property import cached_property
from datetime import timedelta, datetime
from module.atom.gif import RuleGif
from module.atom.image import RuleImage
from module.atom.click import RuleClick
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from module.image.recipes import match_highlight_rule

from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.Component.GeneralRoom.general_room import GeneralRoom
from tasks.Component.GeneralInvite.general_invite import GeneralInvite
from tasks.Component.ReplaceShikigami.replace_shikigami import ReplaceShikigami
from tasks.Exploration.assets import ExplorationAssets
from tasks.Exploration.config import ChooseRarity, UpType, ExplorationLevel, AutoRotate, UserStatus, Exploration, DiscoverDifficulty
from tasks.Component.GeneralBattle.general_battle import GeneralBattle, ExitMatcher, BattleContext, BattleAction
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.default_pages import random_click
from tasks.LevelRush.assets import LevelRushAssets
from tasks.LevelRush.page import page_achievement
from tasks.Utils.config_enum import ShikigamiClass
import tasks.Exploration.page as pages

from module.logger import logger
from module.exception import TaskEnd, GameStuckError, RequestHumanTakeover
from module.atom.animate import RuleAnimate
from typing import Optional


class BaseExploration(GameUi, GeneralBattle, GeneralRoom, GeneralInvite, ReplaceShikigami, SwitchSoul, ExplorationAssets):
    fire_monster_type: str = ''
    need_exit: bool = False
    user_status: UserStatus = UserStatus.ALONE
    wait_start_time: datetime = datetime.now()
    pre_page: pages.Page = None

    # 聊天抽屉把手(战斗等待期出现时会遮挡画面)
    I_CHAT_WINDOW_HANDLE = RuleImage(
        roi_front=(615, 300, 85, 180), roi_back=(600, 285, 115, 210),
        threshold=0.78, method='Template matching',
        file='./tasks/Exploration/res/chat_window_handle.png')
    # 抽屉关闭三角(展开态把手条上的左箭头, 仅抽屉展开时可见)
    I_CHAT_WINDOW_CLOSE = RuleImage(
        roi_front=(636, 370, 44, 54), roi_back=(615, 285, 100, 230),
        threshold=0.85, method='Template matching',
        file='./tasks/Exploration/res/chat_window_close.png')
    # 抽屉右侧安全点击区
    C_CHAT_WINDOW_CLOSE_SAFE = RuleClick(
        (930, 315, 80, 70), (930, 315, 80, 70), 'chat_window_close_safe')
    # 章节侧边栏成就宝箱(红金宝箱含顶部封条; 侧边栏半透明底板透出地图内容,
    # 用同目录 _mask.png 排除背景, 离线实测 2/3/4 章命中 1.00/0.97/0.93、全屏无误命中)
    I_E_ACHIEVEMENT_CHEST = RuleImage(
        roi_front=(1221, 287, 38, 40), roi_back=(1185, 190, 95, 380),
        threshold=0.85, method='Masked template matching',
        file='./tasks/Exploration/res/explore_achievement_chest.png')
    # 普通模式/困难模式/切换困难(章节详情页: 左侧"巫+困难"选项行=未锁定困难,
    # 右下探索按钮=普通选中态, 组队按钮=困难选中态; 与一键起号 LevelRush 同源同帧资产)
    I_E_NORMAL_MODE = RuleImage(
        roi_front=(986, 601, 108, 44), roi_back=(986, 601, 108, 44),
        threshold=0.8, method='Template matching',
        file='./tasks/Exploration/res/explore_normal_mode.png')
    I_E_HARD_MODE = RuleImage(
        roi_front=(887, 606, 102, 34), roi_back=(887, 606, 102, 34),
        threshold=0.8, method='Template matching',
        file='./tasks/Exploration/res/explore_hard_mode.png')
    I_E_TO_HARD = RuleImage(
        roi_front=(28, 313, 108, 44), roi_back=(15, 260, 200, 110),
        threshold=0.8, method='Template matching',
        file='./tasks/Exploration/res/explore_to_hard.png')
    # 详情页左侧「普通/困难」选中态(红底亮字): 两态文字形状相同, 普通模板匹配
    # 选中与未选中都在 0.95 以上分不开, 必须走 match_highlight_rule 亮度窗口;
    # 只裁文字本体, 红条底板不整块裁入。离线 11/9/8/26 章详情页正样本全命中、
    # 140 张历史帧零误命中。
    I_E_NORMAL_SELECTED = RuleImage(
        roi_front=(73, 229, 58, 30), roi_back=(15, 220, 170, 45),
        threshold=0.8, method='Template matching',
        file='./tasks/Exploration/res/explore_normal_selected.png')
    I_E_HARD_SELECTED = RuleImage(
        roi_front=(73, 317, 58, 30), roi_back=(15, 308, 170, 45),
        threshold=0.8, method='Template matching',
        file='./tasks/Exploration/res/explore_hard_selected.png')
    # 详情页困难选项上的挂锁(困难按账号等级逐章解锁, 挂锁=等级不足锁定态;
    # 锁体掩码排除每章不同的画卷背景, 离线实测锁定帧 1.0/未锁定帧零命中)
    I_E_HARD_LOCKED = RuleImage(
        roi_front=(36, 294, 30, 38), roi_back=(15, 260, 200, 110),
        threshold=0.8, method='Masked template matching',
        file='./tasks/Exploration/res/explore_hard_locked.png')
    # 大世界右侧「主线/玩法」标签选中态: 只裁文字本体, 选中态是亮白描金字、
    # 未选中态是暗灰字。普通模板匹配两态得分都在 0.96 以上分不开, 必须走
    # match_highlight_rule 的亮度窗口; 玩法标签亮即表示当前没有章节列表。
    I_E_PLAY_TAB_SELECTED = RuleImage(
        roi_front=(1188, 172, 55, 26), roi_back=(1172, 158, 100, 52),
        threshold=0.8, method='Template matching',
        file='./tasks/Exploration/res/res_e_play_tab_selected.png')
    I_E_MAIN_TAB_SELECTED = RuleImage(
        roi_front=(1083, 172, 50, 26), roi_back=(1067, 158, 100, 52),
        threshold=0.8, method='Template matching',
        file='./tasks/Exploration/res/res_e_main_tab_selected.png')
    # 切回主线标签(标签块 1055~1160 x 170~204, 取中心区域)
    C_E_MAIN_TAB = RuleClick((1070, 170, 80, 32), (1070, 170, 80, 32), 'click_main_tab')
    # 探索页顶部体力数(与一键起号 O_CURRENT_SUSHI_LOW 同源识别带)
    O_E_SUSHI_NUMBER = RuleOcr(
        roi=(881, 0, 181, 53), area=(881, 0, 181, 53),
        mode='Single', method='Default', keyword='', name='sushi_number')
    # 详情页右下角成就提示横幅(困难选中态): 含「可同时解锁」= 章节成就未达成,
    # 横幅消失即已达成, 据此跳过无需重复清怪的章节
    O_E_ACHIEVEMENT_HINT = RuleOcr(
        roi=(840, 680, 425, 36), area=(840, 680, 425, 36),
        mode='Full', method='Default', keyword='可同时解锁', name='achievement_hint')

    def _exit_matcher(self) -> ExitMatcher:
        return pages.any_of(self.I_E_SETTINGS_BUTTON, self.I_E_AUTO_ROTATE_ON, self.I_E_AUTO_ROTATE_OFF)

    @cached_property
    def _config(self) -> Exploration:
        self.config.exploration.general_battle_config.lock_team_enable = True
        limit_time = self.config.exploration.exploration_config.limit_time
        self.limit_time: timedelta = timedelta(
            hours=limit_time.hour,
            minutes=limit_time.minute,
            seconds=limit_time.second
        )
        return self.config.model.exploration

    @cached_property
    def _match_end(self):
        return RuleAnimate(self.I_SWIPE_END)

    def pre_process(self):
        if self._config.switch_soul_config.enable:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul(self._config.switch_soul_config.switch_group_team)

        if self._config.switch_soul_config.enable_switch_by_name:
            self.goto_page(pages.page_shikigami_records)
            self.run_switch_soul_by_name(self._config.switch_soul_config.group_name,
                                         self._config.switch_soul_config.team_name)
        # 开启加成
        con = self._config.exploration_config
        if con.buff_gold_50_click or con.buff_gold_100_click or con.buff_exp_50_click or con.buff_exp_100_click:
            self.goto_page(pages.page_main)
            self.open_buff()
            if con.buff_gold_50_click:
                self.gold_50()
            if con.buff_gold_100_click:
                self.gold_100()
            if con.buff_exp_50_click:
                self.exp_50()
            if con.buff_exp_100_click:
                self.exp_100()
            self.close_buff()
        self.user_status = self._config.exploration_config.user_status
        self.wait_start_time = datetime.now()  # 重置等待时间

    def post_process(self):
        self.goto_page(pages.page_exploration)
        con = self._config.exploration_config
        if con.buff_gold_50_click or con.buff_gold_100_click or con.buff_exp_50_click or con.buff_exp_100_click:
            self.goto_page(pages.page_main)
            self.open_buff()
            self.gold_50(is_open=False)
            self.gold_100(is_open=False)
            self.exp_50(is_open=False)
            self.exp_100(is_open=False)
            self.close_buff()
        self.set_next_run(task='Exploration', success=True, finish=False)
        raise TaskEnd

    def ensure_main_tab(self) -> bool:
        """右侧停留在「玩法」标签时切回「主线」, 返回是否执行了切换(要求已截图)。

        探索页右侧是同一面板的两个标签, 只有主线态显示章节列表, 且游戏会记住
        上次停留的标签。停在玩法态时章节 OCR 读到「活动」「御魂」等玩法文案,
        全部转换章节失败, open_expect_level 空转 25 次抛 GameStuckError;
        主线成就清扫的侧边栏扫描同样扫不到章节。选中态亮字与未选中态暗字
        用亮度窗口模板匹配区分, 两个标签同时亮属异常态, 不点击。
        """
        image = self.device.image
        frame_id = self.device.image_frame_id
        play_front = list(self.I_E_PLAY_TAB_SELECTED.roi_front)
        main_front = list(self.I_E_MAIN_TAB_SELECTED.roi_front)
        play_selected = match_highlight_rule(self.I_E_PLAY_TAB_SELECTED, image, frame_id=frame_id)
        main_selected = match_highlight_rule(self.I_E_MAIN_TAB_SELECTED, image, frame_id=frame_id)
        # 亮度窗口接口命中时会改写 roi_front, 这里只做检测, 还原避免污染资产
        self.I_E_PLAY_TAB_SELECTED.roi_front = play_front
        self.I_E_MAIN_TAB_SELECTED.roi_front = main_front
        if not play_selected or main_selected:
            return False
        logger.info('[探索] 右侧停留在玩法标签, 切换回主线以显示章节列表')
        self.click(self.C_E_MAIN_TAB, interval=1)
        self.device.click_record_clear()
        time.sleep(0.5)
        return True

    # 打开指定的章节：
    def open_expect_level(self):
        swipeCount = 0
        main_tab_fallback_done = False
        config_exploration_level = self._config.exploration_config.exploration_level
        while True:
            # 判断有无目标章节
            self.screenshot()
            # 停留在玩法标签时没有章节列表, 切回主线后重新取帧再读章节
            if self.ensure_main_tab():
                swipeCount = 0
                self.screenshot()
            # 获取当前章节名
            results = self.O_E_EXPLORATION_LEVEL_NUMBER.detect_and_ocr(self.device.image)
            text1 = [result.ocr_text for result in results]
            exp_level_enum_list = []
            for txt in text1:
                try:
                    exp_level_enum_list.append(ExplorationLevel(txt))
                except ValueError as e:
                    logger.warning(f'[探索] 转换 {txt} 失败')
            sorted(exp_level_enum_list, key=lambda x: x.get_index())  # Sort by index
            # 判断当前章节有无目标章节
            result = set(text1).intersection({config_exploration_level})
            # 有则跳出检测
            if self.appear(self.I_E_EXPLORATION_CLICK) or result and len(result) > 0:
                break
            if self.click_ui_confirm(interval=1):
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1):
                continue
            self.device.click_record_clear()
            if len(exp_level_enum_list) > 0:
                min_level = exp_level_enum_list[0]
                max_level = exp_level_enum_list[-1]
                if config_exploration_level.get_index() < min_level.get_index():
                    self.swipe(self.S_SWIPE_LEVEL_UP)
                elif config_exploration_level.get_index() > max_level.get_index():
                    # 目标章节超出已解锁范围: 先移交新手剧情解锁一章, 再重试一次
                    if getattr(self, '_newbie_story_handoff_target', None) != config_exploration_level:
                        self._newbie_story_handoff_target = config_exploration_level
                        self.run_newbie_story_handoff()
                        swipeCount = 0
                        continue
                    self.disable_completed_chapter()
                    raise RequestHumanTakeover(
                        f"[探索] 目标章节 {config_exploration_level} 未解锁; "
                        f"已运行一次新手剧情但仍未解锁下一章"
                    )
            # 章节列表连续读不出来: 标签模板漏检时兜底再切一次主线, 避免空转到底
            if not exp_level_enum_list and swipeCount >= 3 and not main_tab_fallback_done:
                main_tab_fallback_done = True
                logger.warning('[探索] 未识别到任何章节, 尝试点击主线标签')
                self.click(self.C_E_MAIN_TAB, interval=1)
                self.device.click_record_clear()
                swipeCount = 0
                time.sleep(0.5)
                continue
            swipeCount += 1
            debug_info = f"[探索] 已滑动 {swipeCount} 次，当前章节: {text1}"
            logger.info(debug_info)
            if swipeCount >= 25:
                raise GameStuckError(
                    f"Swiped too many times ({swipeCount}), seems stuck in exploration level selection"
                )
            time.sleep(1)

        # 选中对应章节
        while 1:
            self.screenshot()
            if self.click_ui_confirm(interval=1):
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1):
                continue
            self.O_E_EXPLORATION_LEVEL_NUMBER.keyword = config_exploration_level
            if self.ocr_appear_click(self.O_E_EXPLORATION_LEVEL_NUMBER):
                self.wait_until_appear(self.I_E_EXPLORATION_CLICK, wait_time=3)
            if self.appear(self.I_E_EXPLORATION_CLICK):
                break
            if self.is_in_room():
                break

        return True

    def close_chat_window(self) -> bool:
        """聊天抽屉展开时优先点击其关闭三角收起, 模板未命中再退回右侧空白区关闭。"""
        if self.appear_then_click(self.I_CHAT_WINDOW_CLOSE, interval=0.5):
            logger.info('[探索] 检测到聊天窗, 点击关闭三角收起')
            self.device.click_record_clear()
            time.sleep(0.5)
            return True
        if not self.appear(self.I_CHAT_WINDOW_HANDLE):
            return False
        logger.info('[探索] 检测到聊天窗, 从右侧空白区关闭')
        self.click(self.C_CHAT_WINDOW_CLOSE_SAFE)
        self.device.click_record_clear()
        time.sleep(0.5)
        return True

    def disable_completed_chapter(self):
        """章节已完成时先持久化禁用探索, 防止弹窗或重启导致重打。"""
        with self.config.lock_config:
            self.config.reload()
            self.config.model.exploration.scheduler.enable = False
            self.config.save()
        logger.info('[探索] 章节已完成: 探索任务已禁用, 需手动重新开启')

    def run_newbie_story_handoff(self) -> None:
        """章节未解锁时运行新手剧情, 结束后恢复探索。"""
        from tasks.NewbieStory.script_task import ScriptTask as NewbieStoryTask

        logger.info('[探索] 需要剧情交互, 移交 NewbieStory 处理')
        self.disable_completed_chapter()
        try:
            NewbieStoryTask(self.config, self.device).run()
        except TaskEnd as error:
            logger.info(f'[探索] NewbieStory 移交执行结束: {error}')

        self.config.reload()
        self.__dict__.pop('_config', None)
        # NewbieStory 在独立任务实例中运行, 页面变化不会更新本实例导航缓存
        self.navigator.current_page = None
        if not self.goto_page(pages.page_exploration, skip_first_screenshot=False):
            raise RequestHumanTakeover(
                '[探索] NewbieStory 结束后无法返回探索页面; 探索保持禁用'
            )
        with self.config.lock_config:
            self.config.model.exploration.scheduler.enable = True
            self.config.save()
        logger.info('[探索] 已从 NewbieStory 返回, 重试一次章节选择')

    def fill_shikigami(self):
        """填充式神(最后回到探索主界面)"""
        # 候补出战数量识别
        cu, res, total = self.O_E_ALTERNATE_NUMBER.ocr(self.device.image)
        if cu >= 40:
            logger.info("[探索] 候补出战数量足够")
            self.goto_page(pages.page_exp_main)
            return
        choose_rarity = self._config.exploration_config.choose_rarity
        rarity = ShikigamiClass.N if choose_rarity == ChooseRarity.N else ShikigamiClass.MATERIAL
        self.click(self.C_CLICK_STANDBY_TEAM)  # 先点击候补出战区域
        self.switch_shikigami_class(rarity)  # 切换式神类别
        pre = -1
        while True:
            time.sleep(0.5)
            self.screenshot()
            if not self.appear(self.I_E_OPEN_SETTINGS):
                logger.warning('[探索] 打开设置失败')
                return
            cur, res, total = self.O_E_ALTERNATE_NUMBER.ocr(self.device.image)
            if cur >= 40:
                logger.info(f'[探索] 候补出战数量足够，退出')
                break
            # 连续向后滑动超过6次还能识别到候补狗粮(1. 滑动的不够× 2. 没新狗粮了)
            if self.device.click_record.count(self.S_SWIPE_SHIKI_TO_LEFT.name) >= 6 or \
                    self.device.click_record.count(self.S_SWIPE_SHIKI_TO_LEFT_ONE.name) >= 6:
                if cur > 0: # 上了一部分狗粮, 先用着
                    logger.warning(f'[探索] 候补出战数量不足，当前: {cur}')
                    break
                # 滑动很多次了, 结果也没成功上狗粮, 要么滑的不够(基本不可能)要么没狗粮(大概率)
                # TODO: 1. 增加选项狗粮不够时继续打 2. 去召唤界面换狗粮(这里还有问题是否去商店买厕纸)
                raise GameStuckError(f"Alternate number is not enough")
            # 识别到右侧候补狗粮, 则大幅度向右移动
            if self.appear(self.I_E_ROTATE_EXIST_RIGHT):
                self.swipe(self.S_SWIPE_SHIKI_TO_LEFT)
                continue
            # 识别到候补狗粮, 则滑动一部分
            if self.appear(self.I_E_RATATE_EXSIT):
                self.swipe(self.S_SWIPE_SHIKI_TO_LEFT_ONE)
                continue
            # 没识别到候补狗粮(没狗粮/已经全满级)导致不滑动了, 但是上狗粮后数量又没变
            if pre == cur:
                if cur > 0:  # 上了一部分狗粮, 先用着
                    logger.warning(f'[探索] 候补出战数量不足，当前: {cur}')
                    break
                # TODO: 同上一个todo
                raise GameStuckError(f"Alternate number is not enough")
            pre = cur
            # 长按上狗粮
            self.click(self.L_ROTATE_1)
            self.device.click_record_clear()
        self.goto_page(pages.page_exp_main)

    # 找up按钮
    def search_up_fight(self, up_type: UpType = None) -> Optional[RuleImage | RuleGif]:
        up_type = self._config.exploration_config.up_type if up_type is None else up_type
        if up_type == UpType.ALL and self.appear(self.I_NORMAL_BATTLE_BUTTON):
            # 全部模式打的是普通小怪, 显式标记, 防止残留上一场的 boss 标记
            self.fire_monster_type = 'normal'
            return self.I_NORMAL_BATTLE_BUTTON
        match up_type:
            case UpType.EXP:
                find_flag = self.I_UP_EXP
            case UpType.COIN:
                find_flag = self.I_UP_COIN
            case UpType.DARUMAA:
                find_flag = self.I_UP_DARUMA
            case _:
                find_flag = self.I_UP_EXP
        appear = self.appear(find_flag)
        if not appear:
            return None
        # logger.info(f'Found up type: {up_type} at  {find_flag.roi_front}')
        x, y, _, _ = find_flag.roi_front
        x_center, y_center = find_flag.front_center()
        roi_back_y = max(0, y - 300)
        roi_back_h = y - 20 - roi_back_y
        roi_back_x = max(0, x - 160)
        roi_back_w = min(1280, x + 200) - roi_back_x
        # self.I_NORMAL_BATTLE_BUTTON.roi_back = [roi_back_x, roi_back_y, roi_back_w, roi_back_h]
        # logger.info(f'It will search normal battle button at {roi_back_x, roi_back_y, roi_back_w, roi_back_h}')
        matches = self.I_NORMAL_BATTLE_BUTTON.match_all(
            image=self.device.image,
            threshold=0.9,
            roi=[roi_back_x, roi_back_y, roi_back_w, roi_back_h],
            frame_id=self.device.image_frame_id,
        )
        if not matches:
            return None
        distances = []
        for match in matches:
            x_match, y_match = match[1], match[2]
            distance = np.linalg.norm(
                np.array([x_center, y_center]) - np.array([x_match, y_match])
            )
            distances.append((distance, match))
        distances.sort(key=lambda x: x[0], reverse=False)
        match = distances[0][1]
        roi_front = list(match[1:])  # x,y,w,h
        self.I_NORMAL_BATTLE_BUTTON.roi_front = roi_front
        # logger.info(f"Found normal battle button at {roi_front}")
        self.fire_monster_type = 'normal'
        return self.I_NORMAL_BATTLE_BUTTON

    def activate_realm_raid(self, con_scrolls, con, current_page: pages.Page | None) -> None:
        # 判断是否开启突破票检测
        if not con_scrolls.scrolls_enable or current_page is None or \
                current_page not in (pages.page_exploration, pages.page_exp_entrance):
            return
        if current_page == pages.page_exp_entrance:
            cu, res, total = self.O_REALM_RAID_NUMBER1.ocr(self.device.image)
        else:
            cu, res, total = self.O_REALM_RAID_NUMBER.ocr(self.device.image)
        # 判断突破票数量
        if cu < con_scrolls.scrolls_threshold:
            return
        # 关闭加成
        if con.buff_gold_50_click or con.buff_gold_100_click or con.buff_exp_50_click or con.buff_exp_100_click:
            self.goto_page(pages.page_main)
            self.open_buff()
            self.gold_50(is_open=False)
            self.gold_100(is_open=False)
            self.exp_50(is_open=False)
            self.exp_100(is_open=False)
            self.close_buff()
        # 设置下次执行行时间
        logger.info("[探索] 结界突破和探索已设置下次运行时间")
        next_run = datetime.now() + con_scrolls.scrolls_cd
        self.goto_page(pages.page_exploration)
        self.set_next_run(task='Exploration', success=False, finish=False, target=next_run)
        self.set_next_run(task='RealmRaid', success=False, finish=False, server=False, target=datetime.now())
        self.set_next_run(task='MemoryScrolls', success=False, finish=False, target=datetime.now())
        raise TaskEnd

    def check_exit(self, current_page: pages.Page | None) -> bool:
        # True 表示要退出这个任务
        if self.current_count >= self._config.exploration_config.minions_cnt:
            logger.info('[探索] 已达小怪数量上限，退出')
            return True
        if datetime.now() - self.start_time >= self.limit_time:
            logger.info('[探索] 探索时间已用完，退出')
            return True
        if self.user_status == UserStatus.MEMBER and \
                datetime.now() - self.wait_start_time >= self._config.invite_config.wait_time_v:
            logger.info('[探索] 队员等待超时，退出')
            return True
        self.activate_realm_raid(self._config.scrolls, self._config.exploration_config, current_page)
        return False

    def fire(self, button) -> bool:
        """进入战斗(True:成功进入战斗/识别到退出弹窗, 否则False)
        这里之所以违反页面特性使用循环, 是因为由于怪物移动的原因可能导致一次点击会无法进入战斗,
        回到外循环之后由于UP旋转的特性可能导致识别不到怪物然后开始滑动, 导致错过的怪物更多
        因此这里使用贪心的思想, 只要识别到怪物一次就尽最大可能直接进入战斗, 保证尽可能有怪则打
        """
        max_tries = 4
        timeout_timer = Timer(10).start()  # 增加最大时间限制, 防止因未知因素引起无限等待
        while max_tries > 0 and not timeout_timer.reached():
            self.screenshot()
            cur_page = self.get_current_page()
            # 退出动画期间可能再次识别到怪物开始攻击, 因此取消退出
            if cur_page == pages.page_exp_exit:
                self.need_exit = False
                return True
            if cur_page in (pages.page_battle_prepare, pages.page_battle):
                return True
            if self.appear_then_click(button, interval=0.8):
                max_tries -= 1
                continue
        return False

    def switch_rotate(self) -> bool:
        """切换轮换类型并添加式神 True(执行了切换)/False"""
        match self._config.exploration_config.auto_rotate:
            case AutoRotate.yes:
                if self.appear(self.I_E_AUTO_ROTATE_OFF):  # 轮换关闭/式神不够了则需要打开并添加式神
                    self.click(self.C_CLICK_SETTINGS, interval=2)
                    return True
            case AutoRotate.no:  # 不是自动添加候补式神则关闭轮换
                if self.appear_then_click(self.I_E_AUTO_ROTATE_ON, interval=0.8):
                    return True
        return False

    def arrive_end(self) -> bool:
        """是否到达探索的最后方, 需要先调用截图(滑动超过6次直接判定已经到达底部)"""
        if self.device.click_record.count(self.S_SWIPE_BACKGROUND_RIGHT.name) >= 6:
            self.device.click_record_clear()
            return True
        return self._match_end.stable(self.device.image, refresh_after_stable=True, frame_id=self.device.image_frame_id)

    def get_fire_button(self) -> Optional[RuleImage | RuleGif]:
        """获取需要攻击的按钮"""
        if self.appear(self.I_BOSS_BATTLE_BUTTON):
            self.fire_monster_type = 'boss'
            return self.I_BOSS_BATTLE_BUTTON
        return self.search_up_fight()

    def collect_treasure_box(self) -> bool:
        """收集宝箱奖励"""
        if self.appear(self.I_E_REWARD_BOX_SMALL):  # 小宝箱
            logger.info('[探索] 出现小宝箱，领取')
            self.ui_click(self.I_E_REWARD_BOX_SMALL, self.I_REWARD, interval=0.8)
            self.ui_click_until_disappear(self.I_REWARD, interval=0.8)
            return True
        if self.appear(self.I_E_REWARD_BOX_BIG):  # 大宝箱
            logger.info('[探索] 出现大宝箱，领取')
            self.ui_click(self.I_E_REWARD_BOX_BIG, self.I_REWARD, interval=0.8)
            self.ui_click_until_disappear(self.I_REWARD, interval=0.8)
            return True
        return False

    def collect_paper_man_reward(self) -> bool:
        """收集小纸人奖励, 若未开启则自动退出"""
        # 已经打过boss了且设置了不收集小纸人奖励则直接返回
        if self.fire_monster_type == 'boss' and not self._config.exploration_config.collect_paper_reward:
            logger.info("[探索] 未开启小纸人奖励收集")
            self.quit_exp_main()
            return True
        # 没打boss或者收集纸人奖励, 且出现了纸人则处理掉落奖励
        if self.appear(self.I_BATTLE_REWARD) and self._config.exploration_config.collect_paper_reward:
            self.ui_get_reward(self.I_BATTLE_REWARD)
            self.wait_start_time = datetime.now()  # 队友等待时间重置
            return True
        return False

    def quit_exp_main(self):
        """退出探索主界面(要求当前必须处于探索主界面, 不保证任何后续结果)"""
        self.need_exit = True
        self.appear_then_click(self.I_UI_BACK_YELLOW, interval=0.8)
        self.wait_start_time = datetime.now()  # 队友等待时间重置

    # ==================== 主线章节成就清扫 ====================
    # 扫描章节侧边栏, 对带成就宝箱的章节逐章选中困难, 复用探索刷怪 FSM 的
    # 页面处理器清图打怪直到 boss 刷出并击杀, 完成章节成就; 遇到困难锁定
    # (等级不足)的章节即结束, 之后顺路去成就页面领取奖励。
    _SWEEP_MAX_LOSE = 3      # 连续战斗失败上限(整个清扫轮内累计, 胜一场清零)
    _SWEEP_MIN_SUSHI = 6     # 困难探索单场体力消耗, 低于该值停止清扫
    _SWEEP_MAX_SWIPE = 150   # 侧边栏翻页防呆上限(每章访问后列表弹回顶部, 需按章重复下翻)
    _SWEEP_CLAIM_EVERY = 4   # 每清 4 章中途领一次成就奖励, 防中断后从低章重扫
    # 清扫点章节行用(扫描到哪行就把 roi_front 挪到哪行, 不按关键词 OCR 防点错行)
    C_SWEEP_CHAPTER_ROW = RuleClick((1070, 300, 60, 26), (1060, 190, 130, 380), 'sweep_chapter_row')
    _sweep_lose_streak: int = 0

    def _sushi_number(self) -> int:
        """读取探索页顶部的体力数, 识别失败返回 -1(不阻塞流程)"""
        try:
            text = self.O_E_SUSHI_NUMBER.ocr(self.device.image)
        except Exception as e:
            logger.warning(f'[探索] 体力数识别异常: {e}')
            return -1
        digits = re.sub(r'\D', '', str(text))
        return int(digits) if digits else -1

    def _parse_chapter_text(self, text: str) -> Optional[ExplorationLevel]:
        """解析侧边栏 OCR 文本为章节枚举, 容忍「章」被误读成草/音/意等。

        实机日志常见误读: 第十七草(第十七章)、第十音(第十章); 直接解析失败
        时用正则抠出「第+中文数字+类章尾字」归一后再试, 仍失败返回 None。
        """
        try:
            return ExplorationLevel(text)
        except ValueError:
            pass
        m = re.search(r'第([一二三四五六七八九十]{1,3})[章草音意]', text)
        if m:
            try:
                return ExplorationLevel(f'第{m.group(1)}章')
            except ValueError:
                return None
        return None

    def _scan_sidebar(self) -> tuple[list, list]:
        """扫描章节侧边栏。

        返回 (带成就宝箱的章节行, 可见章节列表):
        行为 (ExplorationLevel, (x, y)), 即章节名点击中心; 两列均按章节序升序。
        要求调用前已截图且侧边栏展开。
        """
        results = self.O_E_EXPLORATION_LEVEL_NUMBER.detect_and_ocr(self.device.image)
        roi_x = self.O_E_EXPLORATION_LEVEL_NUMBER.roi[0]
        roi_y = self.O_E_EXPLORATION_LEVEL_NUMBER.roi[1]
        named = []
        for r in results:
            level = self._parse_chapter_text(r.ocr_text)
            if level is None:
                continue
            box = np.array(r.box)
            named.append((level, (box[:, 0].mean() + roi_x, box[:, 1].mean() + roi_y)))
        if not named:
            return [], []
        # 侧边栏可见章节是连续的, 与相邻行章节序相差超过 2 的解析结果视为
        # 误读丢弃(如 第七章 被重误读成 第十意 后会被错恢复成 第十章)
        named.sort(key=lambda t: t[1][1])
        filtered = []
        prev_index = None
        for level, pos in named:
            index = level.get_index()
            if prev_index is not None and abs(index - prev_index) > 2:
                continue
            filtered.append((level, pos))
            prev_index = index
        named = filtered
        if not named:
            return [], []
        matches = self.I_E_ACHIEVEMENT_CHEST.match_all(
            image=self.device.image, threshold=self.I_E_ACHIEVEMENT_CHEST.threshold,
            frame_id=self.device.image_frame_id)
        # 同一宝箱会在相邻位置产生一簇命中, 按 y 聚类后取簇内最高分
        clusters = []
        for score, x, y, w, h in matches:
            cy = y + h / 2
            for c in clusters:
                if abs(cy - c['y']) <= 20:
                    c['y'] = (c['y'] * c['n'] + cy) / (c['n'] + 1)
                    c['n'] += 1
                    c['score'] = max(c['score'], score)
                    break
            else:
                clusters.append({'y': cy, 'n': 1, 'score': score})
        rows = []
        for c in clusters:
            if c['score'] < self.I_E_ACHIEVEMENT_CHEST.threshold:
                continue
            best = min(named, key=lambda t: abs(t[1][1] - c['y']))
            if abs(best[1][1] - c['y']) <= 55:  # 同一行内宝箱与章节名的距离
                rows.append(best)
        seen = set()
        unique = []
        for level, pos in sorted(rows, key=lambda t: t[0].get_index()):
            if level not in seen:
                seen.add(level)
                unique.append((level, pos))
        return unique, [level for level, _ in named]

    def _sweep_ensure_sidebar_open(self) -> bool:
        """侧边栏折叠时展开, 执行了展开返回 True"""
        if self.appear_then_click(self.I_E_OPEN_FOLDER, interval=1):
            time.sleep(0.5)
            return True
        return False

    def _current_difficulty(self) -> Optional[str]:
        """详情页左侧选中态判定当前难度, 返回 'normal'/'hard'/None(判据失效)。

        两个选中态互斥: 同时亮或同时暗都视为判据失效, 交回右下按钮文字判据兜底。
        """
        image = self.device.image
        frame_id = self.device.image_frame_id
        normal_front = list(self.I_E_NORMAL_SELECTED.roi_front)
        hard_front = list(self.I_E_HARD_SELECTED.roi_front)
        normal = match_highlight_rule(self.I_E_NORMAL_SELECTED, image, frame_id=frame_id)
        hard = match_highlight_rule(self.I_E_HARD_SELECTED, image, frame_id=frame_id)
        # 亮度窗口接口命中会改写 roi_front, 这里只做检测, 还原避免污染资产
        self.I_E_NORMAL_SELECTED.roi_front = normal_front
        self.I_E_HARD_SELECTED.roi_front = hard_front
        if normal == hard:
            return None
        return 'normal' if normal else 'hard'

    def _switch_to_hard(self) -> bool:
        """详情页选中困难难度: 左侧困难选项行亮起即完成, 右下组队按钮作兜底"""
        for _ in range(6):
            self.screenshot()
            state = self._current_difficulty()
            if state == 'hard':
                return True
            # 左侧判据失效(动画帧等)时, 仍可用右下按钮文字确认难度
            if state is None and self.appear(self.I_E_HARD_MODE):
                return True
            if state == 'normal' or self.appear(self.I_E_NORMAL_MODE):
                if self.appear(self.I_E_TO_HARD):
                    self.click(self.I_E_TO_HARD, interval=1)
                    continue
            time.sleep(0.5)
        logger.warning('[探索] 未能选中困难难度')
        return False

    def _enter_exp_main(self) -> bool:
        """从章节详情页点击探索按钮进入章节地图"""
        timer = Timer(15).start()
        while not timer.reached():
            self.screenshot()
            if self.get_current_page() == pages.page_exp_main:
                return True
            self.appear_then_click(self.I_E_EXPLORATION_CLICK, interval=1.2)
        logger.warning('[探索] 点击探索按钮后未能进入章节地图')
        return False

    def _back_to_exploration(self) -> None:
        """从章节地图/详情页返回探索大世界, 失败抛 GameStuckError。

        注意探索大世界顶部的返回键会退出到庭院, 因此识别到 page_exploration
        必须立即停止点击返回。
        """
        timer = Timer(30).start()
        while not timer.reached():
            self.screenshot()
            page = self.get_current_page()
            if page == pages.page_exploration:
                return
            if page is None:
                # 章节详情页未注册独立页面(识别为 None), 靠返回键退出到大世界
                self.appear_then_click(self.I_UI_BACK_YELLOW, interval=0.8)
                time.sleep(0.5)
                continue
            if page == pages.page_exp_exit:
                self.appear_then_click(self.I_E_EXIT_CONFIRM, interval=0.8)
                continue
            if page == pages.page_main:
                self.goto_page(pages.page_exploration)
                return
            # 章节详情态侧边栏是收起的, 优先点展开按钮直接回大世界;
            # 展开按钮不在场再按黄返回键(大世界上严禁再点, 上方已拦截)
            if self.appear_then_click(self.I_E_OPEN_FOLDER, interval=0.8):
                continue
            self.appear_then_click(self.I_UI_BACK_YELLOW, interval=0.8)
            time.sleep(0.5)
        raise GameStuckError('[探索] 主线成就清扫后无法返回探索页面')

    def _sweep_clear_map(self) -> str:
        """清图阶段: 页面处理完全复用探索刷怪 FSM 的处理器, 返回 'win'/'lose'/'skip'

        run_on_exp_main 负责收奖励/轮换开关/boss 优先找怪/进战/右滑/到头自动
        退出地图, 战斗由 run_general_battle 处理到回到地图(即 run_on_battle,
        此处仅取其返回值记录连败); 本循环只做 exec_exp_page 同款的页面分发
        加清扫特有终止判定: boss 战胜利即本章完成, FSM 把地图走完退出
        (到头未见 boss)即本章结束交由外层重进或跳过。boss 刷出时机以游戏
        实际表现为准, 循环不依赖任何小怪数量假设。不调用 check_exit:
        刷怪的场次/时长上限不适用于清扫, 由连败计数与体力预检兜底。
        """
        # 同 run_on_exp_entrance 的进场重置: 防上一章 boss 标记残留,
        # 否则本章首场小怪战会被误判成 boss 战而提前报 win
        self.fire_monster_type = ''
        handlers = {
            pages.page_exp_main: self.run_on_exp_main,
            pages.page_exp_settings: self.run_on_exp_settings,
        }
        while True:
            self.screenshot()
            current_page = self.get_current_page()
            if current_page is None:
                # 聊天抽屉等浮层盖住识别按钮时先关抽屉(同 exec_exp_page)
                if self.close_chat_window():
                    continue
                time.sleep(0.5)
                continue
            if current_page in (pages.page_battle_prepare, pages.page_battle,
                                pages.page_battle_result, pages.page_reward):
                win = self.run_general_battle(
                    self._config.general_battle_config, exit_matcher=pages.page_exp_main)
                self._match_end.refresh()  # 同 run_on_battle, 防止同图滑动终点残留误判
                if win:
                    self._sweep_lose_streak = 0
                    if self.fire_monster_type == 'boss':
                        return 'win'  # boss 已击杀, 本章成就完成
                else:
                    self._sweep_lose_streak += 1
                    if self._sweep_lose_streak >= self._SWEEP_MAX_LOSE:
                        logger.info('[探索] 连续战斗失败 3 次, 中止主线成就清扫')
                        return 'lose'
                self.pre_page = current_page
                continue
            if current_page == pages.page_exp_exit:
                # run_on_exp_main 到头后自动退出地图: 本章没有等到 boss
                return 'skip'
            if current_page in (pages.page_exp_entrance, pages.page_exploration):
                return 'skip'
            handler = handlers.get(current_page)
            if handler is None:
                logger.warning(f'[探索] 清图阶段遇到未处理页面, 跳过该章')
                return 'skip'
            handler()
            self.pre_page = current_page

    def _sweep_scroll_to_level(self, level: ExplorationLevel) -> bool:
        """把侧边栏滚动到目标章节可见(重进章节前用), 最多 12 屏"""
        for _ in range(12):
            self.screenshot()
            _, visible = self._scan_sidebar()
            if level in visible:
                return True
            if not visible:
                self.swipe(self.S_SWIPE_LEVEL_DOWN)
                time.sleep(0.8)
                continue
            index = level.get_index()
            indexes = [lv.get_index() for lv in visible]
            if index > max(indexes):
                self.swipe(self.S_SWIPE_LEVEL_DOWN)
            elif index < min(indexes):
                self.swipe(self.S_SWIPE_LEVEL_UP)
            else:
                return True  # 行已在视口内, 即便名字没配对上也可定位
            time.sleep(0.8)
        return False

    def _sweep_locate_row(self, level: ExplorationLevel) -> Optional[tuple]:
        """在当前视口重新定位目标章节的宝箱行, 返回点击坐标或 None"""
        rows, _ = self._scan_sidebar()
        for lv, pos in rows:
            if lv == level:
                return pos
        return None

    def _sweep_enter_chapter(self, pos: tuple) -> bool:
        """点击章节行进入章节详情页(按扫描行坐标直点, 不按关键词 OCR)"""
        x, y = int(pos[0]), int(pos[1])
        self.C_SWEEP_CHAPTER_ROW.roi_front = (x - 30, y - 13, 60, 26)
        self.click(self.C_SWEEP_CHAPTER_ROW, interval=1)
        # 详情页底部按钮随选中难度变化: 普通态探索(986,601)/困难态组队(887,606),
        # 章节会记住上次选中难度, 两者其一出现即详情页加载完成
        timer = Timer(10).start()
        while not timer.reached():
            self.screenshot()
            if self.appear(self.I_E_NORMAL_MODE) or self.appear(self.I_E_HARD_MODE):
                return True
            time.sleep(0.5)
        logger.warning('[探索] 点击章节行后未进入详情页')
        return False

    def _sweep_scroll_sidebar_top(self) -> None:
        """回到章节列表顶部, 保证清扫从第一章开始向下推。

        游戏会记住上次停留的章节位置(例如刷图后停在 26~28 章), 不归零的话
        清扫会从中间开始, 漏掉前面所有章节, 还可能先撞上高章的困难锁定
        直接结束整轮清扫。快速归零: 随便进一个章节再退出一次, 列表即重置
        回第一章; 未重置成功再逐屏向上滑动兜底。
        """
        self.screenshot()
        rows, visible = self._scan_sidebar()
        if ExplorationLevel.EXPLORATION_1.value in [lv.value for lv in visible]:
            return
        if rows:
            logger.info(f'[探索] 侧边栏归零: 进入 {rows[0][0].value} 再退出')
            try:
                self._sweep_enter_chapter(rows[0][1])
            finally:
                self._back_to_exploration()
        # 归零校验, 未重置则逐屏向上滑动兜底
        last: list = []
        stall = 0
        for _ in range(15):
            self.screenshot()
            _, visible = self._scan_sidebar()
            names = [lv.value for lv in visible]
            if ExplorationLevel.EXPLORATION_1.value in names:
                return
            if names and names == last:
                stall += 1
                if stall >= 2:  # 连续两屏章节一致说明已到顶(第一章未被 OCR 读出也放行)
                    return
            else:
                stall = 0
            last = names
            self.swipe(self.S_SWIPE_LEVEL_UP)
            time.sleep(0.8)
        logger.warning('[探索] 未能滚动回章节列表顶部, 按当前位置继续清扫')

    def _sweep_achievement_done(self) -> bool:
        """判断章节成就是否已达成(要求当前处于困难选中态的详情页且已截图)。

        成就未达成时详情页右下角有横幅「成就达成后可同时解锁普通难度成就奖励」;
        横幅消失即已达成, 该章无需再清。
        """
        return self.O_E_ACHIEVEMENT_HINT.ocr(self.device.image) == (0, 0, 0, 0)

    def _sweep_one_chapter(self, level: ExplorationLevel, pos: tuple) -> str:
        """进入单个章节选中困难并清图, 返回 'win'/'lose'/'skip'/'locked'

        困难难度按账号等级逐章解锁(与通关普通无关); 详情页困难带挂锁(等级不足)
        时返回 'locked'。清图交给刷怪 FSM 的页面处理器: 若整张图走完仍没等到
        boss 刷出(小怪游走出视野/首次进图资源加载慢), 重新进入一次再清——
        重进后小怪会重新刷新; 两次都没等到才跳过。困难通关可同时解锁该章
        普通难度成就奖励。pos 为扫描到的章节行点击坐标。
        """
        for attempt in range(1, 3):
            if attempt == 2:
                # 首次进出后侧边栏已弹回顶部, 先滚回目标章节可见再重新定位行
                if not self._sweep_scroll_to_level(level):
                    logger.warning(f'[探索] {level.value} 未能重新滚动到位, 跳过')
                    return 'skip'
                relocated = self._sweep_locate_row(level)
                if relocated is None:
                    logger.warning(f'[探索] {level.value} 未能重新定位章节行, 跳过')
                    return 'skip'
                pos = relocated
            if not self._sweep_enter_chapter(pos):
                self._back_to_exploration()
                return 'skip'
            if self.appear(self.I_E_HARD_LOCKED):
                logger.info(f'[探索] {level.value} 困难未解锁(等级不足), 主线成就清扫到此结束')
                self._back_to_exploration()
                return 'locked'
            if not self._switch_to_hard():
                self._back_to_exploration()
                return 'skip'
            if self._sweep_achievement_done():
                logger.info(f'[探索] {level.value} 章节成就已达成, 跳过')
                self._back_to_exploration()
                return 'skip'
            if not self._enter_exp_main():
                self._back_to_exploration()
                return 'skip'
            result = self._sweep_clear_map()
            if result in ('win', 'lose'):
                self.collect_treasure_box()  # boss 战后的地图掉落宝箱(FSM 下一轮本会收)
                logger.info(f'[探索] {level.value} 困难清扫结果: {result}')
                self._back_to_exploration()
                return result
            logger.info(f'[探索] {level.value} 第 {attempt} 次进入未见 boss')
            self._back_to_exploration()
        logger.warning(f'[探索] {level.value} 两次进入仍未等到 boss, 跳过该章')
        return 'skip'

    def claim_achievement_rewards(self) -> None:
        """顺路领取成就页面的可领奖励(含主线章节成就), 流程与一键起号一致"""
        logger.info('[探索] 前往成就页面领取奖励')
        self.goto_page(page_achievement)
        loop = 0
        while 1:
            time.sleep(0.8)
            self.screenshot()
            if self.appear_then_click(LevelRushAssets.I_ACHIEVEMENT_MENU_CLOSE, interval=1.2):
                self.device.click_record_clear()
                continue
            if self.appear(LevelRushAssets.I_GET_ACHIEVEMENT_REWARD):
                self.ui_get_reward(LevelRushAssets.I_GET_ACHIEVEMENT_REWARD)
                self.click(random_click(ltrb=(False, True, False, False)))
                self.device.click_record_clear()
                continue
            if self.appear_then_click(LevelRushAssets.I_ACHIEVEMENT_REWARD_EXIST, interval=1.2):
                self.device.click_record_clear()
                continue
            if loop >= 3:
                break
            if not self.appear(LevelRushAssets.I_GET_ACHIEVEMENT_REWARD) and \
                    not self.appear(LevelRushAssets.I_ACHIEVEMENT_REWARD_EXIST):
                loop += 1
        logger.info('[探索] 成就奖励领取完成')
        self.goto_page(pages.page_exploration)

    def chapter_achievement_sweep_run(self) -> None:
        """主线章节成就清扫入口: 逐章清扫带成就宝箱的章节困难 boss"""
        logger.hr('主线章节成就清扫', 2)
        self.goto_page(pages.page_exploration)
        # 清扫全程依赖右侧章节列表, 先确保停在主线标签
        for _ in range(3):
            self.screenshot()
            if not self.ensure_main_tab():
                break
        while self._sweep_ensure_sidebar_open():
            self.screenshot()
        self._sweep_scroll_sidebar_top()
        self.screenshot()
        sushi = self._sushi_number()
        if 0 <= sushi < self._SWEEP_MIN_SUSHI:
            logger.info(f'[探索] 体力不足 {self._SWEEP_MIN_SUSHI}(当前 {sushi}), 跳过主线成就清扫')
            return
        self._sweep_lose_streak = 0
        win_count = 0
        processed: set = set()
        swipe_count = 0
        stall = 0
        # 清图复用刷怪 FSM 处理器, 需打所有小怪才能刷出 boss; 刷怪模式可能
        # 配置为只打经验怪, 清扫期间临时改为全部, 结束后还原
        old_up_type = self._config.exploration_config.up_type
        self._config.exploration_config.up_type = UpType.ALL
        try:
            while True:
                self.screenshot()
                # 进出章节/领取成就后标签可能被重置, 每轮先确认回主线
                if self.ensure_main_tab():
                    self.screenshot()
                if self._sweep_ensure_sidebar_open():
                    continue
                sushi = self._sushi_number()
                if 0 <= sushi < self._SWEEP_MIN_SUSHI:
                    logger.info(f'[探索] 体力不足 {self._SWEEP_MIN_SUSHI}(当前 {sushi}), 清扫提前结束')
                    break
                rows, visible = self._scan_sidebar()
                rows = [row for row in rows if row[0] not in processed]
                if rows:
                    level, pos = rows[0]
                    processed.add(level)
                    logger.info(f'[探索] 主线成就清扫: 进入 {level.value}')
                    result = self._sweep_one_chapter(level, pos)
                    # 每章固定三连点(章节名/切困难/返回), 及时清记录防止
                    # GameTooManyClickError 把整轮清扫打断
                    self.device.click_record_clear()
                    if result in ('locked', 'lose'):
                        break
                    if result == 'win':
                        win_count += 1
                        if win_count >= self._SWEEP_CLAIM_EVERY:
                            win_count = 0
                            logger.info(f'[探索] 已连续清扫 {self._SWEEP_CLAIM_EVERY} 章, 中途领取成就奖励')
                            self.claim_achievement_rewards()
                    continue
                if len(processed) >= 28:
                    logger.info('[探索] 已处理完全部章节, 主线成就清扫结束')
                    break
                if stall >= 2:
                    logger.info('[探索] 章节列表已到最底, 主线成就清扫结束')
                    break
                if swipe_count >= self._SWEEP_MAX_SWIPE:
                    logger.warning(f'[探索] 侧边栏翻页达 {swipe_count} 次上限, 提前结束清扫')
                    break
                # 当前屏没有待清扫章节, 向后翻一页; 翻页前后可见章节一致说明已到最底
                before = set(visible)
                self.swipe(self.S_SWIPE_LEVEL_DOWN)
                swipe_count += 1
                time.sleep(0.8)
                self.screenshot()
                _, visible_after = self._scan_sidebar()
                if visible_after and set(visible_after) == before:
                    stall += 1
                else:
                    stall = 0
        finally:
            self._config.exploration_config.up_type = old_up_type
        logger.info(f'[探索] 主线成就清扫收尾, 已处理章节: {sorted(lv.value for lv in processed)}')
        self.claim_achievement_rewards()

    # ==================== 发现妖怪模式 ====================
    # 逐章重复清图, 直到章节详情页妖怪阵容中的未知式神剪影消失(隐藏妖怪
    # 被击败发现)。隐藏妖怪不保证每次进图都刷出, 由单章清图次数上限兜底。
    # 仅前 18 章存在未知式神(与游戏图鉴范围一致), 难度可配置。
    _DISCOVER_MAX_CLEAR = 6   # 单章重复清图上限
    # 章节详情页妖怪阵容的未知式神剪影(深色圆底金色问号徽章); 与清扫的
    # 难度选中态资产同一张详情页, 布局同源(kongdr 实机帧裁剪, 坐标 1280x720)
    I_UNKNOWN_SHIKIGAMI = RuleImage(
        roi_front=(882, 333, 55, 59), roi_back=(867, 294, 334, 140),
        threshold=0.8, method='Template matching',
        file='./tasks/Exploration/res/res_unknown_shikigami.png')

    def _discover_ensure_difficulty(self, hard: bool) -> str:
        """详情页选中发现妖怪难度, 返回 'ok'/'locked'。

        困难选项带挂锁(等级不足)时返回 'locked' 由调用方结束整轮(困难按
        账号等级逐章解锁, 后续章节必然同样锁定)。切普通直接点普通选项行
        文字(I_E_NORMAL_SELECTED 模板对选中/未选中两态通吃, 点击落
        roi_front 中心即行内坐标), 切困难复用清扫的 I_E_TO_HARD。
        """
        desired = 'hard' if hard else 'normal'
        timer = Timer(8).start()
        while not timer.reached():
            self.screenshot()
            state = self._current_difficulty()
            if state is None:
                # 左侧判据失效时用右下按钮兜底确认(同 _switch_to_hard)
                if hard and self.appear(self.I_E_HARD_MODE):
                    return 'ok'
                if not hard and self.appear(self.I_E_NORMAL_MODE):
                    return 'ok'
            elif state == desired:
                return 'ok'
            if self.appear(self.I_E_HARD_LOCKED) and hard:
                return 'locked'
            if hard:
                self.click(self.I_E_TO_HARD, interval=1)
            else:
                self.click(self.I_E_NORMAL_SELECTED, interval=1)
        raise GameStuckError('[探索] 发现妖怪模式未能选中难度')

    def _discover_has_unknown(self) -> bool:
        """判断详情页妖怪阵容是否仍有未知式神。

        要求详情页已渲染(右下难度按钮在场)再判定, 标记连续 3 帧不出现
        才算已发现, 防首次渲染/切难度动画误判。渲染超时按未发现处理
        (清一次再走), 由单章清图上限兜底, 不抛错保证整轮可控。
        """
        timer = Timer(6).start()
        clear_frames = 0
        while not timer.reached():
            self.screenshot()
            if not (self.appear(self.I_E_NORMAL_MODE) or self.appear(self.I_E_HARD_MODE)):
                clear_frames = 0
                continue
            if self.appear(self.I_UNKNOWN_SHIKIGAMI):
                return True
            clear_frames += 1
            if clear_frames >= 3:
                return False
        logger.warning('[探索] 未能确认未知式神标记, 保守按未发现处理')
        return True

    def discover_monsters_run(self) -> None:
        """发现妖怪模式入口: 前 18 章逐章重复清图直到未知式神消失。

        每次进出章节后侧边栏会弹回顶部, 复用清扫的滚动/定位/进入方法
        重新找行; 清图复用刷怪 FSM(_sweep_clear_map, 走完地图即算一次
        清图, boss 胜利与否不影响发现判定); 连败与体力预检沿用清扫阈值。
        """
        logger.hr('发现妖怪模式', 2)
        difficulty = self._config.exploration_config.discover_difficulty
        hard = difficulty == DiscoverDifficulty.HARD
        max_index = ExplorationLevel.EXPLORATION_18.get_index()
        self.goto_page(pages.page_exploration)
        for _ in range(3):
            self.screenshot()
            if not self.ensure_main_tab():
                break
        while self._sweep_ensure_sidebar_open():
            self.screenshot()
        self._sweep_scroll_sidebar_top()
        self.screenshot()
        sushi = self._sushi_number()
        if 0 <= sushi < self._SWEEP_MIN_SUSHI:
            logger.info(f'[探索] 体力不足 {self._SWEEP_MIN_SUSHI}(当前 {sushi}), 跳过发现妖怪模式')
            return
        self._sweep_lose_streak = 0
        # 隐藏妖怪不一定是经验怪, 清图期间临时改为打全部, 结束后还原
        old_up_type = self._config.exploration_config.up_type
        self._config.exploration_config.up_type = UpType.ALL
        attempts_of: dict = {}
        try:
            for level in list(ExplorationLevel)[:max_index + 1]:
                while True:
                    self.screenshot()
                    if self.ensure_main_tab():
                        self.screenshot()
                    if self._sweep_ensure_sidebar_open():
                        continue
                    sushi = self._sushi_number()
                    if 0 <= sushi < self._SWEEP_MIN_SUSHI:
                        logger.info(f'[探索] 体力不足 {self._SWEEP_MIN_SUSHI}(当前 {sushi}), 发现妖怪模式提前结束')
                        return
                    if attempts_of.get(level, 0) >= self._DISCOVER_MAX_CLEAR:
                        logger.warning(f'[探索] {level.value} 已清图 {self._DISCOVER_MAX_CLEAR} 次仍有未知式神, 放弃该章')
                        break
                    if not self._sweep_scroll_to_level(level):
                        logger.warning(f'[探索] {level.value} 未能滚动到位, 跳过')
                        break
                    pos = self._sweep_locate_row(level)
                    if pos is None:
                        logger.warning(f'[探索] {level.value} 未能定位章节行, 跳过')
                        break
                    if not self._sweep_enter_chapter(pos):
                        self._back_to_exploration()
                        break
                    state = self._discover_ensure_difficulty(hard)
                    if state == 'locked':
                        logger.info(f'[探索] {level.value} 困难未解锁(等级不足), 发现妖怪模式到此结束')
                        self._back_to_exploration()
                        return
                    if not self._discover_has_unknown():
                        logger.info(f'[探索] {level.value} 未知式神已发现({difficulty.value})')
                        self._back_to_exploration()
                        break
                    if not self._enter_exp_main():
                        self._back_to_exploration()
                        break
                    result = self._sweep_clear_map()
                    self.collect_treasure_box()  # boss 战后的地图掉落宝箱(FSM 下一轮本会收)
                    self._back_to_exploration()
                    # 每轮固定多次点击(选行/切难度/探索/地图内点击), 及时清记录防止
                    # GameTooManyClickError 打断整轮
                    self.device.click_record_clear()
                    attempts_of[level] = attempts_of.get(level, 0) + 1
                    if result == 'lose':
                        logger.info('[探索] 连续战斗失败 3 次, 中止发现妖怪模式')
                        return
        finally:
            self._config.exploration_config.up_type = old_up_type
        summary = {lv.value: n for lv, n in attempts_of.items()}
        logger.info(f'[探索] 发现妖怪模式收尾, 各章清图次数: {summary}')

    def collect_reward(self) -> bool:
        """处理掉落奖励(True表示进行了操作, False表示没有操作)"""
        return self.collect_treasure_box() or self.collect_paper_man_reward()

    def enter_team(self) -> bool:
        """进入战斗组队页面"""
        return self.create_room(self.I_EXP_CREATE_TEAM) and self.ensure_private() and self.create_ensure()

if __name__ == "__main__":
    from module.config.config import Config
    from module.device.device import Device

    config = Config('绘卷oas2')
    device = Device(config)
    t = BaseExploration(config, device)
    t.screenshot()
    t.fill_shikigami()

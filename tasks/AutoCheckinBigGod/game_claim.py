"""AutoCheckinBigGod 游戏内领取流程（大神福利中心）。

背景：2026-10 起网易调整发放链路，大神 APP 侧领取（API 或手动 UI）只是登记，
奖励真正到账需要在游戏内「福利中心」弹窗点击金色「领奖」按钮（API 侧领取返回
「请到游戏中查看任务完成进度，在游戏中领取奖励」即此原因，连每日礼包也是如此）。

导航链路（2026-10-04 实机确认，1280x720 横屏）：
庭院曜日牌 → 日程面板 → 右侧「通知」页签 → 「大神福利中心」横幅 → 「福利中心」弹窗
→ 逐个点「领奖」（弹「获得奖励」展示窗，点击任意处关闭，条目随之变「已达成」）
→ 关闭弹窗与面板 → 镜头还原。

要点：
- 曜日牌是挂在庭院场景里的物体，屏幕位置随皮肤与镜头变化：默认庭院为左侧石碑
  （无需动镜头）；部分皮肤（如盈空月）默认镜头下不可见，需向左平移镜头。牌上
  文字首字随星期变化（日曜/月曜/…），模板只取稳定不变的「曜」字，且不同皮肤
  美术不同（石碑/挂轴各一个模板）。
- 「福利中心」弹窗条目右侧状态：金色「领奖」=可领取；「已达成」红章=已到账；
  红字「进行中」=未完成。
- 位置会变的目标（曜日牌/横幅/领奖按钮）用 match_all_any 匹配后点击命中位置，
  不能用 appear_then_click（它点击的是 roi_front 坐标）。
- 本流程全程自捕获异常，失败只记日志，不影响任务本身成败；未领完的条目会在
  下次任务运行时重试（游戏内领取状态由服务端保留）。
"""
import time

from module.logger import logger
from module.base.timer import Timer
from tasks.AutoCheckinBigGod.assets import AutoCheckinBigGodAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.GlobalGame.assets import GlobalGameAssets

# 等待回到庭院的超时（游戏一般已在后台驻留；冷启动登录不在本流程范围内）
YARD_WAIT_SECONDS = 120
# 向左平移镜头查找曜日牌的最大次数（每次一屏）
PAN_MAX = 3
# 通知页 / 福利中心弹窗内滚动查找的最大次数
SCROLL_MAX = 3
# 领奖点击硬上限，防异常界面死循环
CLAIM_CLICK_MAX = 20


class GameClaimMixin(AutoCheckinBigGodAssets, GlobalGameAssets, GameUiAssets):
    """游戏内领取大神福利混入类。依赖宿主(BaseTask)的 screenshot/appear/device。

    继承 AutoCheckinBigGodAssets 以便通过 self.I_GAME_* 访问本任务资产
    （宿主 ScriptTask 未直接继承该资产类，manual_claim 路径是经类名 A.I_* 访问的）；
    I_CHECK_MAIN / I_UI_REWARD 由 BaseTask(CostumeBase) 提供。"""

    def _run_game_claim(self):
        """游戏内领取入口：捕获全部异常，失败只记日志，不影响任务成败。"""
        logger.hr('游戏内领取大神福利', level=2)
        try:
            self._game_claim_run()
        except Exception as e:
            logger.warning(f'游戏内领取异常，跳过（待下次运行重试）: {e}')

    def _game_claim_run(self):
        if not self._game_wait_yard():
            logger.warning('未回到庭院，游戏内领取跳过')
            return
        opened, pan_count = self._game_open_schedule_panel()
        if not opened:
            logger.warning('未找到曜日牌/日程面板，游戏内领取跳过')
            self._game_restore_camera(pan_count)
            return
        logger.info('日程面板已打开')
        try:
            if not self._game_open_welfare_popup():
                logger.warning('未找到大神福利中心入口，游戏内领取跳过')
                return
            claimed = self._game_collect()
            logger.info(f'游戏内领取完成，共点击领奖 {claimed} 次')
        finally:
            try:
                self._game_close_welfare_popup()
            except Exception as e:
                logger.warning(f'关闭福利中心弹窗失败: {e}')
            try:
                self._game_close_schedule_panel()
            except Exception as e:
                logger.warning(f'关闭日程面板失败: {e}')
            self._game_restore_camera(pan_count)

    # ------------------------------------------------------------------ 步骤

    def _game_wait_yard(self):
        """把游戏拉回前台并等待庭院出现。返回是否成功。"""
        try:
            self.device.app_start()
        except Exception as e:
            logger.warning(f'拉起游戏失败: {e}')
        deadline = Timer(YARD_WAIT_SECONDS).start()
        while not deadline.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_MAIN, threshold=0.9):
                # 竖屏手动领取路径可能把 orientation 改为 0，游戏前台后重新获取
                try:
                    self.device.get_orientation()
                except Exception:
                    pass
                logger.info('已回到庭院')
                return True
            # 处理可能残留的「获得奖励」展示窗
            if self.ui_reward_appear_click():
                time.sleep(1)
                continue
            time.sleep(2)
        logger.warning(f'等待回到庭院超时（{YARD_WAIT_SECONDS}s）')
        return False

    def _game_open_schedule_panel(self):
        """查找庭院曜日牌并点击打开日程面板。返回 (是否成功, 镜头平移次数)。"""
        boards = (self.I_GAME_BOARD_STELE, self.I_GAME_BOARD_SCROLL)
        for attempt in range(PAN_MAX + 1):
            self.screenshot()
            match = self._game_match_any(boards)
            if match:
                score, x, y, w, h = match
                logger.info(f'找到曜日牌 ({x + w // 2},{y + h // 2})，点击打开日程面板')
                self.device.click(x + w // 2, y + h // 2, control_name='I_GAME_BOARD')
                if self._game_wait_appear((self.I_GAME_RICHENG_TAG, self.I_GAME_NOTICE_LANTERN), 8):
                    return True, attempt
                logger.info('点击曜日牌后日程面板未出现，继续查找')
            if attempt < PAN_MAX:
                logger.info('未找到曜日牌，向左平移镜头后重试')
                self.device.swipe((200, 400), (900, 400))
                time.sleep(2)
        return False, PAN_MAX

    def _game_open_welfare_popup(self):
        """在日程面板内切到通知页并打开大神福利中心弹窗。"""
        for attempt in range(SCROLL_MAX + 1):
            self.screenshot()
            if self.appear(self.I_GAME_NOTICE_LANTERN):
                self.appear_then_click(self.I_GAME_NOTICE_LANTERN)
                time.sleep(1.5)
            self.screenshot()
            match = self._game_match_any((self.I_GAME_DS_BANNER,))
            if match:
                score, x, y, w, h = match
                logger.info(f'找到大神福利中心横幅 ({x + w // 2},{y + h // 2})，点击进入')
                self.device.click(x + w // 2, y + h // 2, control_name='I_GAME_DS_BANNER')
                if self._game_wait_appear((self.I_GAME_WELFARE_TITLE,), 10):
                    return True
                logger.info('点击横幅后福利中心弹窗未出现，重试')
            if attempt < SCROLL_MAX:
                logger.info('通知页向下滚动查找大神福利中心横幅')
                self.device.swipe((420, 560), (420, 250))
                time.sleep(1.5)
        return False

    def _game_collect(self):
        """在福利中心弹窗内逐个点击「领奖」。返回点击次数。"""
        claimed = 0
        for _ in range(CLAIM_CLICK_MAX):
            self.screenshot()
            # 先处理残留的「获得奖励」展示窗
            if self.ui_reward_appear_click():
                time.sleep(1)
                continue
            matches = self.I_GAME_CLAIM_BTN.match_all_any(self.device.image)
            if not matches:
                if self._game_scroll_popup():
                    continue
                break
            matches.sort(key=lambda m: m[2])
            score, x, y, w, h = matches[0]
            logger.info(f'点击领奖按钮 @ ({x + w // 2},{y + h // 2})')
            self.device.click(x + w // 2, y + h // 2, control_name='I_GAME_CLAIM_BTN')
            claimed += 1
            # 等「获得奖励」展示窗出现并点掉；条目随后变「已达成」
            if self._game_wait_appear((self.I_UI_REWARD,), 10):
                for _ in range(10):
                    self.screenshot()
                    if not self.appear(self.I_UI_REWARD, threshold=0.6):
                        break
                    self.ui_reward_appear_click()
                    time.sleep(1)
            else:
                logger.info('未出现获得奖励展示窗，继续扫描')
            time.sleep(1)
        return claimed

    def _game_scroll_popup(self):
        """福利中心列表向下滚动一屏；内容无变化（已到底）返回 False。"""
        before = [m[2] for m in self.I_GAME_CLAIM_DONE.match_all_any(self.device.image)]
        self.device.swipe((540, 600), (540, 280))
        time.sleep(1.5)
        self.screenshot()
        after = [m[2] for m in self.I_GAME_CLAIM_DONE.match_all_any(self.device.image)]
        if before == after:
            logger.info('福利中心列表已到底')
            return False
        return True

    def _game_close_welfare_popup(self):
        """关闭福利中心弹窗。"""
        for _ in range(3):
            self.screenshot()
            if not self.appear(self.I_GAME_WELFARE_TITLE):
                return True
            if self.appear_then_click(self.I_GAME_POPUP_CLOSE):
                time.sleep(1.5)
            else:
                time.sleep(1)
        logger.warning('福利中心弹窗关闭失败')
        return False

    def _game_close_schedule_panel(self):
        """关闭日程面板。"""
        for _ in range(3):
            self.screenshot()
            if not (self.appear(self.I_GAME_RICHENG_TAG) or self.appear(self.I_GAME_NOTICE_LANTERN)):
                return True
            if self.appear_then_click(self.I_GAME_PANEL_CLOSE):
                time.sleep(1.5)
            else:
                time.sleep(1)
        logger.warning('日程面板关闭失败')
        return False

    def _game_restore_camera(self, pan_count):
        """把镜头平移回默认位置（向右等量补偿）。"""
        if pan_count <= 0:
            return
        logger.info(f'镜头还原：向右平移 {pan_count} 次')
        for _ in range(pan_count):
            self.device.swipe((900, 400), (200, 400))
            time.sleep(1.5)

    # ------------------------------------------------------------------ 工具

    def _game_match_any(self, assets):
        """返回第一个有匹配的资产中得分最高的 (score, x, y, w, h)，无匹配返回 None。"""
        best = None
        for asset in assets:
            matches = asset.match_all_any(self.device.image)
            for m in matches:
                if best is None or m[0] > best[0]:
                    best = m
        return best

    def _game_wait_appear(self, assets, timeout):
        """轮询截图等待任一资产出现。"""
        deadline = Timer(timeout).start()
        while not deadline.reached():
            self.screenshot()
            for asset in assets:
                if self.appear(asset):
                    return True
            time.sleep(1)
        return False

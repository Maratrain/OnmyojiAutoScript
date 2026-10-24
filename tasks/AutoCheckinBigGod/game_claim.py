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
- 收尾以「回到庭院」为唯一成功判据循环清理残留弹层：领奖可能弹出 I_UI_REWARD
  识别不到的变体奖励窗盖住全部判据，单次 appear 判断会误判「已关闭」而留下脏
  界面带崩下一个任务（2026-10-23 实机案例）。
- 本流程全程自捕获异常，失败只记日志，不影响任务本身成败；未领完的条目会在
  下次任务运行时重试（游戏内领取状态由服务端保留）。
"""
import time

from module.logger import logger
from module.base.timer import Timer
from tasks.AutoCheckinBigGod.assets import AutoCheckinBigGodAssets
from tasks.Component.Login.service import LoginService
from tasks.Component.SwitchAccount.assets import SwitchAccountAssets
from tasks.GameUi.assets import GameUiAssets
from tasks.GlobalGame.assets import GlobalGameAssets

# 等待回到庭院的超时（模拟器关停后冷启动需走完整登录流程，实机约 2 分钟，放宽到 4 分钟兜底）
YARD_WAIT_SECONDS = 240
# 向左平移镜头查找曜日牌的最大次数（每次一屏）
PAN_MAX = 3
# 通知页 / 福利中心弹窗内滚动查找的最大次数
SCROLL_MAX = 3
# 领奖点击硬上限，防异常界面死循环
CLAIM_CLICK_MAX = 20
# 收尾清理回到庭院的超时
CLOSE_YARD_SECONDS = 30
# 收尾中点未知弹层右上角关闭键的次数上限（防止对同一按钮连点触发保护）
CLOSE_UNKNOWN_MAX = 3


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
                self._game_close_after_claim(pan_count)
            except Exception as e:
                logger.warning(f'收尾清理异常: {e}')
                try:
                    self._game_restore_camera(pan_count)
                except Exception:
                    pass

    # ------------------------------------------------------------------ 步骤

    def _game_wait_yard(self):
        """把游戏拉回前台并等待庭院出现，冷启动落在登录页时顺带走完登录。返回是否成功。"""
        try:
            self.device.app_start()
        except Exception as e:
            logger.warning(f'拉起游戏失败: {e}')
        # 竖屏手动领取路径可能把 orientation 改为 0，游戏前台后重新获取（登录点击也依赖正确朝向）
        try:
            self.device.get_orientation()
        except Exception:
            pass
        deadline = Timer(YARD_WAIT_SECONDS).start()
        while not deadline.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_MAIN, threshold=0.9):
                logger.info('已回到庭院')
                return True
            # 冷启动停在登录页：复用登录流程走到庭院（进入游戏/加载/公告/式神录确认都在其中）
            if self.appear(SwitchAccountAssets.I_CHECK_LOGIN_FORM):
                logger.info('检测到登录页，执行登录流程')
                LoginService(config=self.config, device=self.device).app_handle_login()
                continue
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
                # 弹窗被未知弹层盖住时标题不可见，滑动无意义，直接交给收尾清理
                if self.appear(self.I_GAME_WELFARE_TITLE) and self._game_scroll_popup():
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

    def _game_close_after_claim(self, pan_count):
        """收尾清理：循环关闭残留弹层，以回到庭院为唯一成功判据。

        2026-10-23 08:03 实机案例：第三个领奖点击后弹出一个 I_UI_REWARD
        识别不到的变体奖励窗，盖住了福利中心弹窗与日程面板。旧收尾各自只做
        一次 appear 判断，标题/庭院元素被盖住即误判「已关闭」，未发任何点击
        就结束任务，脏界面导致下一个任务导航失败触发整进程重启。
        现逐层关闭：未知弹层右上角关闭键 → 福利中心红色关闭钮 → 日程面板
        紫色关闭钮 → 标准获得奖励展示窗，每轮重新截图确认，超时未回到庭院
        则告警，不再静默放行。"""
        logger.info('开始收尾清理，目标回到庭院')
        # 镜头先还原：平移过的镜头会让庭院判定失效，必须先回到默认视角再验证
        self._game_restore_camera(pan_count)
        deadline = Timer(CLOSE_YARD_SECONDS).start()
        unknown_clicks = 0
        while not deadline.reached():
            self.screenshot()
            if self.appear(self.I_CHECK_MAIN, threshold=0.9):
                logger.info('收尾完成，已回到庭院')
                return
            # 福利中心弹窗：标题可见时优先点它自己的红色关闭钮
            # （其下层日程面板的紫色 X 会被弹窗压暗误匹配，必须先关弹窗）
            if self.appear(self.I_GAME_WELFARE_TITLE):
                self.appear_then_click(self.I_GAME_POPUP_CLOSE)
                time.sleep(1.5)
                continue
            # 日程面板（紫色 X 关闭按钮）
            if self.appear_then_click(self.I_GAME_PANEL_CLOSE):
                time.sleep(1.5)
                continue
            # 标准获得奖励展示窗
            if self.ui_reward_appear_click():
                time.sleep(1)
                continue
            # 变体奖励窗等带右上角关闭键的未知弹层，限量点击防连点保护
            if unknown_clicks < CLOSE_UNKNOWN_MAX and self.appear(self.I_UI_BACK_RED):
                self.appear_then_click(self.I_UI_BACK_RED)
                unknown_clicks += 1
                time.sleep(1.5)
                continue
            time.sleep(1)
        logger.warning(f'收尾清理超时（{CLOSE_YARD_SECONDS}s）未回到庭院，'
                       f'界面可能残留弹窗，下一个任务可能导航失败触发重启恢复')

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

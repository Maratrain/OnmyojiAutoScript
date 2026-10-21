# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from module.base.timer import Timer
from module.exception import RequestHumanTakeover, GameTooManyClickError, GameStuckError
from module.logger import logger
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.chess_battle import ChessBattleNavigationMixin
from tasks.Restart.assets import RestartAssets
from tasks.base_task import BaseTask

# 登录期间 MPay 弹窗「关掉又重弹」的容忍上限，超过说明回车已走不出去，交 Restart 重建
DESKTOP_MPAY_CLOSE_LIMIT = 5


class LoginService(
    ChessBattleNavigationMixin,
    BaseTask,
    RestartAssets,
    GameUiAssets,
):
    character: str

    def __init__(self, *wargs, **kwargs):
        super().__init__(*wargs, **kwargs)
        self.character = self.config.restart.login_character_config.character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = self.character

    def _app_handle_login(self) -> bool:
        """
        最终是在庭院界面
        :return:
        """
        logger.hr('应用登录')
        self.device.stuck_record_add('LOGIN_CHECK')

        confirm_timer = Timer(1.5, count=2).start()
        orientation_timer = Timer(10)
        skip_login_animation = True
        skip_click_mx_cnt = 5
        enter_game_fallback_used = False
        login_success = False
        # 本次登录已处理过的 MPay 弹窗次数，用于给「关掉又重弹」封顶
        popup_handled = 0

        def handle_desktop_login_popup() -> bool:
            """登录期间处理 MPay 弹窗，返回是否刚关闭了弹窗。

            MPay 是独立顶层窗口，主窗口截图识别不到，只能按 HWND 枚举检查。
            """
            nonlocal popup_handled
            if not self.device.is_desktop or not self.device.find_desktop_login_popup():
                return False
            popup_handled += 1
            if popup_handled > DESKTOP_MPAY_CLOSE_LIMIT:
                raise GameStuckError(
                    f'[登录] 桌面端 MPay 登录弹窗反复出现超过 {DESKTOP_MPAY_CLOSE_LIMIT} 次')
            if not self.device.desktop_confirm_login_popup():
                # 弹窗可能恰好在确认函数最后一次枚举后自行关闭，重新确认避免误判卡死
                if not self.device.find_desktop_login_popup():
                    return True
                # 弹窗仍存活时不能继续识别页面，否则 MPay 会被当成未知页面
                raise GameStuckError('[登录] 桌面端 MPay 登录弹窗无法关闭')
            return True

        while 1:
            # MPay 可能在启动后、重登时或登录中途反复出现，每轮都要处理
            if handle_desktop_login_popup():
                continue
            if not login_success and orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

            self.screenshot()
            # 截图与窗口枚举有竞态，截图后再查一次，避免刚出现的 MPay 进入图像识别
            if handle_desktop_login_popup():
                continue
            # 取消“返回中断的棋局战斗”，改走棋局结算流程
            if self.appear_then_click(self.I_RETURN_CHESS_CANCEL, interval=0.8):
                logger.info('[登录] 取消返回中断的棋局战斗，等待结算流程')
                continue
            # 恢复登录时若直接落在棋局大厅或残留结算页，在此清理后即算恢复完成
            if self.appear(self.I_CHECK_CHESS):
                logger.info('[登录] 恢复登录到达棋局大厅，无需返回庭院')
                return True
            if self.chess_result_flow_visible():
                logger.info('[登录] 恢复登录检测到未完成的棋局结算流程')
                self.return_to_chess_lobby()
                return True
            if self.appear_then_click(self.I_UI_CANCEL_SAMLL, interval=0.8):
                logger.info('[登录] 取消继续战斗')
                continue
            if self.appear(self.I_CHECK_MAIN, interval=0.2) and not self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS):
                logger.info('[登录] 庭院已出现，但式神录按钮尚未出现')
                skip_login_animation = False
                if self.click(self.C_LOGIN_SCROLL_CLOSE_AREA, interval=2):
                    continue
            if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, interval=0.2):
                if confirm_timer.reached():
                    logger.info('[登录] 确认登录到庭院（式神录按钮已出现）')
                    break
            else:
                confirm_timer.reset()
            if self.appear(self.I_MAIN_GOTO_SHIKIGAMI_RECORDS, interval=0.5):
                logger.info('[登录] 登录成功：式神录按钮已出现')
                login_success = True
                skip_login_animation = False
            if self.appear(self.I_HARVEST_ZIDU, interval=1):
                self.I_HARVEST_ZIDU.roi_front[0] -= 200
                self.I_HARVEST_ZIDU.roi_front[1] -= 200
                if self.click(self.I_HARVEST_ZIDU, interval=2):
                    logger.info('[登录] 关闭 zidu 弹窗')
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=2.5):
                logger.info('[登录] 御魂溢出确认')
                continue
            if self.appear_then_click(self.I_LOGIN_LOAD_DOWN, interval=1):
                logger.info('[登录] 下载补间动画')
                continue
            if self.appear_then_click(self.I_UI_CANCEL_SAMLL, interval=0.6):
                logger.info('[登录] 关闭视频')
                continue
            if self.appear_then_click(self.I_LOGIN_RED_CLOSE, interval=0.6):
                logger.info('[登录] 点击红色关闭按钮')
                continue
            if self.appear_then_click(self.I_LOGIN_YELLOW_CLOSE, interval=0.6):
                logger.info('[登录] 点击黄色关闭按钮')
                continue
            if self.appear_then_click(self.I_LOGIN_LOGIN_GOTO_BIND_PHONE):
                while 1:
                    self.screenshot()
                    if self.appear_then_click(self.I_UI_CANCEL_SAMLL):
                        logger.info("[登录] 关闭绑定手机弹窗")
                        break
                continue
            from tasks.Component.GeneralInvite.assets import GeneralInviteAssets as gia
            if self.appear_then_click(gia.I_I_REJECT, interval=0.8):
                logger.info("[登录] 拒绝邀请")
                continue
            if self.appear_then_click(self.I_LOGIN_LOGIN_ONMYOJI_GENIE):
                logger.info("[登录] 点击阴阳师精灵")
                continue
            if self.appear(self.I_LOGIN_SPECIFIC_SERVE, interval=0.6) \
                    and self.ocr_appear_click(self.O_LOGIN_SPECIFIC_SERVE, interval=0.6):
                while True:
                    self.screenshot()
                    if self.appear(self.I_LOGIN_SPECIFIC_SERVE):
                        self.click(self.C_LOGIN_ENSURE_LOGIN_CHARACTER_IN_SAME_SVR, interval=2)
                        continue
                    break
                logger.info('[登录] 登录指定角色')
                continue

            if self.appear(self.I_CREATE_ACCOUNT):
                logger.warning('[登录] 出现创建账号界面')
                raise GameStuckError('Appear create account')
            if self.appear(self.I_CHARACTARS, interval=1):
                logger.info('误入区服设置')
                self.device.click(x=106, y=535)
                continue
            if self.appear(self.I_EARLY_SERVER) and self.appear_then_click(self.I_EARLY_SERVER_CANCEL):
                logger.info('[登录] 取消从体验服切换到正式服')
                continue

            # 进入登录页面后或点击超过一定次数不再处理登录动画逻辑
            if self.appear(self.I_LOGIN_8, interval=0.6) or skip_click_mx_cnt <= 0:
                skip_login_animation = False
            if skip_login_animation:
                if self.ocr_appear_click(self.O_LOGIN_ANIMATION_SKIP, interval=2.5):  # 点击跳过登录动画
                    continue
                if self.click(self.C_LOGIN_ANIMATION_CENTER, interval=5):  # 点击屏幕中央触发跳过显示
                    skip_click_mx_cnt -= 1

            if self.ocr_appear_click(self.O_LOGIN_ENTER_GAME, interval=3):
                skip_login_animation = False  # 进入登录页面后不再处理登录动画逻辑
                self.wait_until_appear(self.I_LOGIN_SPECIFIC_SERVE, True, wait_time=5)
                continue
            # OCR 未识别到进入游戏且确认仍在登录页时，每次登录仅备用点击一次。
            # appear 不带 interval 复核，避免把 OCR 的冷却期误当作识别失败。
            if (
                not enter_game_fallback_used
                and self.appear(self.I_LOGIN_8)
                and not self.ocr_appear(self.O_LOGIN_ENTER_GAME)
            ):
                if self.click(self.C_LOGIN_ENTER_GAME, interval=3):
                    enter_game_fallback_used = True
                    skip_login_animation = False
                    logger.info('[登录] 进入游戏 OCR 识别失效，使用保底点击')
                    self.wait_until_appear(self.I_LOGIN_SPECIFIC_SERVE, True, wait_time=5)
                    continue

        return login_success

    def app_handle_login(self) -> bool:
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        try:
            self._app_handle_login()
            # 桌面：登录成功后标记登录态，app_is_running 才会判定为已在游戏中
            if self.device.is_desktop:
                self.device.desktop_mark_logged_in()
            return True
        except (GameTooManyClickError, GameStuckError) as e:
            logger.warning(e)
            self.device.app_stop()
            self.device.app_start()

        logger.critical('[登录] 登录失败')
        logger.critical('[登录] 阴阳师服务器可能正在维护，或者网络连接已断开')
        raise RequestHumanTakeover

    def set_specific_usr(self, character: str):
        self.character = character
        self.O_LOGIN_SPECIFIC_SERVE.keyword = character

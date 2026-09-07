# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from module.base.timer import Timer
from module.exception import RequestHumanTakeover, GameTooManyClickError, GameStuckError
from module.logger import logger
from tasks.GameUi.assets import GameUiAssets
from tasks.Restart.assets import RestartAssets
from tasks.base_task import BaseTask


class LoginService(BaseTask, RestartAssets, GameUiAssets):
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
        login_success = False

        while 1:
            if not login_success and orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

            self.screenshot()
            if self.appear_then_click(self.I_CANCEL_BATTLE, interval=0.8):
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
            if self.appear_then_click(self.I_WATCH_VIDEO_CANCEL, interval=0.6):
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
                    if self.appear_then_click(self.I_LOGIN_LOGIN_CANCEL_BIND_PHONE):
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

        return login_success

    def app_handle_login(self) -> bool:
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        try:
            self._app_handle_login()
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

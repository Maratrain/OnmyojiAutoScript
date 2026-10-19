# This Python file uses the following encoding: utf-8
from module.base.timer import Timer
from module.logger import logger

from tasks.base_task import BaseTask
from tasks.GameUi.page import page_main, page_secret_zones
from tasks.WeeklyTrifles.assets import WeeklyTriflesAssets


class SecretShare(BaseTask, WeeklyTriflesAssets):
    """
    秘闻分享通用流程，由任务类混入使用（需具备庭院导航能力，如 GameUi）
    每周琐事的「秘闻分享」与秘闻副本打完第十层后的分享共用本套逻辑
    """

    def enter_secret_share(self) -> bool:
        """
        从秘闻入口一路点到微信分享按钮出现
        :return: 是否到达微信分享界面
        """
        valid = False
        timeout = Timer(30).start()
        while 1:
            if timeout.reached():
                logger.warning('[秘闻分享] 等待分享界面超时，跳过')
                return False
            self.screenshot()
            if self.appear(self.I_WT_SE_WECHAT):
                self.wait_until_stable(self.I_WT_SE_WECHAT, skip_first_screenshot=True)
                return True
            if self.appear_then_click(self.I_WT_ENTER_SE, interval=1):
                continue
            if self.appear_then_click(self.I_WT_SE_SHARE, interval=5):
                valid = True
                continue
            if self.appear(self.I_WT_SE_RANK) and not valid:
                # 出现排行却没有分享按钮，说明本周尚未通关秘闻
                self.wait_until_stable(self.I_WT_SE_SHARE, skip_first_screenshot=True)
                if self.appear(self.I_WT_SE_SHARE):
                    continue
                logger.warning('[秘闻分享] 本周尚未通关秘闻，无法分享')
                return False

    def click_share(self, wechat) -> bool:
        """
        点击微信分享按钮，出现二维码后完成分享并领取奖励
        :param wechat: 微信分享按钮资产
        :return: 是否领取到奖励
        """
        appeared = self.ui_click_until_appear_or_timeout(wechat, self.I_WT_QR_CODE, 2.5, 10)
        if not appeared:
            logger.warning('[秘闻分享] 未出现二维码，跳过分享')
            return False
        logger.info('[秘闻分享] 点击分享')
        get_timer = Timer(7).start()
        while 1:
            self.screenshot()
            if self.ui_reward_appear_click():
                logger.info('[秘闻分享] 获得奖励')
                return True
            if self.appear_then_click(self.I_WT_QR_CODE, self.C_WT_WECHAT, interval=4.8):
                continue
            if get_timer.reached():
                logger.warning('[秘闻分享] 分享等待超时，奖励可能已获得')
                return False

    def share_secret_inplace(self) -> bool:
        """
        已停在秘闻副本界面（分享按钮就在当前页面上）时就地完成分享，不回庭院重新进入
        秘闻副本的任务结束后页面就在这里，再退出去从入口重进一遍纯属绕路
        :return: 是否完成分享（本周已领取也算完成）
        """
        logger.hr('秘闻分享', 2)
        self.screenshot()
        if not self.appear(self.I_WT_SE_SHARE):
            logger.warning('[秘闻分享] 当前界面没有秘闻分享按钮，跳过')
            return False
        if not self.ui_click_until_appear_or_timeout(self.I_WT_SE_SHARE, self.I_WT_SE_WECHAT, 1, 10):
            logger.warning('[秘闻分享] 未出现微信分享界面，跳过')
            return False
        self.screenshot()
        if not self.appear(self.I_WT_SE_JADE):
            logger.warning('[秘闻分享] 本周奖励已领取')
            return True
        return self.click_share(self.I_WT_SE_WECHAT)

    def share_secret(self) -> None:
        """
        秘闻分享：庭院 → 秘闻副本入口 → 进入 → 微信分享
        """
        logger.hr('秘闻分享', 2)
        self.goto_page(page_secret_zones)
        if not self.enter_secret_share():
            self.goto_page(page_main)
            return
        self.screenshot()
        if not self.appear(self.I_WT_SE_JADE):
            logger.warning('[秘闻分享] 本周奖励已领取')
        else:
            self.click_share(self.I_WT_SE_WECHAT)
        self.goto_page(page_main)

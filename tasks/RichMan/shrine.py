# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from module.logger import logger
from module.base.timer import Timer

from tasks.GameUi.page import page_main, page_summon
from tasks.GameUi.game_ui import GameUi
from tasks.RichMan.assets import RichManAssets
from tasks.RichMan.config import Shrine as ConfigShrine


class Shrine(GameUi, RichManAssets):

    def execute_shrine(self, con: ConfigShrine):
        logger.hr('开始神社')
        if not con.enable:
            logger.info('[大富翁] 神社未启用')
            return
        self.goto_page(page_summon)

        while 1:
            self.screenshot()
            if self.appear(self.I_S_NEXT_PERIOD):
                break
            if self.appear_then_click(self.I_S_SUMMON_TO_SHRINE, interval=2):
                continue
        logger.info('[大富翁] 进入神社')
        time.sleep(0.5)
        if con.black_daruma:
            self.shrine_black_daruma()
        if con.white_daruma_five:
            self.shrine_white_five()
        if con.white_daruma_four:
            self.shrine_white_four()

    def shrine_check_money(self, mix: int) -> bool:
        self.screenshot()
        current = self.O_TT_TOTOL.ocr(self.device.image)
        if not isinstance(current, int):
            logger.warning('[大富翁] 当前货币识别失败')
            return False
        if current >= mix:
            logger.info('[大富翁] 货币足够')
            return True
        logger.info('[大富翁] 货币不足')
        return False

    def _check_bought(self, target) -> bool:
        """
        检查是否已经购买, 弃用，无法识别任何文字
        :return: True 已经购买
        """
        self.screenshot()
        result = target.ocr(self.device.image)
        if '已' in result or '兑' in result or '换' in result:
            logger.info('[大富翁] 已购买')
            return True
        logger.info('[大富翁] 未购买')
        return False

    def shrine_black_daruma(self):
        logger.hr('神社黑达摩', 2)
        self.screenshot()
        if not self.shrine_check_money(1500):
            return
        if not self.appear(self.I_S_BLACK):
            logger.info('[大富翁] 黑达摩已购买')
            return
        # 限时重试循环: 确认/购买/商品逐层点, 弹出奖励即领;
        # 确认弹窗慢一拍不会再被误判成已购买
        timer = Timer(10).start()
        while 1:
            self.screenshot()
            if timer.reached():
                logger.warning('[大富翁] 黑达摩购买等待超时')
                break
            if self.ui_reward_appear_click():
                logger.info('[大富翁] 领取购买奖励')
                break
            if self.appear_then_click(self.I_S_CONFIRM_BLACK, interval=1):
                continue
            if self.appear_then_click(self.I_S_BUY_BLACK, interval=1):
                continue
            if self.appear_then_click(self.I_S_BLACK, interval=2.5):
                continue
        self.ui_click_until_disappear(self.I_UI_BACK_RED)
        time.sleep(1)

    def shrine_white_five(self):
        logger.hr('神社五星白蛋', 2)
        self.screenshot()
        if not self.appear(self.I_S_WHITE_FIVE):
            logger.info('[大富翁] 五星白蛋未上架')
            return
        if not self.shrine_check_money(1200):
            return
        # 限时重试循环, 同黑达摩
        timer = Timer(10).start()
        while 1:
            self.screenshot()
            if timer.reached():
                logger.warning('[大富翁] 五星白蛋购买等待超时')
                break
            if self.ui_reward_appear_click():
                logger.info('[大富翁] 领取购买奖励')
                break
            if self.appear_then_click(self.I_S_CONFIRM_WHITE_FIVE, interval=1):
                continue
            if self.appear_then_click(self.I_S_BUY_WHITE_FIVE, interval=1):
                continue
            if self.appear_then_click(self.I_S_WHITE_FIVE, interval=2.5):
                continue
        self.ui_click_until_disappear(self.I_UI_BACK_RED)
        time.sleep(1)

    def shrine_white_four(self):
        logger.hr('神社四星白蛋', 2)
        self.screenshot()
        if not self.appear(self.I_S_WHITE_FOUR):
            logger.info('[大富翁] 四星白蛋未上架')
            return
        if not self.shrine_check_money(400):
            return
        # 限时重试循环, 同黑达摩
        timer = Timer(10).start()
        while 1:
            self.screenshot()
            if timer.reached():
                logger.warning('[大富翁] 四星白蛋购买等待超时')
                break
            if self.ui_reward_appear_click():
                logger.info('[大富翁] 领取购买奖励')
                break
            if self.appear_then_click(self.I_S_CONFIRM_WHITE_FOUR, interval=1):
                continue
            if self.appear_then_click(self.I_S_BUY_WHITE_FOUR, interval=1):
                continue
            if self.appear_then_click(self.I_S_WHITE_FOUR, interval=2.5):
                continue
        self.ui_click_until_disappear(self.I_UI_BACK_RED)
        time.sleep(1)



if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = Shrine(c, d)

    # t.shrine_white_four()
    t.execute_shrine(t.config.model.rich_man.shrine)
    # t.screenshot()
    # print(t.appear(t.I_S_BUY_WHITE_FIVE, threshold=0.9))



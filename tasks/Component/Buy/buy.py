# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from tasks.GameUi.page import random_click
from typing import Union

from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.atom.click import RuleClick
from module.logger import logger
from module.base.timer import Timer

from tasks.base_task import BaseTask
from tasks.Component.Buy.assets import BuyAssets

class Buy(BaseTask, BuyAssets):

    def buy_one(self, start_click: Union[RuleImage, RuleOcr, RuleClick],
                check_image: RuleImage):
        """
        购买一个物品
        :param check_image: 购买确认时候的图片
        :param start_click: 开始点击
        :return:
        """
        while 1:
            self.screenshot()

            if self.appear(check_image):
                break

            if isinstance(start_click, RuleImage):
                if self.appear_then_click(start_click, interval=1):
                    continue
            elif isinstance(start_click, RuleOcr):
                if self.ocr_appear_click(start_click, interval=1):
                    continue
            elif isinstance(start_click, RuleClick):
                if self.click(start_click, interval=1):
                    continue
        while 1:
            self.screenshot()

            if self.appear(self.I_BUY_RMB):
                # 用人民币购买的，就取消
                logger.warning('[购买] 脚本不支持人民币购买，已取消')
                while 1:
                    self.screenshot()
                    if not self.appear(self.I_BUY_RMB):
                        break
                    if self.click(self.C_BUY_CANCEL, interval=1):
                        continue
                return False

            if self.appear(self.I_BUY_SUCCESS):
                self.ui_click_until_smt_disappear(random_click(), self.I_BUY_SUCCESS, interval=0.8)
                logger.info('[购买] 获取奖励成功')
                break

            if self.ui_reward_appear_click():
                while 1:
                    self.screenshot()
                    # 等待动画结束
                    if not self.appear(self.I_UI_REWARD, threshold=0.6):
                        logger.info('[购买] 获取奖励成功')
                        break
                    # 一直点击
                    if self.ui_reward_appear_click():
                        continue
                break

            if self.click(self.C_BUY_ONE, interval=2.8):
                continue

        return True

    def buy_more(self, start_click: Union[RuleImage, RuleOcr, RuleClick],
                 number: int = None):
        """
        购买多个物品
        :param start_click:
        :param number: 不指定就是拉满
        :return:
        """
        try_click_count = 0
        while 1:
            self.screenshot()

            if self.appear(self.I_BUY_PLUS):
                break
            if try_click_count >= 5:
                logger.warning(f'[购买] 批量购买失败，已尝试点击次数: {try_click_count}')
                logger.warning('[购买] 关闭购买界面')
                return

            if isinstance(start_click, RuleImage):
                if self.appear_then_click(start_click, interval=1):
                    try_click_count += 1
                    continue
            elif isinstance(start_click, RuleOcr):
                if self.ocr_appear_click(start_click, interval=1):
                    try_click_count += 1
                    continue
            elif isinstance(start_click, RuleClick):
                if self.click(start_click, interval=1):
                    try_click_count += 1
                    continue
        # 设置购买的数量
        if number is None:
            self.appear_then_click(self.I_BUY_PLUS, interval=0.4)
            time.sleep(0.5)
            self.appear_then_click(self.I_BUY_PLUS, interval=0.4)
        else:
            # 四次截图数字都一样，就可以退出了
            number_record = []
            ocr_timer = Timer(0.8)
            ocr_timer.start()
            while 1:
                self.screenshot()

                if self.appear_then_click(self.I_BUY_ADD, interval=0.8):
                    continue

                if not ocr_timer.reached():
                    continue
                ocr_timer.reset()
                current = self.O_BUY_NUMBER.ocr(self.device.image)
                if current >= number:
                    break
                if current == 0:
                    logger.warning(f'[购买] OCR 识别当前数量失败: {current}')
                number_record.append(current)
                if len(number_record) >= 4:
                    if number_record[0] == number_record[1] == number_record[2] == number_record[3]:
                        break
                    number_record.pop(0)

        buy_more_mx_click = 5

        # 购买确认
        while 1:
            self.screenshot()

            if self.ui_reward_appear_click():
                time.sleep(0.5)
                while 1:
                    self.screenshot()
                    # 等待动画结束
                    if not self.appear(self.I_UI_REWARD, threshold=0.6):
                        logger.info('[购买] 获取奖励成功')
                        break
                    # 一直点击
                    if self.ui_reward_appear_click():
                        continue
                break

            if buy_more_mx_click <= 0:
                logger.warning('[购买] 批量购买点击次数已达上限')
                return False

            # 如果这个购买已达上限
            if self.appear(self.I_UI_CONFIRM_SAMLL):
                self.ui_click_until_disappear(self.I_UI_CONFIRM_SAMLL, interval=1)
                logger.warning('[购买] 购买数量已达上限')
                return False

            if self.click(self.C_BUY_MORE, interval=2):
                buy_more_mx_click -= 1
                continue

    def buy_check_money(self, target: RuleOcr, minimum: int):
        """
        检查钱是否足够
        :param target:
        :param minimum:
        :return:
        """
        self.screenshot()
        if not isinstance(target, RuleOcr):
            logger.error('[购买] 识别目标不是 RuleOcr 类型')
            return False
        current = target.ocr(self.device.image)
        if not isinstance(current, int):
            logger.warning('[购买] OCR 识别当前货币数量失败')
            return False
        if current >= minimum:
            logger.info('[购买] 货币数量足够')
            return True
        logger.info('[购买] 货币数量不足')
        return False



if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = Buy(c, d)


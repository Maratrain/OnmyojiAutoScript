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
                 number: int = None) -> bool:
        """
        购买多个物品
        :param start_click:
        :param number: 不指定就是拉满
        :return: True 购买完成 / False 购买失败
        """
        try_click_count = 0
        while 1:
            self.screenshot()

            if self.appear(self.I_BUY_PLUS):
                break
            if try_click_count >= 5:
                logger.warning(f'[购买] 批量购买失败，已尝试点击次数: {try_click_count}')
                logger.warning('[购买] 关闭购买界面')
                return False

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
        return True

    def buy_one_or_more(self, start_click: Union[RuleImage, RuleOcr, RuleClick],
                        check_image: RuleImage, number: int = None,
                        max_price: int = None, money: int = None, remain: int = None) -> bool:
        """
        购买弹窗可能是单个购买窗口, 也可能是带数量选择(加号)的多数量购买窗口
        先点开弹窗, 出现加号走多数量购买, 出现单个购买窗口走 buy_one
        :param start_click: 开始点击
        :param check_image: 单个购买窗口确认时候的图片
        :param number: 多数量窗口的购买数量, 不指定就是拉满. 指定 max_price 时不用, 数量按 money 和 remain 算
        :param max_price: 单价上限, 不为 None 时先读确认按钮上的勾玉单价, 没有勾玉、读不到或超过上限就取消购买
        :param money: 当前余额, 指定 max_price 时用来算买得起几个
        :param remain: 剩余购买次数, 指定 max_price 时用来算购买数量
        :return: 超时没等到任何购买弹窗或取消购买返回 False
        """
        timeout = Timer(10).start()
        while 1:
            self.screenshot()

            if self.appear(self.I_BUY_PLUS):
                if max_price is not None:
                    return self._buy_with_price(start_click, check_image, True, max_price, money, remain)
                if number == 1:
                    # buy_more 指定数量时会先点一次加号再 OCR, 买 1 个会变成买 2 个
                    return self._buy_more_default(start_click)
                logger.info('[购买] 多数量购买窗口, 走 buy_more')
                return self.buy_more(start_click, number)
            if self.appear(check_image):
                if max_price is not None:
                    return self._buy_with_price(start_click, check_image, False, max_price, money, remain)
                logger.info('[购买] 单个购买窗口, 走 buy_one')
                return self.buy_one(start_click, check_image)
            if timeout.reached():
                logger.warning('[购买] 等待购买弹窗超时')
                return False

            if isinstance(start_click, RuleImage):
                if self.appear_then_click(start_click, interval=1):
                    continue
            elif isinstance(start_click, RuleOcr):
                if self.ocr_appear_click(start_click, interval=1):
                    continue
            elif isinstance(start_click, RuleClick):
                if self.click(start_click, interval=1):
                    continue

    def _buy_with_price(self, start_click: Union[RuleImage, RuleOcr, RuleClick], check_image: RuleImage,
                        more: bool, max_price: int, money: int, remain: int) -> bool:
        """
        购买弹窗已打开, 读确认按钮上的勾玉单价, 不超过上限才买
        :param more: True 为多数量购买窗口, False 为单个购买窗口
        :return: 买到返回 True, 取消购买或达到购买上限返回 False
        """
        price = self._buy_read_price()
        if price is None or price > max_price:
            logger.warning(f'[购买] 单价 {price} 读不到或超过上限 {max_price}, 取消购买')
            self._buy_cancel(check_image)
            return False
        if not more:
            logger.info(f'[购买] 单个购买窗口, 单价 {price}, 购买数量 1')
            return self.buy_one(start_click, check_image)
        if money is None or remain is None:
            # 没传余额或剩余次数时只买 1 个
            number = 1
        else:
            number = min(remain, money // price)
        logger.info(f'[购买] 单价 {price}, 余额 {money}, 剩余次数 {remain}, 购买数量 {number}')
        if number < 1:
            logger.warning('[购买] 余额不足购买 1 个, 取消购买')
            self._buy_cancel(check_image)
            return False
        if number == 1:
            return self._buy_more_default(start_click)
        if number == remain:
            return self.buy_more(start_click, None)
        # buy_more(start_click, number) 点加号后才读数量, 可能超过 number.
        # 余额不够买满时每次只买 1 个, 调用方循环会重新读余额和剩余次数再买下一个
        logger.info(f'[购买] 余额不足买满剩余 {remain}, 逐张购买')
        return self._buy_more_default(start_click)

    def _buy_read_price(self, min_price: int = 40) -> Union[int, None]:
        """
        读购买确认按钮上的勾玉单价: 先等勾玉图标出现, 再读图标右边的数字
        :param min_price: 单价下限, 低于它当作 OCR 读错(例如 90 少读一位成 9). 默认 40: 蓝票已知最低价 50, 留一点余量
        :return: 单价, 没有勾玉图标、读不到或低于下限返回 None
        """
        jade_timer = Timer(2).start()
        while 1:
            if self.appear(self.I_BUY_JADE):
                break
            if jade_timer.reached():
                logger.warning('[购买] 确认按钮上未找到勾玉图标, 可能不是勾玉支付')
                return None
            self.screenshot()
        x, y, w, h = self.I_BUY_JADE.roi_front
        # 只取图标右边, 裁剪框碰到图标会把图标读成 1, 例如 90 读成 190
        self.O_BUY_PRICE.roi = [x + w, y, 60, h]
        price = self.O_BUY_PRICE.ocr(self.device.image)
        try:
            price = int(price)
        except (TypeError, ValueError):
            price = 0
        if price == 0:
            # Digit 读不到时返回 0
            logger.warning('[购买] OCR 读取单价失败')
            return None
        if price < min_price:
            logger.warning(f'[购买] 单价 {price} 低于下限 {min_price}, 按 OCR 误读处理')
            return None
        return price

    def _buy_cancel(self, check_image: RuleImage) -> bool:
        """
        点取消关掉购买弹窗, 直到多数量窗口的加号和单个购买窗口的确认图都消失
        :return: 关掉返回 True, 超时返回 False
        """
        timeout = Timer(10).start()
        while 1:
            self.screenshot()
            if not self.appear(self.I_BUY_PLUS) and not self.appear(check_image):
                return True
            if timeout.reached():
                logger.warning('[购买] 关闭购买弹窗超时')
                return False
            if self.click(self.C_BUY_CANCEL, interval=1):
                continue

    def _buy_more_default(self, start_click: Union[RuleImage, RuleOcr, RuleClick]) -> bool:
        """
        多数量购买窗口不调整数量, 默认数量为 1 时直接确认买 1 个
        :param start_click: 默认数量不是 1 时退回 buy_more(start_click, 1) 用
        :return: 买到返回 True, 达到购买上限返回 False
        """
        ocr_timer = Timer(2).start()
        while 1:
            current = self.O_BUY_NUMBER.ocr(self.device.image)
            if current == 1:
                break
            if ocr_timer.reached():
                logger.warning(f'[购买] 默认购买数量为 {current}, 回退 buy_more')
                return self.buy_more(start_click, 1)
            self.screenshot()
        logger.info('[购买] 多数量购买窗口, 按默认数量购买 1 个')
        confirm_click = 5
        while 1:
            self.screenshot()

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
                return True

            if confirm_click <= 0:
                logger.warning('[购买] 确认购买点击次数已达上限')
                return False

            if self.appear(self.I_UI_CONFIRM_SAMLL):
                self.ui_click_until_disappear(self.I_UI_CONFIRM_SAMLL, interval=1)
                logger.warning('[购买] 购买数量已达上限')
                return False

            if self.click(self.C_BUY_MORE, interval=2):
                confirm_click -= 1
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


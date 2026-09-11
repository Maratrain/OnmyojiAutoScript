# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from module.logger import logger

from tasks.Component.Buy.buy import Buy
# from tasks.WeeklyPurchase.assets import WeeklyPurchaseAssets
from tasks.WeeklyPurchase.mall.navbar import MallNavbar
from tasks.WeeklyPurchase.config import Consignment as ConsignmentStore


class Consignment(Buy, MallNavbar):

    def execute_consignment(self, con: ConsignmentStore=None):
        """
        必须要求这个是第一个执行的对于 商店来说
        :param con:
        :return:
        """
        if not con:
            con = self.config.weekly_purchase.consignment
        if not con.enable:
            logger.info('[商店-寄售] 寄售商店未启用，跳过')
            return
        if not con.buy_sale_ticket:
            logger.info('[商店-寄售] 未启用购买特售券，跳过')
            return
        self._enter_consignment()
        self.ui_click(self.I_CON_ENTER, self.I_CON_ENTER_CHECK)
        time.sleep(0.5)
        self.screenshot()
        if not self.mall_check_money(3, 100):
            logger.warning('[商店-寄售] 金币不足，无法购买特售券')
            return
        remain_number = self.O_CON_NUMBER.ocr(self.device.image)
        if remain_number == 0:
            logger.warning('[商店-寄售] 本周购买次数已用完')
            return
        if remain_number == 10:
            self.buy_more(self.I_CON_TICKET)
        else:
            self.buy_one(self.I_CON_TICKET, remain_number)
        logger.info('[商店-寄售] 购买特售券成功')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = Consignment(c, d)

    t.execute_consignment()



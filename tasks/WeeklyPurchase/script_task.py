# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep
from datetime import time, datetime, timedelta

from module.logger import logger
from module.exception import TaskEnd


from tasks.WeeklyPurchase.assets import WeeklyPurchaseAssets
from tasks.WeeklyPurchase.config import WeeklyPurchase
from tasks.WeeklyPurchase.mall.mall import Mall
from tasks.WeeklyPurchase.guild import Guild
from tasks.WeeklyPurchase.itachi_shop import ItachiCoinShop
from tasks.WeeklyPurchase.shrine import Shrine
from tasks.WeeklyPurchase.thousand_things import ThousandThings


class ScriptTask(Mall, Guild, ThousandThings, Shrine, ItachiCoinShop):

    def run(self):
        con: WeeklyPurchase = self.config.weekly_purchase
        # 千物宝箱
        self.execute_tt(con.thousand_things)
        # 神龛
        self.execute_shrine(con.shrine)
        # 功勋商店
        self.execute_guild(con.guild_store)
        # 鼬乐币商店
        self.execute_itachi_coin_shop(con.itachi_coin_shop)
        # 商店
        self.execute_mall()

        self.set_next_run(task='WeeklyPurchase', success=True, finish=False)
        raise TaskEnd('WeeklyPurchase')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()
    # t.execute_mall()



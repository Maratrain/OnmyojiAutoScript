# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

import random
import re

from module.logger import logger
from module.atom.image import RuleImage
from tasks.GameUi.default_pages import page_shirin

from tasks.GameUi.page import page_main, page_guild
from tasks.GameUi.game_ui import GameUi
from tasks.Component.Buy.buy import Buy
from tasks.RichMan.assets import RichManAssets
from tasks.RichMan.config import GuildStore
from tasks.RichMan.page import page_guild_store


class Guild(Buy, GameUi, RichManAssets):

    def _default_detect_categories(self) -> set[str]:
        categories = super()._default_detect_categories()
        categories.add("guild")
        return categories

    def execute_guild(self, con: GuildStore = None):
        if not con.enable:
            return
        logger.hr('开始寮商店', 1)
        self.goto_page(page_guild_store)
        logger.info('[大富翁] 进入寮商店成功')
        time.sleep(0.5)
        swipe_cnt, max_swipe = 0, random.randint(3, 5)
        mystery_ret, scrap_ret, skin_ret, gift_ret = False, False, False, False
        while swipe_cnt <= max_swipe:
            self.screenshot()
            if con.honor_gift and self.appear(self.I_GUILD_HONOR_GIFT, interval=1.5) and not gift_ret:  # 功勋礼包
                gift_ret = self._guild_honor_gift()
            if con.mystery_amulet and self.appear(self.I_GUILD_BLUE, interval=1.5) and not mystery_ret:  # 蓝票
                mystery_ret = self._guild_mystery_amulet()
            if con.black_daruma_scrap and self.appear(self.I_GUILD_SCRAP, interval=1.5) and not scrap_ret:  # 黑碎
                scrap_ret = self._guild_black_daruma_scrap()
            if con.skin_ticket and self.appear(self.I_GUILD_SKIN, interval=1.5) and not skin_ret:  # 皮肤券
                skin_ret = self._guild_skin_ticket()
            self.swipe(self.S_GUILD_STORE, interval=1.5)
            time.sleep(2)
            logger.attr(max_swipe - swipe_cnt, '剩余滑动次数')
            swipe_cnt += 1
        # 回去
        self.goto_page(page_shirin)

    def _guild_honor_gift(self):
        # 功勋礼包
        logger.hr('功勋礼包', 2)
        self.screenshot()
        if not self.buy_check_money(self.O_GUILD_TOTAL, 210):
            return False
        number = self.check_remain(self.I_GUILD_HONOR_GIFT)
        if number == 0:
            logger.warning('[大富翁] 没有可购买的蓝票')
            return False
        self.buy_more(self.I_GUILD_HONOR_GIFT)
        time.sleep(0.5)
        return True

    def _guild_mystery_amulet(self):
        # 蓝票
        logger.hr('寮商店蓝票', 2)
        self.screenshot()
        if not self.buy_check_money(self.O_GUILD_TOTAL, 240):
            return False
        number = self.check_remain(self.I_GUILD_BLUE)
        if number == 0:
            logger.warning('[大富翁] 没有可购买的蓝票')
            return False
        self.buy_more(self.I_GUILD_BLUE, number)
        time.sleep(0.5)
        return True

    def _guild_black_daruma_scrap(self):
        # 黑碎
        logger.hr('寮商店黑碎', 2)
        self.screenshot()
        if not self.buy_check_money(self.O_GUILD_TOTAL, 200):
            return False
        number = self.check_remain(self.I_GUILD_SCRAP)
        if number == 0:
            logger.warning('[大富翁] 没有可购买的黑碎')
            return False
        self.buy_one(self.I_GUILD_SCRAP, self.I_GUILD_CHECK_SCRAP)
        time.sleep(0.5)
        return True

    def _guild_skin_ticket(self, num: int = 0):
        # 皮肤券
        logger.hr('寮商店皮肤券', 2)
        if num == 0:
            logger.warning('[大富翁] 皮肤券购买数量为 0')
            return False
        self.screenshot()
        if not self.buy_check_money(self.O_GUILD_TOTAL, 50):
            return False
        # 检查功勋商店皮肤券 本周剩余数量
        number = self.check_remain(self.I_GUILD_SKIN)
        if number == 0:
            logger.warning('[大富翁] 没有可购买的皮肤券')
            return False
        # 购买功勋商店皮肤券
        self.buy_more(self.I_GUILD_SKIN, number)
        time.sleep(0.5)
        return True

    def check_remain(self, image: RuleImage) -> int:
        self.O_GUILD_REMAIN.roi[0] = image.roi_front[0] - 38
        self.O_GUILD_REMAIN.roi[1] = image.roi_front[1] + 83
        logger.info(f'[大富翁] 图片 ROI: {image.roi_front}')
        logger.info(f'[大富翁] 剩余数量识别区域 ROI: {self.O_GUILD_REMAIN.roi}')
        self.screenshot()
        result = self.O_GUILD_REMAIN.ocr(self.device.image)
        logger.warning(result)
        result = result.replace('？', '2').replace('?', '2').replace(':', '；')
        try:
            result = re.findall(r'本周[剩刺][余条]数量(\d+)', result)[0]
            result = int(result)
        except:
            result = 0
        logger.info('剩余数量: %s' % result)
        return int(result)


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常1')
    d = Device(c)
    t = Guild(c, d)

    # t._guild_skin_ticket(5)
    t._guild_honor_gift()


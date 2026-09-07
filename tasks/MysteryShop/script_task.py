# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import re
from time import sleep
from datetime import timedelta, datetime, time
from cached_property import cached_property

from module.exception import TaskEnd
from module.logger import logger
from module.base.timer import Timer

from tasks.GameUi.page import page_main, page_mall
from tasks.GameUi.game_ui import GameUi
from tasks.RichMan.mall.friendship_points import FriendshipPoints
from tasks.MysteryShop.config import MysteryShop, ShopConfig
from tasks.MysteryShop.assets import MysteryShopAssets
from tasks.Component.GeneralInvite.general_invite import GeneralInvite
from tasks.Component.GeneralInvite.config_invite import InviteConfig

class ScriptTask(FriendshipPoints, MysteryShopAssets, GeneralInvite):

    def run(self):
        day_of_week = self.start_time.weekday()
        if day_of_week != 2 and day_of_week != 5:
            logger.warning('[神秘商店] 今天不是神秘商店开放日')
            self.next_time(False)
        self.goto_page(page_mall)
        self.ui_click(self.I_ME_ENTER, self.I_MS_SHARE)
        logger.info('[神秘商店] 进入神秘商店')
        con = self.config.mystery_shop
        self.share(con.invite_config)
        while 1:
            self.run_shop(con.shop_config)
            if not self.next_one():
                break
        self.shop_reward()
        logger.info('[神秘商店] 退出神秘商店')
        self.back_mall()


        self.next_time(True)

    def next_one(self):
        """
        切换下一个好友的商店
        :return:
        """
        self.screenshot()
        if not self.appear(self.I_MS_NEXT):
            sleep(0.5)
            self.screenshot()
            if self.appear(self.I_MS_NEXT):
                pass
            else:
                logger.info('没有下一个好友')
                return False

        own_page = self.appear(self.I_MS_SHARE)
        if own_page:
            while 1:
                self.screenshot()
                if not self.appear(self.I_MS_SHARE):
                    break
                if self.appear_then_click(self.I_MS_NEXT, interval=1):
                    continue
            logger.info('切换到下一个好友')
            return True

        present_friend = self.O_MS_FRIEND.ocr(self.device.image)
        while 1:
            self.screenshot()
            next_friend = self.O_MS_FRIEND.ocr(self.device.image)
            if present_friend != next_friend:
                break
            if self.appear_then_click(self.I_MS_NEXT, interval=2.5):
                continue

        logger.info('切换到下一个好友')
        return True



    def run_shop(self, shop_config: ShopConfig = None):
        """
        在当前的商店进行购买
        :return:
        """
        if shop_config.mystery_amulet:
            while self.buy_mall_one(buy_button=self.I_MS_BLUE, buy_check=self.I_MS_CHECK_BLUE,
                                    money_ocr=self.O_MALL_RESOURCE_5, buy_money=85):
                pass
        if shop_config.black_daruma_scrap:
            while self.buy_mall_one(buy_button=self.I_MS_BLACK, buy_check=self.I_MS_CHECK_BLACK,
                                    money_ocr=self.O_MALL_RESOURCE_5, buy_money=60):
                pass
        if shop_config.shop_kaiko_3:
            while self.buy_mall_one(buy_button=self.I_MS_TAIKO_3, buy_check=self.I_MS_CHECK_TAIKO_3,
                                    money_ocr=self.O_MALL_RESOURCE_5, buy_money=45):
                pass
        if shop_config.shop_kaiko_4:
            while self.buy_mall_one(buy_button=self.I_MS_TAIKO_4, buy_check=self.I_MS_CHECK_TAIKO_4,
                                    money_ocr=self.O_MALL_RESOURCE_5, buy_money=80):
                pass

    def share(self, invite_config: InviteConfig = None):
        logger.hr('分享', 3)
        if len(invite_config.friend_list_v) == 0:
            logger.info('分享未开启')
            return
        self.ui_click(self.I_MS_SHARE, self.I_INVITE_ENSURE)
        self.invite_friends(invite_config, False, self.I_INVITE_ENSURE)

    def shop_reward(self):
        logger.info('领取商店奖励')
        self.screenshot()
        number = self.O_MS_RECORDS.ocr(self.device.image)
        if not isinstance(number, int):
            logger.warning('没有商店奖励')
            return
        logger.info(f'领取商店奖励 {number}')
        if number >= 3:
            self.ui_get_reward(self.I_MS_REWARD_3)
            sleep(0.5)
        if number >= 5:
            self.ui_get_reward(self.I_MS_REWARD_5)
            sleep(0.5)
        if number >= 10:
            self.ui_get_reward(self.I_MS_REWARD_10)
            sleep(0.5)
        logger.info('商店奖励领取完成')

    def next_time(self, success: bool = True):
        """
        重写
        """
        target_time: time = self.config.mystery_shop.shop_config.time_of_mystery
        target_time: timedelta = timedelta(hours=target_time.hour, minutes=target_time.minute,
                                           seconds=target_time.second)
        if target_time == time(hour=0, minute=0, second=0):
            if success:
                self.set_next_run(task='MysteryShop', success=True, finish=True)
            else:
                self.set_next_run(task='MysteryShop', success=False, finish=True)
            raise TaskEnd('MysteryShop')
        now = datetime.now()
        day_of_week = now.weekday()
        now_datetime = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if 2 <= day_of_week <= 4:
            # 如果现在是周三和周五之间，那就设定下一次为这周六（hour=0, minute=0, second=0）+ target_time
            next_time = now_datetime + timedelta(days=5 - day_of_week) + target_time
        elif 5 <= day_of_week <= 6 or 0 <= day_of_week <= 1:
            # 如果现在是周六和周一之间，那就设定下一次为下周三（hour=0, minute=0, second=0）+ target_time
            next_time = now_datetime + timedelta(days=6 - day_of_week + 3) + target_time
        else:
            next_time = now_datetime + timedelta(days=2 - day_of_week) + target_time
            logger.warning('[神秘商店] 当前不在神秘商店开放时间')
        self.set_next_run(task='MysteryShop', target=next_time)
        raise TaskEnd('MysteryShop')


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    # t.run_shop(t.config.mystery_shop.shop_config)
    t.run()



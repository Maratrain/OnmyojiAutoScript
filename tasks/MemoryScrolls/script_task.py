# This Python file uses the following encoding: utf-8
# @author ghg11
# github https://github.com/ghg11
from time import sleep
from enum import Enum
from module.logger import logger
from module.exception import TaskEnd
from module.base.timer import Timer
from datetime import timedelta, datetime

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_summon, page_main
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.MemoryScrolls.assets import MemoryScrollsAssets
from tasks.MemoryScrolls.config import ScrollNumber


class ScriptTask(GameUi, MemoryScrollsAssets):

    def run(self):        
        self.goto_page(page_summon)
        con = self.config.memory_scrolls.memory_scrolls_config
        # 进入绘卷主界面
        self.goto_memoryscrolls_main(con)
        # 返回主界面
        self.goto_page(page_main)
        raise TaskEnd
    
    def goto_memoryscrolls_main(self, con):
        # 循环寻找&点击绘卷入口
        if self.wait_until_appear(self.I_MS_ENTER, wait_time=30):
            while 1:
                self.screenshot()
                if self.appear(self.I_MS_FRAGMENT_S):
                    logger.info('[绘卷] 已进入绘卷主界面')
                    break
                # 周年庆等时期会使用双绘卷
                if self.appear(self.I_MS_DOUBLE_SCROLLS_ENTER):
                    logger.info('[绘卷] 使用绘卷双倍')
                    if con.double_scrolls == con.double_scrolls.ONE:
                        logger.info('[绘卷] 选择双倍绘卷一')
                    else:
                        logger.info('[绘卷] 选择双倍绘卷二')
                        self.click(self.C_MS_DOUBLE_SCROLLS_2, interval=1)
                    if self.appear_then_click(self.I_MS_DOUBLE_SCROLLS_ENTER, interval=1):
                        continue
                # 右上角绘卷铃铛
                if self.appear_then_click(self.I_MS_ENTER, interval=1):
                    continue
        else:
            logger.error('[绘卷] 进入绘卷主界面失败')
            self.set_next_run(task='MemoryScrolls', success=False)
            raise TaskEnd
        # 如果每天只刷小绘卷50，则先检测小绘卷数量
        if self.config.memory_scrolls.memory_scrolls_finish.auto_finish_exploration:
            self.ui_click(self.I_MS_FRAGMENT_S, self.I_MS_FRAGMENT_S_VERIFICATION, interval=1.5)
            self.screenshot()  # 再次截图刷新图像帧
            if self.appear(self.I_MS_FRAGMENT_S_50):
                logger.info('[绘卷] 小绘卷碎片已达50，安排明天探索')
                # 安排下次探索
                self.custom_next_run(task='Exploration', custom_time=self.config.memory_scrolls.memory_scrolls_finish.next_exploration_time, time_delta=1)
            else:
                logger.warning('[绘卷] 小绘卷碎片未达到50，任务失败')
                # 先返回绘卷主界面
                self.ui_click_until_disappear(GlobalGameAssets.I_UI_BACK_YELLOW, interval=1.5)
                # 再返回庭院主界面
                self.goto_page(page_main)
                self.set_next_run(task='MemoryScrolls', success=False)
                raise TaskEnd
            self.ui_click_until_smt_disappear(self.I_MS_FRAGMENT_S, stop=self.I_MS_FRAGMENT_S_VERIFICATION, interval=1.5)
        # 进入指定分卷
        self.goto_scroll(con)
        # 返回召唤界面
        self.ui_click_until_disappear(GlobalGameAssets.I_UI_BACK_YELLOW, interval=1)
        logger.info('返回召唤界面')
    
    def goto_scroll(self, con):
        """
        进入指定分卷
        :param scroll_number: 分卷编号
        """
        while 1:
            self.screenshot()
            if self.appear(GlobalGameAssets.I_UI_BACK_RED):
                logger.info('[绘卷] 已进入绘卷捐献界面')
                break
            match con.scroll_number:
                case ScrollNumber.ONE:
                    self.click(self.C_MS_SCROLL_1, interval=1)
                case ScrollNumber.TWO:
                    self.click(self.C_MS_SCROLL_2, interval=1)
                case ScrollNumber.THREE:
                    self.click(self.C_MS_SCROLL_3, interval=1)
                case ScrollNumber.FOUR:
                    self.click(self.C_MS_SCROLL_4, interval=1)
                case ScrollNumber.FIVE:
                    self.click(self.C_MS_SCROLL_5, interval=1)
                case ScrollNumber.SIX:
                    self.click(self.C_MS_SCROLL_6, interval=1)
                case _:
                    logger.error(f'未知绘卷编号: {con.scroll_number.name}')
                    self.set_next_run(task='MemoryScrolls', success=False)
                    raise TaskEnd
        
        # 到达指定进度时进行通知提示
        if con.notification_95 and not self.appear(self.I_MS_COMPLETE_95):
            logger.info('[绘卷] 绘卷进度已达95%，发送通知')
            self.config.notifier.push(title='追忆绘卷进度95%', content='绘卷进度已达95%，请立即空降')

        # 判断是否需要捐献碎片
        if self.appear(self.I_MS_CONTRIBUTE) or not self.appear(self.I_MS_COMPLETE):
            logger.info(f'正在为绘卷 {con.scroll_number.name} 捐献')
            if con.auto_contribute_memoryscrolls:
                # 自动捐献碎片
                logger.info('自动捐献绘卷')
                self.contribute_memoryscrolls()
            # 设置下一次运行时间
            self.set_next_run(task='MemoryScrolls', success=True)
        else:
            logger.info(f'绘卷 {con.scroll_number.name} 已完成')
            self.set_next_run(task='MemoryScrolls', success=False)
            if con.auto_close_exploration:
                # 自动关闭探索任务
                logger.info('绘卷完成后自动关闭探索任务')
                self.config.exploration.scheduler.enable = False
                self.config.save()
                # next_run=datetime.now() + timedelta(days=1)
                # self.set_next_run(task='Exploration', success=False, finish=False, target=next_run)
        # 返回绘卷主界面
        self.ui_click_until_disappear(GlobalGameAssets.I_UI_BACK_RED, interval=1)
        logger.info('已关闭绘卷捐献界面')
    
    def contribute_memoryscrolls(self):
        """
        捐献碎片
        :return: None
        """
        while 1:
            self.screenshot()
            if self.appear(self.I_MS_ZERO_S) and self.appear(self.I_MS_ZERO_M) and self.appear(self.I_MS_ZERO_L):
                logger.info('[绘卷] 绘卷捐献已完成')
                return
            self.swipe(self.S_MS_SWIPE_S, interval=1)
            self.swipe(self.S_MS_SWIPE_M, interval=1)
            self.swipe(self.S_MS_SWIPE_L, interval=1)
            if self.appear_then_click(self.I_MS_CONTRIBUTE, interval=3):
                logger.info('已捐献绘卷')
                # 等待捐献动画结束
                while 1:
                    self.screenshot()
                    if self.wait_until_appear(self.I_MS_CONTRIBUTED, wait_time=5):
                        self.click(self.C_MS_CONTRIBUTED, interval=1)
                    else:
                        break
    



if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()







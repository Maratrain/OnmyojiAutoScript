# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main, page_daily
from tasks.TalismanPass.assets import TalismanPassAssets
from tasks.TalismanPass.config import TalismanConfig, LevelReward

from module.logger import logger
from module.exception import TaskEnd
from module.base.timer import Timer


class ScriptTask(GameUi, TalismanPassAssets):

    def run(self):
        self.goto_page(page_daily)
        con: TalismanConfig = self.config.talisman_pass.talisman

        # 收取任务全部奖励
        if self.in_task():
            self.get_all()
        # 收取花合战等级奖励
        if con.get_flower:
            self.get_flower(con.level_reward)
        # 收取1500签御魂
        if con.harvest_soul:
            self.goto_page(page_main)
            self.harvest_soul()
        self.goto_page(page_main)
        self.set_next_run(task='TalismanPass', success=True, finish=True)
        raise TaskEnd('TalismanPass')

    def get_all(self):
        """
        一键收取所有的
        :return:
        """
        self.screenshot()
        if not self.appear(self.I_TP_GET_ALL):
            logger.info('[花合战] 未出现一键领取按钮')
        self.ui_get_reward(self.I_TP_GET_ALL)
        logger.info('领取全部奖励')
        time.sleep(0.5)

    def get_flower(self, level: LevelReward = LevelReward.TWO):
        """
        收取花合战等级奖励
        :return:
        """
        match_level = {
            LevelReward.ONE: self.I_TP_LEVEL_1,
            LevelReward.TWO: self.I_TP_LEVEL_2,
            LevelReward.THREE: self.I_TP_LEVEL_3,
        }
        self.screenshot()
        if not self.appear(self.I_RED_POINT_LEVEL):
            logger.info('没有可领取的等级奖励')
            return
        logger.info('出现等级奖励')
        self.ui_click(self.I_RED_POINT_LEVEL, self.I_TP_GET_ALL)
        logger.info('点击等级奖励')
        check_timer = Timer(2)
        check_timer.start()
        while 1:
            self.screenshot()
            if self.appear_then_click(match_level[level], interval=0.8):
                logger.info(f'选择 {level} 档奖励')
                if self.appear_then_click(self.I_OVERFLOW_CONFIRME):
                    pass
                check_timer.reset()
                continue

            if self.ui_reward_appear_click(False):
                logger.info('获得奖励')
                check_timer.reset()
                continue
            if check_timer.reached():
                logger.warning('没有奖励，退出')
                break
            if self.appear_then_click(self.I_TP_GET_ALL, interval=2.1):
                logger.info('领取全部奖励')
                check_timer.reset()
                continue

    def in_task(self) -> bool:
        """
        判断是否在任务的界面
        :return:
        """
        self.screenshot()
        if self.appear(self.I_TP_GOTO) or self.appear(self.I_TP_EXP):
            return True
        if self.appear(self.I_RED_POINT_TASK):
            self.click(self.I_RED_POINT_TASK)
            logger.info('出现任务奖励')
            return True
        logger.info('没有可领取的任务奖励')
        return False
    
    def harvest_soul(self):
        """
        获得1500签御魂奖励
        :return: 如果没有发现御魂奖励则退出
        """
        logger.hr('收获御魂')
        timer_harvest = Timer(5)  # 如果连续5秒没有发现任何奖励，退出
        while 1:
            self.screenshot()
            # 自选御魂
            if self.appear(self.I_TP_SOUL_1):
                logger.info('选择自选御魂2')
                self.ui_click(self.I_TP_SOUL_1, stop=self.I_TP_SOUL_2)
                self.ui_click(self.I_TP_SOUL_2, stop=self.I_TP_SOUL_3, interval=3)
                self.ui_click_until_disappear(click=self.I_TP_SOUL_3)
                timer_harvest.reset()
            # 五秒内没有发现任何奖励，退出
            if not timer_harvest.started():
                timer_harvest.start()
            else:
                if timer_harvest.reached():
                    logger.info('没有更多奖励')
                    return



if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()



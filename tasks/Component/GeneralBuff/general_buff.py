# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time

from tasks.Component.GeneralBuff.assets import GeneralBuffAssets
from module.atom.ocr import RuleOcr
from module.atom.image import RuleImage
from tasks.base_task import BaseTask
from module.logger import logger
from module.base.timer import Timer
from typing import Optional

# 加成面板开/关与滑动的有界等待上限, 需小于设备 60 秒卡死检测阈值
BUFF_SWITCH_TIMEOUT = 30
# 聊天面板收起的最大尝试次数
CHAT_CLOSE_LIMIT = 3


class GeneralBuff(BaseTask, GeneralBuffAssets):

    def open_buff(self) -> bool:
        """
        打开buff的总界面
        :return: 成功打开返回True; 超时未打开返回False, 调用方应跳过本次加成设置
        """
        logger.info('[通用加成] 打开加成界面')
        open_timer = Timer(BUFF_SWITCH_TIMEOUT).start()
        chat_close_left = CHAT_CLOSE_LIMIT
        while 1:
            self.screenshot()
            if self.appear(self.I_CLOUD):
                break
            if self.appear_then_click(self.I_BUFF_1, interval=2):
                continue
            # 聊天面板展开会盖住庭院左上角的加成入口, 点击右缘三角收起
            if chat_close_left > 0 and self.appear_then_click(self.I_CHAT_CLOSE, interval=1):
                chat_close_left -= 1
                logger.info('[通用加成] 检测到聊天面板, 点击收起')
                continue
            if open_timer.reached():
                logger.warning('[通用加成] 打开加成界面等待超时, 跳过本次加成设置')
                return False

        check_image = self.I_AWAKE
        swipe_left = 4
        swipe_timer = Timer(BUFF_SWITCH_TIMEOUT).start()
        while 1:
            self.screenshot()
            if self.appear(check_image):
                break
            if swipe_left <= 0 or swipe_timer.reached():
                logger.warning('[通用加成] 滑动后仍未找到觉醒加成行, 跳过本次加成设置')
                return False
            self.swipe(self.S_BUFF_UP, interval=2)
            swipe_left -= 1
        return True

    def close_buff(self):
        """
        关闭buff的总界面, 但是要确保buff界面已经打开了
        :return:
        """
        logger.info('[通用加成] 关闭加成界面')
        close_timer = Timer(BUFF_SWITCH_TIMEOUT).start()
        while 1:
            self.screenshot()
            if not self.appear(self.I_CLOUD):
                break
            if self.appear_then_click(self.I_BUFF_1, interval=2):
                continue
            if close_timer.reached():
                logger.warning('[通用加成] 关闭加成界面等待超时, 继续后续流程')
                break

    def get_area(self, buff: RuleOcr) -> Optional[tuple[int, int, int, int]]:
        """
        获取要点击的开关buff的区域
        :param cls:
        :param image:
        :param buff:
        :return:  如果没有就返回None
        """
        # 防止邀请框挡住BUFF框架
        self.reject_invite()
        self.screenshot()
        result_list = buff.detect_and_ocr(self.device.image)
        area = None
        for result in result_list:
            if result.ocr_text == buff.keyword:
                area = (buff.roi[0] + result.box[0, 0], buff.roi[1] + result.box[0, 1],
                        result.box[1, 0] - result.box[0,0], result.box[2, 1] - result.box[0,1])
                break
        if area is None:
            return None
        # 开始的x坐标就是文字的右边
        start_x = area[0] + area[2] + 10  # 10是文字和开关之间的间隔
        start_y = area[1] - 10
        width = 80  # 开关的宽度 80够了
        height = 45
        return int(start_x), int(start_y), int(width), int(height)

    def set_switch_area(self, area, kind: str = "buff"):
        """
        设置开关的区域
        :param area:
        :param kind: 开关所属行，buff(觉醒/御魂)、gold(金币)、experience(经验)
        各行使用独立规则，避免共用同一实例时后一次设置覆盖前一次
        :return:
        """
        getattr(self, f"I_{kind.upper()}_OPEN_YELLOW").roi_back = list(area)  # 动态设置roi
        getattr(self, f"I_{kind.upper()}_CLOSE_RED").roi_back = list(area)

    def gold_50(self, is_open: bool = True) -> bool:
        """
        金币50buff
        :param is_open: 是否打开
        :return: 识别到且操作成功True
        """
        logger.info('[通用加成] 金币50加成')
        self.screenshot()
        area = self.get_area(self.O_GOLD_50)
        if not area:
            logger.warning('[通用加成] 未找到金币50加成')
            return False
        self.set_switch_area(area, kind="gold")
        if is_open:
            logger.info('[通用加成] 开始开启金币50加成')
            self.ui_click(self.I_GOLD_CLOSE_RED, self.I_GOLD_OPEN_YELLOW, interval=1)
            return True
        logger.info('[通用加成] 开始关闭金币50加成')
        self.ui_click(self.I_GOLD_OPEN_YELLOW, self.I_GOLD_CLOSE_RED, interval=1)
        return True

    def gold_100(self, is_open: bool = True) -> bool:
        """
        金币100buff
        :param is_open: 是否打开
        :return:
        """
        logger.info('[通用加成] 金币100加成')
        self.screenshot()
        area = self.get_area(self.O_GOLD_100)
        if not area:
            logger.warning('[通用加成] 未找到金币100加成')
            return False
        self.set_switch_area(area, kind="gold")
        if is_open:
            logger.info('[通用加成] 开始开启金币100加成')
            self.ui_click(self.I_GOLD_CLOSE_RED, self.I_GOLD_OPEN_YELLOW, interval=1)
            return True
        logger.info('[通用加成] 开始关闭金币100加成')
        self.ui_click(self.I_GOLD_OPEN_YELLOW, self.I_GOLD_CLOSE_RED, interval=1)
        return True

    def exp_50(self, is_open: bool = True) -> bool:
        """
        经验50buff
        :param is_open: 是否打开
        :return:
        """
        logger.info('[通用加成] 经验50加成')
        max_swipe = 2
        while True:
            self.screenshot()
            if max_swipe <= 0:
                logger.warning('[通用加成] 未找到经验50加成')
                return False
            area = self.get_area(self.O_EXP_50)
            if area:
                self.set_switch_area(area, kind="experience")
            if not area or (not self.appear(self.I_EXPERIENCE_CLOSE_RED) and not self.appear(self.I_EXPERIENCE_OPEN_YELLOW)):
                self.device.swipe(p2=(530, 240), p1=(580, 320))
                max_swipe -= 1
                time.sleep(1)
                continue
            break
        if is_open:
            logger.info('[通用加成] 开始开启经验50加成')
            self.ui_click(self.I_EXPERIENCE_CLOSE_RED, self.I_EXPERIENCE_OPEN_YELLOW, interval=1)
            return True
        logger.info('[通用加成] 开始关闭经验50加成')
        self.ui_click(self.I_EXPERIENCE_OPEN_YELLOW, self.I_EXPERIENCE_CLOSE_RED, interval=1)
        return True

    def exp_100(self, is_open: bool = True) -> bool:
        """
        经验100buff
        :param is_open: 是否打开
        :return:
        """
        logger.info('[通用加成] 经验100加成')
        max_swipe = 2
        while True:
            if max_swipe <= 0:
                logger.warning('[通用加成] 未找到经验100加成')
                return False
            self.screenshot()
            area = self.get_area(self.O_EXP_100)
            if area:
                self.set_switch_area(area, kind="experience")
            if not area or (not self.appear(self.I_EXPERIENCE_CLOSE_RED) and not self.appear(self.I_EXPERIENCE_OPEN_YELLOW)):
                self.device.swipe(p2=(530, 240), p1=(580, 320))
                max_swipe -= 1
                time.sleep(1)
                continue
            break
        if is_open:
            logger.info('[通用加成] 开始开启经验100加成')
            self.ui_click(self.I_EXPERIENCE_CLOSE_RED, self.I_EXPERIENCE_OPEN_YELLOW, interval=1)
            return True
        logger.info('[通用加成] 开始关闭经验100加成')
        self.ui_click(self.I_EXPERIENCE_OPEN_YELLOW, self.I_EXPERIENCE_CLOSE_RED, interval=1)
        return True

    def get_area_image(self, target: RuleImage) -> Optional[tuple[int, int, int, int]]:
        """
        获取觉醒加成或者是御魂加成所要点击的区域
        因为实在的图片比ocr快
        :param image:
        :param target:
        :return:
        """
        self.reject_invite()
        self.screenshot()

        if not self.appear(target):
            logger.warning(f'[通用加成] 未找到 {target.name} 加成')
            return None
        start_x = int(target.roi_front[0] + 390)
        start_y = int(target.roi_front[1])
        width = 80
        height = int(target.roi_front[3])
        return start_x, start_y, width, height

    def awake(self, is_open: bool = True):
        """
        觉醒buff
        :param is_open: 是否打开
        :return:
        """
        logger.info('[通用加成] 觉醒加成')
        self.screenshot()
        area = self.get_area_image(self.I_AWAKE)
        if not area:
            logger.warning('[通用加成] 未找到觉醒加成')
            return None
        self.set_switch_area(area)
        if is_open:
            logger.info('[通用加成] 开始开启觉醒加成')
            self.ui_click(self.I_BUFF_CLOSE_RED, self.I_BUFF_OPEN_YELLOW, interval=1)
            return True
        logger.info('[通用加成] 开始关闭觉醒加成')
        self.ui_click(self.I_BUFF_OPEN_YELLOW, self.I_BUFF_CLOSE_RED, interval=1)
        return True

    def soul(self, is_open: bool = True):
        """
        御魂buff
        :param is_open: 是否打开
        :return:
        """
        logger.info('[通用加成] 御魂加成')
        self.screenshot()
        area = self.get_area_image(self.I_SOUL)
        if not area:
            logger.warning('[通用加成] 未找到御魂加成')
            return None
        self.set_switch_area(area)
        if is_open:
            logger.info('[通用加成] 开始开启御魂加成')
            self.ui_click(self.I_BUFF_CLOSE_RED, self.I_BUFF_OPEN_YELLOW, interval=1)
            return True
        logger.info('[通用加成] 开始关闭御魂加成')
        self.ui_click(self.I_BUFF_OPEN_YELLOW, self.I_BUFF_CLOSE_RED, interval=1)
        return True

    def reject_invite(self):
        from tasks.Component.GeneralInvite.assets import GeneralInviteAssets as gia
        while 1:
            self.screenshot()
            if not (self.appear(gia.I_I_REJECT_1) or self.appear(gia.I_I_REJECT_2) or self.appear(gia.I_I_REJECT_3)):
                break
            if self.appear(gia.I_I_REJECT_3):
                self.click(gia.I_I_REJECT_3, 6)
                continue
            if self.appear(gia.I_I_REJECT_2):
                self.click(gia.I_I_REJECT_2, 6)
                continue
            if self.appear(gia.I_I_REJECT_1):
                self.click(gia.I_I_REJECT_1, 6)
                continue


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常2')
    d = Device(c)
    t = GeneralBuff(c, d)

    t.awake(is_open=True)

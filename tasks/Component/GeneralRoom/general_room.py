# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import time
import random

from random import randint

from tasks.Component.GeneralRoom.assets import GeneralRoomAssets
from module.atom.ocr import RuleOcr
from module.atom.image import RuleImage
from tasks.base_task import BaseTask
from module.logger import logger
from module.base.timer import Timer


class GeneralRoom(BaseTask, GeneralRoomAssets):

    def create_room(self, create_room_rule: RuleImage = None, ensure_rules: list[RuleImage] = None) -> bool:
        """
        创建队伍  一般是下方的黄色按钮
        :param create_room_rule: 创建房间入口按钮；缺省用组件自带资产
        :param ensure_rules: 创建确认弹窗的识别规则；缺省用组件自带资产
        :return:
        """
        logger.info('[通用房间] 创建房间')
        create_room_rule = self.I_CREATE_ROOM if create_room_rule is None else create_room_rule
        ensure_rules = ensure_rules if ensure_rules is not None else [self.I_CREATE_ENSURE, self.I_CREATE_ENSURE_2]
        if not self.appear(create_room_rule):
            logger.warning('[通用房间] 未找到创建房间按钮')
            return False
        click_number = 0
        while 1:
            self.screenshot()
            if click_number > 3:
                logger.warning('[通用房间] 创建房间按钮点击未生效')
                logger.warning('[通用房间] 最可能的原因是没有挑战券了')
                return False
            if self.appear_then_click(create_room_rule, interval=2):
                click_number += 1
                continue
            if any(self.appear(rule) for rule in ensure_rules):
                return True
        return False

    def ensure_private(self, room_mark: RuleImage = None,
                       private_rules: list[RuleImage] = None,
                       private_false_rules: list[RuleImage] = None) -> bool:
        """
        确认私人房间, 不公开仅邀请

        正常情况下弹窗上的"不公开(仅邀请)"开关匹配到即返回。
        但存在建房过渡动画期间(弹窗已关闭、房间已建成)本方法仍被调用的时序,
        此时四个弹窗资产全部匹配不到会空转直至卡死检测。传入 room_mark 后,
        若检测到房间已建成则视为私人设置已生效, 直接返回, 避免空转。

        :param room_mark: 可选。房间已建成界面的特征图(如房间标题栏/协战队伍)。
                          为 None 时行为与旧版完全一致。
        :param private_rules: 已勾选「不公开」的识别规则；缺省用组件自带资产
        :param private_false_rules: 未勾选「不公开」的识别规则；缺省用组件自带资产
        :return:
        """
        logger.info('[通用房间] 确认私人房间')
        checked = private_rules if private_rules is not None else [self.I_ENSURE_PRIVATE, self.I_ENSURE_PRIVATE_2]
        unchecked = private_false_rules if private_false_rules is not None else \
            [self.I_ENSURE_PRIVATE_FALSE, self.I_ENSURE_PRIVATE_FALSE_2]
        timeout = Timer(15).start()
        while 1:
            self.screenshot()
            if timeout.reached():
                logger.warning('[通用房间] 确认私人房间超时')
                return False
            if any(self.appear(rule) for rule in checked):
                return True
            if any(self.appear_then_click(rule, interval=1) for rule in unchecked):
                continue
            # 弹窗上的开关匹配不到但房间已经建成: 私人设置此前已生效(或沿用上次设置), 直接放行
            if room_mark is not None and self.appear(room_mark):
                logger.info('[通用房间] 房间已建成，私人设置视为生效')
                return True
        return False

    def ensure_public(self, room_mark: RuleImage = None,
                      public_rules: list[RuleImage] = None,
                      public_false_rules: list[RuleImage] = None) -> bool:
        """
        确认公开房间， 允许任何人加入

        与 ensure_private 同理: 弹窗开关匹配到即返回; 建房过渡帧内弹窗已关闭,
        可通过 room_mark 放行; 15 秒无进展则超时返回 False, 避免空转卡死。

        :param room_mark: 可选。房间已建成界面的特征图(如房间标题栏/协战队伍)。
        :param public_rules: 已勾选「公开」的识别规则；缺省用组件自带资产
        :param public_false_rules: 未勾选「公开」的识别规则；缺省用组件自带资产
        :return:
        """
        logger.info('[通用房间] 确认公开房间')
        checked = public_rules if public_rules is not None else [self.I_ENSURE_PUBLIC, self.I_ENSURE_PUBLIC_2]
        unchecked = public_false_rules if public_false_rules is not None else \
            [self.I_ENSURE_PUBLIC_FALSE, self.I_ENSURE_PUBLIC_FALSE_2]
        timeout = Timer(15).start()
        while 1:
            self.screenshot()
            if timeout.reached():
                logger.warning('[通用房间] 确认公开房间超时')
                return False
            if any(self.appear(rule) for rule in checked):
                return True
            if any(self.appear_then_click(rule, interval=1) for rule in unchecked):
                continue
            # 弹窗上的开关匹配不到但房间已经建成: 公开设置此前已生效(或沿用上次设置), 直接放行
            if room_mark is not None and self.appear(room_mark):
                logger.info('[通用房间] 房间已建成，公开设置视为生效')
                return True
        return False

    def create_ensure(self, ensure_rules: list[RuleImage] = None) -> bool:
        """
        创建确认
        :param ensure_rules: 确认按钮的识别规则；缺省用组件自带资产
        :return:
        """
        logger.info('[通用房间] 创建确认')
        rules = ensure_rules if ensure_rules is not None else [self.I_CREATE_ENSURE, self.I_CREATE_ENSURE_2]
        target = None
        for rule in rules:
            if rule.match(self.device.image, frame_id=self.device.image_frame_id):
                target = rule
                break
        if not target:
            logger.warning('[通用房间] 未找到创建确认按钮')
            return False

        while True:
            self.screenshot()
            if self.appear_then_click(target, interval=1.5):
                continue
            if not self.appear(target):
                return True
        return False

    def exit_team(self) -> bool:
        """
        在组队界面 退出组队的界面， 返回到庭院或者是你一开始进入的入口
        :return:
        """
        if self.appear(self.I_CHECK_TEAM):
            logger.info('[通用房间] 退出组队界面')
            while 1:
                self.screenshot()
                if not self.appear(self.I_CHECK_TEAM):
                    return True
                if self.appear_then_click(self.I_GR_BACK_YELLOW, interval=0.5):
                    continue
        return False

    def check_zones(self, name: str) -> bool:
        """
        确认副本的名称，并选中
        :param name:
        :return:
        """
        pos = self.list_find(self.L_TEAM_LIST, name)
        if not pos:
            return False
        if name == '愤怒的石距' or name == '喷怒的石距':
            name = '价悠的石距'
        self.O_GR_ZONES_NAME.keyword = name
        click_timer = Timer(1.1)
        click_timer.start()
        while 1:
            self.screenshot()

            if self.ocr_appear(self.O_GR_ZONES_NAME):
                break
            # https://github.com/runhey/OnmyojiAutoScript/issues/488
            # 只能说朴实无华
            text_ocr = self.O_GR_ZONES_NAME.ocr(self.device.image)
            if name == '石距' and name in text_ocr:
                break
            if name == '金币妖怪' and "金币" in text_ocr:
                break
            if name == '经验妖怪' and '经验' in text_ocr:
                break
            if click_timer.reached():
                click_timer.reset()
                self.device.click(x=pos[0] + randint(-5, 5), y=pos[1] + randint(-5, 5))

        return True

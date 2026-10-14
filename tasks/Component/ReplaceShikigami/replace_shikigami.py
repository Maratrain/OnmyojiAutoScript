# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from module.atom.ocr import RuleOcr
from module.atom.image import RuleImage
from module.base.timer import Timer
from module.logger import logger

from tasks.base_task import BaseTask
from tasks.Utils.config_enum import ShikigamiClass
from tasks.Component.ReplaceShikigami.assets import ReplaceShikigamiAssets
import time
from module.exception import GameStuckError


class ReplaceShikigami(BaseTask, ReplaceShikigamiAssets):

    def in_shikigami_growth(self, screenshot=False) -> bool:
        # 判定是否在式神育成界面
        # 判定的依据是是否出现了 式神录 这个图片
        # 好友寄养页面不一定有式神录图标, 用好友结界标识兜底
        if screenshot:
            self.screenshot()
        return (self.appear(self.I_RS_RECORDS_SHIKI)
                or self.appear(self.I_CHECK_FRIEND_REALM_1)
                or self.appear(self.I_CHECK_FRIEND_REALM_3))

    def switch_shikigami_class(self, shikigami_class: ShikigamiClass = ShikigamiClass.N,
                               require_growth: bool = False):
        """
        要求在式神育成的界面
        切换分类
        :param shikigami_class:
        :param require_growth: 为 True 时若中途离开育成界面立即报错, 避免在错误页面上乱点
        :return:
        """
        match_selected = {ShikigamiClass.MATERIAL: self.I_RS_MATERIAL_SELECTED,
                          ShikigamiClass.N: self.I_RS_N_SELECTED,
                          ShikigamiClass.R: self.I_RS_R_SELECTED,
                          ShikigamiClass.SR: self.I_RS_SR_SELECTED,
                          ShikigamiClass.SSR: self.I_RS_SSR_SELECTED,
                          ShikigamiClass.SP: self.I_RS_SP_SELECTED,
                          ShikigamiClass.UR: self.I_RS_UR_SELECTED}
        match_click = {ShikigamiClass.MATERIAL: self.I_RS_MATERIAL,
                       ShikigamiClass.N: self.I_RS_N,
                       ShikigamiClass.R: self.I_RS_R,
                       ShikigamiClass.SR: self.I_RS_SR,
                       ShikigamiClass.SSR: self.I_RS_SSR,
                       ShikigamiClass.SP: self.I_RS_SP,
                       ShikigamiClass.UR: self.I_RS_UR}
        check_selected = match_selected[shikigami_class]
        check_click = match_click[shikigami_class]
        # 选择式神的种类
        selection_timer = Timer(20).start()
        while not selection_timer.reached():
            self.screenshot()
            if self.appear(check_selected, interval=1):
                break
            if self.appear(check_click, interval=3):
                if self.wait_until_pos_stable(check_click, stable_time=0.8, timeout=2.5):
                    self.click(check_click)
                continue
            if self.appear_then_click(self.I_RS_ALL_SELECTED, interval=5):
                continue
            if require_growth and not self.in_shikigami_growth():
                raise GameStuckError('[更换式神] 切换分类前已离开式神育成界面')
        else:
            raise GameStuckError('[更换式神] 切换式神分类 20 秒未确认')
        logger.info('[更换式神] 选择式神类别: %s' % shikigami_class)

    def _fill_own_growth(self, preferred: int, slots: dict) -> bool:
        """
        自身育成填充: 满级式神不能喂给自身育成, 按配置优先位再从高到低逐个可见候选试一次,
        跳过满级候选, 而不是在 7/6 号位之间来回换
        :param preferred: 配置优先的坑位号
        :param slots: 坑位点击规则表 (set_shikigami 的 _click_match)
        :return: 是否填满所有坑位
        """
        order = [preferred] + [i for i in range(7, 0, -1) if i != preferred]
        for index in order:
            self.screenshot()
            if not self.in_shikigami_growth():
                raise GameStuckError('[更换式神] 自身育成填充期间页面丢失')
            if not self.appear(self.I_RS_NO_ADD):
                return True
            x = max(0, slots[index].roi_front[0] - 15)
            full = RuleImage(roi_front=(x, 487, 60, 53), roi_back=(x, 487, 60, 53),
                             threshold=0.8, method='Template matching',
                             file=self.I_RS_LEVEL_MAX.file)
            if self.appear(full):
                continue
            self.click(slots[index], interval=1.5)
            time.sleep(1.5)
            self.screenshot()
            if (self.appear_then_click(self.I_U_CONFIRM_SMALL, interval=0.5)
                    or self.appear_then_click(self.I_UI_CONFIRM, interval=1)
                    or self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=1)):
                time.sleep(1)
        self.screenshot()
        if not self.in_shikigami_growth():
            raise GameStuckError('[更换式神] 自身育成填充完成后页面丢失')
        filled = not self.appear(self.I_RS_NO_ADD)
        if not filled:
            logger.warning('[更换式神] 没有更多可用的非满级式神，剩余育成坑位留空')
        return filled

    def unset_shikigami_max_lv(self):
        """
        要求在式神育成的界面
        拉下满级的式神，留空位置
        :return:
        """
        while 1:
            self.screenshot()
            if not self.appear(self.I_RS_LEVEL_MAX):
                break
            else:
                self.appear_then_click(self.I_RS_LEVEL_MAX, interval=0.5)
        logger.info('[更换式神] 已撤下所有满级式神')

    def set_shikigami(self, shikigami_order: int = 7, stop_image: RuleImage = None):
        """
        要求在式神育成的界面
        选择式神 1-7
        :param stop_image:  结束的图片，如果不出现就结束
        :param shikigami_order:
        :return:
        """
        # 选择式神
        _click_match = {1: self.C_SHIKIGAMI_LEFT_1,
                        2: self.C_SHIKIGAMI_LEFT_2,
                        3: self.C_SHIKIGAMI_LEFT_3,
                        4: self.C_SHIKIGAMI_LEFT_4,
                        5: self.C_SHIKIGAMI_LEFT_5,
                        6: self.C_SHIKIGAMI_LEFT_6,
                        7: self.C_SHIKIGAMI_LEFT_7}
        # 自身育成（stop_image 为「无空位」标记）不能使用满级式神，走跳过满级的填充路径
        if stop_image == self.I_RS_NO_ADD:
            return self._fill_own_growth(shikigami_order, _click_match)
        click_match = _click_match[shikigami_order]
        TIMEOUT_SEC = 120          # 超时时长（秒）
        start_time = time.time()   # 记录起始时间
        click_interval_timer = Timer(1.5).start()  # 点击选择式神间隔
        clicked = False
        while 1:
            # ——1. 先做超时检查——
            if time.time() - start_time > TIMEOUT_SEC:
                logger.error('寄养等待超过 2 分钟，自动退出')
                raise GameStuckError('寄养超时（>120 s）')
            # 恢复点击操作
            if click_interval_timer.reached_and_reset():
                clicked = False
            self.screenshot()
            if self.appear_then_click(self.I_U_CONFIRM_SMALL, interval=0.5):
                clicked = False  # 点击了确认, 恢复选式神的操作
                continue
            if not self.appear(stop_image):
                break
            # 与下方点击第7个式神操作互斥, 防止确认按钮还没有出现被下方取消掉
            if not clicked and self.click(click_match, interval=1.5):
                clicked = True
                continue
            if not clicked and self.click(_click_match[6], interval=4.5):
                # 有的时候第七个格子被占用到寄养上去了
                # 导致一直无法选上
                clicked = True
                continue
            if self.appear_then_click(self.I_U_CIRCLE_ALTERNATE, interval=2.5):
                self.appear_then_click(self.I_UI_CONFIRM, interval=1.5)
                continue
        logger.info('[更换式神] 选择式神: %d' % shikigami_order)

    def detect_no_shikigami(self) -> bool:
        self.screenshot()
        if self.appear(self.I_DETECT_EMPTY_1)\
            or self.appear(self.I_DETECT_EMPTY_2) \
                or self.appear(self.I_DETECT_EMPTY_3) \
                or self.appear(self.I_DETECT_EMPTY_4) \
                or self.appear(self.I_DETECT_EMPTY_5) \
                or self.appear(self.I_DETECT_EMPTY_6):
            return True
        return False


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('日常2')
    d = Device(c)
    t = ReplaceShikigami(c, d)
    t.switch_shikigami_class(ShikigamiClass.N)

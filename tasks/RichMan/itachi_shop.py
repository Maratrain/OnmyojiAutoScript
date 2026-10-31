# This Python file uses the following encoding: utf-8
import time
from copy import copy

from module.atom.click import RuleClick
from module.logger import logger
from tasks.Chess.assets import ChessAssets
from tasks.Component.Buy.buy import Buy
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_entertainment
from tasks.RichMan.assets import RichManAssets
from tasks.RichMan.config import ItachiCoinShop as ItachiCoinShopConfig
from tasks.RichMan.page import page_itachi_shop


class ItachiCoinShop(Buy, GameUi, RichManAssets):
    """购买鼬乐园商店中自动前移的三个鼬乐礼盒。"""

    ENTERTAINMENT_OVERLAY_TIMEOUT = 8.0
    ENTERTAINMENT_STABLE_TIME = 1.0
    GIFT_DIALOG_TIMEOUT = 3.0
    PURCHASE_RESULT_TIMEOUT = 8.0
    PURCHASE_RETURN_GRACE = 3.0
    REWARD_DISMISS_TIMEOUT = 5.0
    MAX_GIFT_PURCHASES = 3

    def execute_itachi_coin_shop(self, con: ItachiCoinShopConfig) -> None:
        if not con.itachi_coin_buy_jade:
            logger.info('[鼬乐币] 未启用鼬乐币购买，跳过')
            return

        logger.hr('开始鼬乐币商店', 1)
        self.goto_page(page_entertainment)
        if not self._wait_entertainment_overlay_closed():
            logger.warning('[鼬乐币] 鼬乐园弹窗未关闭，跳过购买')
            return

        self.goto_page(page_itachi_shop)
        purchased = 0
        purchased_gifts = set()
        for _ in range(self.MAX_GIFT_PURCHASES):
            gift = self._find_itachi_gift(purchased_gifts)
            if gift is not None:
                name, area = gift
                opened = self._open_front_gift_once(
                    RuleClick(roi_front=area, roi_back=area, name=f'itachi_gift_{name}'))
            else:
                # 名称未识别到时退回前排固定位置，避免直接放弃购买
                name = None
                opened = self._open_front_gift_once()
            if not opened:
                # 已购买商品不会再打开购买弹窗。这里只点击一次，避免在同一
                # 商品位置进行高频试探。
                logger.info('[鼬乐币] 本周已购买')
                break
            if not self._buy_opened_gift():
                break
            purchased += 1
            if name is not None:
                purchased_gifts.add(name)

        logger.info(f'[鼬乐币] 已购买鼬乐礼盒 {purchased} 次')
        self.goto_page(page_entertainment)

    def _wait_entertainment_overlay_closed(self) -> bool:
        """处理鼬乐园附属页，跳过消失并稳定后才允许识别商店。"""

        deadline = time.monotonic() + self.ENTERTAINMENT_OVERLAY_TIMEOUT
        stable_since = None
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(ChessAssets.I_SKIP):
                self.appear_then_click(ChessAssets.I_SKIP, interval=0.5)
                stable_since = None
                continue

            if stable_since is None:
                stable_since = time.monotonic()
                continue
            if time.monotonic() - stable_since >= self.ENTERTAINMENT_STABLE_TIME:
                return True

        return False

    def _find_itachi_gift(self, purchased_gifts: set[str]) -> tuple[str, tuple[int, int, int, int]] | None:
        """同一截图扫描商品区，只接受完整礼盒名称，不做逐字兜底匹配。"""

        self.screenshot()
        rules = (self.O_ITACHI_MINI, self.O_ITACHI_MEDIUM, self.O_ITACHI_LARGE)
        scan = copy(rules[0])
        scan.roi = tuple(rules[0].area)
        results = scan.detect_and_ocr(self.device.image)
        for rule in rules:
            if rule.keyword in purchased_gifts:
                continue
            for result in results:
                text = ''.join(result.ocr_text.split())
                if text != rule.keyword:
                    continue
                box = result.box
                x, y = box.min(axis=0)
                right, bottom = box.max(axis=0)
                area = (int(x + scan.roi[0]), int(y + scan.roi[1]),
                        int(right - x), int(bottom - y))
                if area[2] > 0 and area[3] > 0:
                    logger.info(f'[鼬乐币] 识别到礼盒: {rule.keyword}, 区域={area}')
                    return rule.keyword, area
        logger.info('[鼬乐币] 未识别到可购买的鼬乐礼盒名称')
        return None

    def _open_front_gift_once(self, click_rule: RuleClick = None) -> bool:
        """点击一次礼盒，并等待至多三秒确认购买框。

        :param click_rule: 按名称识别到的礼盒位置，为空时点击前排固定位置
        """

        self.screenshot()
        self.click(click_rule if click_rule is not None else self.C_ITACHI_GIFT)
        deadline = time.monotonic() + self.GIFT_DIALOG_TIMEOUT
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_BUY_PLUS):
                return True
        return False

    def _read_itachi_coin(self) -> tuple[int, int] | None:
        result = self.O_ITACHI_COIN.ocr(self.device.image)
        if isinstance(result, tuple) and len(result) >= 3:
            current, _, total = result[:3]
            if total > 0:
                logger.info(f'[鼬乐币] 当前鼬乐币: {current}/{total}')
                return int(current), int(total)
        logger.warning(f'[鼬乐币] 鼬乐币识别失败: {result}')
        return None

    def _read_buy_cost(self) -> int | None:
        result = self.O_ITACHI_BUY_COST.ocr(self.device.image)
        if isinstance(result, int) and result > 0:
            logger.info(f'[鼬乐币] 鼬乐礼盒价格: {result}')
            return result
        logger.warning(f'[鼬乐币] 鼬乐礼盒价格识别失败: {result}')
        return None

    def _buy_opened_gift(self) -> bool:
        """确认一次购买，并区分奖励成功与直接退回商店的失败状态。"""

        self.screenshot()
        before_coin = self._read_itachi_coin()
        cost = self._read_buy_cost()
        self.click(self.C_BUY_MORE)

        deadline = time.monotonic() + self.PURCHASE_RESULT_TIMEOUT
        dialog_absent_since = None
        while time.monotonic() < deadline:
            self.screenshot()
            if self.appear(self.I_UI_REWARD, threshold=0.6):
                reward_closed = self._dismiss_purchase_reward()
                if reward_closed:
                    self._verify_coin_cost(before_coin, cost)
                return reward_closed

            if self.appear(self.I_BUY_PLUS):
                dialog_absent_since = None
                continue

            if dialog_absent_since is None:
                dialog_absent_since = time.monotonic()
                continue
            if time.monotonic() - dialog_absent_since >= self.PURCHASE_RETURN_GRACE:
                logger.warning('[鼬乐币] 购买失败或鼬乐币不足')
                return False

        logger.warning('[鼬乐币] 等待购买结果超时')
        return False

    def _dismiss_purchase_reward(self) -> bool:
        deadline = time.monotonic() + self.REWARD_DISMISS_TIMEOUT
        while time.monotonic() < deadline:
            self.screenshot()
            if not self.appear(self.I_UI_REWARD, threshold=0.6):
                return True
            self.ui_reward_appear_click()
        logger.warning('[鼬乐币] 礼盒奖励弹窗未关闭')
        return False

    def _verify_coin_cost(
        self,
        before_coin: tuple[int, int] | None,
        cost: int | None,
    ) -> None:
        self.screenshot()
        after_coin = self._read_itachi_coin()
        if before_coin is None or after_coin is None or cost is None:
            return
        consumed = before_coin[0] - after_coin[0]
        if consumed == cost:
            logger.info(f'[鼬乐币] 购买确认完成: 消耗={consumed}')
        else:
            logger.warning(
                '[鼬乐币] 鼬乐币变动与价格不符: '
                f'before={before_coin[0]}, after={after_coin[0]}, '
                f'cost={cost}'
            )

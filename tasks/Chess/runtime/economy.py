"""Chess 运行时：商店访问、购买与原子化经济操作。"""

# This Python file uses the following encoding: utf-8

import re
import time

import cv2
import numpy as np

from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.logger import logger
from tasks.Chess.strategy.shikigami_catalog import SHIKIGAMI_BY_ROMAJI


class ChessEconomyMixin:
    """内部 mixin；仅通过 ``ScriptTask`` 使用。"""

    def _shop_slots(self) -> list[tuple[int, RuleClick]]:
        """返回商店五个卡面点击区；编号按原资源定义从右向左。"""
        return [
            (
                index,
                getattr(self, f'C_SHIKIGAMI_{index}'),
            )
            for index in range(1, 6)
        ]

    def _is_shop_open(self) -> bool:
        """使用刷新按钮判断商店是否展开；禁止在此读取价格 OCR。

        ``check_market`` 是开店确认的辅助标志，不能用于“商店仍展开”
        的通用判断，否则商店关闭后仍可能命中该图标，导致上卡阶段被
        误判为商店未关闭。
        """
        visible = self._shop_refresh_marker_visible()
        if visible:
            self._shop_assumed_open = True
            return True
        # 战斗技能会遮住右侧刷新按钮。经济续跑期间以脚本自己记录的
        # 商店状态为准，避免因“看不见刷新”而反复开关商店。
        return bool(
            getattr(self, '_economy_battle_mode', False)
            and getattr(self, '_shop_assumed_open', False)
        )

    def _shop_refresh_marker_visible(self) -> bool:
        """刷新/金币不足刷新任一出现，表示商店明确展开。"""
        return self.appear(self.I_REFRESH) or self.appear(self.I_REFRESH_NOT_GOLD)

    def _shop_open_confirm_marker_visible(self) -> bool:
        """开店确认：非战阶段只看 refresh；战阶段追加 check_market。"""
        if self._shop_refresh_marker_visible():
            return True
        return self._read_chess_mode() == '战' and self.appear(
            self.I_CHECK_MARKET
        )

    def _is_preparation_mode(self) -> bool:
        """只有无符咒弹窗的“备”可继续操作；弹窗出现立即中断。"""
        if self._read_chess_mode() != '备':
            return False
        if self.appear(self.I_SELECT_GRIGRI):
            logger.debug(
                '[棋局] 立即中断准备阶段: 检测到御念选择'
                '面板'
            )
            return False
        return True

    def _is_purchase_allowed(self) -> bool:
        """商店动作遇到“鬼”必停；其余阶段由外层状态机调度。"""
        mode = self._read_chess_mode()
        if mode == '鬼':
            return False
        return True

    def _read_shop_gold(self) -> int | None:
        """读取当前金币；OCR 异常时返回 None，避免误停购买流程。"""
        value = self.O_GOLD.ocr(self.device.image)
        if not isinstance(value, int) or value < 0:
            logger.warning(f'[棋局] 金币 OCR 无效: [{value}]')
            return None
        return value

    @staticmethod
    def _parse_coin_text(raw_text: str) -> dict | None:
        """解析鼬乐币 m/600，并恢复斜杠丢失或误识别为 1/I 的结果。"""
        raw = ''.join(str(raw_text or '').split())
        if not raw:
            return None

        # 标准斜杠以及被识别为 I/l/竖线的分隔符。
        explicit = re.search(r'(\d{1,3})[/／Iil|](600)$', raw)
        recovered = False
        if explicit is not None:
            current = int(explicit.group(1))
            recovered = '/' not in raw and '／' not in raw
        else:
            digits = ''.join(re.findall(r'\d', raw))
            if not digits.endswith('600'):
                return None
            prefix = digits[:-3]
            # 3441600 表示 344/600，其中额外的 1 是斜杠误识别。
            if len(prefix) == 4 and prefix.endswith('1'):
                prefix = prefix[:-1]
                recovered = True
            elif prefix:
                recovered = True
            if not prefix:
                return None
            current = int(prefix)

        if not 0 <= current <= 600:
            return None
        return {
            'current': current,
            'remaining': 600 - current,
            'total': 600,
            'raw': raw,
            'recovered': recovered,
        }

    def _read_coin(self) -> dict | None:
        """读取棋局大厅鼬乐币，优先消费 DigitCounter 三元组。"""
        result = self.O_COIN.ocr(self.device.image)
        coin = None
        if isinstance(result, (tuple, list)) and len(result) == 3:
            current, remaining, total = result
            if (
                all(isinstance(value, int) for value in result)
                and current >= 0
                and remaining >= 0
                and total == 600
                and current + remaining == total
            ):
                coin = {
                    'current': current,
                    'remaining': remaining,
                    'total': total,
                    'raw': f'{current}/{total}',
                    'recovered': False,
                }
        else:
            # 兼容尚未重新生成资源、仍返回文本的旧版 OCR 配置。
            raw = self._normalize_ocr_text(result)
            coin = self._parse_coin_text(raw)

        if coin is None:
            logger.warning(f'[棋局] 鼬乐币 OCR 无效: [{result}]')
            return None
        if coin['recovered']:
            logger.debug(
                f'[棋局] 鼬乐币 OCR 已恢复: [{coin["raw"]}] -> '
                f'{coin["current"]}/{coin["total"]}'
            )
        else:
            logger.debug(
                f'[棋局] 鼬乐币: {coin["current"]}/{coin["total"]}'
            )
        return coin

    def _coin_is_full(self) -> bool:
        """最多复查三帧，仅 600/600 才视为鼬乐币已满。"""
        for attempt in range(1, 4):
            coin = self._read_coin()
            if coin is not None:
                full = coin['current'] == coin['total'] == 600
                if full:
                    logger.info('[棋局] 鼬乐币已满: 600/600')
                return full
            if attempt < 3:
                time.sleep(self.SCREENSHOT_INTERVAL)
                self.screenshot()
        return False

    def _can_afford_shop_shikigami(
        self,
        slot_index: int,
        known_price: int,
    ) -> bool:
        """判断购买能力；身份已确定时优先使用目录费用。"""
        if slot_index not in range(1, 6):
            logger.warning(f'[棋局] 商店格子索引无效: {slot_index}')
            return False

        gold = self._read_shop_gold()
        raw_price = ''
        price = known_price
        if gold is None or price is None:
            logger.warning(
                '[棋局] 跳过商店购买: 购买力 OCR'
                f'不可用: 格子={slot_index}, 金币={gold}, '
                f'价格原文=[{raw_price}]'
            )
            return False

        affordable = gold >= price
        logger.debug(
            '[棋局] 商店购买力: '
            f'格子={slot_index}, 金币={gold}, 价格={price}, '
            f'可购买={affordable}'
        )
        return affordable


    def _ensure_shop_open(self) -> bool:
        """必要时点击商店图标，并等待刷新按钮确认商店已经展开。"""
        if not self._is_purchase_allowed():
            logger.debug('[棋局] 检测到百鬼模式，停止打开商店')
            return False
        if getattr(self, '_economy_battle_mode', False):
            return self._ensure_battle_economy_shop_open()
        if self._is_shop_open():
            logger.debug('[棋局] 商店已打开')
            self._shop_assumed_open = True
            return True

        logger.debug('[棋局] 商店已关闭，点击市场打开')
        # C_MARKET 是跨回合反复使用的合法开关；每次新状态转换单独计数。
        self.device.click_record_remove(self.I_MARKET)
        deadline = time.monotonic() + self.SHOP_OPEN_TIMEOUT
        attempts = 0
        while time.monotonic() < deadline:
            if not self._is_purchase_allowed():
                logger.debug('[棋局] 检测到百鬼模式，停止打开商店')
                return False
            attempts += 1
            self.click(self.I_MARKET)
            attempt_deadline = min(
                deadline,
                time.monotonic() + 2 * self.SLOW_POLL_INTERVAL,
            )
            while time.monotonic() < attempt_deadline:
                time.sleep(self.SCREENSHOT_INTERVAL)
                self.screenshot()
                if not self._is_purchase_allowed():
                    logger.debug('[棋局] 检测到百鬼模式，停止打开商店')
                    return False
                if self._shop_open_confirm_marker_visible():
                    logger.debug(
                        f'[棋局] 商店打开成功，尝试次数={attempts}'
                    )
                    self._shop_assumed_open = True
                    return True

        logger.warning('[棋局] 等待打开商店超时')
        return False

    def _ensure_battle_economy_shop_open(self) -> bool:
        """战斗中只开一次商店，不以可能被技能遮挡的刷新图标反复切换。"""
        if self._read_chess_mode() != '战':
            logger.debug('[棋局] 模式已不再是战，停止打开战斗经济商店')
            return False
        if getattr(self, '_shop_assumed_open', False):
            logger.debug('[棋局] 假定战斗经济商店已打开')
            return True
        if self._shop_open_confirm_marker_visible():
            self._shop_assumed_open = True
            logger.debug('[棋局] 战斗经济商店已可见打开')
            return True

        logger.debug(
            '[棋局] 战斗经济仅打开一次商店，后续状态'
            '由内部跟踪'
        )
        self.device.click_record_remove(self.I_MARKET)
        self.click(self.I_MARKET)
        time.sleep(2 * self.SLOW_POLL_INTERVAL)
        self.screenshot()
        if self._read_chess_mode() != '战':
            logger.debug('[棋局] 打开经济商店时战斗模式已结束')
            return False
        self._shop_assumed_open = True
        return True

    def _ensure_shop_closed(
        self,
        allowed_modes: tuple[str, ...] = ('备',),
    ) -> bool:
        """在指定模式内关闭商店；上卡默认仅允许“备”。"""
        if self._read_chess_mode() not in allowed_modes:
            logger.debug(
                '[棋局] 停止关闭商店: 模式不在'
                f'{allowed_modes}'
            )
            return False
        shop_visible = self._shop_refresh_marker_visible()
        shop_assumed_open = getattr(self, '_shop_assumed_open', False)
        if not shop_visible and not shop_assumed_open:
            logger.debug('[棋局] 商店已关闭')
            return True
        if self._read_chess_mode() != '战' and not shop_visible:
            # 非战斗画面刷新按钮不会被技能遮挡；看不到即以实际画面为准，
            # 清除跨阶段遗留的内部状态，禁止误点后把商店反而打开。
            self._shop_assumed_open = False
            logger.debug('[棋局] 商店可见已关闭；清理过期状态')
            return True
        if (
            self._read_chess_mode() in ('鬼', '待')
            and not shop_visible
        ):
            # 进入鬼/待后游戏会自行收起商店；内部状态可能仍停留在上一帧。
            # 此时不能点击不可用的商店位置，只清除脚本侧状态。
            self._shop_assumed_open = False
            logger.debug('[棋局] 被动模式下清理过期商店状态')
            return True

        logger.debug('[棋局] 商店已打开，点击市场关闭')
        self.device.click_record_remove(self.I_MARKET)
        # 战斗中刷新按钮可能完全被技能遮挡。若商店仅由内部状态确认，
        # 固定点击一次即可关闭，禁止进入“看不见 -> 再点一次”的抖动。
        if (
            self._read_chess_mode() == '战'
            and shop_assumed_open
            and not shop_visible
        ):
            self.click(self.I_MARKET)
            time.sleep(2 * self.SLOW_POLL_INTERVAL)
            self.screenshot()
            self._shop_assumed_open = False
            logger.debug('[棋局] 战斗经济商店已被一次性开关关闭')
            return True

        deadline = time.monotonic() + self.SHOP_CLOSE_TIMEOUT
        while time.monotonic() < deadline:
            if self._read_chess_mode() not in allowed_modes:
                logger.debug(
                    '[棋局] 停止关闭商店: 模式已改变，允许模式为'
                    f'{allowed_modes}'
                )
                return False
            self.click(self.I_MARKET)
            attempt_deadline = min(
                deadline,
                time.monotonic() + 2 * self.SLOW_POLL_INTERVAL,
            )
            while time.monotonic() < attempt_deadline:
                time.sleep(self.SCREENSHOT_INTERVAL)
                self.screenshot()
                if self._read_chess_mode() not in allowed_modes:
                    logger.debug(
                        '[棋局] 停止关闭商店: 模式已改变，允许模式为'
                        f'{allowed_modes}'
                    )
                    return False
                if not self._is_shop_open():
                    logger.debug('[棋局] 商店关闭成功')
                    self._shop_assumed_open = False
                    return True

        logger.warning('[棋局] 等待关闭商店超时')
        return False

    def _clear_economy_click_history(self) -> None:
        """豁免合法的经验/刷新/买卡循环，保留其他按钮的全局防重复点击保护。

        商店槽位 C_SHIKIGAMI_1~5 每局要反复点击买卡，不清记录会在第 10 次触发
        GameTooManyClickError。
        """
        removed = {}
        for rule in (self.I_EXPERIENCE, self.I_REFRESH,
                     self.C_SHIKIGAMI_1, self.C_SHIKIGAMI_2, self.C_SHIKIGAMI_3,
                     self.C_SHIKIGAMI_4, self.C_SHIKIGAMI_5):
            removed[rule.name] = self.device.click_record_remove(rule)
        if any(removed.values()):
            logger.debug(
                '[棋局] 合规循环前清空经济点击历史: '
                + ', '.join(f'{k}={v}' for k, v in removed.items() if v)
            )


    def _recognize_shop_slot(
        self,
        slot_index: int,
        click_rule: RuleClick,
        expected_name: str | None = None,
    ) -> dict | None:
        """商店统一识别入口：金币定位，Frame 读取名字、特质及头像。"""
        return self._frame_shop_in_slot(click_rule, expected_name=expected_name)

    @staticmethod
    def _template_gray(image: np.ndarray) -> np.ndarray:
        if image.ndim == 2:
            return image
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


    def _buy_shop_slot(
        self,
        slot_index: int,
        click_rule: RuleClick,
        matched_name: str,
    ) -> bool:
        """持续点击目标商店格，直到原头像不再出现在该格。"""
        known_price = SHIKIGAMI_BY_ROMAJI[matched_name].cost
        deadline = time.monotonic() + self.SHOP_BUY_TIMEOUT
        current_match = self._recognize_shop_slot(
            slot_index,
            click_rule,
            expected_name=matched_name,
        )
        # 点击前目标就消失，不视为确认购买。
        if current_match is None:
            return False
        attempts = 0
        emergency_cleanup_done = False
        lineup_sale_done = False

        while current_match is not None and time.monotonic() < deadline:
            if not self._is_purchase_allowed():
                logger.debug(
                    f'[棋局] 检测到百鬼模式，停止购买{matched_name}'
                )
                return False
            if not self._can_afford_shop_shikigami(
                slot_index,
                known_price=known_price,
            ):
                logger.debug(
                    f'[棋局] 跳过购买{matched_name}: 金币不足，'
                    f'商店格子 {slot_index}'
                )
                return False
            attempts += 1
            logger.info(
                f'[棋局] 购买卡牌: '
                f'{self._shikigami_display_name(matched_name)} '
                f'（格子={slot_index}, '
                f'尝试={attempts}, 来源={current_match["source"]}, '
                f'识别得分={current_match["score"]:.3f})'
            )
            # 买卡是合法的反复点击；不清记录会累计到 10 次触发防连点保护
            self.device.click_record_remove(click_rule)
            clicked_and_gone = self.ui_click_until_disappear(
                click_rule,
                click_target=click_rule,
                visible=lambda: self._recognize_shop_slot(
                    slot_index, click_rule, expected_name=matched_name,
                ) is not None,
                guard=lambda: self._is_purchase_allowed() and not self.appear(self.I_SELECT_GRIGRI),
                interval=0.3,
                timeout=min(2.0, max(0.0, deadline-time.monotonic())),
                confirm_frames=2,
            )
            if clicked_and_gone:
                return True
            if not self._is_purchase_allowed() or self.appear(self.I_SELECT_GRIGRI):
                return False
            current_match = self._recognize_shop_slot(
                slot_index,
                click_rule,
                expected_name=matched_name,
            )
            if current_match is None:
                # 超时或点击前消失，未通过两帧确认。
                return False
            if current_match is not None:
                if not self._is_purchase_allowed():
                    logger.debug(
                        f'[棋局] 检测到百鬼模式，停止购买{matched_name}'
                    )
                    return False
                if not self._can_afford_shop_shikigami(
                    slot_index,
                    known_price=known_price,
                ):
                    logger.debug(
                        f'[棋局] 停止重试购买{matched_name}: 金币不足'
                        f'商店格子 {slot_index}'
                    )
                    return False
                logger.debug(
                    f'[棋局] 商店格子 {slot_index} 仍匹配'
                    f'{matched_name}，点击后清理手牌再重试'
                )
                if emergency_cleanup_done and lineup_sale_done:
                    logger.warning(
                        f'[棋局] 购买{matched_name}在紧急清理并售出一张阵容卡后仍受阻'
                        ''
                    )
                    return False
                sell_lineup = emergency_cleanup_done
                recovery = self._free_one_hand_slot_for_purchase(
                    sell_lineup=sell_lineup,
                )
                if recovery is None:
                    logger.warning(
                        f'[棋局] 购买{matched_name}仍未确认，'
                        '且无安全手牌可清理；阻止商店刷新'
                    )
                    return False
                if sell_lineup or recovery.get('type') == 'lineup':
                    emergency_cleanup_done = True
                    lineup_sale_done = True
                    logger.debug(
                        f'[棋局] 售出一张阵容卡后重试购买{matched_name}'
                        ''
                    )
                else:
                    emergency_cleanup_done = True
                    logger.debug(
                        f'[棋局] 紧急清理手牌后重试购买{matched_name}'
                        ''
                    )

        if current_match is None:
            logger.debug(
                '[棋局] 商店购买成功（目标消失确认）: '
                f'格子={slot_index}, 名称={matched_name}, 尝试={attempts}'
            )
            return True

        logger.warning(
            f'[棋局] 商店购买超时: 格子={slot_index}, '
            f'名称={matched_name}, 目标仍在格子中'
        )
        return False

    def buy_lineup_shikigami_from_shop(self) -> list[str] | None:
        """整页识别一次记录目标，再逐格复核头像并购买。"""
        if not self._is_purchase_allowed():
            logger.debug('[棋局] 检测到百鬼模式，停止商店购买')
            return None
        if not self._ensure_shop_open():
            return None

        logger.debug('[棋局] 购买前扫描全部商店格子')
        targets = []
        recognized_slots = {}

        for slot_index, click_rule in self._shop_slots():
            if not self._is_purchase_allowed():
                logger.debug('[棋局] 检测到百鬼模式，停止商店购买')
                return None
            matched = self._recognize_shop_slot(
                slot_index,
                click_rule,
            )
            if matched is None:
                recognized_slots[slot_index] = '未识别'
                logger.debug(
                    f'[棋局] 商店格子 {slot_index}: 未能识别目标'
                )
                continue

            recognized_slots[slot_index] = self._shikigami_display_name(
                matched['name']
            )

            if matched['name'] not in self.shikigami_deploy_positions:
                logger.debug(
                    f'[棋局] 商店格子 {slot_index}: 识别到非阵容'
                    f'卡牌 {matched["name"]}'
                )
                continue

            logger.debug(
                f'[棋局] 商店格子 {slot_index}: {matched["source"]} -> '
                f'{matched["name"]}, 得分={matched["score"]:.3f}'
            )
            targets.append({
                'slot_index': slot_index,
                'click_rule': click_rule,
                'matched_name': matched['name'],
                'known_price': SHIKIGAMI_BY_ROMAJI[matched['name']].cost,
            })

        # 资源编号从右向左为 1→5；日志按玩家看到的左→右输出 5→1。
        logger.info(
            '[棋局] 商店识别结果（从左到右）: '
            + ' | '.join(
                recognized_slots.get(slot_index, '未识别')
                for slot_index in range(5, 0, -1)
            )
        )
        logger.debug(
            '[棋局] 商店目标扫描完成: '
            f'{[(item["slot_index"], item["matched_name"]) for item in targets]}'
        )
        purchased = []
        for target in targets:
            if not self._is_purchase_allowed():
                logger.debug('[棋局] 检测到百鬼模式，停止商店购买')
                return None
            if not self._can_afford_shop_shikigami(
                target['slot_index'],
                known_price=target['known_price'],
            ):
                logger.debug(
                    '[棋局] 跳过买不起的商店目标: '
                    f'格子={target["slot_index"]}, '
                    f'名称={target["matched_name"]}'
                )
                continue
            if self._buy_shop_slot(
                slot_index=target['slot_index'],
                click_rule=target['click_rule'],
                matched_name=target['matched_name'],
            ):
                purchased.append(target['matched_name'])
                # 复用两帧消失确认所用的截图；
                # 下一个目标在点击前只复查自己的头像。
            elif not self._is_purchase_allowed():
                return None
            elif not self._can_afford_shop_shikigami(
                target['slot_index'],
                known_price=target['known_price'],
            ):
                logger.debug(
                    '[棋局] 目标已买不起；跳过并继续: '
                    f'格子={target["slot_index"]}, '
                    f'名称={target["matched_name"]}'
                )
                continue
            else:
                logger.warning(
                    '[棋局] 目标购买未经头像'
                    '消失确认；'
                    f'格子={target["slot_index"]}, '
                    f'名称={target["matched_name"]}; '
                    '本轮商店循环就此停止，暂不刷新'
                )
                return None

        logger.debug(f'[棋局] 商店检查完成，已购={purchased}')
        return purchased

    def purchase_lineup_cards_once(self) -> list[str] | None:
        """确保商店打开后扫描并购买，不负责关闭商店。"""
        return self.buy_lineup_shikigami_from_shop()

    def _reset_economy_state(self) -> None:
        """重置单局可暂停的回目结束任务和商店状态。"""
        self._economy_pending = False
        self._economy_step_state = 'idle'
        self._economy_sequence_level = None
        self._economy_sequence_index = 0
        self._economy_battle_mode = False
        self._shop_assumed_open = False

    def _schedule_economy_cycle(self) -> None:
        """登记一次经济任务；已有未完成原子动作时保持其精确进度。"""
        if getattr(self, '_economy_pending', False):
            logger.debug(
                '[棋局] 经济操作已在进行中: '
                f'状态={self._economy_step_state}'
            )
            return
        self._economy_pending = True
        self._economy_step_state = 'ready'
        logger.debug('[棋局] 调度经济升级/刷新周期')


    def _finish_economy_cycle(self, reason: str) -> None:
        self._economy_pending = False
        self._economy_step_state = 'idle'
        logger.debug(f'[棋局] 经济周期完成: {reason}')

    def _click_economy_button_and_confirm_gold(
        self,
        button: RuleImage,
        expected_cost: int,
        label: str,
        allow_hidden: bool,
    ) -> str:
        """点击经济按钮，以金币下降确认；返回 success/no_progress/unknown。"""
        gold_before = self._read_shop_gold()
        if gold_before is None:
            logger.warning(f'[棋局] 无法确认{label}: 金币 OCR 不可用')
            return 'no_progress'
        if not allow_hidden and not self.appear(button):
            logger.warning(f'[棋局] 无法执行{label}: 按钮不存在')
            return 'no_progress'

        for attempt in range(1, self.ECONOMY_CONFIRM_RETRIES + 1):
            logger.debug(
                f'[棋局] {label}: 定点点击第{attempt}次，'
                f'点击前金币={gold_before}'
            )
            self._clear_economy_click_history()
            self.click(button)
            time.sleep(self.ACTION_SETTLE_INTERVAL)
            self.screenshot()
            gold_after = self._read_shop_gold()
            if gold_after is None:
                logger.warning(
                    f'[棋局] {label}已点击，但确认 OCR'
                    '不可用；保留既有进度'
                )
                return 'unknown'
            if gold_after <= gold_before - expected_cost:
                logger.debug(
                    f'[棋局] {label}经金币确认: '
                    f'{gold_before} -> {gold_after}'
                )
                return 'success'
            logger.warning(
                f'[棋局] {label}点击后无已确认进度: '
                f'{gold_before} -> {gold_after}'
            )

        return 'no_progress'

    def _shop_slot_refresh_snapshot(self) -> dict[int, dict]:
        """保存五个商店槽位的身份和低分辨率图像，用于确认刷新。"""
        snapshot = {}
        image_height, image_width = self.device.image.shape[:2]
        for slot_index, click_rule in self._shop_slots():
            matched = self._recognize_shop_slot(
                slot_index,
                click_rule,
            )
            x, y, width, height = click_rule.roi_back
            x = max(0, int(x))
            y = max(0, int(y))
            width = min(int(width), image_width - x)
            height = min(int(height), image_height - y)
            crop = self.device.image[y:y + height, x:x + width]
            if crop.size:
                gray = self._template_gray(crop)
                signature = cv2.resize(
                    gray,
                    (32, 32),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                signature = None
            snapshot[slot_index] = {
                'name': None if matched is None else matched['name'],
                'image': signature,
            }
        return snapshot

    def _shop_refresh_changed_slots(
        self,
        before: dict[int, dict],
        after: dict[int, dict],
    ) -> tuple[list[int], dict[int, float]]:
        """比较对应槽位；身份可用时比较身份，否则以卡面图像差异兜底。"""
        changed = []
        image_differences = {}
        for slot_index in range(1, 6):
            previous = before[slot_index]
            current = after[slot_index]
            previous_name = previous['name']
            current_name = current['name']
            previous_image = previous['image']
            current_image = current['image']
            difference = 0.0
            if previous_image is not None and current_image is not None:
                difference = float(np.mean(cv2.absdiff(
                    previous_image,
                    current_image,
                )))
            image_differences[slot_index] = difference
            if previous_name is not None and current_name is not None:
                slot_changed = previous_name != current_name
            else:
                slot_changed = (
                    difference
                    >= self.SHOP_REFRESH_SLOT_IMAGE_DIFF_THRESHOLD
                )
            if slot_changed:
                changed.append(slot_index)
        return changed, image_differences

    def _click_shop_refresh_and_confirm_slots(
        self,
        allow_hidden: bool,
    ) -> str:
        """点击刷新，以至少三个对应商店槽位变化确认成功。"""
        if not allow_hidden and not self.appear(self.I_REFRESH):
            logger.warning('[棋局] 无法刷新商店: 按钮不存在')
            return 'no_progress'

        before = self._shop_slot_refresh_snapshot()
        for attempt in range(1, self.ECONOMY_CONFIRM_RETRIES + 1):
            self._clear_economy_click_history()
            self.click(self.I_REFRESH)
            time.sleep(self.ACTION_SETTLE_INTERVAL)
            self.screenshot()
            after = self._shop_slot_refresh_snapshot()
            changed, differences = self._shop_refresh_changed_slots(
                before,
                after,
            )
            logger.info(
                '[棋局] 商店刷新格子对比: '
                f'尝试={attempt}, 变化={changed}, '
                f'变化格子数={len(changed)}/5, '
                f'刷新前='
                f'{[before[index]["name"] for index in range(5, 0, -1)]}, '
                f'刷新后='
                f'{[after[index]["name"] for index in range(5, 0, -1)]}, '
                f'图像差异='
                f'{[round(differences[index], 2) for index in range(5, 0, -1)]}'
            )
            if len(changed) >= self.SHOP_REFRESH_CHANGED_SLOT_MINIMUM:
                return 'success'
            before = after
        logger.warning(
            '[棋局] 商店刷新未确认: 变化格子少于'
            f'{self.SHOP_REFRESH_CHANGED_SLOT_MINIMUM} 个格子变化'
        )
        return 'no_progress'

    def _economy_sequence_for_level(self, level: int) -> tuple[str, ...]:
        """返回当前阶数的原子操作序列。"""
        if level >= self._lineup_final_level():
            return ('refresh',)
        if level <= 2:
            return ('experience',)
        if level <= 7:
            return ('experience', 'refresh')
        return ('experience', 'refresh', 'refresh')

    def _economy_reserve_for_level(self, level: int) -> int:
        if level >= self._lineup_final_level():
            return 0
        if level <= 2:
            return 0
        elif level <= 5:
            return 35
        elif level <= 7:
            return 23
        return 10

    def _reset_economy_sequence_if_level_changed(self, level: int) -> None:
        if self._economy_sequence_level == level:
            return
        logger.debug(
            '[棋局] 重置经济操作计数: '
            f'{self._economy_sequence_level} -> {level}'
        )
        self._economy_sequence_level = level
        self._economy_sequence_index = 0

    def _next_economy_operation(self, level: int) -> str:
        self._reset_economy_sequence_if_level_changed(level)
        sequence = self._economy_sequence_for_level(level)
        index = self._economy_sequence_index % len(sequence)
        operation = sequence[index]
        logger.debug(
            '[棋局] 经济下一操作: '
            f'级={level}, 序列={sequence}, 索引={index}, '
            f'操作={operation}'
        )
        return operation

    def _advance_economy_operation_counter(self, level: int) -> None:
        self._reset_economy_sequence_if_level_changed(level)
        sequence = self._economy_sequence_for_level(level)
        self._economy_sequence_index = (
            self._economy_sequence_index + 1
        ) % len(sequence)
        logger.debug(
            '[棋局] 推进经济操作计数: '
            f'级={level}, 下一索引={self._economy_sequence_index}'
        )

    def _can_execute_economy_operation(
        self,
        level: int,
        gold: int,
        operation: str,
    ) -> bool:
        reserve = self._economy_reserve_for_level(level)
        cost = (
            self.EXPERIENCE_COST
            if operation == 'experience'
            else self.SHOP_REFRESH_COST
        )
        if level < self._lineup_final_level() and gold <= reserve:
            return False
        return gold >= reserve + cost

    def _run_economy_atomic_batch(self, battle_mode: bool = False) -> str:
        """执行一个由计数器决定的升级/刷新原子动作。"""
        if not getattr(self, '_economy_pending', False):
            return 'complete'
        if not self._is_purchase_allowed():
            logger.debug('[棋局] 检测到百鬼模式，暂停经济运营')
            return 'blocked'

        previous_battle_mode = getattr(self, '_economy_battle_mode', False)
        self._economy_battle_mode = battle_mode
        try:
            level = self._read_level()
            gold = self._read_shop_gold()
            if level is None or gold is None:
                logger.warning(
                    '[棋局] 等级或金币 OCR 不可用，暂停经济运营'
                )
                return 'blocked'

            operation = self._next_economy_operation(level)
            if not self._can_execute_economy_operation(level, gold, operation):
                self._finish_economy_cycle(
                    f'budget limit reached, level={level}, gold={gold}, '
                    f'operation={operation}, '
                    f'reserve={self._economy_reserve_for_level(level)}, '
                    f'final_level={self._lineup_final_level()}'
                )
                return 'complete'

            if operation == 'experience':
                result = self._click_economy_button_and_confirm_gold(
                    self.I_EXPERIENCE,
                    self.EXPERIENCE_COST,
                    'buy experience',
                    allow_hidden=battle_mode,
                )
                if result == 'no_progress':
                    return 'blocked'
                self._advance_economy_operation_counter(level)
            else:
                # 只有刷新动作要求商店打开；购买经验不改变商店状态。
                if not self._ensure_shop_open():
                    return 'blocked'
                result = self._click_shop_refresh_and_confirm_slots(
                    allow_hidden=battle_mode,
                )
                if result == 'no_progress':
                    return 'blocked'
                logger.info('[棋局] 刷新商店完成')
                self._advance_economy_operation_counter(level)
                # 槽位变化确认时商店已完成换牌；仍额外等待稳定帧，
                # 再读取费用和羁绊，避免残余动画影响购买识别。
                time.sleep(self.ACTION_SETTLE_INTERVAL)
                self.screenshot()
                purchased = self.purchase_lineup_cards_once()
                if purchased is None:
                    logger.warning(
                        '[棋局] 刷新后购买未'
                        '得到确认，暂停经济运营'
                    )
                    return 'blocked'
            self._economy_step_state = 'ready'

            logger.debug(
                '[棋局] 经济原子批次完成: '
                f'操作={operation}, 战斗模式={battle_mode}'
            )

            # 只判断是否还有下一批；真正执行留到外层重新截图、检查回目
            # 后，确保新回目的备阶段能够抢占长时间经济循环。
            level = self._read_level()
            gold = self._read_shop_gold()
            if level is None or gold is None:
                return 'pending'
            next_operation = self._next_economy_operation(level)
            if self._can_execute_economy_operation(
                level,
                gold,
                next_operation,
            ):
                return 'pending'
            self._finish_economy_cycle(
                f'budget limit reached after batch, level={level}, '
                f'gold={gold}, next_operation={next_operation}, '
                f'reserve={self._economy_reserve_for_level(level)}, '
                f'final_level={self._lineup_final_level()}'
            )
            return 'complete'
        finally:
            self._economy_battle_mode = previous_battle_mode

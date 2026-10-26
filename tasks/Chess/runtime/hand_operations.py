"""Chess 运行时：手牌、上阵、御魂、清理与召回操作。"""

# This Python file uses the following encoding: utf-8

import random
import time
from collections import Counter

import cv2
import numpy as np

from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.exception import GameStuckError
from module.logger import logger
from tasks.Chess.runtime.press_and_drag import Press_and_Drag
from tasks.Chess.strategy.grigri import (
    grigri_bond_name,
)
from tasks.Chess.strategy.shikigami_catalog import (
    SHIKIGAMI_BONDS_BY_ROMAJI,
    resolve_shikigami,
)


class ChessHandOperationsMixin:
    """内部 mixin；仅通过 ``ScriptTask`` 使用。"""

    def _shikigami_attributes(
        self,
        name: str,
    ) -> tuple[str | None, str | None, str | None]:
        """返回式神本局属性：(守护之印, 御魂1, 御魂2)。"""
        attributes = getattr(self, '_board_shikigami_attributes', {})
        return attributes.get(name, (None, None, None))

    def _set_shikigami_attributes(
        self,
        name: str,
        values: tuple[str | None, str | None, str | None],
    ) -> None:
        attributes = dict(
            getattr(self, '_board_shikigami_attributes', {})
        )
        attributes[name] = values
        self._board_shikigami_attributes = attributes
        logger.debug(f'[棋局] 式神属性: {name}={values}')

    def _shikigami_name_at_set(self, set_index: int) -> str | None:
        """按本局实际位置反查指定站位的目标式神。"""
        if (
            getattr(self, '_arakawa_goldfish_current_position', None)
            == set_index
        ):
            # 荒川金鱼属于特殊单位，不能成为任何装备的目标。
            return None
        deployed_names = set(getattr(self, '_board_lineup_names', set()))
        actual_positions = getattr(self, '_board_actual_positions', {})
        return next((
            name
            for name in deployed_names
            if actual_positions.get(
                name,
                self.shikigami_deploy_positions.get(name),
            ) == set_index
        ), None)

    def _record_actual_lineup_position(
        self,
        name: str,
        set_index: int,
    ) -> None:
        positions = dict(getattr(self, '_board_actual_positions', {}))
        positions[name] = int(set_index)
        self._board_actual_positions = positions

    def _record_shikigami_soul(self, name: str, soul_name: str) -> bool:
        """写入普通御魂槽；重复御魂或两槽已满时拒绝写入。"""
        protect, soul_1, soul_2 = self._shikigami_attributes(name)
        if soul_name in (soul_1, soul_2):
            return False
        if soul_1 is None:
            soul_1 = soul_name
        elif soul_2 is None:
            soul_2 = soul_name
        else:
            return False
        self._set_shikigami_attributes(
            name,
            (protect, soul_1, soul_2),
        )
        return True

    @staticmethod
    def _rule_center(rule: RuleImage | RuleClick) -> tuple[int, int]:
        x, y, width, height = rule.roi_back
        return x + width // 2, y + height // 2

    def _set_position(self, set_index: int) -> tuple[int, int]:
        """读取普通/首领 Frame 第 13-24 项的上阵落点。"""
        index = int(set_index)
        if not 1 <= index <= 12:
            raise ValueError(f'[棋局] 棋盘套装位置未配置: {set_index}')
        frame = (self.F_BOSS_BOARD_OCCUPANCY if self._is_boss_challenge_round()
                 else self.F_BOARD_OCCUPANCY)
        if not self.appear(frame):
            raise GameStuckError('[棋局] 棋盘部署 Frame 锚点未找到')
        x, y, w, h = frame.matched_ranges[12 + index - 1]
        return int(round(x + w / 2)), int(round(y + h / 2))

    def sell_hand_card(self, source: tuple[int, int]) -> None:
        """统一拖到左侧售卖区，避免出售动作改变商店开关状态。"""
        target_rule = self.I_EXPERIENCE
        # 卖卡前清掉点击记录，避免连续出售合法手牌累积触发防连点保护
        self.device.click_record_remove('CHESS_SELL_UNKNOWN_HAND_CARD')
        Press_and_Drag(
            self.device,
            p1=source,
            p2=self._rule_center(target_rule),
            hold_duration=(0.2, 0.3),
            point_random=(-3, -3, 3, 3),
            swipe_duration=0.5,
            name='CHESS_SELL_UNKNOWN_HAND_CARD',
        )
        self.close_shikigami_specifics_if_open()

    def _wait_hand_card_removed(self, count_before: int, count_cards) -> bool:
        """按新截图确认手牌数量减少，处理误开的详情页，不固定空等。"""
        def removed():
            if self.close_shikigami_specifics_if_open():
                return False
            return count_cards() < count_before

        return self._wait_chess_action_state(removed)

    def close_shikigami_specifics_if_open(self) -> bool:
        """卖卡/上卡误打开式神详情页时，点击安全区域直到关闭。"""
        if not hasattr(self, 'I_SHIKIGAMI_SPECIFICS'):
            return False
        if not self.appear(self.I_SHIKIGAMI_SPECIFICS):
            return False

        logger.warning(
            '[棋局] 式神详情意外打开，关闭它'
        )
        for attempt in range(1, self.ACTION_ICON_MAX_ATTEMPTS + 1):
            self.device.click_record_remove(self.C_CLICK_CLOSE_SPECIFICS_AREA)
            self.click(self.C_CLICK_CLOSE_SPECIFICS_AREA)
            if self._wait_chess_action_state(
                lambda: not self.appear(self.I_SHIKIGAMI_SPECIFICS)
            ):
                logger.debug(
                    '[棋局] 式神详情已关闭: '
                    f'尝试={attempt}/{self.ACTION_ICON_MAX_ATTEMPTS}'
                )
                return True
            logger.warning(
                '[棋局] 点击关闭后式神详情仍可见: '
                f'尝试={attempt}/{self.ACTION_ICON_MAX_ATTEMPTS}, '
                f'超时={self.ACTION_ICON_WAIT_TIMEOUT:.0f}秒'
            )
        raise GameStuckError(
            '[棋局] 关闭式神详情 3 次尝试后失败'
        )

    def sell_one_lineup_hand_card(self) -> dict | None:
        """紧急清理后仍然手满时，出售最右侧的已识别阵容式神。"""
        hand_cards = self._hand_card_detections()
        if not hand_cards:
            logger.warning(
                '[棋局] 手牌已满但未检测到手牌锚点'
            )
            return None

        lineup_names = set(self.shikigami_deploy_positions)
        candidates = []
        for card in hand_cards:
            identity = self.classify_hand_card(card['roi'])
            if (
                identity['type'] == 'shikigami'
                and identity['name'] in lineup_names
            ):
                candidates.append(identity)
        if not candidates:
            logger.warning(
                '[棋局] 手牌仍满，且没有可识别的阵容卡'
                '可供紧急出售'
            )
            return None

        identity = max(
            candidates,
            key=lambda item: item['position'][0],
        )
        position = identity['position']
        sale_key = (identity['type'], identity['name'])
        count_before = self._hand_card_identity_count(*sale_key)
        logger.info(
            f'[棋局] 手牌持续满后出售阵容卡: '
            f'名称={self._shikigami_display_name(identity["name"])}, '
            f'位置={position}'
        )
        self.sell_hand_card(position)
        confirmed = self._wait_hand_card_removed(
            count_before,
            lambda: self._hand_card_identity_count(*sale_key),
        )
        count_after = self._hand_card_identity_count(*sale_key)
        if not confirmed:
            logger.warning(
                '[棋局] 紧急出售阵容卡未确认；'
                f'数量={count_before}->{count_after}'
            )
            return None
        logger.info(
            '[棋局] 紧急出售阵容卡已确认: '
            f'数量={count_before}->{count_after}'
        )
        return {
            'type': 'lineup',
            'name': identity['name'],
            'position': position,
        }

    def _hakuzosu_protect_target_position(
        self,
        verified_names: set[str] | None = None,
    ) -> int | None:
        """从阵容级配置读取守护之印目标位置。"""
        strategy = self.get_lineup_strategy()
        if self.HAKUZOSU_NAME not in strategy['shikigami']:
            return None
        position = strategy.get('hakuzosu_protect_position')
        if position is not None:
            position = int(position)
            target_name = next((
                name
                for name, config in strategy['shikigami'].items()
                if int(config['position']) == position
            ), None)
            if (
                target_name is not None
                and (
                    verified_names is None
                    or target_name in verified_names
                )
            ):
                return position

        # 兼容尚未迁移的第三方四元组阵容配置。
        for name, config in strategy['shikigami'].items():
            if verified_names is not None and name not in verified_names:
                continue
            if config.get('equip_hakuzosu_protect', False):
                return int(config['position'])
        return None

    def _arakawa_goldfish_target_position(self) -> int | None:
        """返回当前阵容配置的荒川金鱼目标格。"""
        position = self.get_lineup_strategy().get(
            'arakawa_goldfish_position'
        )
        return None if position is None else int(position)

    def _lineup_arakawa_names(self) -> set[str]:
        """返回当前阵容中带有荒川羁绊的式神。"""
        return {
            name
            for name in self.get_lineup_strategy()['shikigami']
            if self.ARAKAWA_BOND_NAME
            in SHIKIGAMI_BONDS_BY_ROMAJI.get(name, ())
        }

    def _record_arakawa_goldfish_position(self, set_index: int, identified=False) -> None:
        """登记本局金鱼状态；金鱼不占人口且不能佩戴任何装备。"""
        set_index = int(set_index)
        self._arakawa_goldfish_current_position = set_index
        units = dict(getattr(self, '_board_special_units', {}))
        previous = units.get('arakawa_goldfish', {})
        units['arakawa_goldfish'] = {
            **previous,
            'display_name': '金鱼',
            'position': set_index,
            'counts_toward_capacity': False,
            'can_equip_soul': False,
            'can_equip_emblem': False,
            'can_equip_hakuzosu_protect': False,
        }
        if identified:
            units['arakawa_goldfish'].update(identified=True, detected_position=set_index)
        self._board_special_units = units
        logger.debug(
            '[棋局] 棋盘特殊单位状态: '
            f'荒川金鱼={units["arakawa_goldfish"]}'
        )

    def _move_arakawa_goldfish(self, source_position: int) -> bool:
        """将已确认的金鱼移动到阵容指定位置，并同步交换的式神位置。"""
        target_position = self._arakawa_goldfish_target_position()
        if target_position is None:
            return False
        if not self._is_preparation_mode():
            self._goldfish_relocation_pending = True
            return False
        source_position = int(source_position)
        protected_before = set(
            getattr(self, '_player_deployed_positions', set())
        )
        if source_position == target_position:
            protected_positions = set(protected_before)
            protected_positions.add(target_position)
            self._player_deployed_positions = protected_positions
            self._record_arakawa_goldfish_position(target_position)
            self._goldfish_relocation_pending = False
            logger.info(
                '[棋局] 已确认金鱼本就在'
                f'指定套装 {target_position}'
            )
            return True
        Press_and_Drag(
            self.device,
            p1=self._set_position(source_position),
            p2=self._set_position(target_position),
            hold_duration=(0.2, 0.3),
            point_random=(-2, -2, 2, 2),
            swipe_duration=0.5,
            name=(
                f'CHESS_MOVE_ARAKAWA_GOLDFISH_SET_{source_position}'
                f'_TO_{target_position}'
            ),
        )
        swapped_names = [name for name in getattr(self, '_board_lineup_names', set())
                         if getattr(self, '_board_actual_positions', {}).get(
                             name, self.shikigami_deploy_positions.get(name)) == target_position]
        for name in swapped_names:
            self._record_actual_lineup_position(name, source_position)
        self._record_arakawa_goldfish_position(target_position)
        self._goldfish_relocation_pending = False
        protected_positions = set(protected_before)
        protected_positions.discard(source_position)
        protected_positions.add(target_position)
        # 若目标格原来是脚本上阵式神，拖动会交换双方位置；源格仍需保护。
        if target_position in protected_before:
            protected_positions.add(source_position)
        self._player_deployed_positions = protected_positions
        logger.info(
            '[棋局] 移动已确认荒川金鱼: '
            f'{source_position} -> {target_position}'
        )
        return True

    def _active_arakawa_names(self) -> set[str]:
        return {name for name in getattr(self, '_board_lineup_names', set())
                if self.ARAKAWA_BOND_NAME in SHIKIGAMI_BONDS_BY_ROMAJI.get(name, ())
                or '荒川纹章' in self._shikigami_attributes(name)[1:]}

    def _goldfish_formation_baseline(self, next_name, emblem=False):
        """只在下一次上阵/纹章装备会形成二荒川时保存占位快照。"""
        active = self._active_arakawa_names()
        if (getattr(self, '_arakawa_goldfish_current_position', None) is not None
                or len(active) != 1 or next_name in active
                or self._arakawa_goldfish_target_position() is None):
            return None
        if not emblem and next_name not in self._lineup_arakawa_names():
            return None
        slots = self._board_frame_scan()
        if not slots:
            return None
        return {'before': {index for index, slot in enumerate(slots, 1) if slot['occupied']},
                'deployed_position': None if emblem else self.shikigami_deploy_positions[next_name]}

    def _inspect_arakawa_goldfish(self, set_index: int) -> bool:
        """打开新增占位的详情，用金鱼专属标志确认身份。"""
        if not self._is_preparation_mode():
            return False
        x, y = self._set_position(set_index)
        rule = RuleClick(roi_front=(x-8, y-8, 16, 16), roi_back=(x-8, y-8, 16, 16),
                         name=f'chess_inspect_arakawa_goldfish_set_{set_index}')
        for _ in range(self.ACTION_ICON_MAX_ATTEMPTS):
            if not self._is_preparation_mode():
                return False
            self.device.click_record_remove(rule)
            self.click(rule)
            if not self._wait_chess_action_state(lambda: self.appear(self.I_SHIKIGAMI_SPECIFICS)):
                continue
            identified = self._wait_chess_action_state(lambda: self.appear(self.I_CHECK_GOLDFISH))
            self.close_shikigami_specifics_if_open()
            logger.info(f'[棋局] 新增荒川单位确认: 套装={set_index}, 是金鱼={identified}')
            return identified
        return False

    def _detect_pending_arakawa_goldfish(self) -> bool:
        if (getattr(self, '_goldfish_relocation_pending', False)
                and getattr(self, '_arakawa_goldfish_current_position', None) is not None):
            return self._move_arakawa_goldfish(self._arakawa_goldfish_current_position)
        pending = getattr(self, '_pending_goldfish_probe', None)
        if not pending or len(self._active_arakawa_names()) < 2:
            return False
        candidates = []
        def new_position_visible():
            nonlocal candidates
            if not self._is_preparation_mode():
                return True
            slots = self._board_frame_scan()
            if not slots:
                return False
            occupied = {index for index, slot in enumerate(slots, 1) if slot['occupied']}
            target = pending['deployed_position']
            expected = int(target is not None and target not in pending['before'])
            if len(occupied) <= len(pending['before']) + expected:
                return False
            known = {getattr(self, '_board_actual_positions', {}).get(name, position)
                     for name, position in self.shikigami_deploy_positions.items()
                     if name in getattr(self, '_board_lineup_names', set())}
            candidates = sorted(occupied - pending['before'] - known)
            return bool(candidates)
        self._wait_chess_action_state(new_position_visible)
        if not self._is_preparation_mode():
            return False
        for position in candidates:
            if not self._inspect_arakawa_goldfish(position):
                continue
            self._record_arakawa_goldfish_position(position, identified=True)
            self._pending_goldfish_probe = None
            self._move_arakawa_goldfish(position)
            return True
        logger.debug('[棋局] 荒川金鱼尚未确认；保留探测到下次准备阶段')
        return False

    def _handle_goldfish_after_board_action_failure(self, set_index, action):
        """下阵失败仅处理已登记的金鱼，不再盲点未知式神详情。"""
        if (getattr(self, '_arakawa_goldfish_current_position', None) != int(set_index)
                or not self._is_preparation_mode()):
            return False
        return self._move_arakawa_goldfish(set_index)

    def _find_hakuzosu_protect_hand_card(self) -> dict | None:
        """定位手牌中的守护之印。"""
        if self._hakuzosu_protect_target_position() is None:
            return None
        matches = self.hakuzosu_protect_rule.match_all_any(
            self.device.image,
            roi=list(self.HAND_AREA),
            threshold=self.hakuzosu_protect_rule.threshold,
            nms_threshold=0.3,
            frame_id=self.device.image_frame_id,
        )
        if not matches:
            return None
        score, x, y, width, height = max(matches, key=lambda item: item[0])
        return {
            'name': self.HAKUZOSU_PROTECT_NAME,
            'display_name': self.HAKUZOSU_PROTECT_DISPLAY_NAME,
            'score': score,
            'position': (x + width // 2, y + height // 2),
        }

    def _hakuzosu_protect_hand_count(self) -> int:
        """统计完整手牌区中的守护之印数量。"""
        if self._hakuzosu_protect_target_position() is None:
            return 0
        return len(self.hakuzosu_protect_rule.match_all_any(
            self.device.image,
            roi=list(self.HAND_AREA),
            threshold=self.hakuzosu_protect_rule.threshold,
            nms_threshold=0.3,
            frame_id=self.device.image_frame_id,
        ))

    def _hakuzosu_protect_match_in_card(
        self,
        card_roi: tuple[int, int, int, int],
    ) -> dict | None:
        """确认指定手牌框是否为守护之印，用于卖卡保护。"""
        if self._hakuzosu_protect_target_position() is None:
            return None
        matches = self.hakuzosu_protect_rule.match_all_any(
            self.device.image,
            roi=list(card_roi),
            threshold=self.hakuzosu_protect_rule.threshold,
            nms_threshold=0.3,
            frame_id=self.device.image_frame_id,
        )
        if not matches:
            return None
        score, x, y, width, height = max(matches, key=lambda item: item[0])
        return {
            'name': self.HAKUZOSU_PROTECT_NAME,
            'text': self.HAKUZOSU_PROTECT_DISPLAY_NAME,
            'score': score,
            'position': (x + width // 2, y + height // 2),
        }

    def equip_hakuzosu_protect_after_deploy(
        self,
        verified_names: set[str] | None = None,
    ) -> bool:
        """按阵容专属御魂配置尝试装备守护之印。"""
        target_position = self._hakuzosu_protect_target_position(
            verified_names
        )
        if target_position is None:
            return False
        target_name = self._shikigami_name_at_set(target_position)
        if target_name is None:
            return False
        protect, soul_1, soul_2 = self._shikigami_attributes(target_name)
        if protect is not None:
            return False
        if not self._is_preparation_mode():
            return False
        card = self._find_hakuzosu_protect_hand_card()
        if card is None:
            logger.debug(
                '[棋局] 白狐主保牌不在手牌，'
                '百目鬼上阵'
            )
            return False
        logger.info(
            f'[棋局] 检测到{card["display_name"]}(功能)，'
            f'移动到{target_position}号位'
        )
        protect_before = self._hakuzosu_protect_hand_count()
        if not self._equip_soul_card(
            source=card['position'],
            set_index=int(target_position),
            operation_name=self.HAKUZOSU_PROTECT_NAME.upper(),
        ):
            return False
        confirmed = self._wait_hand_card_removed(
            protect_before,
            self._hakuzosu_protect_hand_count,
        )
        protect_after = self._hakuzosu_protect_hand_count()
        if not confirmed:
            logger.warning(
                '[棋局] 白狐主保装备未确认: '
                f'{target_name} 到套装 {target_position}, '
                f'手牌数={protect_before}->{protect_after}'
            )
            return False
        self._set_shikigami_attributes(
            target_name,
            (self.HAKUZOSU_PROTECT_DISPLAY_NAME, soul_1, soul_2),
        )
        logger.info(
            '[棋局] 白狐主保装备已确认: '
            f'{target_name} 到套装 {target_position}'
        )
        return True

    def _equip_soul_card(
        self,
        source: tuple[int, int],
        set_index: int,
        operation_name: str,
    ) -> bool:
        """御魂及阵容特殊手牌共用入口；拖动前必须关闭商店。"""
        if not self._ensure_shop_closed():
            logger.warning(
                f'[棋局] 中止式盘装备: 商店无法关闭，'
                f'操作={operation_name}'
            )
            return False
        target = self._soul_target_position(set_index)
        logger.debug(
            f'[棋局] 装备式盘类卡{operation_name}到套装 '
            f'{set_index}: 源={source}, 目标={target}'
        )
        Press_and_Drag(
            self.device,
            p1=source,
            p2=target,
            hold_duration=(0.2, 0.3),
            point_random=(-3, -3, 3, 3),
            swipe_duration=0.5,
            name=f'CHESS_EQUIP_SOUL_{operation_name}_SET_{set_index}',
        )
        return True

    def deploy_shikigami_hand_card(
        self,
        name: str,
        source: tuple[int, int],
    ) -> bool:
        """按当前策略站位拖动式神，并交叉确认是否上阵。"""
        set_index = self.shikigami_deploy_positions.get(name)
        if set_index is None:
            logger.warning(f'[棋局] 式神无可上阵位置: {name}')
            return False

        if not self._ensure_shop_closed():
            logger.warning(
                f'[棋局] 中止式神上阵: 商店未关闭'
                f'拖拽 {name} 前'
            )
            return False
        count_before = self._read_shikigami_count()
        hand_count_before = self._lineup_hand_card_match_count(name)
        hand_stars_before = self._lineup_hand_stars(name)
        actual_position = getattr(self, '_board_actual_positions', {}).get(name, set_index)
        same_board_unit = (name in getattr(self, '_board_lineup_names', set())
                           and actual_position == set_index)
        board_star_before = self._board_set_star(set_index) if same_board_unit else None
        target_occupied_before = self._board_set_has_shikigami(set_index)
        target_position = self._set_position(set_index)
        logger.debug(
            f'[棋局] 上阵式神 {name} 到套装 {set_index}, '
            f'源={source}, 目标={target_position}'
        )
        Press_and_Drag(
            self.device,
            p1=source,
            p2=target_position,
            hold_duration=(0.2, 0.3),
            point_random=(-3, -3, 3, 3),
            swipe_duration=0.5,
            name=f'CHESS_DEPLOY_{name.upper()}_SET_{set_index}',
        )
        self.close_shikigami_specifics_if_open()
        star_confirmations = 0
        confirmed_stars = None
        success_reason = None

        def deployed():
            nonlocal star_confirmations, confirmed_stars, success_reason
            if self.close_shikigami_specifics_if_open():
                star_confirmations = 0
                return False
            if self._lineup_hand_card_match_count(name) < hand_count_before:
                success_reason = 'hand_count_decreased'
                return True
            hand_stars = self._lineup_hand_stars(name)
            board_star = self._board_set_star(set_index) if same_board_unit else None
            hand_upgraded = (hand_stars_before is not None and hand_stars is not None
                             and len(hand_stars_before) == len(hand_stars)
                             and hand_stars > hand_stars_before)
            board_upgraded = (board_star_before is not None and board_star is not None
                              and board_star > board_star_before)
            if not (hand_upgraded or board_upgraded):
                star_confirmations = 0
                confirmed_stars = None
                return False
            current = (hand_stars, board_star)
            star_confirmations = star_confirmations + 1 if current == confirmed_stars else 1
            confirmed_stars = current
            success_reason = 'hand_star_increased' if hand_upgraded else 'board_star_increased'
            return star_confirmations >= 2

        succeeded = self._wait_chess_action_state(deployed)
        count_after = self._read_shikigami_count()
        hand_count_after = self._lineup_hand_card_match_count(name)
        target_occupied_after = self._board_set_has_shikigami(set_index)

        count_increased = False
        if count_before is not None and count_after is not None:
            count_increased = (
                count_after['current'] > count_before['current']
            )
        target_became_occupied = (
            not target_occupied_before and target_occupied_after
        )

        # 手牌减少或连续两帧确认星级提升，均视为本次上卡成功。
        if succeeded:
            logger.info(
                f'[棋局] 式神上阵已确认: {name} -> 套装 {set_index}, '
                f'原因={success_reason}, '
                f'手牌星级={hand_stars_before}->{self._lineup_hand_stars(name)}, '
                f'棋盘星级={board_star_before}->{confirmed_stars[1] if confirmed_stars else None}, '
                f'棋盘数={count_before["current"] if count_before else "?"}'
                f'->{count_after["current"] if count_after else "?"}, '
                f'手牌数={hand_count_before}->{hand_count_after}, '
                f'目标占用={target_occupied_before}'
                f'->{target_occupied_after}'
            )
            return True

        logger.warning(
            f'[棋局] 式神上阵未确认: {name} -> 套装 {set_index}, '
            f'棋盘数={count_before["current"] if count_before else "?"}'
            f'->{count_after["current"] if count_after else "?"}, '
            f'手牌数={hand_count_before}->{hand_count_after}, '
            f'目标占用={target_occupied_before}'
            f'->{target_occupied_after}'
        )
        return False

    def _lineup_hand_card_match_count(self, name: str) -> int:
        """统计本截图共享 Frame 扫描出的身份数量。"""
        return sum(card['name'] == name for card in self._frame_card_scan('card'))

    def _lineup_hand_stars(self, name: str) -> tuple | None:
        cards = [card for card in self._frame_card_scan('card') if card['name'] == name]
        if not cards or any(card.get('star') not in (1, 2, 3) for card in cards):
            return None
        return tuple(sorted(card['star'] for card in cards))

    def _board_set_star(self, set_index: int) -> int | None:
        """从普通或首领棋盘 Frame 读取星级；歧义结果不参与确认。"""
        index = int(set_index)
        if not 1 <= index <= 12:
            raise ValueError(f'[棋局] 棋盘套装位置未配置: {set_index}')
        slots = self._board_frame_scan()
        return slots[index - 1]['star'] if slots else None

    def _find_best_shikigami_hand_card(
        self,
        excluded_names: set[str] | None = None,
    ) -> dict | None:
        """让阵容头像模板直接扫描整个手牌区，返回最左侧命中卡。"""
        excluded_names = excluded_names or set()
        frame_candidates = []
        for frame_index in range(1, self.HAND_DEPLOY_CONFIRM_FRAMES + 1):
            if frame_index > 1:
                self.screenshot()
            frame_candidates.append(
                self._scan_lineup_hand_card_candidates_once(excluded_names)
            )

        merged = {}
        for candidates in frame_candidates:
            for candidate in candidates:
                key = (
                    candidate['name'],
                    round(candidate['position'][0] / 12),
                )
                item = merged.setdefault(key, {
                    **candidate,
                    'scores': [],
                    'frames': 0,
                })
                item['scores'].append(candidate['score'])
                item['frames'] += 1

        candidates = []
        for item in merged.values():
            if item['frames'] < self.HAND_DEPLOY_CONFIRM_FRAMES:
                logger.debug(
                    '[棋局] 跳过阵容手牌候选: '
                    f'名称={item["name"]}, 帧={item["frames"]}/'
                    f'{self.HAND_DEPLOY_CONFIRM_FRAMES}'
                )
                continue
            avg_score = sum(item['scores']) / len(item['scores'])
            item['score'] = avg_score
            if avg_score < self.HAND_DEPLOY_TEMPLATE_THRESHOLD:
                logger.debug(
                    '[棋局] 跳过低于阈值的阵容手牌候选: '
                    f'名称={item["name"]}, 均分={avg_score:.3f}, '
                    f'阈值={self.HAND_DEPLOY_TEMPLATE_THRESHOLD}'
                )
                continue
            candidates.append(item)
            logger.debug(
                '[棋局] 阵容手牌候选已确认: '
                f'名称={item["name"]}, '
                f'均分={avg_score:.3f}, '
                f'位置={item["position"]}'
            )

        if not candidates:
            logger.debug('[棋局] 未检测到可上阵的阵容手牌')
            return None

        # 同名多张时先保留最左侧。不同式神先按阵容配置的上阵权重
        # 排序（数值越低越优先），同权重再保持原有的从左到右顺序。
        selected_by_name = {}
        for candidate in sorted(
            candidates,
            key=lambda item: (item['position'][0], -item['score']),
        ):
            selected_by_name.setdefault(candidate['name'], candidate)
        strategy_shikigami = self.get_lineup_strategy()['shikigami']
        selected = min(
            selected_by_name.values(),
            key=lambda item: (
                int(
                    strategy_shikigami[item['name']].get(
                        'deploy_weight', 1
                    )
                ),
                item['position'][0],
            ),
        )
        selected['deploy_weight'] = int(
            strategy_shikigami[selected['name']].get('deploy_weight', 1)
        )
        return selected

    def _scan_lineup_hand_card_candidates_once(
        self,
        excluded_names: set[str],
    ) -> list[dict]:
        """返回当前阵容允许的已识别 Frame 卡。"""
        allowed = self.get_lineup_strategy()['shikigami']
        return [dict(card) for card in self._frame_card_scan('card')
                if card['name'] in allowed and card['name'] not in excluded_names]

    def _soul_category(self, name: str) -> str | None:
        if name in self.ATTACK_SOUL_NAMES:
            return 'attack'
        if name in self.FUNCTIONAL_SOUL_NAMES:
            return 'functional'
        return None

    def _soul_target_position(self, set_index: int) -> tuple[int, int]:
        """返回御魂类卡牌的投放位置；前排 1-6 号位统一向北偏移 5 像素。"""
        x, y = self._set_position(set_index)
        if set_index <= 6:
            y += self.SOUL_FRONT_ROW_Y_OFFSET
        return x, y

    def _soul_targets(
        self,
        soul_name: str,
        category: str,
        verified_names: set[str],
    ) -> list[tuple[int, tuple[int, int]]]:
        """优先返回阵容专属御魂目标，否则按原类型规则选位。"""
        strategy_shikigami = self.get_lineup_strategy()['shikigami']
        def can_equip(name: str) -> bool:
            _, soul_1, soul_2 = self._shikigami_attributes(name)
            occupied = (soul_1, soul_2)
            reserved_emblems = sum(emblem not in occupied for emblem in
                                   strategy_shikigami[name].get('preferred_emblems', ()))
            return (
                soul_name not in occupied
                and sum(item is None for item in occupied) > reserved_emblems
            )

        preferred_names = {
            name
            for name, config in strategy_shikigami.items()
            if soul_name in config.get('preferred_souls', ())
        }
        active_preferred_names = preferred_names & verified_names
        preferred_positions = sorted(
            int(strategy_shikigami[name]['position'])
            for name in active_preferred_names
            if can_equip(name)
        )
        if preferred_positions:
            return [
                (set_index, self._soul_target_position(set_index))
                for set_index in preferred_positions
            ]

        # 专属目标已经上阵时保持硬优先；若目标式神尚未上阵，则不再
        # 把御魂留在手牌，直接回退到普通攻/功能御魂分配规则。
        if active_preferred_names:
            return []

        active_positions = sorted(
            self.shikigami_deploy_positions[name]
            for name in verified_names
            if name in self.shikigami_deploy_positions
            # 声明过专属御魂的式神是硬约束目标，只能接受其列表中的
            # 御魂；通用输出/功能分类不得再把其他御魂塞给它。
            and not strategy_shikigami[name].get('preferred_souls', ())
        )
        wanted_front = category != 'attack'
        targets = []
        for set_index in active_positions:
            target_name = self._shikigami_name_at_set(set_index)
            if (
                (set_index <= 6) != wanted_front
                or target_name is None
                or not can_equip(target_name)
            ):
                continue
            # 前排 1-6 号位统一使用向北偏移后的御魂投放位置。
            targets.append((set_index, self._soul_target_position(set_index)))
        return targets

    def _is_lineup_preferred_soul(self, soul_name: str) -> bool:
        """判断御魂是否被当前阵容任一式神列为专属御魂。"""
        return any(
            soul_name in config.get('preferred_souls', ())
            for config in self.get_lineup_strategy()['shikigami'].values()
        )

    def _template_soul_hand_cards(self) -> list[dict]:
        """在手牌区对 soul 模板执行多尺度匹配。"""
        candidates = []
        roi_x, roi_y, roi_width, roi_height = self.HAND_AREA
        source = self.device.image[
            roi_y:roi_y + roi_height,
            roi_x:roi_x + roi_width,
        ]
        for name, rule in self.soul_hand_rules:
            category = self._soul_category(name)
            if category is None:
                continue
            matches = []
            template = rule.image
            for scale in self.SOUL_TEMPLATE_SCALES:
                width = max(1, int(template.shape[1] * scale))
                height = max(1, int(template.shape[0] * scale))
                if width > source.shape[1] or height > source.shape[0]:
                    continue
                scaled = cv2.resize(
                    template,
                    (width, height),
                    interpolation=(
                        cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
                    ),
                )
                result = cv2.matchTemplate(
                    source,
                    scaled,
                    cv2.TM_CCOEFF_NORMED,
                )
                locations = np.where(
                    result >= self.SOUL_TEMPLATE_THRESHOLD
                )
                for point_x, point_y in zip(*locations[::-1]):
                    matches.append((
                        float(result[point_y, point_x]),
                        roi_x + int(point_x),
                        roi_y + int(point_y),
                        width,
                        height,
                    ))
            if matches:
                boxes = [list(match[1:]) for match in matches]
                scores = [match[0] for match in matches]
                indices = cv2.dnn.NMSBoxes(
                    boxes,
                    scores,
                    score_threshold=self.SOUL_TEMPLATE_THRESHOLD,
                    nms_threshold=0.3,
                )
                matches = [
                    matches[int(index)]
                    for index in np.array(indices).reshape(-1).tolist()
                ] if len(indices) else []
            for score, x, y, width, height in matches:
                candidates.append({
                    'name': name,
                    'text': self.SOUL_DISPLAY_NAMES[name],
                    'position': (x + width // 2, y + height // 2),
                    'score': score,
                    'source': 'template',
                    'category': category,
                })
                logger.debug(
                    f'[棋局] 式盘图像匹配: {self.SOUL_DISPLAY_NAMES[name]}, '
                    f'得分={score:.3f}, 框={(x, y, width, height)}'
                )
        return candidates

    def _soul_hand_cards(self) -> list[dict]:
        """仅使用 soul 文件夹图片识别御魂，并按手牌横坐标去重。"""
        merged = []
        candidates = self._template_soul_hand_cards()
        for candidate in sorted(
            candidates,
            key=lambda item: (
                item['position'][0],
                -item['score'],
            ),
        ):
            existing = next((
                item
                for item in merged
                if abs(item['position'][0] - candidate['position'][0]) <= 24
            ), None)
            if existing is None:
                merged.append(candidate)
            elif candidate['score'] > existing['score']:
                merged.remove(existing)
                merged.append(candidate)
        return sorted(merged, key=lambda item: item['position'][0])

    def _soul_match_in_card(
        self,
        card_roi: tuple[int, int, int, int],
        soul_cards: list[dict] | None = None,
    ) -> dict | None:
        """返回落在指定手牌框内的最佳御魂图片匹配。"""
        x, _, width, _ = card_roi
        soul_cards = (
            self._soul_hand_cards() if soul_cards is None else soul_cards
        )
        matches = [
            item
            for item in soul_cards
            if x - 8 <= item['position'][0] <= x + width + 8
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item['score'])

    def _discover_named_hand_cards(self, expected_text: str) -> list[dict]:
        """共用灰度 badge 定位；只接受 OCR 完整命中的发现卡名称。"""
        if any(self.appear(rule) for rule in
               (self.I_SELECT_SOUL_1, self.I_SELECT_SOUL_2, self.I_SELECT_SOUL_3)):
            return []  # 三选一弹窗后的手牌仍可能可见，不操作被遮挡的背景卡。
        return [dict(card) for card in self._frame_card_scan('emblem')
                if card['type'] == 'discovery' and card['kind'] == expected_text]

    def _discover_soul_hand_cards(self) -> list[dict]:
        return self._discover_named_hand_cards('发现御魂')

    def _discover_badge_hand_cards(self) -> list[dict]:
        return self._discover_named_hand_cards('发现纹章')

    def _wait_for_discover_soul_choices(self) -> list[RuleImage]:
        """等待发现御魂三选一界面，并返回本帧实际出现的选项。"""
        deadline = time.monotonic() + self.DISCOVER_SOUL_UI_TIMEOUT
        rules = (
            self.I_SELECT_SOUL_1,
            self.I_SELECT_SOUL_2,
            self.I_SELECT_SOUL_3,
        )
        while time.monotonic() < deadline:
            self.screenshot()
            options = [rule for rule in rules if self.appear(rule)]
            if options:
                return options
        return []

    def discover_souls_from_hand(self) -> int:
        """优先使用所有“发现御魂/发现纹章”卡并随机选择。"""
        used = 0
        for _ in range(self.DISCOVER_SOUL_SAFETY_LIMIT):
            if not self._is_preparation_mode():
                logger.debug(
                    '[棋局] 停止使用发现式盘卡: 准备阶段被'
                    '被打断或已结束'
                )
                break
            cards = sorted(
                self._discover_badge_hand_cards()
                + self._discover_soul_hand_cards(),
                key=lambda item: item['position'][0],
            )
            if not cards:
                break

            card = cards[0]
            logger.debug(
                f'[棋局] 使用{card["kind"]}手牌: '
                f'文本={card["text"]}, '
                f'相似度={card["similarity"]:.3f}, '
                f'位置={card["position"]}'
            )
            self.device.click(
                x=card['position'][0],
                y=card['position'][1],
                control_name='CHESS_DISCOVER_CARD',
            )

            use_deadline = time.monotonic() + self.DISCOVER_SOUL_UI_TIMEOUT
            while time.monotonic() < use_deadline:
                self.screenshot()
                if not self._is_preparation_mode():
                    logger.debug(
                        '[棋局] 停止使用发现式盘卡: 准备阶段被'
                        '被打断或已结束'
                    )
                    return used
                if self.appear_then_click(
                    self.I_USE_SOUL,
                    interval=self.ACTION_SETTLE_INTERVAL,
                ):
                    break
            else:
                logger.warning(
                    f'[棋局] 已选{card["kind"]}卡，但使用按钮'
                    '未出现；保留该卡并停止本轮'
                )
                break

            options = self._wait_for_discover_soul_choices()
            if not options:
                logger.warning(
                    '[棋局] 发现式盘选择未出现；'
                    '停止本轮'
                )
                break

            selected = random.choice(options)
            logger.debug(
                f'[棋局] 随机{card["kind"]}选项: '
                f'{selected.name}, 可用={[rule.name for rule in options]}'
            )
            select_rules = (
                self.I_SELECT_SOUL_1,
                self.I_SELECT_SOUL_2,
                self.I_SELECT_SOUL_3,
            )
            for attempt in range(1, self.ACTION_ICON_MAX_ATTEMPTS + 1):
                self.device.click_record_remove(selected)
                self.click(selected)
                if self._wait_chess_action_state(
                    lambda: not any(
                        self.appear(rule) for rule in select_rules
                    )
                ):
                    used += 1
                    logger.debug(
                        '[棋局] 发现式盘选项已确认: '
                        f'{selected.name}, '
                        f'尝试={attempt}/'
                        f'{self.ACTION_ICON_MAX_ATTEMPTS}'
                    )
                    break
                logger.warning(
                    '[棋局] 点击后发现式盘选择仍打开: '
                    f'{selected.name}, '
                    f'尝试={attempt}/{self.ACTION_ICON_MAX_ATTEMPTS}, '
                    f'超时={self.ACTION_ICON_WAIT_TIMEOUT:.0f}秒'
                )
            else:
                raise GameStuckError(
                    '[棋局] 发现御魂选项选择 3 次尝试后失败'
                )
        else:
            logger.warning(
                '[棋局] 发现式盘卡使用已达安全上限，停止'
                f'{self.DISCOVER_SOUL_SAFETY_LIMIT}'
            )

        logger.debug(f'[棋局] 发现式盘处理完成，使用={used}')
        return used

    def equip_souls_from_hand(
        self,
        verified_names: set[str] | None = None,
    ) -> list[str]:
        """给已确认式神装备御魂，并用完整手牌同名数量减少确认。"""
        if not self._is_preparation_mode():
            logger.debug(
                '[棋局] 跳过式盘装备: 准备阶段被打断或'
                '已结束'
            )
            return []
        # “发现御魂”会生成普通御魂，因此必须先全部处理，再扫描并装配
        # soul 文件夹中的御魂卡。
        self.discover_souls_from_hand()
        verified_names = set(verified_names or set())
        self.use_golden_copies_from_hand(verified_names)
        if not verified_names:
            logger.debug(
                '[棋局] 手中保留式盘: 无式神位置'
                '已在棋盘上确认'
            )
            return []

        equipped = []
        equipped.extend(self.equip_emblems_from_hand(verified_names))
        # 守护之印与普通御魂共享阵容优先目标；它使用独立图片模板，
        # 因此在普通 soul 文件夹扫描前单独处理。每次备阶段都会重试，
        # 不再局限于梦山白藏主刚上阵的瞬间。
        if self.equip_hakuzosu_protect_after_deploy(verified_names):
            equipped.append(self.HAKUZOSU_PROTECT_NAME)
        repeated_attempts = {}
        target_failures = Counter()
        for _ in range(self.SOUL_EQUIP_SAFETY_LIMIT):
            if not self._is_preparation_mode():
                logger.debug(
                    '[棋局] 停止装备式盘: '
                    '模式已不再是准备'
                )
                break

            selected = None
            selected_target = None
            soul_candidates = sorted(
                self._soul_hand_cards(),
                key=lambda candidate: (
                    not self._is_lineup_preferred_soul(candidate['name']),
                    candidate['position'][0],
                ),
            )
            for candidate in soul_candidates:
                for target in self._soul_targets(
                    candidate['name'],
                    candidate['category'],
                    verified_names,
                ):
                    attempt_key = (
                        candidate['name'],
                        candidate['position'][0] // 20,
                        target[0],
                    )
                    if repeated_attempts.get(attempt_key, 0) >= 2:
                        continue
                    selected = candidate
                    selected_target = target
                    repeated_attempts[attempt_key] = (
                        repeated_attempts.get(attempt_key, 0) + 1
                    )
                    break
                if selected is not None:
                    break

            if selected is None or selected_target is None:
                break

            set_index, _ = selected_target
            target_name = self._shikigami_name_at_set(set_index)
            if target_name is None:
                break
            hand_counts_before = Counter(
                card['name'] for card in self._soul_hand_cards()
            )
            logger.info(
                f'[棋局] 检测到{selected["text"]}'
                f'({self._soul_category_display(selected["category"])})，'
                f'移动到{set_index}号位'
            )
            if not self._equip_soul_card(
                source=selected['position'],
                set_index=set_index,
                operation_name=selected['name'].upper(),
            ):
                break
            confirmed = self._wait_hand_card_removed(
                hand_counts_before[selected['name']],
                lambda: sum(
                    card['name'] == selected['name']
                    for card in self._soul_hand_cards()
                ),
            )
            hand_counts_after = Counter(
                card['name'] for card in self._soul_hand_cards()
            )
            if not confirmed:
                attempts = repeated_attempts[
                    (
                        selected['name'],
                        selected['position'][0] // 20,
                        set_index,
                    )
                ]
                logger.warning(
                    f'[棋局] 式盘装备未确认: '
                    f'{selected["text"]} -> 套装 {set_index}, '
                    f'手牌数={hand_counts_before[selected["name"]]}'
                    f'->{hand_counts_after[selected["name"]]}, '
                    f'尝试={attempts}/2'
                )
                target_failures[target_name] += 1
                _, soul_1, soul_2 = self._shikigami_attributes(target_name)
                if (
                    target_failures[target_name] >= 2
                    and (soul_1 is None or soul_2 is None)
                    and self._is_preparation_mode()
                ):
                    # 只撤销已失效的站位记录，式神携带属性随式神保留。
                    deployed_names = set(
                        getattr(self, '_board_lineup_names', set())
                    )
                    deployed_names.discard(target_name)
                    self._board_lineup_names = deployed_names
                    actual_positions = dict(
                        getattr(self, '_board_actual_positions', {})
                    )
                    actual_positions.pop(target_name, None)
                    self._board_actual_positions = actual_positions
                    player_positions = set(
                        getattr(self, '_player_deployed_positions', set())
                    )
                    player_positions.discard(set_index)
                    self._player_deployed_positions = player_positions
                    verified_names.discard(target_name)
                    logger.warning(
                        f'[棋局] 式神已被转移，标记为未上阵: '
                        f'名称={target_name}, 套装={set_index}, '
                        f'御魂装配失败次数={target_failures[target_name]}'
                    )
                continue

            target_failures.pop(target_name, None)
            if not self._record_shikigami_soul(
                target_name,
                selected['name'],
            ):
                logger.warning(
                    '[棋局] 式盘已从手牌消失但目标属性'
                    f'被拒绝: 目标={target_name}, '
                    f'式盘={selected["text"]}'
                )
                continue
            equipped.append(selected['name'])
            logger.debug(
                f'[棋局] 式盘装备已确认: '
                f'{selected["text"]} -> {target_name} 到套装 {set_index}, '
                f'手牌数={hand_counts_before[selected["name"]]}'
                f'->{hand_counts_after[selected["name"]]}'
            )
        else:
            logger.warning(
                '[棋局] 式盘装备已达安全上限，停止'
                f'{self.SOUL_EQUIP_SAFETY_LIMIT}'
            )

        logger.debug(f'[棋局] 式盘装备完成，装备={equipped}')
        return equipped

    def deploy_shikigami_from_hand(self) -> list[str]:
        """关闭商店后上阵手牌式神，并以当前阶数限制场上人数。"""
        # 场上人数 OCR 只有在商店完全收起后才可见。把约束放在上卡
        # 方法内部，避免其他调用入口绕过外层准备流程后无效拖卡。
        if not self._is_preparation_mode():
            logger.debug(
                '[棋局] 跳过式神上阵: 准备阶段被打断'
                '或已结束'
            )
            return []
        if not self._ensure_shop_closed():
            logger.warning(
                '[棋局] 跳过式神上阵: 商店无法关闭'
            )
            return []
        if self._is_shop_open():
            logger.warning(
                '[棋局] 跳过式神上阵: 商店仍可见'
                '关闭确认后'
            )
            return []

        self._detect_pending_arakawa_goldfish()
        deployed = []
        deployed_names = set(getattr(self, '_board_lineup_names', set()))
        player_positions = set(
            getattr(self, '_player_deployed_positions', set())
        )

        # 已确认上阵的阵容式神在本局内保持登记。战斗动画、遮挡或勾玉
        # 模板单帧漏识别不能证明式神已经离场；若据此清除名称，会同时
        # 导致重复上阵和专属御魂失去目标。
        failed_attempts = {}
        for _ in range(self.HAND_DEPLOY_SAFETY_LIMIT):
            if not self._is_preparation_mode():
                logger.debug(
                    '[棋局] 停止上阵手牌: '
                    '模式已不再是准备'
                )
                break
            if not self._ensure_shop_closed():
                logger.warning(
                    '[棋局] 停止上阵手牌: 商店重开或'
                    '容量检查前未能确认关闭'
                )
                break

            capacity = self._read_lineup_capacity_status()
            if capacity is None:
                logger.warning(
                    '[棋局] 停止上阵手牌: 阵容容量'
                    '未能确认'
                )
                break
            candidate = self._find_best_shikigami_hand_card(
                excluded_names=(
                    deployed_names
                    | {
                        name
                        for name, attempts in failed_attempts.items()
                        if attempts >= 2
                    }
                ),
            )
            if candidate is None:
                logger.info(
                    '[棋局] 停止上阵手牌: 无可上阵阵容'
                    '手牌候选'
                )
                break

            logger.info(
                f'[棋局] 上阵候选: '
                f'{self._shikigami_display_name(candidate["name"])}, '
                f'权重={candidate.get("deploy_weight", 1)}, '
                f'得分={candidate["score"]:.3f}, '
                f'位置={candidate["position"]}'
            )
            set_index = self.shikigami_deploy_positions[candidate['name']]
            # 每次上阵前都检查系统自动上阵区域。若存在未由脚本登记的
            # 单位，先将其中一个下阵；只有系统位为空时才以动态人数
            # 判断是否还能直接上阵。
            recalled_set = self._recall_one_system_board_card(
                preferred_set_index=set_index,
            )
            if recalled_set is not None:
                # 下阵卡进入手牌后会让整排手牌重新布局。下阵前保存的
                # candidate.position 已失效，必须基于新截图重新定位同名卡。
                self.screenshot()
                candidate_name = candidate['name']
                candidate = self._find_best_shikigami_hand_card(
                    excluded_names=(
                        set(self.shikigami_deploy_positions)
                        - {candidate_name}
                    ),
                )
                if candidate is None or candidate['name'] != candidate_name:
                    logger.warning(
                        '[棋局] 系统召回后停止当前上阵: '
                        f'{self._shikigami_display_name(candidate_name)} '
                        '无法在重排后的手牌中定位'
                    )
                    failed_attempts[candidate_name] = (
                        failed_attempts.get(candidate_name, 0) + 1
                    )
                    continue
                set_index = self.shikigami_deploy_positions[candidate_name]
                logger.info(
                    f'[棋局] 先召回套装 {recalled_set} 的系统卡，然后'
                    f'上阵 {self._shikigami_display_name(candidate["name"])} '
                    f'到套装 {set_index}, 刷新位置='
                    f'{candidate["position"]}'
                )
            elif capacity['full']:
                logger.warning(
                    '[棋局] 停止上阵手牌: 运行时阵容已满'
                    '且未找到可移除的系统上阵卡，位于'
                    f'{self.BOARD_RECALL_POSITIONS}'
                )
                break

            goldfish_baseline = self._goldfish_formation_baseline(candidate['name'])
            if not self.deploy_shikigami_hand_card(
                candidate['name'],
                candidate['position'],
            ):
                failed_attempts[candidate['name']] = (
                    failed_attempts.get(candidate['name'], 0) + 1
                )
                logger.warning(
                    f'[棋局] 稍后重试式神上阵: '
                    f'{candidate["name"]}, '
                    f'尝试={failed_attempts[candidate["name"]]}/2'
                )
                continue

            deployed.append(candidate['name'])
            deployed_names.add(candidate['name'])
            self._board_lineup_names = deployed_names
            self._record_actual_lineup_position(
                candidate['name'],
                set_index,
            )
            if candidate['name'] not in getattr(
                self,
                '_board_shikigami_attributes',
                {},
            ):
                self._set_shikigami_attributes(
                    candidate['name'],
                    (None, None, None),
                )
            player_positions = set(
                getattr(self, '_player_deployed_positions', set())
            )
            player_positions.add(set_index)
            self._player_deployed_positions = player_positions
            logger.debug(
                '[棋局] 标记玩家上阵位置: '
                f'套装={set_index}, 名称={candidate["name"]}'
            )
            if goldfish_baseline is not None:
                self._pending_goldfish_probe = goldfish_baseline
                self._detect_pending_arakawa_goldfish()
            if candidate['name'] == self.HAKUZOSU_NAME:
                self.equip_hakuzosu_protect_after_deploy(deployed_names)
        else:
            logger.warning(
                '[棋局] 手牌上阵已达安全上限，停止'
                f'{self.HAND_DEPLOY_SAFETY_LIMIT}'
            )

        logger.debug(f'[棋局] 手牌上阵完成，上阵={deployed}')
        return deployed

    def _hand_card_detections(self) -> list[dict]:
        """Frame 定位式神/纹章卡；御魂沿用既有匹配。"""
        template_rules = [rule for _, rule in self.soul_hand_rules]
        template_rules.append(self.hakuzosu_protect_rule)
        candidates = [(card['badge_score'], *card['roi']) for card in self._frame_card_scan('card') + self._frame_card_scan('emblem')]
        for rule in template_rules:
            matches = rule.match_all_any(
                self.device.image,
                roi=list(self.HAND_AREA),
                threshold=rule.threshold,
                nms_threshold=0.3,
                frame_id=self.device.image_frame_id,
            )
            for score, x, y, width, height in matches:
                candidates.append((score, x, y, width, height))

        # 多个素材可能在同一张卡上产生近邻命中；每个实际卡位只保留
        # 最高分结果。这里保留素材自身矩形，拖动时使用其中心即可。
        card_matches = []
        for candidate in sorted(candidates, key=lambda item: item[0], reverse=True):
            _, x, y, width, height = candidate
            center_x = x + width // 2
            center_y = y + height // 2
            if any(
                abs(center_x - (kept[1] + kept[3] // 2)) <= 28
                and abs(center_y - (kept[2] + kept[4] // 2)) <= 40
                for kept in card_matches
            ):
                continue
            card_matches.append(candidate)

        detections = []
        for score, x, y, width, height in sorted(
            card_matches,
            key=lambda item: item[1],
        ):
            if width <= 0 or height <= 0:
                continue
            detection = {
                'roi': (x, y, width, height),
                'score': score,
            }
            detections.append(detection)
            logger.debug(
                f'[棋局] 检测到手牌模板: 得分={score:.3f}, '
                f'roi={detection["roi"]}'
            )
        if not detections:
            logger.debug('[棋局] 手牌模板未匹配到任何卡牌')
        return detections

    def _hand_capacity_count(self) -> int:
        """容量只扫描式神/特殊卡锚点与御魂图片，不识别式神身份。"""
        image = self.device.image
        candidates = []
        for frame, kind in ((self.F_HAND_CARD, 'card'), (self.F_FETTER_BADGE, 'emblem')):
            x, y, w, h = frame.roi_back
            # 只扫描手牌顶部及下方，排除棋盘上的星级标志。
            top = max(y, self.HAND_AREA[1])
            region = image[top:y+h, x:x+w]
            bx, _, _, _ = frame.badge_references[0]
            cx, _, cw, _ = frame.roi_ranges[-1 if kind == 'card' else 1]
            offset = cx + cw/2 - bx
            if frame.badge_grayscale:
                region = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
            for front in self.frame_badges[kind]:
                if frame.badge_grayscale:
                    front = cv2.cvtColor(front, cv2.COLOR_RGB2GRAY)
                if region.shape[0] < front.shape[0] or region.shape[1] < front.shape[1]:
                    continue
                scores = cv2.matchTemplate(region, front, cv2.TM_CCOEFF_NORMED)
                ys, xs = np.where(scores >= frame.threshold)
                candidates.extend((float(scores[py, px]), x+int(px)+offset) for py, px in zip(ys, xs))
        candidates.extend((item['score'], item['position'][0]) for item in self._soul_hand_cards())
        # 守护之印不占容量；不依赖当前阵容是否配置守护之印。
        x, y, w, h = self.HAND_AREA
        protect = self.hakuzosu_protect_rule.image
        region = image[y:y+h, x:x+w]
        protect_x = []
        if region.shape[0] >= protect.shape[0] and region.shape[1] >= protect.shape[1]:
            scores = cv2.matchTemplate(region, protect, cv2.TM_CCOEFF_NORMED)
            _, xs = np.where(scores >= self.hakuzosu_protect_rule.threshold)
            protect_x = [x+int(px)+protect.shape[1]/2 for px in xs]
        positions = []
        for _, center in sorted(candidates, reverse=True):
            if any(abs(center-x) <= 28 for x in protect_x):
                continue
            if not any(abs(center-x) <= 28 for x in positions):
                positions.append(center)
        logger.debug(f'[棋局] 手牌容量: 数量={len(positions)}/10, 位置={sorted(positions)}')
        return len(positions)

    def _hand_card_rois(self) -> list[tuple[int, int, int, int]]:
        """兼容只需要卡框的分类流程。"""
        return [item['roi'] for item in self._hand_card_detections()]

    def _hand_card_identity_count(
        self,
        card_type: str,
        name: str | None,
    ) -> int:
        """统计手牌中指定素材的命中张数，用于确认出售确实生效。"""
        if card_type == 'shikigami' and name:
            return self._lineup_hand_card_match_count(name)
        if card_type == 'emblem' and name:
            return sum(card['name'] == name for card in self._frame_card_scan('emblem'))
        if card_type == 'soul' and name:
            rules = [
                rule
                for rule_name, rule in self.soul_hand_rules
                if rule_name == name
            ]
        else:
            return len(self._hand_card_detections())

        matches = []
        for rule in rules:
            matches.extend(rule.match_all_any(
                self.device.image,
                roi=list(self.HAND_AREA),
                threshold=rule.threshold,
                nms_threshold=0.3,
                frame_id=self.device.image_frame_id,
            ))

        centers = []
        for score, x, y, width, height in sorted(
            matches,
            key=lambda item: item[0],
            reverse=True,
        ):
            center = (x + width // 2, y + height // 2)
            if any(
                abs(center[0] - kept[0]) <= 28
                and abs(center[1] - kept[1]) <= 40
                for kept in centers
            ):
                continue
            centers.append(center)
        return len(centers)

    def cleanup_non_lineup_hand_cards(
        self,
        allowed_modes: tuple[str, ...] = ('战',),
        emergency: bool = False,
    ) -> list[tuple[int, int]]:
        """独立卖卡环节：循环出售纹章和非阵容卡，直到连续确认干净。"""
        if not emergency and self._is_early_round_layout():
            logger.debug(
                '[棋局] 跳过手牌清理: '
                '备用布局指第1-3回合'
            )
            return []

        sold = []
        failed_sale_attempts = {}
        clean_confirm_frames = 0
        strategy = self.get_lineup_strategy()
        logger.debug(
            '[棋局] 手牌清理阵容保护: '
            f'阵容={strategy["key"]}, '
            f'名称列表={list(strategy["shikigami"].keys())}'
        )
        for cleanup_pass in range(1, self.HAND_CLEANUP_SAFETY_LIMIT + 1):
            self.close_shikigami_specifics_if_open()
            mode = self._read_chess_mode()
            if not self._is_hand_cleanup_allowed(allowed_modes):
                logger.debug(
                    '[棋局] 停止清理手牌: '
                    f'模式={mode} 不在 {allowed_modes} 内'
                )
                break

            # 先处理 Frame 已确认种类的纹章；图案未知的纹章留给下方保护。
            badge_target = self._find_badge_hand_card()
            if badge_target is not None:
                logger.info(
                    '[棋局] 出售卡牌: '
                    f'文本={badge_target["text"]}, '
                    f'位置={badge_target["position"]}'
                )
                before = self._hand_card_identity_count(
                    'emblem', badge_target['name'],
                )
                self.sell_hand_card(badge_target['position'])
                if self._wait_hand_card_removed(
                    before,
                    lambda: self._hand_card_identity_count(
                        'emblem', badge_target['name'],
                    ),
                ):
                    sold.append(badge_target['position'])
                clean_confirm_frames = 0
                continue

            # 御魂图片可能与星级卡框同时命中。先独立识别御魂，避免
            # classify_hand_card 的固定尺寸模板漏检后将它当作 unknown 出售。
            soul_cards = self._soul_hand_cards()
            discover_cards = (
                self._discover_soul_hand_cards()
                + self._discover_badge_hand_cards()
            )
            sell_target = None
            for card_roi in self._hand_card_rois():
                card_x, _, card_width, _ = card_roi
                discover_card = next((
                    item
                    for item in discover_cards
                    if (
                        card_x - 8
                        <= item['position'][0]
                        <= card_x + card_width + 8
                    )
                ), None)
                if discover_card is not None:
                    logger.debug(
                        '[棋局] 清理时保留未使用的发现卡: '
                        f'文本={discover_card["text"]}, '
                        f'位置={discover_card["position"]}'
                    )
                    continue
                soul = self._soul_match_in_card(card_roi, soul_cards)
                if soul is not None:
                    logger.debug(
                        '[棋局] 清理时保留式盘手牌: '
                        f'名称={soul["text"]}, 得分={soul["score"]:.3f}, '
                        f'位置={soul["position"]}'
                    )
                    continue
                protect = self._hakuzosu_protect_match_in_card(card_roi)
                if protect is not None:
                    logger.debug(
                        '[棋局] 清理时保留白狐主保牌: '
                        f'得分={protect["score"]:.3f}, '
                        f'位置={protect["position"]}'
                    )
                    continue
                result = self.classify_hand_card(card_roi)
                keep = (
                    (result.get('source') == 'frame' and result['type'] == 'unknown')
                    or result['type'] in ('soul', 'discovery', 'duplicator')
                    or (result['type'] == 'emblem' and self._keep_preferred_emblem(result['name']))
                    or (
                        result['type'] == 'shikigami'
                        and result['name'] in self.shikigami_deploy_positions
                    )
                )
                if keep:
                    continue

                sale_key = (result['type'], result['name'])
                if failed_sale_attempts.get(sale_key, 0) >= 2:
                    logger.debug(
                        '[棋局] 本轮跳过反复失败的出售目标，'
                        f'清理轮次: 类型={result["type"]}, '
                        f'名称={result["name"]}'
                    )
                    continue
                sell_target = result
                break
            if sell_target is None:
                clean_confirm_frames += 1
                if (
                    clean_confirm_frames
                    >= self.HAND_CLEANUP_CLEAN_CONFIRM_FRAMES
                ):
                    logger.debug(
                        '[棋局] 手牌清理确认已清空: '
                        f'帧={clean_confirm_frames}'
                    )
                    break
                logger.debug(
                    '[棋局] 本轮扫描无可出售手牌，'
                    '等待布局就绪后重新验证: '
                    f'帧={clean_confirm_frames}/'
                    f'{self.HAND_CLEANUP_CLEAN_CONFIRM_FRAMES}'
                )
                self.screenshot()
                continue

            logger.info(
                f'[棋局] 出售卡牌: '
                f'类型={sell_target["type"]}, '
                f'名称={self._shikigami_display_name(sell_target["name"])}, '
                f'位置={sell_target["position"]}'
            )
            sale_key = (sell_target['type'], sell_target['name'])
            count_before = self._hand_card_identity_count(*sale_key)
            self.sell_hand_card(sell_target['position'])
            confirmed = self._wait_hand_card_removed(
                count_before,
                lambda: self._hand_card_identity_count(*sale_key),
            )
            count_after = self._hand_card_identity_count(*sale_key)
            if confirmed:
                sold.append(sell_target['position'])
                failed_sale_attempts.pop(sale_key, None)
                clean_confirm_frames = 0
                logger.info(
                    '[棋局] 卡牌出售已确认: '
                    f'类型={sell_target["type"]}, '
                    f'名称={self._shikigami_display_name(sell_target["name"])}, '
                    f'数量={count_before}->{count_after}'
                )
                continue

            failed_sale_attempts[sale_key] = (
                failed_sale_attempts.get(sale_key, 0) + 1
            )
            clean_confirm_frames = 0
            logger.warning(
                '[棋局] 卡牌出售未确认；不登记为已售: '
                f'类型={sell_target["type"]}, '
                f'名称={self._shikigami_display_name(sell_target["name"])}, '
                f'数量={count_before}->{count_after}, '
                f'尝试={failed_sale_attempts[sale_key]}/2'
            )
        else:
            logger.warning(
                '[棋局] 手牌清理已达安全上限，停止'
                f'{self.HAND_CLEANUP_SAFETY_LIMIT}'
            )

        logger.debug(f'[棋局] 非阵容手牌清理完成，售出={sold}')
        return sold

    def _is_hand_cleanup_allowed(
        self,
        allowed_modes: tuple[str, ...] = ('战',),
    ) -> bool:
        """卖卡只在调用方指定阶段执行，阶段变化后立刻停止。"""
        return self._read_chess_mode() in allowed_modes

    def emergency_cleanup_hand(self) -> dict | None:
        """手牌满时依次装配御魂、出售非阵容卡，然后交还原操作重试。"""
        mode = self._read_chess_mode()
        if mode not in ('备', '战'):
            logger.warning(
                f'[棋局] 模式={mode}下无法执行紧急手牌清理'
            )
            return None
        if not self._ensure_shop_closed(allowed_modes=('备', '战')):
            logger.warning(
                '[棋局] 无法执行紧急手牌清理: '
                '商店无法关闭'
            )
            return None

        self.screenshot()
        equipped = []
        soul_cards = self._soul_hand_cards()
        if soul_cards:
            verified_board_names = {
                name
                for name in getattr(self, '_board_lineup_names', set())
                if name in self.shikigami_deploy_positions
            }
            logger.info(
                '[棋局] 紧急手牌清理发现式盘；先装备: '
                f'数量={len(soul_cards)}'
            )
            equipped = self.equip_souls_from_hand(verified_board_names)
            self.screenshot()

        sold = self.cleanup_non_lineup_hand_cards(
            allowed_modes=(mode,),
            emergency=True,
        )
        logger.info(
            '[棋局] 紧急手牌清理完成: '
            f'已装备={equipped}, 售出非阵容={sold}'
        )
        return {
            'type': 'emergency_cleanup',
            'equipped': equipped,
            'sold_non_lineup': sold,
        }

    def _free_one_hand_slot_for_purchase(
        self,
        sell_lineup: bool = False,
    ) -> dict | None:
        """购买受阻时清理；未腾出位置则直接出售一张阵容卡。"""
        if sell_lineup:
            if not self._ensure_shop_closed(allowed_modes=('备', '战')):
                return None
            self.screenshot()
            result = self.sell_one_lineup_hand_card()
            if result is None:
                return None
        else:
            result = self.emergency_cleanup_hand()
            if result is None:
                return None
            if not result.get('equipped') and not result.get('sold_non_lineup'):
                logger.info(
                    '[棋局] 紧急清理未腾出手牌位；先出售一张阵容卡再重试购买'
                )
                if not self._is_hand_cleanup_allowed(('备', '战')):
                    return None
                self.screenshot()
                result = self.sell_one_lineup_hand_card()
                if result is None:
                    return None

        # 本方法只会在购买失败的恢复路径调用；清理后必须恢复“商店开”
        # 这一购买前置状态，至于卖卡过程本身不主动切换商店。
        if not self._ensure_shop_open():
            logger.warning(
                '[棋局] 紧急手牌清理成功，但商店无法'
                '重新打开'
            )
            return None
        self.screenshot()
        return result

    def _golden_copy_targets(self, verified_names: set[str]) -> list[tuple[str, int]]:
        """仅选择已确认在棋盘上的一费式神，使用本局实际站位。"""
        actual = getattr(self, '_board_actual_positions', {})
        targets = []
        for name in verified_names:
            entry = resolve_shikigami(name)
            position = actual.get(name, self.shikigami_deploy_positions.get(name))
            if entry is not None and entry.cost == 1 and position in range(1, 13):
                targets.append((name, int(position)))
        return sorted(targets, key=lambda item: (item[1], item[0]))

    def _golden_copy_hand_cards(self) -> list[dict]:
        return [card for card in self._frame_card_scan('emblem')
                if card['type'] == 'duplicator']

    def use_golden_copies_from_hand(self, verified_names: set[str]) -> int:
        """黄金复制术拖至已部署的一费式神；没有目标或未消耗则保留。"""
        used = 0
        for _ in range(self.SOUL_EQUIP_SAFETY_LIMIT):
            if not self._is_preparation_mode():
                break
            cards = self._golden_copy_hand_cards()
            if not cards:
                break
            targets = self._golden_copy_targets(verified_names)
            if not targets:
                logger.info('[棋局] 保留黄金复制术: 无已确认上阵的一费式神')
                break
            if not self._ensure_shop_closed() or not self._is_preparation_mode():
                break
            # 关闭商店后重新读取卡牌位置，避免使用旧画面的坐标。
            cards = self._golden_copy_hand_cards()
            if not cards:
                break
            card = min(cards, key=lambda item: item['position'][0])
            name, position = targets[0]
            before = len(cards)
            if not self._equip_soul_card(card['position'], position, 'GOLDEN_COPY'):
                break
            if not self._wait_hand_card_removed(before, lambda: len(self._golden_copy_hand_cards())):
                logger.warning(
                    f'[棋局] 黄金复制术使用未确认: '
                    f'目标={name}, 套装={position}'
                )
                break
            used += 1
            logger.info(f'[棋局] 黄金复制术已使用: 目标={name}, 套装={position}')
        return used

    def _recognized_emblem_hand_cards(self) -> list[dict]:
        """纹章 Frame 定位卡牌，中心图案确认种类；Click 范围用于拖拽。"""
        return [dict(card) for card in self._frame_card_scan('emblem')
                if card['type'] == 'emblem']

    def _emblem_targets(
        self,
        emblem_name: str,
        verified_names: set[str],
    ) -> list[tuple[str, int]]:
        """按站位升序选择不具有目标羁绊、且允许佩戴该纹章的式神。"""
        bond = grigri_bond_name(emblem_name)
        strategy_shikigami = self.get_lineup_strategy()['shikigami']
        lineup_bonds = {
            item
            for name in strategy_shikigami
            for item in SHIKIGAMI_BONDS_BY_ROMAJI.get(name, ())
        }
        # 阵容内完全不存在该羁绊时，纹章没有转化目标，直接进入出售。
        assigned = any(emblem_name in unit.get('preferred_emblems', ())
                       for unit in strategy_shikigami.values())
        if bond is None or (not assigned and bond not in lineup_bonds):
            return []
        targets = []
        for name in verified_names:
            config = strategy_shikigami.get(name)
            if config is None or bond in SHIKIGAMI_BONDS_BY_ROMAJI.get(name, ()):
                continue
            preferred_souls = config.get('preferred_souls', ())
            preferred_emblems = config.get('preferred_emblems', ())
            # 声明了专属御魂的式神默认不接受纹章；只有显式白名单可放行。
            if (preferred_souls or preferred_emblems) and emblem_name not in preferred_emblems:
                continue
            _, soul_1, soul_2 = self._shikigami_attributes(name)
            if emblem_name in (soul_1, soul_2) or (soul_1 is not None and soul_2 is not None):
                continue
            targets.append((name, int(config['position'])))
        return sorted(targets, key=lambda item: item[1])

    def _keep_preferred_emblem(self, emblem_name: str) -> bool:
        """保留尚未装备给指定式神的专属纹章。"""
        strategy = self.get_lineup_strategy()
        for name, unit in strategy['shikigami'].items():
            if emblem_name not in unit.get('preferred_emblems', ()):
                continue
            _, first, second = self._shikigami_attributes(name)
            if emblem_name not in (first, second) and (first is None or second is None):
                return True
        return False

    def equip_emblems_from_hand(
        self,
        verified_names: set[str],
    ) -> list[str]:
        """识别并装备纹章；全部候选失败或无合法目标时出售。"""
        equipped = []
        for _ in range(self.SOUL_EQUIP_SAFETY_LIMIT):
            cards = self._recognized_emblem_hand_cards()
            if not cards:
                break
            card = next((item for item in cards
                         if self._emblem_targets(item['name'], verified_names)
                         or not self._keep_preferred_emblem(item['name'])), None)
            if card is None:
                break
            targets = self._emblem_targets(card['name'], verified_names)
            succeeded = False
            for target_name, set_index in targets:
                before = sum(
                    item['name'] == card['name']
                    for item in self._recognized_emblem_hand_cards()
                )
                logger.info(
                    f'[棋局] 检测到{card["name"]}(纹章)，'
                    f'尝试移动到{set_index}号位({target_name})'
                )
                goldfish_baseline = (self._goldfish_formation_baseline(target_name, emblem=True)
                                     if card['name'] == '荒川纹章' else None)
                if not self._equip_soul_card(
                    source=card['position'],
                    set_index=set_index,
                    operation_name=f'EMBLEM_{card["name"]}',
                ):
                    continue
                confirmed = self._wait_hand_card_removed(
                    before,
                    lambda: self._hand_card_identity_count('emblem', card['name']),
                )
                after = sum(
                    item['name'] == card['name']
                    for item in self._recognized_emblem_hand_cards()
                )
                if not confirmed:
                    logger.warning(
                        f'[棋局] 纹章装备未确认: '
                        f'{card["name"]} -> {target_name} 到套装 {set_index}, '
                        f'手牌数={before}->{after}'
                    )
                    refreshed = next((
                        item for item in self._recognized_emblem_hand_cards()
                        if item['name'] == card['name']
                    ), None)
                    if refreshed is not None:
                        card = refreshed
                    continue
                if not self._record_shikigami_soul(
                    target_name,
                    card['name'],
                ):
                    logger.warning(
                        f'[棋局] 纹章已消失但状态更新失败: '
                        f'{card["name"]} -> {target_name}'
                    )
                    break
                if goldfish_baseline is not None:
                    self._pending_goldfish_probe = goldfish_baseline
                    self._detect_pending_arakawa_goldfish()
                equipped.append(card['name'])
                succeeded = True
                logger.info(
                    f'[棋局] 纹章装备已确认: '
                    f'{card["name"]} -> {target_name} 到套装 {set_index}'
                )
                break

            if succeeded:
                continue
            if self._keep_preferred_emblem(card['name']):
                break
            latest = next((
                item for item in self._recognized_emblem_hand_cards()
                if item['name'] == card['name']
            ), None)
            if latest is not None:
                logger.info(
                    f'[棋局] 全部目标失败后出售纹章: '
                    f'{card["name"]}, 目标={targets}'
                )
                before = self._hand_card_identity_count('emblem', latest['name'])
                self.sell_hand_card(latest['position'])
                self._wait_hand_card_removed(
                    before,
                    lambda: self._hand_card_identity_count('emblem', latest['name']),
                )
        return equipped

    def _find_badge_hand_card(self) -> dict | None:
        """返回最左侧已确认种类的纹章，未识别的纹章保留。"""
        cards = self._recognized_emblem_hand_cards()
        return next((card for card in cards if not self._keep_preferred_emblem(card['name'])), None)

    def _recall_one_system_board_card(
        self,
        preferred_set_index: int | None = None,
    ) -> int | None:
        """满员上卡时只下阵一个系统卡位，成功则返回对应站位。"""
        if not self._is_preparation_mode():
            return None
        if not self._ensure_shop_closed():
            logger.warning(
                '[棋局] 无法释放阵容位: 商店无法关闭'
            )
            return None

        player_positions = set(
            getattr(self, '_player_deployed_positions', set())
        )
        positions = list(self.BOARD_RECALL_POSITIONS)
        if preferred_set_index in positions:
            positions.remove(preferred_set_index)
            positions.insert(0, preferred_set_index)

        hand_target = self._rule_center(
            RuleClick(
                roi_front=self.HAND_AREA,
                roi_back=self.HAND_AREA,
                name='chess_hand_area',
            )
        )
        self.screenshot()
        for set_index in positions:
            if set_index in player_positions:
                continue
            if not self._board_set_has_shikigami(set_index):
                continue

            source = self._set_position(set_index)
            goldfish_kept_at_target = False
            for attempt in range(1, self.ACTION_ICON_MAX_ATTEMPTS + 1):
                if self._hand_capacity_count() >= 10:
                    logger.info('[棋局] 暂停系统卡召回: 手牌已满，召回的卡无处可放')
                    return None
                drag_source = (
                    source
                    if attempt == 1
                    else (source[0], source[1] - 14)
                )
                Press_and_Drag(
                    self.device,
                    p1=drag_source,
                    p2=hand_target,
                    hold_duration=(0.2, 0.3),
                    point_random=(-2, -2, 2, 2),
                    swipe_duration=0.5,
                    name=(
                        f'CHESS_FREE_SYSTEM_SET_{set_index}'
                        f'_ATTEMPT_{attempt}'
                    ),
                )
                if self._wait_chess_action_state(
                    lambda: self._board_set_is_empty(set_index)
                ):
                    tracked_names = set(
                        getattr(self, '_board_lineup_names', set())
                    )
                    self._board_lineup_names = {
                        name
                        for name in tracked_names
                        if getattr(
                            self,
                            '_board_actual_positions',
                            {},
                        ).get(
                            name,
                            self.shikigami_deploy_positions.get(name),
                        )
                        != set_index
                    }
                    logger.debug(
                        f'[棋局] 系统卡已召回以上阵: '
                        f'套装={set_index}, 尝试={attempt}'
                    )
                    return set_index
                if self._handle_goldfish_after_board_action_failure(
                    set_index,
                    action='recall_for_deploy',
                ):
                    self.screenshot()
                    source_still_occupied = self._board_set_has_shikigami(
                        set_index
                    )
                    if not source_still_occupied:
                        logger.info(
                            '[棋局] 移动后失败召回的源位置已清空，'
                            f'金鱼: 套装={set_index}'
                        )
                        return set_index
                    if set_index == self._arakawa_goldfish_target_position():
                        goldfish_kept_at_target = True
                        logger.info(
                            '[棋局] 期间将金鱼保持在指定位置，'
                            f'系统召回: 套装={set_index}'
                        )
                        break
                    logger.info(
                        '[棋局] 移动后失败召回的源位置仍被占用，'
                        '金鱼换位；继续原召回: '
                        f'套装={set_index}'
                    )
                    continue
                logger.warning(
                    '[棋局] 系统卡召回未清除玉石标记: '
                    f'套装={set_index}, '
                    f'尝试={attempt}/{self.ACTION_ICON_MAX_ATTEMPTS}, '
                    f'超时={self.ACTION_ICON_WAIT_TIMEOUT:.0f}秒'
                )
            else:
                raise GameStuckError(
                    f'[棋局] 召回占用中的系统卡失败: 套装={set_index}, 已尝试 3 次'
                )
            if goldfish_kept_at_target:
                continue
        return None

    def recall_all_board_cards(self) -> bool:
        """按系统自动上阵顺序，快速回收棋盘右侧四个候选位置。"""
        if not self._ensure_shop_closed():
            logger.warning(
                '[棋局] 中止棋盘召回: 商店无法关闭'
            )
            return False
        hand_target = self._rule_center(
            RuleClick(
                roi_front=self.HAND_AREA,
                roi_back=self.HAND_AREA,
                name='chess_hand_area',
            )
        )

        count = self._read_shikigami_count()
        if count is not None and count['current'] == 0:
            logger.debug('[棋局] 棋盘已空，跳过召回')
            self._board_lineup_names = set()
            self._player_deployed_positions = set()
            self._board_actual_positions = {}
            return True

        tracked_names = set(getattr(self, '_board_lineup_names', set()))
        player_positions = set(
            getattr(self, '_player_deployed_positions', set())
        )
        recall_positions = tuple(
            set_index
            for set_index in self.BOARD_RECALL_POSITIONS
            if set_index not in player_positions
        )
        protected_recall_positions = sorted(
            set(self.BOARD_RECALL_POSITIONS) & player_positions
        )
        if protected_recall_positions:
            logger.debug(
                '[棋局] 召回时保留系统设定位置: '
                f'它们由脚本上阵，位置='
                f'{protected_recall_positions}'
            )
        logger.debug(
            f'[棋局] 棋盘召回顺序: {recall_positions}, '
            f'当前数={None if count is None else count["current"]}'
        )
        if not self._is_preparation_mode():
            logger.debug(
                '[棋局] 停止召回棋盘卡: '
                '模式已不再是准备'
            )
            return False

        # 刷新棋盘状态；若商店收起动画吞掉首个手势，由下方勾玉确认
        # 和有界重试处理，不再无条件等待收起动画。
        self.screenshot()

        # 每个已占用候选格均以勾玉图标消失确认；单次最多等待3秒，
        # 超时后上移到模型主体重拖，连续三次失败则直接报错。
        for set_index in recall_positions:
            if not self._board_set_has_shikigami(set_index):
                logger.debug(
                    f'[棋局] 跳过召回套装 {set_index}: '
                    '未检测到玉石标记'
                )
                continue
            source = self._set_position(set_index)
            goldfish_handled = False
            for attempt in range(1, self.ACTION_ICON_MAX_ATTEMPTS + 1):
                if self._hand_capacity_count() >= 10:
                    logger.info('[棋局] 暂停棋盘召回: 手牌已满，召回的卡无处可放')
                    return False
                drag_source = (
                    source
                    if attempt == 1
                    else (source[0], source[1] - 14)
                )
                Press_and_Drag(
                    self.device,
                    p1=drag_source,
                    p2=hand_target,
                    hold_duration=(0.2, 0.3),
                    point_random=(-3, -3, 3, 3),
                    swipe_duration=0.5 if attempt > 1 else 0.45,
                    name=(
                        f'CHESS_RECALL_SET_{set_index}'
                        f'_ATTEMPT_{attempt}'
                    ),
                )
                if self._wait_chess_action_state(
                    lambda: self._board_set_is_empty(set_index)
                ):
                    logger.debug(
                        '[棋局] 棋盘召回经玉石标记确认: '
                        f'套装={set_index}, '
                        f'尝试={attempt}/'
                        f'{self.ACTION_ICON_MAX_ATTEMPTS}'
                    )
                    count = self._read_shikigami_count()
                    break
                if self._handle_goldfish_after_board_action_failure(
                    set_index,
                    action='recall_all',
                ):
                    self.screenshot()
                    source_still_occupied = self._board_set_has_shikigami(
                        set_index
                    )
                    if (
                        not source_still_occupied
                        or set_index
                        == self._arakawa_goldfish_target_position()
                    ):
                        goldfish_handled = True
                        logger.info(
                            '[棋局] 处理后继续棋盘召回，'
                            f'金鱼: 套装={set_index}, '
                            f'源占用={source_still_occupied}'
                        )
                        break
                    logger.info(
                        '[棋局] 棋盘召回后源位置仍被占用，'
                        '金鱼换位；重试原召回: '
                        f'套装={set_index}'
                    )
                    continue
                logger.warning(
                    '[棋局] 棋盘召回后玉石标记仍可见: '
                    f'套装={set_index}, '
                    f'尝试={attempt}/{self.ACTION_ICON_MAX_ATTEMPTS}, '
                    f'超时={self.ACTION_ICON_WAIT_TIMEOUT:.0f}秒'
                )
            else:
                raise GameStuckError(
                    f'[棋局] 棋盘召回失败: 套装={set_index}, 已尝试 3 次'
                )
            if goldfish_handled:
                count = self._read_shikigami_count()

        self.screenshot()
        count = self._read_shikigami_count()
        # 只清除脚本记录中确实位于本次回收区域的式神。若 5 号位是脚本
        # 上阵的卡，或场上仍有其他站位的式神，则保留对应记录。
        self._board_lineup_names = {
            name
            for name in tracked_names
            if getattr(self, '_board_actual_positions', {}).get(
                name,
                self.shikigami_deploy_positions.get(name),
            )
            not in recall_positions
        }
        self._board_actual_positions = {
            name: set_index
            for name, set_index in getattr(
                self,
                '_board_actual_positions',
                {},
            ).items()
            if set_index not in recall_positions
        }
        special_positions = {
            int(unit['position'])
            for unit in getattr(self, '_board_special_units', {}).values()
            if unit.get('position') is not None
        }
        self._player_deployed_positions = (
            (player_positions - set(recall_positions))
            | special_positions
        )
        if count is not None and count['current'] == 0:
            self._board_lineup_names = set()
            self._board_actual_positions = {}
            self._player_deployed_positions = special_positions
        if count is None:
            logger.debug('[棋局] 棋盘召回完成；计数不可用')
        else:
            logger.debug(
                '[棋局] 棋盘召回完成于位置 '
                f'{self.BOARD_RECALL_POSITIONS}: '
                f'{count["current"]}/{count["total"]}'
            )
        return True

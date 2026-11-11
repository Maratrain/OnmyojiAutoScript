# This Python file uses the following encoding: utf-8
from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from time import sleep

import cv2
import numpy as np

from module.atom.click import RuleClick
from module.atom.image import RuleImage
from module.atom.frame import RuleFrame
from module.atom.ocr import RuleOcr
from module.atom.swipe import RuleSwipe
from module.base.timer import Timer
from module.logger import logger
from tasks.Component.QuickLoadout.config import (
    NamedQuickLoadoutConfig,
    QuickLoadoutConfig,
)
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.base_task import BaseTask


class QuickLoadoutOcr(RuleOcr):
    """适配快捷配置面板的棕色/橙色文字。"""

    def pre_process(self, image):
        # 项目截图使用 RGB；该小面板的选中态文字在交换红蓝通道后识别更稳定。
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


@dataclass(frozen=True)
class QuickLoadoutLayout:
    """由 frame.range1 推导出的快捷配置面板运行时布局。"""

    panel: tuple[int, int, int, int]
    group_ocr: RuleOcr
    preset_ocr: RuleOcr
    group_swipe_to_top: RuleSwipe
    group_swipe_down: RuleSwipe
    preset_swipe_to_top: RuleSwipe
    preset_swipe_down: RuleSwipe
    group_click_x: int
    preset_select_x: int
    preset_equip_x: int


class QuickLoadout(BaseTask, SwitchSoulAssets):
    """frame 锚点为入口，range1 为面板，range2 为出战；只按 OCR 名称选组和预设。

    range2 自带出战模板，所有坐标和资源都取自传入 frame；不修改 frame.back。
    """

    # 面板内部布局比例的基准尺寸；实际操作区域只取 frame.range1。
    PANEL_REFERENCE_SIZE = (555, 388)
    GROUP_OCR_ROI = (8, 7, 105, 365)
    PRESET_OCR_ROI = (145, 7, 278, 320)
    GROUP_CLICK_X = 61
    PRESET_SELECT_X = 300
    PRESET_EQUIP_X = 482

    PANEL_OPEN_TIMEOUT = 8
    PANEL_CLOSE_TIMEOUT = 5
    CONFIRM_TIMEOUT = 1.5
    MAX_GROUP_SWIPES = 10
    MAX_PRESET_SWIPES = 15
    STAGE_NAME_MATCH_THRESHOLD = 0.75

    @staticmethod
    def _parse_custom_presets(
        value: str,
    ) -> dict[str, tuple[str, str]]:
        """解析按名称指定的预设；仅接受两个非空字符串。"""
        presets = {}
        for raw_item in re.split(r'[;；]+', value):
            item = raw_item.strip()
            if not item:
                continue
            parts = re.split(r'[:：]', item, maxsplit=1)
            if len(parts) != 2 or not parts[0].strip():
                raise ValueError(f'自定义预设条目无效: {item}')
            boss_name, target_text = parts[0].strip(), parts[1].strip()
            try:
                target = ast.literal_eval(target_text)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f'自定义预设目标无效: {item}') from exc
            if not isinstance(target, (tuple, list)) or len(target) != 2:
                raise ValueError(f'自定义预设目标必须包含两个值: {item}')
            group, preset = target
            if not isinstance(group, str) or not isinstance(preset, str):
                raise ValueError(f'一键配置仅支持 OCR 名称，不支持数字序号: {item}')
            group, preset = group.strip(), preset.strip()
            if not group or not preset:
                raise ValueError(f'自定义预设目标不能为空: {item}')
            presets[boss_name] = (group, preset)
        return presets

    def _read_quick_loadout_stage_name(self, name_ocr: RuleOcr) -> str:
        """在打开一键配置面板前读取任务关卡名称。"""
        best = ''
        for attempt in range(1, 4):
            self.screenshot()
            value = str(name_ocr.ocr(self.device.image)).strip()
            if len(self._normalize_name(value)) > len(self._normalize_name(best)):
                best = value
            logger.info(f'关卡名 OCR {attempt}/3: {value}')
            if best:
                break
            sleep(0.3)
        return best

    @classmethod
    def _match_custom_preset(cls, stage_name, presets):
        """显式关卡名优先；没有显式匹配时使用 ALL。"""
        best_name = None
        best_target = None
        best_score = 0.0
        all_target = None
        for candidate, target in presets.items():
            if candidate.upper() == 'ALL':
                all_target = target
                continue
            score = cls._name_similarity(stage_name, candidate)
            if score > best_score:
                best_name, best_target, best_score = candidate, target, score
        if best_target is not None and best_score >= cls.STAGE_NAME_MATCH_THRESHOLD:
            return best_name, best_target, best_score
        if all_target is not None:
            return 'ALL', all_target, 1.0
        return None, None, 0.0

    def _resolve_named_quick_loadout(
        self,
        config: NamedQuickLoadoutConfig,
        name_ocr: RuleOcr,
    ) -> tuple[QuickLoadoutConfig, str | None]:
        """按 OCR 关卡名生成本轮配置，并返回用于一次性装魂的稳定键。"""
        stage_name = self._read_quick_loadout_stage_name(name_ocr)
        normalized_stage = self._normalize_name(stage_name)
        if not normalized_stage:
            logger.warning('关卡名 OCR 为空，使用默认预设')
            return config, None

        try:
            presets = self._parse_custom_presets(config.custom_preset)
        except ValueError as exc:
            logger.warning(str(exc))
            return config, normalized_stage

        best_name, best_target, best_score = self._match_custom_preset(stage_name, presets)
        if best_target is None:
            logger.info(f'关卡 {stage_name} 无自定义预设，使用默认预设')
            return config, normalized_stage

        group, preset = best_target
        updates = {'group_name': group, 'preset_name': preset}
        logger.info(
            f'关卡 {stage_name} 命中自定义预设: ({group}, {preset}) [{best_score:.2f}]'
        )
        return config.model_copy(update=updates), self._normalize_name(best_name)

    @staticmethod
    def _result_center_y(result, roi_top: int) -> int:
        return int(round(float(np.mean(result.box[:, 1])))) + roi_top

    @staticmethod
    def _normalize_name(value: str) -> str:
        return re.sub(r'[\s·•,，.。:：_\-—]+', '', str(value)).strip()

    @classmethod
    def _name_similarity(cls, actual: str, expected: str) -> float:
        actual = cls._normalize_name(actual)
        expected = cls._normalize_name(expected)
        if not actual or not expected:
            return 0.0
        if expected in actual or actual in expected:
            return 1.0
        return difflib.SequenceMatcher(None, actual, expected).ratio()

    def _build_quick_loadout_layout(self, frame: RuleFrame) -> QuickLoadoutLayout:
        if len(frame.roi_ranges) not in (2, 3):
            raise ValueError('一键配置 frame 需要第一段=面板 第二段=出战')
        panel = tuple(int(round(value)) for value in frame.matched_ranges[0])
        x, y, width, height = panel
        screen_h, screen_w = self.device.image.shape[:2]
        if x < 0 or y < 0 or x + width > screen_w or y + height > screen_h:
            raise ValueError(f'一键配置面板超出屏幕: {panel}')
        sx, sy = width / self.PANEL_REFERENCE_SIZE[0], height / self.PANEL_REFERENCE_SIZE[1]

        def roi(relative):
            rx, ry, rw, rh = relative
            return (x + round(rx * sx), y + round(ry * sy),
                    max(1, round(rw * sx)), max(1, round(rh * sy)))

        group_roi = roi(self.GROUP_OCR_ROI)
        preset_roi = roi(self.PRESET_OCR_ROI)
        group_ocr = QuickLoadoutOcr(roi=group_roi, area=group_roi, mode='Full', method='Default', keyword='', name='quick_loadout_group_name')
        preset_ocr = QuickLoadoutOcr(roi=preset_roi, area=preset_roi, mode='Full', method='Default', keyword='', name='quick_loadout_preset_name')

        def swipe(name, front, back):
            return RuleSwipe(roi_front=roi(front), roi_back=roi(back), mode='default', name=name)

        return QuickLoadoutLayout(
            panel, group_ocr, preset_ocr,
            swipe('quick_loadout_group_to_top', (55,105,25,20), (55,285,25,20)),
            swipe('quick_loadout_group_down', (55,285,25,20), (55,105,25,20)),
            swipe('quick_loadout_preset_to_top', (355,105,30,20), (355,280,30,20)),
            swipe('quick_loadout_preset_down', (355,280,30,20), (355,105,30,20)),
            x + round(self.GROUP_CLICK_X * sx),
            x + round(self.PRESET_SELECT_X * sx),
            x + round(self.PRESET_EQUIP_X * sx),
        )

    def _quick_loadout_fight(self, frame: RuleFrame, *, fight_file: str | None = None) -> RuleImage:
        if len(frame.roi_ranges) not in (2, 3):
            raise ValueError('一键配置 frame 需要第一段=面板 第二段=出战')
        # range1 仅用于布局；不执行其中的操作，也不改写 frame 的检测范围。
        specs, targets = frame.range_targets(self.device.image.shape, allow_missing_image=True)
        if fight_file and specs[1]['type'] == 'image' and not isinstance(targets[1], RuleImage):
            area = tuple(int(round(value)) for value in frame.matched_ranges[1])
            targets[1] = RuleImage(
                roi_front=area, roi_back=area, method=specs[1]['method'],
                threshold=specs[1]['threshold'], file=fight_file,
            )
        if specs[1]['type'] != 'image' or not isinstance(targets[1], RuleImage):
            raise ValueError('一键配置 frame 第二段必须包含出战图像')
        if not Path(targets[1].file).is_file():
            raise ValueError(f'一键配置 frame 第二段出战图像不存在: {targets[1].file}')
        return targets[1]

    def _quick_loadout_panel_visible(self, frame: RuleFrame) -> bool:
        return bool(self.appear(frame) and self.appear(self._quick_loadout_fight(frame)))

    def _open_quick_loadout(self, frame: RuleFrame) -> bool:
        logger.info('打开一键配置面板')
        timer = Timer(self.PANEL_OPEN_TIMEOUT).start()
        entry_clicked = False
        fallback_timer = Timer(1)
        while not timer.reached():
            self.screenshot()
            if self._quick_loadout_panel_visible(frame):
                return True
            if self.appear(frame):
                if entry_clicked and len(frame.roi_ranges) == 3 and fallback_timer.reached():
                    specs, targets = frame.range_targets(self.device.image.shape, allow_missing_image=True)
                    if specs[2]['type'] != 'click':
                        raise ValueError('一键配置 frame 第三段必须是点击操作')
                    logger.info('一键配置入口未弹出面板，尝试第三段兜底点击')
                    self.click(targets[2], interval=1)
                    fallback_timer.reset()
                elif not entry_clicked or len(frame.roi_ranges) == 2:
                    entry = RuleClick(
                        roi_front=tuple(frame.roi_badge), roi_back=tuple(frame.roi_badge),
                        name='QUICK_LOADOUT_ENTRY',
                    )
                    if self.click(entry, interval=1):
                        entry_clicked = True
                        fallback_timer.reset()
        logger.warning('无法打开一键配置面板')
        return False

    def _dismiss_quick_loadout(self, frame: RuleFrame, dismiss: RuleClick | None = None) -> bool:
        """未指定关闭区域时，使用左侧安全区域随机点击。"""
        target = dismiss if dismiss is not None else GeneralBattleAssets.C_RANDOM_LEFT
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if not self._quick_loadout_panel_visible(frame):
                return True
            self.click(target, interval=1)
        logger.warning('无法安全关闭一键配置面板')
        return False

    def _rewind_list(self, ocr: RuleOcr, swipe: RuleSwipe, max_swipes: int) -> None:
        """将列表拖到顶部；OCR 内容连续不变时提前停止。"""
        previous = None
        stable_count = 0
        for _ in range(max_swipes):
            self.screenshot()
            results = ocr.detect_and_ocr(self.device.image, logDisplay=False)
            current = tuple(result.ocr_text for result in results)
            if current and current == previous:
                stable_count += 1
                if stable_count >= 2:
                    return
            else:
                stable_count = 0
            previous = current
            self.swipe(swipe)
            # 滑动计入全局点击保护，滑后清掉自己的记录，避免连续滑动触发点击上限
            self.device.click_record_remove(swipe.name)
            sleep(0.45)

    def _find_name_y(self, ocr: RuleOcr, target: str, results=None) -> tuple[int | None, float]:
        best_y = None
        best_score = 0.0
        if results is None:
            results = ocr.detect_and_ocr(self.device.image)
        expected = self._normalize_name(target)
        for result in results:
            actual = self._normalize_name(result.ocr_text)
            # 预设标题可能带菱形编号；编号仅从 OCR 文本中去除，不用于位置推算。
            if expected and not expected[0].isdigit():
                actual = re.sub(r'^\d+', '', actual)
            score = 1.0 if expected and actual == expected else 0.0
            if score > best_score:
                best_score = score
                best_y = self._result_center_y(result, ocr.roi[1])
        return best_y, best_score

    def _confirm_name_y(self, ocr: RuleOcr, target: str, y: int, tolerance: int = 6) -> int | None:
        """点击前用新的一帧确认目标仍在原位置，避免列表滚动导致坐标过期。"""
        self.screenshot()
        results = ocr.detect_and_ocr(self.device.image, logDisplay=False)
        y2, _ = self._find_name_y(ocr, target, results)
        if y2 is None or abs(y2 - y) > tolerance:
            logger.info(f'一键配置点击前目标位置变化: {target} y={y} -> {y2}，重试')
            return None
        return y2

    def _select_group(self, layout: QuickLoadoutLayout, config: QuickLoadoutConfig) -> bool:
        self._rewind_list(layout.group_ocr, layout.group_swipe_to_top, self.MAX_GROUP_SWIPES)
        previous = None
        stable_count = 0
        for _ in range(self.MAX_GROUP_SWIPES + 1):
            self.screenshot()
            results = layout.group_ocr.detect_and_ocr(self.device.image, logDisplay=False)
            current = tuple(result.ocr_text for result in results)
            y, score = self._find_name_y(layout.group_ocr, config.group_name, results)
            if y is not None and score >= 0.55:
                logger.info(f'分组 OCR 命中 {config.group_name} [{score:.2f}]')
                confirmed_y = self._confirm_name_y(layout.group_ocr, config.group_name, y)
                if confirmed_y is not None:
                    self.device.click(layout.group_click_x, confirmed_y, control_name='QUICK_LOADOUT_GROUP_OCR')
                    sleep(0.6)
                    return True
                # 列表仍在滚动，坐标已过期；重新截图再找，不做多余滑动
                continue
            stable_count = stable_count + 1 if current and current == previous else 0
            if stable_count >= 2:
                break
            previous = current
            self.swipe(layout.group_swipe_down)
            self.device.click_record_remove(layout.group_swipe_down.name)
            sleep(0.6)
        logger.warning(f'未找到分组: {config.group_name}, 可见分组: {list(previous or ())}')
        return False

    def _select_preset_row(self, layout: QuickLoadoutLayout, config: QuickLoadoutConfig) -> int | None:
        self._rewind_list(layout.preset_ocr, layout.preset_swipe_to_top, self.MAX_PRESET_SWIPES)

        previous = None
        stable_count = 0
        target_label = config.preset_name
        for _ in range(self.MAX_PRESET_SWIPES + 1):
            self.screenshot()
            results = layout.preset_ocr.detect_and_ocr(self.device.image, logDisplay=False)
            current = tuple(result.ocr_text for result in results)
            y, score = self._find_name_y(layout.preset_ocr, config.preset_name, results)
            if y is not None and score >= 0.55:
                logger.info(f'预设命中 {target_label} [{score:.2f}]')
                confirmed_y = self._confirm_name_y(layout.preset_ocr, config.preset_name, y)
                if confirmed_y is not None:
                    return confirmed_y
                # 列表仍在滚动，坐标已过期；重新截图再找，不做多余滑动
                continue
            stable_count = stable_count + 1 if current and current == previous else 0
            if stable_count >= 2:
                break
            previous = current
            self.swipe(layout.preset_swipe_down)
            self.device.click_record_remove(layout.preset_swipe_down.name)
            sleep(0.6)
        logger.warning(f'未找到预设: {target_label}, 可见预设: {list(previous or ())}')
        return None

    def _equip_quick_loadout_souls(self, layout: QuickLoadoutLayout, row_y: int) -> None:
        self.device.click(layout.preset_equip_x, row_y, control_name='QUICK_LOADOUT_EQUIP_SOUL')
        timer = Timer(self.CONFIRM_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if not self.appear(self.I_SOU_SWITCH_SURE):
                sleep(0.15)
                continue
            logger.info('确认装配预设御魂')
            self.ui_click_until_disappear(self.I_SOU_SWITCH_SURE, interval=0.6)
            return
        logger.info('预设御魂确认弹窗未出现，可能已装配')

    def _deploy_quick_loadout(self, layout: QuickLoadoutLayout, frame: RuleFrame, row_y: int, dismiss: RuleClick | None = None) -> bool:
        self.device.click(layout.preset_select_x, row_y, control_name='QUICK_LOADOUT_PRESET')
        sleep(0.4)
        self.screenshot()
        if not self._quick_loadout_panel_visible(frame):
            return False
        self.click(self._quick_loadout_fight(frame))
        timer = Timer(self.PANEL_CLOSE_TIMEOUT).start()
        while not timer.reached():
            self.screenshot()
            if not self._quick_loadout_panel_visible(frame):
                logger.info('一键配置上阵完成')
                return True
            sleep(0.2)
        logger.warning('一键配置上阵后面板未关闭')
        self._dismiss_quick_loadout(frame, dismiss=dismiss)
        return False

    def run_quick_loadout(
        self,
        config: QuickLoadoutConfig,
        *,
        frame: RuleFrame,
        name_ocr: RuleOcr | None = None,
        dismiss: RuleClick | None = None,
        skip_equip_soul: bool = False,
    ) -> bool:
        """将目标预设上阵，默认先装配御魂。"""
        if not config.enable:
            return True
        if isinstance(config, NamedQuickLoadoutConfig) and config.custom_preset_enable:
            if name_ocr is None:
                logger.warning('启用关卡名预设但未提供关卡名 OCR 规则')
            else:
                config, _ = self._resolve_named_quick_loadout(config, name_ocr)
        config.validate_target()
        target = (frame.name, config.group_name.strip(), config.preset_name.strip(), skip_equip_soul)
        if getattr(self, '_last_quick_loadout', None) == target:
            logger.info(f'一键配置未变化，沿用当前阵容: {target[1:3]}')
            return True
        # A failed attempt may have changed souls or selected another preset.
        self._last_quick_loadout = None
        logger.hr('一键配置', 2)
        if not self._open_quick_loadout(frame):
            return False
        try:
            layout = self._build_quick_loadout_layout(frame)
            logger.info(f'一键配置面板: {layout.panel}')
            if not self._select_group(layout, config):
                self._dismiss_quick_loadout(frame, dismiss=dismiss)
                return False
            row_y = self._select_preset_row(layout, config)
            if row_y is None:
                self._dismiss_quick_loadout(frame, dismiss=dismiss)
                return False
            if not skip_equip_soul:
                self._equip_quick_loadout_souls(layout, row_y)
            deployed = self._deploy_quick_loadout(layout, frame, row_y, dismiss=dismiss)
            if deployed:
                self._last_quick_loadout = target
            return deployed
        except Exception:
            self._dismiss_quick_loadout(frame, dismiss=dismiss)
            raise

from datetime import datetime, timedelta
from pathlib import Path
from time import sleep

from cached_property import cached_property
import cv2
import numpy as np
from module.exception import TaskEnd
from module.logger import logger
from module.base.random_delay import CONTINUOUS_CONFIRM_DELAY, FIRST_OPERATION_DELAY
from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_exploration, page_main
from tasks.NewbieStory.assets import NewbieStoryAssets


class ScriptTask(GameUi, GeneralBattle, NewbieStoryAssets, ActivityShikigamiAssets):
    """识别剧情交互图标、跳过对白，并接管新手战斗。"""

    minimum_click_interval = CONTINUOUS_CONFIRM_DELAY
    recognition_click_delay = FIRST_OPERATION_DELAY

    DANMAKU_FORBIDDEN_AREA = (300, 45, 1100, 140)
    QUESTION_SCALES = tuple(round(value / 100, 2) for value in range(65, 136, 5))

    @cached_property
    def _config(self):
        return self.config.model.newbie_story

    @staticmethod
    def find_ellipsis_center(image):
        """按三个水平排列的亮色点识别气泡，避免受气泡后方场景影响。"""
        def clickable(point):
            x, y = point
            # 屏幕中上方为滚动弹幕/系统公告区域，禁止剧情识别点击。
            left, top, right, bottom = ScriptTask.DANMAKU_FORBIDDEN_AREA
            return not (left <= x <= right and top <= y <= bottom)

        red, green, blue = [image[:, :, i] for i in range(3)]
        mask = ((red > 180) & (green > 150) & (blue > 110)
                & ((red.astype(np.int16) - blue.astype(np.int16)) < 120)).astype(np.uint8)
        count, _, stats, centers = cv2.connectedComponentsWithStats(mask)
        dots = []
        for index in range(1, count):
            x, y, width, height, area = stats[index]
            if (20 <= area <= 60 and 4 <= width <= 9 and 4 <= height <= 9
                    and 60 < y < 520):
                dots.append(centers[index])
        dots.sort(key=lambda point: (point[1], point[0]))
        for first in dots:
            row = sorted((point for point in dots if abs(point[1] - first[1]) <= 3),
                         key=lambda point: point[0])
            for offset in range(len(row) - 2):
                one, two, three = row[offset:offset + 3]
                gap_one, gap_two = two[0] - one[0], three[0] - two[0]
                if 8 <= gap_one <= 18 and 8 <= gap_two <= 18:
                    center = (int(round(two[0])),
                              int(round((one[1] + two[1] + three[1]) / 3)))
                    if clickable(center):
                        return center

            # 气泡贴着屏幕左右边缘时，第三个点可能完全落在画面外。
            # 只在 30px 边缘区接受双点，避免把场景内普通亮点当作气泡。
            for offset in range(len(row) - 1):
                one, two = row[offset:offset + 2]
                gap = two[0] - one[0]
                at_edge = one[0] <= 30 or two[0] >= image.shape[1] - 30
                if at_edge and 8 <= gap <= 18:
                    x = int(round((one[0] + two[0]) / 2))
                    y = int(round((one[1] + two[1]) / 2))
                    center = (max(8, min(image.shape[1] - 9, x)), y)
                    if clickable(center):
                        return center
        return None

    @cached_property
    def _question_template_gray(self):
        file = Path(__file__).with_name('res') / 'story_question_icon.png'
        # cv2.imread 在 Windows 下无法稳定读取含中文的绝对路径。
        template = cv2.imdecode(np.fromfile(file, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if template is None:
            logger.warning(f'Unable to load question icon template: {file}')
        return template

    @cached_property
    def _question_templates_gray(self):
        """Load all question styles for the background-independent fallback."""
        templates = []
        folder = Path(__file__).with_name('res')
        for name in (
            'story_question_icon.png',
            'story_question_icon_alt.png',
            'story_question_icon_gold.png',
        ):
            file = folder / name
            template = cv2.imdecode(
                np.fromfile(file, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            if template is None:
                logger.warning(f'Unable to load question icon template: {file}')
                continue
            templates.append((name, template))
        return templates

    def find_question_center(self, image):
        """多尺寸识别头顶问号，兼容场景明暗和透视造成的轻微缩放。"""
        templates = self._question_templates_gray
        if not templates:
            return None

        top, bottom = 60, 500
        search = cv2.cvtColor(image[top:bottom], cv2.COLOR_RGB2GRAY)

        # Match only the central question-mark stroke first. The upper half of
        # the round bubble is often covered by the scrolling announcement, but
        # this small core remains visible. Coordinates below convert the core
        # match back to the center of the original 70x75 alternate template.
        alternate = next((item for name, item in templates
                          if name == 'story_question_icon_alt.png'), None)
        if alternate is not None:
            core = alternate[16:55, 24:46]
            core_best_score, core_best_center, core_best_scale = 0.0, None, None
            for scale in self.QUESTION_SCALES:
                resized = cv2.resize(
                    core, None, fx=scale, fy=scale,
                    interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
                result = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
                _, score, _, location = cv2.minMaxLoc(result)
                if score > core_best_score:
                    core_best_score = score
                    core_best_center = (
                        int(round(location[0] + 11 * scale)),
                        int(round(top + location[1] + 21 * scale)),
                    )
                    core_best_scale = scale
            if core_best_score >= 0.72:
                logger.info(
                    f'Question icon core score={core_best_score:.3f} '
                    f'at {core_best_center}, scale={core_best_scale:.2f}'
                )
                return core_best_center

        best_score, best_center, best_name, best_scale = 0.0, None, None, None
        for name, template in templates:
            for scale in self.QUESTION_SCALES:
                resized = cv2.resize(
                    template, None, fx=scale, fy=scale,
                    interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
                height, width = resized.shape
                result = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
                _, score, _, location = cv2.minMaxLoc(result)
                if score > best_score:
                    best_score = score
                    best_center = (
                        location[0] + width // 2,
                        top + location[1] + height // 2,
                    )
                    best_name, best_scale = name, scale

        # Dynamic characters can cover most of the bubble background. Two
        # consecutive fresh-frame detections are still required before click,
        # so this fallback can use a lower score than the full-template rules.
        if best_score >= 0.54:
            logger.info(
                f'Question icon fallback score={best_score:.3f} at {best_center}, '
                f'template={best_name}, scale={best_scale:.2f}'
            )
            return best_center
        return None

    def _click_story_control(self, target, message, action=None):
        """等待后重新识别动态控件，并点击最新坐标。"""
        if not self.appear(target, interval=0.8):
            return False
        self._wait_before_recognition_click()
        self.screenshot()
        if not self.appear(target, interval=None):
            logger.info(f'{target.name} moved or disappeared while waiting; skip stale click')
            return False
        self.click(action or target)
        self.device.click_record_clear()
        logger.info(message)
        return True

    def _click_danmaku_eye(self):
        """识别被弹幕遮挡的眼睛，并点击弹幕下方的动态安全坐标。"""
        target = self.I_STORY_EYE_ICON_DANMAKU
        if not self.appear(target, interval=0.8):
            return False
        self._wait_before_recognition_click()
        self.screenshot()
        if not self.appear(target, interval=None):
            logger.info('Danmaku eye moved or disappeared while waiting; skip stale click')
            return False
        x, y = target.coord()
        _, _, _, forbidden_bottom = self.DANMAKU_FORBIDDEN_AREA
        safe_y = max(forbidden_bottom + 8, y + 12)
        self.device.click(x, safe_y, control_name=target.name)
        self.device.click_record_clear()
        logger.info(f'Click partially covered eye icon below danmaku area at {(x, safe_y)}')
        return True

    def _click_visible_skip_now(self):
        """在当前截图中优先处理跳过，供动态目标等待后再次仲裁。"""
        if self._click_round_story_skip():
            return True
        skip_controls = (
            (self.I_SKIP_BUTTON, 'Click story skip (priority recheck)'),
            (self.I_CONFIRM_SKIP, 'Confirm story skip (priority recheck)'),
            (self.I_STORY_SKIP_DIALOG, 'Click dialogue story skip (priority recheck)'),
            (self.I_STORY_SKIP_DIALOG_PINK,
             'Click dialogue story skip, pink scene (priority recheck)'),
        )
        for target, message in skip_controls:
            if not self.appear(target, interval=None):
                continue
            self.click(target)
            self.device.click_record_clear()
            logger.info(message)
            return True
        return False

    def _click_round_story_skip(self):
        """仅在剧情播放控件同时存在时点击圆形跳过，避免误点主页频道。"""
        if not self.appear(self.I_STORY_PLAYBACK_PAUSE, interval=None):
            return False
        if not self.appear(self.I_STORY_SKIP_ROUND, interval=None):
            return False
        self._wait_before_recognition_click()
        self.screenshot()
        if not self.appear(self.I_STORY_PLAYBACK_PAUSE, interval=None):
            return False
        if not self.appear(self.I_STORY_SKIP_ROUND, interval=None):
            return False
        self.click(self.I_STORY_SKIP_ROUND)
        self.device.click_record_clear()
        logger.info('Click round story skip with playback context')
        return True

    def _find_exploration_battle(self):
        """Use exploration's compact sword templates on the story map."""
        for target in (self.I_STORY_EXPLORATION_BOSS,
                       self.I_STORY_EXPLORATION_BATTLE):
            if not self.appear(target, interval=None):
                continue
            x, y = target.front_center()
            left, top, right, bottom = self.DANMAKU_FORBIDDEN_AREA
            if left <= x <= right and top <= y <= bottom:
                continue
            return target
        return None

    def _click_exploration_battle(self):
        target = self._find_exploration_battle()
        if target is None:
            return False
        old_center = target.front_center()
        self._wait_before_recognition_click()
        # Like exploration's filtered target handling, re-detect in fresh
        # frames instead of clicking coordinates captured before the delay.
        for attempt in range(4):
            self.screenshot()
            if self.is_in_prepare(False) or self.is_in_real_battle(False):
                self.run_general_battle(self._config.general_battle_config)
                return True
            if self._click_visible_skip_now():
                return True
            refreshed = self._find_exploration_battle()
            if refreshed is not None:
                x, y = refreshed.front_center()
                if np.hypot(x - old_center[0], y - old_center[1]) <= 160:
                    # A precise center click cannot randomly land in the
                    # announcement strip when the icon is near its edge.
                    self.device.click(int(x), int(y),
                                      control_name='newbie_story_exploration_sword')
                    logger.info(f'Click revalidated story sword: {old_center} -> {(x, y)}')
                    sleep(0.4)
                    return True
            if attempt < 3:
                sleep(0.15)
        logger.info('Story sword moved or disappeared; skip stale battle click')
        # A target was handled even if it disappeared. Do not fall through to
        # a less-specific icon or a blank-area click in this same frame.
        return True

    def handle_once(self):
        """处理一帧；返回 True 表示识别并执行了动作。"""
        self.screenshot()

        # 探索章节面板中的问号和眼睛属于关卡单位，不是剧情控件。
        # 自动接力时先返回主页，再由下一帧判断是否出现真正的剧情交互。
        if self.appear(page_exploration.check_button):
            logger.info('Exploration page detected; return to main before running newbie story')
            self.goto_page(page_main)
            sleep(2.0)
            return True

        # 战斗状态优先于剧情图标。战斗画面中的特效、文字可能与问号模板相似，
        # 若先处理剧情图标，会持续误点而无法交给通用战斗流程。
        if self.is_in_prepare(False) or self.is_in_real_battle(False):
            logger.info('Newbie story battle detected')
            self.run_general_battle(self._config.general_battle_config)
            return True

        controls = (
            (self.I_SKIP_BUTTON, 'Click story skip', None),
            (self.I_CONFIRM_SKIP, 'Confirm story skip', None),
            (self.I_STORY_SKIP_DIALOG, 'Click dialogue story skip', None),
            (self.I_STORY_SKIP_DIALOG_PINK,
             'Click dialogue story skip (pink scene)', None),
            (self.I_STORY_NEXT_TRACK, 'Click story next track', None),
            (self.I_STORY_BATTLE_ICON, 'Click newbie story battle icon', None),
            (self.I_STORY_BATTLE_ICON_ALT,
             'Click newbie story battle icon (alternate style)', None),
            (self.I_STORY_BATTLE_ICON_PURPLE,
             'Click newbie story battle icon (purple scene)', None),
            (self.I_STORY_BATTLE_ICON_DANMAKU,
             'Click partially covered battle icon above danmaku area',
             self.C_STORY_BATTLE_DANMAKU_SAFE),
            (self.I_STORY_EYE_ICON_DANMAKU,
             'Click partially covered eye icon below danmaku area', None),
            (self.I_STORY_EYE_ICON, 'Click newbie story eye icon', None),
            (self.I_STORY_EYE_ICON_CORE,
             'Click newbie story eye icon (background independent)', None),
            (self.I_STORY_QUESTION_ICON, 'Click newbie story question icon', None),
            (self.I_STORY_QUESTION_ICON_ALT,
             'Click newbie story question icon (alternate style)', None),
            (self.I_STORY_QUESTION_ICON_GOLD,
             'Click newbie story question icon (gold ring style)', None),
        )

        if self._click_story_control(*controls[0]):
            return True

        if self._click_round_story_skip():
            return True

        if self.ocr_appear_click(self.O_STORY_SKIP, interval=0.8):
            self.device.click_record_clear()
            logger.info('Click story skip (OCR)')
            return True

        # 确认跳过与对白跳过同样优先于主页结束判断。
        for control in controls[1:4]:
            if self._click_story_control(*control):
                return True

        ellipsis = self.find_ellipsis_center(self.device.image)
        if ellipsis is not None:
            self._wait_before_recognition_click()
            self.screenshot()
            # 跳过按钮可能在等待三点期间出现。最新帧中只要同时存在，
            # 必须先点跳过，不能继续使用三点分支。
            if self._click_visible_skip_now():
                return True
            if self.ocr_appear_click(self.O_STORY_SKIP, interval=0.8):
                self.device.click_record_clear()
                logger.info('Click story skip by OCR (priority recheck)')
                return True
            refreshed_ellipsis = self.find_ellipsis_center(self.device.image)
            if refreshed_ellipsis is None:
                logger.info('Story ellipsis moved or disappeared while waiting; skip stale click')
                return False
            self.device.click(*refreshed_ellipsis, control_name='newbie_story_ellipsis_dots')
            self.device.click_record_clear()
            logger.info(
                f'Click story ellipsis dots at refreshed position {refreshed_ellipsis} '
                f'(was {ellipsis})'
            )
            return True

        if self._click_story_control(self.I_STORY_ELLIPSIS,
                                     'Click story ellipsis bubble'):
            return True

        if self._click_exploration_battle():
            return True

        # 沿用探索任务的 page_main 页面标志。剧情气泡和跳过均不存在时，
        # 返回主页代表本轮新手剧情已经结束，不再执行空白区域点击。
        if self.appear(page_main.check_button):
            logger.info('Main page detected without story bubble or skip; finish newbie story')
            self.set_next_run(task='NewbieStory', success=True, finish=True)
            raise TaskEnd('NewbieStory returned to main page')

        for control in controls[4:]:
            if control[0] is self.I_STORY_EYE_ICON_DANMAKU:
                if self._click_danmaku_eye():
                    return True
                continue
            if self._click_story_control(*control):
                return True

        question = self.find_question_center(self.device.image)
        if question is not None:
            self._wait_before_recognition_click()
            refreshed_question = None
            # The icon and characters are continuously animated. A single
            # post-delay frame can temporarily score below the threshold, so
            # sample a short burst and accept only a nearby stable candidate.
            for attempt in range(5):
                self.screenshot()
                candidate = self.find_question_center(self.device.image)
                if candidate is not None:
                    movement = float(np.hypot(
                        candidate[0] - question[0],
                        candidate[1] - question[1],
                    ))
                    if movement <= 160:
                        refreshed_question = candidate
                        break
                    logger.warning(
                        f'Story question candidate jumped {movement:.1f}px '
                        f'from {question} to {candidate}; retry fresh frame'
                    )
                if attempt < 4:
                    sleep(0.15)
            if refreshed_question is None:
                logger.info(
                    'Story question moved or disappeared during 5-frame '
                    'revalidation; skip stale click'
                )
                return False
            self.device.click(*refreshed_question, control_name='newbie_story_question_multiscale')
            self.device.click_record_clear()
            logger.info(
                f'Click newbie story question icon at refreshed position {refreshed_question} '
                f'(was {question})'
            )
            return True

        if self.click(self.C_STORY_BLANK, interval=1.2):
            self.device.click_record_clear()
            logger.info('No story control found; click blank area and inspect next frame')
            return True

        return False

    def run(self):
        logger.hr('newbie story')
        limit = self._config.newbie_story_config.run_time
        deadline = datetime.now() + timedelta(
            hours=limit.hour, minutes=limit.minute, seconds=limit.second
        )

        while datetime.now() < deadline:
            if not self.handle_once():
                sleep(0.5)

        self.set_next_run(task='NewbieStory', success=True, finish=True)
        raise TaskEnd('NewbieStory run time reached')

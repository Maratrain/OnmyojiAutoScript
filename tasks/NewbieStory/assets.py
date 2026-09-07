from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.atom.click import RuleClick
from copy import deepcopy
from tasks.Exploration.assets import ExplorationAssets


class NewbieStoryAssets:
    # Share exploration's sword templates, but not its mutable match coordinates.
    I_STORY_EXPLORATION_BATTLE = deepcopy(ExplorationAssets.I_NORMAL_BATTLE_BUTTON)
    I_STORY_EXPLORATION_BOSS = deepcopy(ExplorationAssets.I_BOSS_BATTLE_BUTTON)
    # Keep the map search above the bottom toolbar. Announcement hits are
    # filtered by their actual click position in the story task.
    I_STORY_EXPLORATION_BATTLE.roi_back = (0, 60, 1280, 540)
    I_STORY_EXPLORATION_BOSS.roi_back = (0, 60, 1280, 540)

    # 角色头顶的问号剧情交互入口。
    I_STORY_QUESTION_ICON = RuleImage(
        roi_front=(1006, 255, 72, 82),
        roi_back=(0, 60, 1280, 500),
        threshold=0.60,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_question_icon.png',
    )

    # 细边框、带底部尖角的问号气泡样式。
    I_STORY_QUESTION_ICON_ALT = RuleImage(
        roi_front=(1162, 242, 70, 75),
        roi_back=(0, 60, 1280, 500),
        threshold=0.68,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_question_icon_alt.png',
    )

    # 金色发光圆环问号样式（新手剧情部分场景）。
    I_STORY_QUESTION_ICON_GOLD = RuleImage(
        roi_front=(252, 252, 75, 75),
        roi_back=(0, 60, 1280, 500),
        threshold=0.68,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_question_icon_gold.png',
    )

    # 角色头顶的眼睛剧情交互入口。
    I_STORY_EYE_ICON = RuleImage(
        roi_front=(572, 86, 135, 140),
        roi_back=(0, 60, 1280, 500),
        threshold=0.74,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_eye_icon.png',
    )

    # 只匹配眼睛内部纹样，避免不同剧情背景降低整张图标的匹配分数。
    I_STORY_EYE_ICON_CORE = RuleImage(
        roi_front=(659, 130, 92, 92),
        roi_back=(0, 80, 1280, 430),
        threshold=0.76,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_eye_icon_core.png',
    )

    # 眼睛图标中部被弹幕遮挡时，只匹配并点击弹幕下方露出的部分。
    I_STORY_EYE_ICON_DANMAKU = RuleImage(
        roi_front=(580, 105, 120, 75),
        roi_back=(0, 105, 1280, 395),
        threshold=0.72,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_eye_icon_danmaku.png',
    )

    # 角色头顶的交叉刀剑战斗入口。
    I_STORY_BATTLE_ICON = RuleImage(
        roi_front=(458, 257, 110, 110),
        roi_back=(0, 80, 1280, 480),
        threshold=0.68,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_battle_icon.png',
    )

    # 蓝色夜景等关卡中出现的较小交叉刀剑入口。
    I_STORY_BATTLE_ICON_ALT = RuleImage(
        roi_front=(165, 195, 100, 100),
        roi_back=(0, 80, 1280, 500),
        threshold=0.68,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_battle_icon_alt.png',
    )

    # 粉紫色海浪场景中的战斗入口。
    I_STORY_BATTLE_ICON_PURPLE = RuleImage(
        roi_front=(186, 153, 110, 110),
        roi_back=(0, 80, 1280, 480),
        threshold=0.72,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_battle_icon_purple.png',
    )

    # 战斗图标下半部分被中上方弹幕遮挡时，只匹配露在弹幕上方的部分。
    I_STORY_BATTLE_ICON_DANMAKU = RuleImage(
        roi_front=(960, 0, 115, 64),
        roi_back=(750, 0, 530, 64),
        threshold=0.72,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_battle_icon_danmaku.png',
    )

    # 点击露出的顶部，严格避开 y=45..140 的弹幕禁点区。
    C_STORY_BATTLE_DANMAKU_SAFE = RuleClick(
        roi_front=(1006, 24, 24, 16),
        roi_back=(1006, 24, 24, 16),
        name='story_battle_danmaku_safe',
    )

    # “事情原委”回放界面右上角最右侧的下一曲按钮。
    I_STORY_NEXT_TRACK = RuleImage(
        roi_front=(1170, 14, 86, 86),
        roi_back=(1140, 0, 140, 120),
        threshold=0.78,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_next_track.png',
    )

    # 普通对白框上方的“跳过”按钮。
    I_STORY_SKIP_DIALOG = RuleImage(
        roi_front=(820, 548, 100, 55),
        roi_back=(790, 520, 180, 110),
        threshold=0.76,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_skip_dialog.png',
    )

    # 粉色剧情场景中的棕色描边“跳过”按钮。
    I_STORY_SKIP_DIALOG_PINK = RuleImage(
        roi_front=(816, 546, 104, 56),
        roi_back=(790, 520, 180, 110),
        threshold=0.74,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_skip_dialog_pink.png',
    )

    # 弹幕剧情右上角的圆形“下一步/跳过”图标。只匹配内部的
    # 三角形和竖线，避免外圈呼吸光效及动态背景拉低识别率。
    I_STORY_SKIP_ROUND = RuleImage(
        roi_front=(1203, 39, 34, 38),
        roi_back=(1170, 10, 100, 90),
        threshold=0.60,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_skip_round.png',
    )

    # 圆形跳过按钮左侧同时出现的暂停符号，用作页面上下文校验，
    # 防止把庭院右上角的频道按钮误认为跳过。
    I_STORY_PLAYBACK_PAUSE = RuleImage(
        roi_front=(999, 38, 31, 40),
        roi_back=(970, 10, 90, 90),
        threshold=0.68,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_playback_pause.png',
    )

    # 当前帧没有可识别控件时，点击底部中间的空白区推进介绍页。
    C_STORY_BLANK = RuleClick(
        roi_front=(620, 575, 40, 25),
        roi_back=(620, 575, 40, 25),
        name='newbie_story_blank',
    )

    # 头顶圆形对话气泡，内含三个点。使用全屏搜索以兼容不同角色位置。
    I_STORY_ELLIPSIS = RuleImage(
        roi_front=(824, 220, 69, 69),
        roi_back=(0, 140, 1280, 430),
        threshold=0.75,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_ellipsis.png',
    )

    # 剧情动画右上角的“跳过”，OCR 作为泛用识别，不依赖某一段剧情的图标。
    O_STORY_SKIP = RuleOcr(
        roi=(1080, 0, 200, 100),
        area=(1040, 0, 240, 130),
        mode='Single',
        method='Default',
        keyword='跳过',
        name='newbie_story_skip',
    )

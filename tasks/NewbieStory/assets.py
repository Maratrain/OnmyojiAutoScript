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

    # 异想剧情段的战斗图标：圆盘只有 ~76px（既有模板 110px），且贴在顶部
    # 公告带（y 45-140）上方，既有窗口（y>=80 或 x>=750）整体漏检，剧情被
    # 空白点击卡死（实测连续 102 秒无进展）。按生产帧重裁圆盘模板，多尺度
    # 兼容 68~114px 的各场景尺寸。生产链路实测：遮挡帧 0.7286、干净帧
    # 1.0；公告文字横向滚过圆盘的 20 个模拟位置得分 0.61~1.0（均值 0.88，
    # 仅最密字簇压盘时低于阈值，下一轮 1~2s 自愈）；77 帧误报回归上限
    # 0.4715，阈值 0.7 对误报有 0.23 余量。
    I_STORY_BATTLE_ICON_DISK = RuleImage(
        roi_front=(717, 22, 76, 76),
        roi_back=(0, 0, 1280, 260),
        threshold=0.7,
        method='Multi-scale template matching',
        file='./tasks/NewbieStory/res/story_battle_icon_disk.png',
    )
    # 圆盘直径跨场景 68~114px，模板按 76px 采集，多尺度覆盖其余尺寸
    I_STORY_BATTLE_ICON_DISK.scale_range = (0.9, 1.5, 0.05)

    # 绿枝夜景段的圆盘战斗图标：86px，公告文字带（屏幕 y 66~101）横穿圆盘
    # 中上部，粉色花瓣漂在盘底。与下午模板虽同属圆盘资产，但花瓣位置
    # （盘顶 vs 盘底）、盘体尺寸（76 vs 86px）、背景（紫底 vs 绿/棕底）
    # 差异大，下午模板对该场景全屏多尺度最佳仅 0.44，低于阈值整段漏检，
    # 剧情被空白点击卡死（实机日志连续 102 秒无进展）。
    # 注意：该规则不进 controls 循环，由 script_task 的掩码多尺度匹配使用
    # （模板 + 同目录 _mask.png 排除公告带/花瓣/盘外背景，阈值 0.80）；
    # 实测同场景两帧互匹 1.000，跨场景（下午干净帧）0.992。
    I_STORY_BATTLE_ICON_DISK_NIGHT = RuleImage(
        roi_front=(869, 57, 86, 86),
        roi_back=(0, 0, 1280, 260),
        threshold=0.80,
        method='Masked template matching',
        file='./tasks/NewbieStory/res/story_battle_icon_disk_night.png',
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

    # 普通对白框上方的“跳过”按钮。搜索窗覆盖整个下侧区域：
    # 不同段落按钮会随对白框布局移动，窄窗会整段漏匹配。
    I_STORY_SKIP_DIALOG = RuleImage(
        roi_front=(820, 548, 100, 55),
        roi_back=(660, 460, 400, 220),
        threshold=0.76,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_skip_dialog.png',
    )

    # 粉色剧情场景中的棕色描边“跳过”按钮。
    I_STORY_SKIP_DIALOG_PINK = RuleImage(
        roi_front=(816, 546, 104, 56),
        roi_back=(660, 460, 400, 220),
        threshold=0.74,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_skip_dialog_pink.png',
    )

    # 对白框中“跳过”按钮的文字部分（紧贴文字裁剪、不含场景背景）。
    # 整按钮模板会把采集时的场景背景一起烘焙进去，而按钮边框半透、
    # 场景色温会透进来：换成紫色场景后 RGB 匹配只有 0.67，低于 0.76
    # 阈值整段漏检（表现为只点三点气泡和空白、剧情一句句磨过去）。
    # 文字部分跨场景完全一致（实测 0.98），与整按钮模板并联兜底。
    I_STORY_SKIP_DIALOG_TEXT = RuleImage(
        roi_front=(841, 558, 57, 27),
        roi_back=(660, 460, 400, 220),
        threshold=0.8,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_skip_dialog_text.png',
    )

    # 弹幕剧情右上角的圆形“下一步/跳过”图标。只匹配内部的
    # 三角形和竖线，避免外圈呼吸光效及动态背景拉低识别率。
    I_STORY_SKIP_ROUND = RuleImage(
        roi_front=(1203, 39, 34, 38),
        roi_back=(1100, 0, 180, 130),
        threshold=0.60,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_skip_round.png',
    )

    # 圆形跳过按钮左侧同时出现的暂停符号，用作页面上下文校验，
    # 防止把庭院右上角的频道按钮误认为跳过。
    I_STORY_PLAYBACK_PAUSE = RuleImage(
        roi_front=(999, 38, 31, 40),
        roi_back=(930, 0, 180, 130),
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

    # 对白框整条区域的“跳过”OCR 兜底。模板匹配会把采集时的场景背景一起
    # 烘焙进去（按钮边框半透、场景色温会透进来），换场景后得分掉到阈值
    # 以下整段漏检；OCR 只认文字、与场景背景无关（实测 0.99+），作为模板
    # 层之外的通用识别。Full 模式子串匹配，命中后点击文字框本身；若误匹配
    # 到对白文字，点击等效于推进对白，无副作用。
    O_STORY_SKIP_DIALOG = RuleOcr(
        roi=(0, 460, 1280, 260),
        area=(0, 460, 1280, 260),
        mode='Full',
        method='Default',
        keyword='跳过',
        name='newbie_story_skip_dialog',
    )

    # 缘初新手专用庭院的底部图标行（珍旅居/纳物库）。新手账号的庭院与
    # 默认庭院差异大，I_CHECK_MAIN 命中不了，任务会一直空白点击不退出。
    I_STORY_CHECK_MAIN_NEWBIE = RuleImage(
        roi_front=(190, 596, 202, 104),
        roi_back=(40, 580, 400, 140),
        threshold=0.85,
        method='Template matching',
        file='./tasks/NewbieStory/res/story_check_main_newbie.png',
    )

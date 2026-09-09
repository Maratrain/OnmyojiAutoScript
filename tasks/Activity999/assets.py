from module.atom.click import RuleClick
from module.atom.image import RuleImage


class Activity999Assets:
    # 999 专用安全点击区域：位于画面中央。
    # 避开左上角返回、右下角挑战、活动主页两侧入口和底部菜单。
    C_ACTIVITY_999_SAFE_RANDOM = RuleClick(
        roi_front=(570, 300, 140, 90),
        roi_back=(570, 300, 140, 90),
        name='activity_999_safe_random',
    )

    # 弹窗关闭点：双列推荐弹窗（灵符挑战补给/金花灵符）之间 x≈640 的竖向缝隙。
    # 弹窗没有关闭按钮，遮罩不响应点击；仅两面板之间的缝隙可穿透关闭。
    C_ACTIVITY_999_POPUP_GAP = RuleClick(
        roi_front=(620, 300, 40, 200),
        roi_back=(620, 300, 40, 200),
        name='activity_999_popup_gap',
    )

    # 奖励图标位于画面中部，结算只能点击面板下方的空白区域。
    # 该区域在返回虚无精锐页后也避开了右下角挑战及底部操作按钮。
    C_ACTIVITY_999_BATTLE_WIN = RuleClick(
        roi_front=(480, 590, 220, 70),
        roi_back=(480, 590, 220, 70),
        name='activity_999_battle_win',
    )
    # 庭院紫色树下方人物头顶的金色活动入口。
    I_ACTIVITY_999_ENTRY = RuleImage(
        roi_front=(709, 259, 72, 76),
        # 庭院角色站位和皮肤会让入口大范围横向漂移（当前庭院在人物头顶偏右）。
        # 搜索框从左侧任务提示一直覆盖到画面中部，避免模板在边界处被裁掉。
        roi_back=(350, 170, 470, 190),
        threshold=0.72,
        method='Template matching',
        file='./tasks/Activity999/res/activity_999_entry.png',
    )

    # “拾光永恒”活动首页左上角标题。
    I_ACTIVITY_999_HOME = RuleImage(
        roi_front=(82, 8, 225, 62),
        roi_back=(75, 0, 245, 80),
        threshold=0.78,
        method='Template matching',
        file='./tasks/Activity999/res/activity_999_home.png',
    )

    I_ACTIVITY_999_BACK = RuleImage(
        roi_front=(8, 7, 68, 65),
        roi_back=(0, 0, 85, 80),
        threshold=0.78,
        method='Template matching',
        file='./tasks/Activity999/res/activity_999_back.png',
    )

    C_ACTIVITY_999_BACK = RuleClick(
        roi_front=(18, 15, 45, 45),
        roi_back=(18, 15, 45, 45),
        name='activity_999_back',
    )

    # 活动首页“回响旧地”入口旁的竖排“战斗”文字。
    I_ACTIVITY_999_BATTLE_TEXT = RuleImage(
        roi_front=(306, 202, 42, 92),
        roi_back=(275, 170, 145, 155),
        threshold=0.76,
        method='Template matching',
        file='./tasks/Activity999/res/activity_999_battle_text.png',
    )

    C_ACTIVITY_999_BATTLE = RuleClick(
        roi_front=(300, 185, 105, 120),
        roi_back=(300, 185, 105, 120),
        name='activity_999_battle',
    )

    I_ACTIVITY_999_ECHO_HOME = RuleImage(
        roi_front=(82, 7, 235, 64), roi_back=(75, 0, 250, 82),
        threshold=0.78, method='Template matching',
        file='./tasks/Activity999/res/activity_999_echo_home.png')

    I_ACTIVITY_999_ELITE_MENU = RuleImage(
        roi_front=(8, 80, 255, 63), roi_back=(0, 70, 280, 85),
        threshold=0.76, method='Template matching',
        file='./tasks/Activity999/res/activity_999_elite_menu.png')

    I_ACTIVITY_999_ELITE_PAGE = RuleImage(
        roi_front=(137, 7, 185, 64), roi_back=(125, 0, 210, 82),
        threshold=0.78, method='Template matching',
        file='./tasks/Activity999/res/activity_999_elite_page.png')

    I_ACTIVITY_999_CHALLENGE = RuleImage(
        roi_front=(1120, 575, 125, 112), roi_back=(1090, 545, 180, 165),
        threshold=0.76, method='Template matching',
        file='./tasks/Activity999/res/activity_999_challenge.png')

    C_ACTIVITY_999_ELITE_MENU = RuleClick(
        roi_front=(25, 88, 215, 48), roi_back=(25, 88, 215, 48),
        name='activity_999_elite_menu')

    C_ACTIVITY_999_CHALLENGE = RuleClick(
        roi_front=(1140, 590, 95, 82), roi_back=(1140, 590, 95, 82),
        name='activity_999_challenge')

    # 活动战斗胜利后的“获得奖励”结算牌。
    I_ACTIVITY_999_BATTLE_WIN = RuleImage(
        roi_front=(455, 165, 375, 115), roi_back=(420, 135, 450, 170),
        threshold=0.76, method='Template matching',
        file='./tasks/Activity999/res/activity_999_battle_win.png')

    # 奖励面板较高时会盖住背景“胜利”，标题的位置和底纹也会发生变化。
    # 单独保留该结算形态，避免依赖被遮挡的通用胜利模板。
    I_ACTIVITY_999_REWARD_WIN = RuleImage(
        roi_front=(454, 135, 375, 115), roi_back=(400, 95, 500, 210),
        threshold=0.72, method='Template matching',
        file='./tasks/Activity999/res/activity_999_reward_win.png')

    # 奖励详情弹窗可能遮住标题，但底部“点击屏幕继续”仍然可见。
    I_ACTIVITY_999_SETTLEMENT_CONTINUE = RuleImage(
        roi_front=(540, 670, 210, 40), roi_back=(500, 650, 290, 70),
        threshold=0.72, method='Template matching',
        file='./tasks/Activity999/res/activity_999_settlement_continue.png')

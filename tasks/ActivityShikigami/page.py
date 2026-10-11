from tasks.ActivityShikigami.assets import ActivityShikigamiAssets
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.RightActivity.assets import RightActivityAssets
from tasks.GameUi.action import conditional_action
from tasks.GameUi.default_pages import random_click
from tasks.GameUi.page import (
    Page,
    page_main,
    sequence,
    page_battle,
    page_battle_prepare,
    page_reward,
    page_battle_result,
    any_of,
)
from tasks.GlobalGame.assets import GlobalGameAssets

# 爬塔活动主界面
page_act = Page(ActivityShikigamiAssets.I_TO_BATTLE_MAIN)
page_act.add_enter_failure_hooks(
    RightActivityAssets.I_TOGGLE_BUTTON,
    conditional_action(GlobalGameAssets.I_UI_REWARD, random_click),
    GlobalGameAssets.I_UI_BACK_RED,
    ActivityShikigamiAssets.I_SKIP_BUTTON,
)
page_act.connect(
    page_main, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act->page_main"
)
page_main.connect(
    page_act, ActivityShikigamiAssets.I_MAIN_GOTO_ACT, key="page_main->page_act"
)
# 是否存在特殊活动界面标志(点击一次无法进入体力爬塔界面，存在中转界面的情况，False表示没有中转界面，True表示有中转界面)
special_act_Flag = False
if special_act_Flag:
    # 特殊活动中转地图页面
    page_act_map = Page(ActivityShikigamiAssets.I_MAP_GOTO_BATTLE)
    page_act_map.connect(
        page_act, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_map->page_act"
    )
    page_act.connect(
        page_act_map,
        ActivityShikigamiAssets.I_TO_BATTLE_MAIN,
        key="page_act->page_act_map",
    )

# 体力爬塔页面
page_act_ap = Page(ActivityShikigamiAssets.I_CLIMB_MODE_AP)
# 存在特殊活动界面
if special_act_Flag:
    page_act_ap.connect(
        page_act_map, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_ap->page_act_map"
    )
# 不存在特殊活动界面
else:
    page_act_ap.connect(
        page_act, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_ap->page_act"
    )

# 门票爬塔页面
page_act_pass = Page(ActivityShikigamiAssets.I_CLIMB_MODE_PASS)
# 存在特殊活动界面
if special_act_Flag:
    page_act_pass.connect(
        page_act_map,
        GlobalGameAssets.I_UI_BACK_YELLOW,
        key="page_act_pass->page_act_map",
    )
# 不存在特殊活动界面
else:
    page_act_pass.connect(
        page_act, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_pass->page_act"
    )

# 100体爬塔页面
page_act_ap100 = Page(ActivityShikigamiAssets.I_CLIMB_MODE_AP100)
page_act_ap100.add_enter_failure_hooks(GlobalGameAssets.I_UI_BACK_RED)
# BOSS爬塔页面
page_act_boss = Page(ActivityShikigamiAssets.I_CHECK_BATTLE_BOSS)
page_act_boss.connect(
    page_act, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_act_boss->page_act"
)
page_act.connect(
    page_act_boss,
    ActivityShikigamiAssets.I_TO_BATTLE_BOSS,
    key="page_act->page_act_boss",
)

# 爬塔活动第2个页面（磐长故地等活动地图页）
# 模块级全局注册：中断残留该页面时, 任意任务的导航 session 都能识别并经 ↩ 返回键退出
page_act_2 = Page(ActivityShikigamiAssets.I_AS_CHECK_MAIN_2)
page_act_2.add_enter_success_hooks(GlobalGameAssets.I_UI_BACK_RED)
page_act.connect(
    page_act_2,
    ActivityShikigamiAssets.I_TO_BATTLE_MAIN,
    key="page_act->page_act_2",
)
page_act_2.connect(
    page_act, GlobalGameAssets.I_UI_BACK_CIRCLE, key="page_act_2->page_act"
)
# 门票和活动页面2关联
page_act_pass.connect(
    page_act_2,
    GlobalGameAssets.I_UI_BACK_YELLOW,
    key="page_act_pass->page_act_2",
)
page_act_2.connect(
    page_act_pass,
    ActivityShikigamiAssets.I_AS_TO_PASS,
    key="page_act_2->page_act_pass",
)
# 主界面和体力页面关联
page_act.connect(
    page_act_ap,
    ActivityShikigamiAssets.I_TO_BATTLE_AP,
    key="page_act->page_act_ap",
)
# 100体和活动页面2关联
page_act_ap100.connect(
    page_act_2,
    GlobalGameAssets.I_UI_BACK_YELLOW,
    key="page_act_ap100->page_act_2",
)
page_act_2.connect(
    page_act_ap100,
    ActivityShikigamiAssets.O_ENTER_AP100,
    key="page_act_2->page_act_ap100",
)

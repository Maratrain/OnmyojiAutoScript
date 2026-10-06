from tasks.GameUi.default_pages import page_main, page_daily, page_friends
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.LevelRush.assets import LevelRushAssets

# 新手活动页面
page_rookie_act = Page(LevelRushAssets.I_CHECK_ROOKIE_ACT)
page_rookie_act.add_enter_failure_hooks(LevelRushAssets.I_RED_CLOSE)
page_main.connect(
    page_rookie_act,
    LevelRushAssets.I_GOTO_ROOKIE_ACT,
    key="page_main->page_rookie_act",
)
page_rookie_act.connect(
    page_main,
    LevelRushAssets.I_YELLOW_BACK_BUTTON,
    key="page_rookie_act->page_main",
)

# 成就页面
page_achievement = Page(LevelRushAssets.I_CHECK_ACHIEVEMENT)
page_daily.connect(
    page_achievement,
    LevelRushAssets.I_DAILY_GOTO_ACHIEVEMENT,
    key="page_daily->page_achievement",
)
page_achievement.connect(
    page_daily,
    LevelRushAssets.I_YELLOW_BACK_BUTTON,
    key="page_achievement->page_daily",
)

# 好友添加页面
page_add_friends = Page(LevelRushAssets.I_CHECK_ADD)
page_friends.connect(
    page_add_friends,
    LevelRushAssets.I_FRIEND_GOTO_ADD,
    key="page_friends->page_add_friends",
)
page_add_friends.connect(
    page_main,
    GlobalGameAssets.I_UI_BACK_RED,
    key="page_add_friends->page_main",
)

# 绑定手机页面
page_bind_phone = Page(LevelRushAssets.I_PHONE_BIND)
page_bind_phone.connect(
    page_main,
    LevelRushAssets.I_PHONE_BIND,
    key="page_bind_phone->page_main",
)
page_main.add_enter_failure_hooks(
    LevelRushAssets.I_PHONE_BIND_CANCEL, LevelRushAssets.I_PHONE_BIND_CANCEL
)

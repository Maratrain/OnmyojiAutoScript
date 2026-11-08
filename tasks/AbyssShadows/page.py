from tasks.AbyssShadows.assets import AbyssShadowsAssets
from tasks.GameUi.page import Page, page_shirin, page_shikigami_records
from tasks.GlobalGame.assets import GlobalGameAssets

page_abyss = Page(AbyssShadowsAssets.I_CHECK_ABYSS)
page_abyss_map = Page(AbyssShadowsAssets.I_ABYSS_NAVIGATION)
page_shirin.connect(page_abyss, AbyssShadowsAssets.L_SHENSHE_TO_ABYSS, key="page_shirin->page_abyss")
page_abyss.connect(page_shirin, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_abyss->page_shirin")
page_abyss_map.connect(page_abyss, GlobalGameAssets.I_UI_BACK_YELLOW, key="page_abyss_map->page_abyss")
page_abyss_map.connect(page_shikigami_records, AbyssShadowsAssets.I_ABYSS_SHIKI, key="page_abyss_map->page_shikigami_records", cost=4)
# 注意: 不登记 page_shikigami_records -> page_abyss_map 的返回边。
# 式神录返回箭头的落点与进入方式相关(狭间进入回狭间地图, 庭院进入回庭院),
# 登记成通用导航边后, 入口失败重试会让惩罚机制把路径绕到这条边上,
# 在庭院里反复"进式神录->点返回"直到点击上限报错(2026-11-07 实证)。
# 狭间内的返回由 AbyssShadows 任务代码直接点击返回箭头处理。

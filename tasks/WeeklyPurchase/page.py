from module.logger import logger
from tasks.GameUi.assets import GameUiAssets
from tasks.GameUi.default_pages import (
    page_entertainment,
    page_guild,
    page_shirin,
    random_click,
)
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.WeeklyPurchase.assets import WeeklyPurchaseAssets


def handle_weekly_purchase_shrine_unknown(task) -> bool:
    """功勋商店导航遇到未知中间页时只补一次安全随机点击。"""

    if not getattr(task, '_weekly_purchase_guild_navigation', False):
        return False
    if getattr(task, '_weekly_purchase_shrine_random_clicked', False):
        return False

    task.screenshot()
    if task.appear(GameUiAssets.I_CHECK_GUILD):
        return False
    if task.appear(GameUiAssets.I_CHECK_SHRIN):
        return False

    task._weekly_purchase_shrine_random_clicked = True
    logger.warning(
        '[神社] 进入神社时出现未知页面，执行一次安全随机点击'
    )
    task.click(random_click())
    return True


# 仅在 WeeklyPurchase 的功勋商店导航标志开启时执行上述保底；其他任务
# 仍沿用原本的公用神社跳转逻辑。
page_guild.connect(
    page_shirin,
    GameUiAssets.I_GUILD_TO_SHRIN,
    key="page_guild->page_shirin",
    on_enter_failure=[handle_weekly_purchase_shrine_unknown],
)

page_guild_store = Page(WeeklyPurchaseAssets.I_RM_CHECK_GUILD_STORE, priority=75, category='guild')
page_guild_store.connect(page_shirin, GlobalGameAssets.I_UI_BACK_RED, key="page_guild_store->page_shirin")
page_shirin.connect(page_guild_store, WeeklyPurchaseAssets.I_GUILD_STORE, key="page_shirin->page_guild_store")

page_itachi_shop = Page(
    WeeklyPurchaseAssets.I_ITACHI_SHOP_CHECK,
    priority=75,
    category='weekly_purchase',
)
page_entertainment.connect(
    page_itachi_shop,
    WeeklyPurchaseAssets.I_ITACHI_SHOP_ENTRY,
    key="page_entertainment->page_itachi_shop",
)
page_itachi_shop.connect(
    page_entertainment,
    GlobalGameAssets.I_UI_BACK_RED,
    key="page_itachi_shop->page_entertainment",
)

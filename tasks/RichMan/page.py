from tasks.GameUi.default_pages import page_entertainment, page_shirin
from tasks.GameUi.page_definition import Page
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.RichMan.assets import RichManAssets

page_guild_store = Page(RichManAssets.I_RM_CHECK_GUILD_STORE, priority=75, category='guild')
page_guild_store.connect(page_shirin, GlobalGameAssets.I_UI_BACK_RED, key="page_guild_store->page_shirin")
page_shirin.connect(page_guild_store, RichManAssets.I_GUILD_STORE, key="page_shirin->page_guild_store")

page_itachi_shop = Page(
    RichManAssets.I_ITACHI_SHOP_CHECK,
    priority=75,
    category='richman',
)
page_entertainment.connect(
    page_itachi_shop,
    RichManAssets.I_ITACHI_SHOP_ENTRY,
    key="page_entertainment->page_itachi_shop",
)
page_itachi_shop.connect(
    page_entertainment,
    GlobalGameAssets.I_UI_BACK_RED,
    key="page_itachi_shop->page_entertainment",
)

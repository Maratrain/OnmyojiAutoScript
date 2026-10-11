from tasks.ActivityShikigami.base_act import BaseAct


class FakeGodAct(BaseAct):
    """伪神活动

    活动第2个页面（磐长故地等活动地图页）及其连边已上移到 page.py 模块级
    全局注册（原在此处 before_run 动态创建，仅本任务 session 可见，其他任务
    中断残留该页面时无法识别也无法退出）。
    """

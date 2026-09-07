"""AutoCheckinBigGod 手动领取流程（纯 UI，不依赖 Frida）。

把"启动大神APP → 圈子 → 福利中心 → 领奖"的状态机拆出来，让 script_task.py 只负责
调度（Frida 路径 or 手动路径），导航逻辑集中在本文件。继承 PortraitUIMixin 复用竖屏
UI 原语（_init_portrait / _appear_then_click / _screenshot_safe / _launch_app_foreground /
_cleanup_portrait），并通过 PortraitUIMixin -> BaseTask 链获得 appear/set_next_run 等。

"""
from typing import TYPE_CHECKING

from module.logger import logger
from module.base.timer import Timer
from module.exception import TaskEnd
from tasks.AutoCheckinBigGod.assets import AutoCheckinBigGodAssets as A
from tasks.AutoCheckinBigGod.portrait_ui import PortraitUIMixin

GL_PACKAGE = "com.netease.gl"


class ManualClaimMixin(PortraitUIMixin):
    """手动领取流程混入类。继承 PortraitUIMixin 复用竖屏 UI 原语与 BaseTask 能力。
    宿主需提供 _check_adb_connection（ScriptTask 已有，依赖 ADB 实现）。"""

    if TYPE_CHECKING:
        # 宿主 ScriptTask 提供的 ADB 连接检查方法（实现在 script_task.py 中）。
        # 此处仅作类型声明，让 IDE 解析 self._check_adb_connection() 调用。
        def _check_adb_connection(self) -> bool: ...

    def _run_manual_claim(self):
        """纯UI手动领取：启动app→圈子→福利中心→领奖。竖屏720x1280原生操作。
        截图走配置方法(nemu_ipc/adb/droidcast/scrcpy均返回原生竖屏)，点击走 adb input tap
        (绕开 minitouch/nemu_ipc 写死的1280x720横屏缩放)，从而与具体截图/控制方法无关。"""
        logger.hr('大神签到（手动）', level=1)

        if not self._check_adb_connection():
            logger.error('未检测到ADB设备，请确保模拟器已启动并已连接ADB')
            self.set_next_run('AutoCheckinBigGod', success=False, finish=True)
            raise TaskEnd('AutoCheckinBigGod')

        # 竖屏720x1280+orientation=0：跳过 check_screen_size(会反复调dumpsys) 与 check_screen_black
        self._init_portrait()

        logger.info('启动大神APP（前台）...')
        if not self._launch_app_foreground(GL_PACKAGE):
            logger.error('无法启动大神APP，请确保模拟器中已安装大神APP')
            self.set_next_run('AutoCheckinBigGod', success=False, finish=True)
            raise TaskEnd('AutoCheckinBigGod')

        # 总超时240s，count=3 容忍低性能设备单次截图耗时过长导致的误判（参考 Timer 文档）
        timeout = Timer(240, count=3).start()
        claimed = False
        while 1:
            self._screenshot_safe()

            # 1. 启动时的重新登录弹窗（如果有的话）
            if self._appear_then_click(A.I_LOGIN_AGAIN, interval=2):
                continue
            if self._appear_then_click(A.I_X,interval=2):
                continue
            # 2. 已领取完成
            if self.appear(A.I_CLAIM_S):
                logger.info('领取完成')
                claimed = True
                break
            # 3. 在福利中心：可领取
            if self._appear_then_click(A.I_CLAIM, interval=3):
                continue
            # 4. 未登录提示（圈子页或福利中心点击领取后出现）
            if self._appear_then_click(A.I_LOGIN, interval=6):
                continue
            # 5. 在圈子页：进福利中心
            if self.appear(A.I_CIRCLE_CHECK):
                self._appear_then_click(A.I_WELFARE, interval=2)
                continue
            # 6. 不在圈子：进圈子
            if self._appear_then_click(A.I_CIRCLE, interval=4):
                continue
            # 超时保护
            if timeout.reached():
                break

        self._cleanup_portrait()
        if claimed:
            logger.info('手动领取完成')
            self.set_next_run('AutoCheckinBigGod', success=True, finish=True)
        else:
            logger.warning('手动领取超时未完成')
            self.set_next_run('AutoCheckinBigGod', success=False, finish=True)
        raise TaskEnd('AutoCheckinBigGod')

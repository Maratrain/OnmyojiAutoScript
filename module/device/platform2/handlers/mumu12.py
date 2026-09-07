import os
import re
import typing as t

from module.device.platform2.handlers.base import EmulatorHandler
from module.logger import logger


class MuMu12Handler(EmulatorHandler):
    """现代 MuMu（Android 12/15）Handler，保留原配置类型以兼容旧配置。"""
    MuMuPlayer12 = 'MuMuPlayer12'
    INSTANCE_NAME_PATTERNS = (
        re.compile(r'MuMuPlayer(?:Global)?-\d+(?:\.\d+)*-(\d+)'),
        re.compile(r'YXArkNights-\d+(?:\.\d+)*-(\d+)'),
    )

    @staticmethod
    def type_names() -> list[str]:
        return ['MuMuPlayer12']

    @staticmethod
    def path_to_type(path: str, exe: str, dir1: str, dir2: str) -> str:
        if exe in ['mumuplayer.exe', 'mumunxmain.exe']:
            return 'MuMuPlayer12'
        return ''

    @staticmethod
    def multi_to_single(exe: str) -> list[str]:
        if 'MuMuMultiPlayer.exe' in exe:
            return [exe.replace('MuMuMultiPlayer.exe', 'MuMuPlayer.exe')]
        if 'MuMuManager.exe' in exe:
            return [exe.replace('MuMuManager.exe', 'MuMuPlayer.exe')]
        return []

    @staticmethod
    def single_to_console(exe: str) -> t.Optional[str]:
        if 'MuMuPlayer.exe' in exe:
            return exe.replace('MuMuPlayer.exe', 'MuMuManager.exe')
        if 'MuMuNxMain.exe' in exe:
            return exe.replace('MuMuNxMain.exe', 'MuMuManager.exe')
        return None

    def get_instance_id(self, instance) -> t.Optional[int]:
        name = getattr(instance, 'name', '')
        if not isinstance(name, str):
            return None
        for pattern in self.INSTANCE_NAME_PATTERNS:
            res = pattern.fullmatch(name)
            if res:
                return int(res.group(1))
        return None

    def _resolve_console(self, instance) -> t.Optional[str]:
        exe = getattr(getattr(instance, 'emulator', None), 'path', '')
        console = self.single_to_console(exe) if isinstance(exe, str) else None
        if not console:
            logger.warning(f'[设备-平台] 无法从路径解析 MuMu 控制程序: {exe}')
            return None
        if not os.path.isfile(console):
            logger.warning(f'[设备-平台] MuMu 控制程序不存在: {console}')
            return None
        return console

    def iter_instances(self, emulator) -> t.Iterable:
        from module.device.platform2.emulator_windows import EmulatorInstance, Emulator
        from module.device.platform2.utils import iter_folder

        # vms/MuMuPlayer-12.0-0 or vms/MuMuPlayer-15.0-0
        for folder in emulator.list_folder('../vms', is_dir=True):
            for file in iter_folder(folder, ext='.nemu'):
                serial = Emulator.vbox_file_to_serial(file)
                name = os.path.basename(folder)
                if serial:
                    yield EmulatorInstance(
                        serial=serial,
                        name=name,
                        path=emulator.path,
                    )
                else:
                    # Fix for MuMu12 v4.0.4
                    instance = EmulatorInstance(
                        serial=serial,
                        name=name,
                        path=emulator.path,
                    )
                    mumu_id = self.get_instance_id(instance)
                    if mumu_id is not None:
                        instance.serial = f'127.0.0.1:{16384 + 32 * mumu_id}'
                        yield instance

    def iter_adb_binaries(self, emulator) -> t.Iterable[str]:
        # MuMu12 特有: ../vmonitor/bin/adb_server.exe
        exe = emulator.abspath('../vmonitor/bin/adb_server.exe')
        if os.path.exists(exe):
            yield exe
        yield from self._iter_common_adb(emulator)

    def start_show_window(self) -> bool:
        # MuMu12 通过 MuMuManager 启动，命令本身不需要窗口
        return False

    def build_start_command(self, instance) -> t.Optional[str]:
        mumu_id = self.get_instance_id(instance)
        if mumu_id is None:
            logger.warning(f'[设备-平台] 无法从名称获取 MuMu 实例序号: {instance.name}')
            return None
        console = self._resolve_console(instance)
        if console is None:
            return None
        # MuMuManager.exe control -v 0 launch
        return f'"{console}" control -v {mumu_id} launch'

    def build_stop_command(self, instance) -> t.Optional[str]:
        mumu_id = self.get_instance_id(instance)
        if mumu_id is None:
            logger.warning(f'[设备-平台] 无法从名称获取 MuMu 实例序号: {instance.name}')
            return None
        console = self._resolve_console(instance)
        if console is None:
            return None
        # MuMuManager.exe control -v 1 shutdown
        return f'"{console}" control -v {mumu_id} shutdown'

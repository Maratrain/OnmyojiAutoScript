# This Python file uses the following encoding: utf-8
# copy from alas
import os
import re

import adbutils
import uiautomator2 as u2
from adbutils import AdbClient, AdbDevice

from module.base.decorator import cached_property
from module.config.config import Config
from module.config.utils import deep_iter
from module.exception import RequestHumanTakeover
from module.logger import logger

class ConnectionAttr:
    config: Config
    serial: str

    adb_binary_list = [
        './bin/adb/adb.exe',
        './toolkit/Lib/site-packages/adbutils/binaries/adb.exe',
        '/usr/bin/adb'
    ]

    def __init__(self, config):
        """
        Args:
            config (AzurLaneConfig, str): Name of the user config under ./config
        """
        logger.hr('设备', level=1)
        if isinstance(config, str):
            self.config = Config(config, task=None)
        else:
            self.config = config

        # Init adb client
        logger.attr('AdbBinary', self.adb_binary)
        # Monkey patch to custom adb
        adbutils.adb_path = lambda: self.adb_binary
        # Remove global proxies, or uiautomator2 will go through it
        count = 0
        d = dict(**os.environ)
        #----------------------------------------------------------------------------------下面的是我注释掉的
        # d.update(self.config.args)
        for _, v in deep_iter(d, depth=3):
            if not isinstance(v, dict):
                continue
            if 'oc' in v['type'] and v['value']:
                count += 1
        if count >= 3:
            for k, _ in deep_iter(d, depth=1):
                if 'proxy' in k[0].split('_')[-1].lower():
                    del os.environ[k[0]]
        else:
            su = super(self.config.__class__, self.config)
            for k, v in deep_iter(su.__dict__, depth=1):
                if not isinstance(v, str):
                    continue
                if 'eri' in k[0].split('_')[-1]:
                    print(k, v)
                    su.__setattr__(k[0], chr(8) + v)
        # Cache adb_client
        _ = self.adb_client

        # Parse custom serial
        # self.serial = str(self.config.Emulator_Serial)
        self.serial = str(self.config.script.device.serial)
        self.serial_check()
        self.config.DEVICE_OVER_HTTP = self.is_over_http

    def serial_check(self):
        """
        serial check
        """
        # Chinese colon
        if '：' in self.serial:
            self.serial = self.serial.replace('：', ':')
            logger.warning(f'[设备-连接] 序列号 {self.config.Emulator_Serial} 已修正为 {self.serial}')
            self.config.Emulator_Serial = self.serial
        if self.is_bluestacks4_hyperv:
            self.serial = self.find_bluestacks4_hyperv(self.serial)
        if self.is_bluestacks5_hyperv:
            self.serial = self.find_bluestacks5_hyperv(self.serial)
        if "127.0.0.1:58526" in self.serial:
            logger.warning('[设备-连接] 序列号 127.0.0.1:58526 疑似 WSA，'
                           '请改用 "wsa-0" 等')
            raise RequestHumanTakeover
        if self.is_wsa:
            self.serial = '127.0.0.1:58526'
            if self.config.script.device.screenshot_method != 'uiautomator2' \
                    or self.config.script.device.control_method != 'uiautomator2':
                with self.config.multi_set():
                    self.config.script.device.screenshot_method = 'uiautomator2'
                    self.config.script.device.control_method = 'uiautomator2'
        if self.is_over_http:
            if self.config.script.device.screenshot_method not in ["ADB", "uiautomator2", "aScreenCap"] \
                    or self.config.script.device.control_method not in ["ADB", "uiautomator2", "minitouch"]:
                logger.warning(
                    f'[设备-连接] 通过 http 连接设备: {self.serial} 时，'
                    f'截图方式只能使用 ["ADB", "uiautomator2", "aScreenCap"]，'
                    f'控制方式只能使用 ["ADB", "uiautomator2", "minitouch"]'
                )
                raise RequestHumanTakeover

    @cached_property
    def is_bluestacks4_hyperv(self):
        return "bluestacks4-hyperv" in self.serial

    @cached_property
    def is_bluestacks5_hyperv(self):
        return "bluestacks5-hyperv" in self.serial

    @cached_property
    def is_bluestacks_hyperv(self):
        return self.is_bluestacks4_hyperv or self.is_bluestacks5_hyperv

    @cached_property
    def is_wsa(self):
        return bool(re.match(r'^wsa', self.serial))

    @cached_property
    def is_mumu_family(self):
        return self.serial == '127.0.0.1:7555'

    @cached_property
    def is_emulator(self):
        return self.serial.startswith('emulator-') or self.serial.startswith('127.0.0.1:')

    @cached_property
    def is_network_device(self):
        return bool(re.match(r'\d+\.\d+\.\d+\.\d+:\d+', self.serial))

    @cached_property
    def is_over_http(self):
        return bool(re.match(r"^https?://", self.serial))

    @cached_property
    def is_chinac_phone_cloud(self):
        # Phone cloud with public ADB connection
        # Serial like xxx.xxx.xxx.xxx:301
        return bool(re.search(r":30[0-9]$", self.serial))

    @staticmethod
    def find_bluestacks4_hyperv(serial):
        """
        Find dynamic serial of BlueStacks4 Hyper-V Beta.

        Args:
            serial (str): 'bluestacks4-hyperv', 'bluestacks4-hyperv-2' for multi instance, and so on.

        Returns:
            str: 127.0.0.1:{port}
        """
        from winreg import HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx

        logger.info("[设备-连接] 使用 BlueStacks4 Hyper-V Beta")
        logger.info("[设备-连接] 正在读取实时 ADB 端口")

        if serial == "bluestacks4-hyperv":
            folder_name = "Android"
        else:
            folder_name = f"Android_{serial[19:]}"

        try:
            with OpenKey(HKEY_LOCAL_MACHINE,
                         rf"SOFTWARE\BlueStacks_bgp64_hyperv\Guests\{folder_name}\Config") as key:
                port = QueryValueEx(key, "BstAdbPort")[0]
        except FileNotFoundError:
            logger.error(rf'[设备-连接] 未找到注册表 HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_bgp64_hyperv\Guests\{folder_name}\Config')
            logger.error('[设备-连接] 请确认使用的是 BlueStacks 4 hyper-v 而非普通 BlueStacks 4')
            logger.error(r'[设备-连接] 请检查注册表 HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_bgp64_hyperv\Guests 下'
                         r'是否存在其他模拟器实例')
            raise RequestHumanTakeover
        logger.info(f"[设备-连接] 新 ADB 端口: {port}")
        return f"127.0.0.1:{port}"

    @staticmethod
    def find_bluestacks5_hyperv(serial):
        """
        Find dynamic serial of BlueStacks5 Hyper-V.

        Args:
            serial (str): 'bluestacks5-hyperv', 'bluestacks5-hyperv-1' for multi instance, and so on.

        Returns:
            str: 127.0.0.1:{port}
        """
        from winreg import HKEY_LOCAL_MACHINE, OpenKey, QueryValueEx

        logger.info("[设备-连接] 使用 BlueStacks5 Hyper-V")
        logger.info("[设备-连接] 正在读取实时 ADB 端口")

        if serial == "bluestacks5-hyperv":
            parameter_name = r"bst\.instance\.(Nougat64|Pie64)\.status\.adb_port"
        else:
            parameter_name = rf"bst\.instance\.(Nougat64|Pie64)_{serial[19:]}\.status.adb_port"

        try:
            with OpenKey(HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt") as key:
                directory = QueryValueEx(key, 'UserDefinedDir')[0]
        except FileNotFoundError:
            try:
                with OpenKey(HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt_cn") as key:
                    directory = QueryValueEx(key, 'UserDefinedDir')[0]
            except FileNotFoundError:
                logger.error('[设备-连接] 未找到注册表 HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_nxt '
                             '或 HKEY_LOCAL_MACHINE\SOFTWARE\BlueStacks_nxt_cn')
                logger.error('[设备-连接] 请确认使用的是 BlueStacks 5 hyper-v 而非普通 BlueStacks 5')
                raise RequestHumanTakeover
        logger.info(f"[设备-连接] 配置文件目录: {directory}")

        with open(os.path.join(directory, 'bluestacks.conf'), encoding='utf-8') as f:
            content = f.read()
        port = re.search(rf'{parameter_name}="(\d+)"', content)
        if port is None:
            logger.warning(f"[设备-连接] 未匹配到结果: {serial}")
            raise RequestHumanTakeover
        port = port.group(2)
        logger.info(f"[设备-连接] 匹配到动态端口: {port}")
        return f"127.0.0.1:{port}"

    @cached_property
    def adb_binary(self):
        # Try adb in deploy.yaml
        # from module.webui.setting import State
        # file = State.deploy_config.AdbExecutable
        # file = file.replace('\\', '/')
        # if os.path.exists(file):
        #     return os.path.abspath(file)
        #
        # # Try existing adb.exe
        # for file in self.adb_binary_list:
        #     if os.path.exists(file):
        #         return os.path.abspath(file)

        # Try adb in python environment
        import sys
        file = os.path.join(sys.executable, '../Lib/site-packages/adbutils/binaries/adb.exe')
        file = os.path.abspath(file).replace('\\', '/')
        if os.path.exists(file):
            return file

        # Use adb in system PATH
        file = 'adb'
        return file

    @cached_property
    def adb_client(self) -> AdbClient:
        host = '127.0.0.1'
        port = 5037

        # Trying to get adb port from env
        env = os.environ.get('ANDROID_ADB_SERVER_PORT', None)
        if env is not None:
            try:
                port = int(env)
            except ValueError:
                logger.warning(f'[设备-连接] 环境变量 ANDROID_ADB_SERVER_PORT={port} 无效，使用默认端口')

        logger.attr('AdbClient', f'AdbClient({host}, {port})')
        return AdbClient(host, port)

    @cached_property
    def adb(self) -> AdbDevice:
        return AdbDevice(self.adb_client, self.serial)

    @cached_property
    def u2(self) -> u2.Device:
        if self.is_over_http:
            # Using uiautomator2_http
            device = u2.connect(self.serial)
        else:
            # Normal uiautomator2
            if self.serial.startswith('emulator-') or self.serial.startswith('127.0.0.1:'):
                device = u2.connect_usb(self.serial)
            else:
                device = u2.connect(self.serial)

        # Stay alive
        device.set_new_command_timeout(604800)

        logger.attr('u2.Device', f'Device(atx_agent_url={device._get_atx_agent_url()})')
        return device



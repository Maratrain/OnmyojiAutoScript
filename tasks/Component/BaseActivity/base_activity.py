# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from collections.abc import Callable
from abc import abstractmethod

from module.logger import logger
from tasks.Component.GeneralBattle.general_battle import GeneralBattle


class BaseActivity(GeneralBattle):
    """活动任务共享行为(合并原版抽象基类与本地门票兜底逻辑)。"""

    @abstractmethod
    def run(self) -> None:
        pass

    @abstractmethod
    def home_main(self) -> bool:
        """从庭院到活动的爬塔界面"""
        pass

    @abstractmethod
    def main_home(self) -> bool:
        """从活动的爬塔界面到庭院"""
        pass

    @staticmethod
    def verify_zero_ticket(
        ticket_name: str,
        fallback_action: Callable[[], bool],
    ) -> bool:
        """门票 OCR 为零时执行一次真实入口操作确认门票是否耗尽。"""
        logger.warning(f'[活动] {ticket_name} OCR 结果为 0，尝试执行一次兜底入口操作')
        if fallback_action():
            logger.info(f'[活动] {ticket_name} 兜底操作成功')
            return True
        logger.info(f'[活动] {ticket_name} 确认已不可用')
        return False

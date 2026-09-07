from collections.abc import Callable

from module.logger import logger


class BaseActivity:
    """活动任务共享行为。"""

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

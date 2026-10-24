from time import sleep

from module.atom.image import RuleImage
from module.exception import GameStuckError
from module.logger import logger


class AudioDownloadPrompt:
    """式神音频下载弹窗处理, 供 SwitchSoul / SoulsTidy 等任务混入复用。"""

    I_AUDIO_DOWNLOAD_TITLE = RuleImage(
        roi_front=(536, 175, 292, 41), roi_back=(536, 175, 292, 41), threshold=0.85,
        method="Template matching", file="./tasks/SoulsTidy/simple/audio_download_title.png")
    I_AUDIO_DOWNLOAD_CANCEL = RuleImage(
        roi_front=(396, 479, 180, 64), roi_back=(396, 479, 180, 64), threshold=0.85,
        method="Template matching", file="./tasks/SoulsTidy/simple/audio_download_cancel.png")

    def dismiss_audio_download(self) -> bool:
        """取消式神音频下载弹窗, 最多 4 次尝试, 关不掉抛 GameStuckError。

        :return: 是否实际处理过弹窗。
        """
        for attempt in range(4):
            if not self.appear(self.I_AUDIO_DOWNLOAD_TITLE):
                return attempt > 0
            if attempt == 3 or not self.appear(self.I_AUDIO_DOWNLOAD_CANCEL):
                raise GameStuckError('[音频下载] 式神音频下载弹窗无法关闭')
            logger.info('[音频下载] 取消式神音频下载弹窗')
            self.click(self.I_AUDIO_DOWNLOAD_CANCEL)
            sleep(0.8)
            self.screenshot()

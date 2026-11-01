"""协同对弈单行 OCR：优先使用 PP-OCRv6-small 识别模型。

V6-small 只有识别模型、没有检测模型，Full/detect 规则继续走共享 OCR；
模型加载失败、识别异常或低分时一律回退共享 OCR，不影响任务推进。
"""

from module.logger import logger
from module.ocr.base_ocr import OcrMode


class DraftDuelV6OcrMixin:
    _v6_ocr_model = None

    def _load_v6_ocr(self):
        if self._v6_ocr_model is not None:
            return self._v6_ocr_model
        try:
            from tasks.DraftDuel.v6_rec import V6Rec

            self._v6_ocr_model = V6Rec()
            logger.info('[协同对弈] v6-small 识别模型已加载')
        except Exception as e:
            logger.warning(f'[协同对弈] v6 识别模型不可用，回退共享 OCR: {e}')
            self._v6_ocr_model = False
        return self._v6_ocr_model

    def _ocr_text(self, rule):
        """单行规则走 V6-small；Full 或加载失败时回退共享 OCR。"""
        mode = getattr(rule, 'mode', None)
        if mode not in (OcrMode.SINGLE, OcrMode.DIGIT, OcrMode.DIGITCOUNTER):
            return rule.ocr(self.device.image)

        model = self._load_v6_ocr()
        if not model:
            return rule.ocr(self.device.image)

        x, y, width, height = rule.roi
        if width <= 0 or height <= 0:
            return rule.ocr(self.device.image)
        crop = self.device.image[y:y + height, x:x + width]
        try:
            text, score = model.recognize_single(crop)
        except Exception as e:
            logger.warning(f'[协同对弈] v6 识别 {rule.name} 失败: {e}')
            return rule.ocr(self.device.image)

        text = text.strip()
        if score < 0.6 or not text:
            logger.warning(
                f'[协同对弈] v6 识别 {rule.name} 低分 {score:.3f}: [{text}]'
            )
            return rule.ocr(self.device.image)

        if mode == OcrMode.DIGIT:
            return rule.after_process(text)
        if mode == OcrMode.DIGITCOUNTER:
            return rule.ocr_str_digit_counter(rule.after_process(text))
        return rule.after_process(text)

"""读取记录页当前可见的完整记录行，以自选红/蓝徽标为锚点。"""
from copy import copy

import cv2


def read_record_rows(image, assets):
    # 只扫描自选方一列，排除对手列
    x0, y0, x1, y1 = 320, 145, 405, 625
    source = image[y0:y1, x0:x1]
    candidates = []
    for side, rule in (('LEFT', assets.I_FROG_LAST_SELECT_RED),
                       ('RIGHT', assets.I_FROG_LAST_SELECT_BLUE)):
        scores = cv2.matchTemplate(source, rule.image, cv2.TM_CCOEFF_NORMED)
        while scores.size:
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            if score <= rule.threshold:
                break
            candidates.append((y + y0, side, score))
            scores[max(0, y - 25):y + 26, :] = -1
    rows = []
    for y, side, score in sorted(candidates):
        if any(abs(y - other[0]) < 25 for other in candidates if other[1] != side):
            continue
        offset = y - assets.I_FROG_LAST_SELECT_RED.roi_front[1]
        # 上下边界处的残缺行直接忽略，避免混入别的记录
        if 154 + offset < 145 or 270 + offset > 625:
            continue
        def matches(rule):
            x, ry, w, h = rule.roi_back
            crop = image[ry + offset:ry + offset + h, x:x + w]
            return cv2.minMaxLoc(cv2.matchTemplate(crop, rule.image, cv2.TM_CCOEFF_NORMED))[1] > rule.threshold
        won, lost = matches(assets.I_FROG_LAST_WIN), matches(assets.I_FROG_LAST_LOSE)
        if won == lost:
            continue
        ocr = copy(assets.O_FROG_LAST_TIME)
        x, ry, w, h = ocr.roi
        ocr.roi = (x, ry + offset, w, h)
        ocr.area = ocr.roi
        stamp = str(ocr.ocr(image)).strip()
        rows.append((stamp, won, side))
    return rows

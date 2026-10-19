# This Python file uses the following encoding: utf-8
"""游戏 UI 改版后的资产体检工具。

用法（仓库自带 python）::

    ./toolkit/python.exe dev_tools/ui_change_audit.py --task WantedQuests --image log/temp/xxx/0.png
    ./toolkit/python.exe dev_tools/ui_change_audit.py --task Chess --dir log/temp/xxx --top 30
    ./toolkit/python.exe dev_tools/ui_change_audit.py --task Chess --dir log/temp/xxx --csv audit_chess.csv

说明:
  - 只读取任务的自动生成资产类（`tasks/<任务>/assets.py` 里的 `*Assets`），不改动任何业务代码。
  - 每张截图对每个规则给出相似度；同一规则在多张截图上取最高分，避免"这张图没走到那个界面"造成误判。
  - 判定列 FAIL 表示最高分仍低于该规则自身阈值，即改版后大概率失效，需要重采模板或调整 ROI。
  - OCR 规则依赖 OCR 服务，取不到时记为 ocr_error，不影响图片规则的输出。
"""

import argparse
import copy
import csv
import importlib
import inspect
import os
import sys
from pathlib import Path

# 屏蔽 OpenCV/libpng 的解码噪音, 体检输出只看结论
os.environ.setdefault('OPENCV_LOG_LEVEL', 'ERROR')
os.environ.setdefault('OPENCV_VIDEOIO_DEBUG', '0')

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from numpy import uint8, fromfile  # noqa: E402

try:
    cv2.setLogLevel(3)
except Exception:  # 老版本 OpenCV 没有该接口也不影响体检
    pass

from dev_tools.assets_test import match_image_detail, match_ocr_detail, load_image  # noqa: E402
from dev_tools.assets_test import _roi_to_text  # noqa: E402
from module.atom.image import RuleImage
from module.atom.ocr import RuleOcr
from module.logger import logger

IMAGE_SUFFIX = {'.png', '.jpg', '.jpeg', '.bmp'}


def collect_rules(task: str):
    """导入 tasks/<task>/assets.py 里的资产类，返回 (图片规则, OCR 规则)。"""
    module = importlib.import_module(f'tasks.{task}.assets')
    images, ocrs = [], []
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if not cls.__name__.endswith('Assets'):
            continue
        for name, value in vars(cls).items():
            if name.startswith('__'):
                continue
            if isinstance(value, RuleImage):
                images.append((name, value))
            elif isinstance(value, RuleOcr):
                ocrs.append((name, value))
    return images, ocrs


def list_images(image: str, directory: str):
    files = []
    if image:
        files.append(Path(image))
    if directory:
        files.extend(sorted(p for p in Path(directory).rglob('*') if p.suffix.lower() in IMAGE_SUFFIX))
    return files


def audit(task: str, files, with_ocr: bool = True):
    images, ocrs = collect_rules(task)
    files = list(files)
    logger.info(f'任务 {task}: 图片规则 {len(images)} 条, OCR 规则 {len(ocrs)} 条, 截图 {len(files)} 张')

    # 截图只解码一次, 后续所有规则复用
    loaded = []
    for file in files:
        img = load_image(str(file), strict_size=False)
        if img is None:
            logger.warning(f'跳过无法读取的截图: {file}')
            continue
        loaded.append((file, img))

    rows = []
    for name, rule in images:
        template = Path(rule.file) if getattr(rule, 'file', '') else None
        if template is not None and not template.exists():
            rows.append({
                'type': 'image', 'name': name, 'threshold': float(getattr(rule, 'threshold', 0.8) or 0.0),
                'score': 0.0, 'status': 'MISSING', 'message': 'template_file_not_found', 'file': '',
                'roi_front': _roi_to_text(rule.roi_front), 'roi_back': _roi_to_text(rule.roi_back),
                'template': template.name,
            })
            continue
        best = {'similarity': -1.0, 'message': 'no_image', 'roiFront': '', 'roiBack': '', 'file': ''}
        for file, img in loaded:
            try:
                result = match_image_detail(img, copy.deepcopy(rule))
            except Exception as e:  # 单张图异常不中断整轮体检
                result = {'similarity': -1.0, 'message': f'exception:{e}', 'roiFront': '', 'roiBack': ''}
            score = result['similarity']
            if score != score:  # NaN: roi 内像素恒定, 匹配结果无意义
                result = dict(result, similarity=0.0, message='nan_score')
            if result['similarity'] > best['similarity']:
                best = dict(result, file=file.name)
        threshold = float(getattr(rule, 'threshold', 0.8) or 0.0)
        score = best['similarity'] if best['similarity'] >= 0 else 0.0
        rows.append({
            'type': 'image',
            'name': name,
            'threshold': threshold,
            'score': round(score, 4),
            'status': 'FAIL' if score < threshold else 'OK',
            'message': best['message'],
            'file': best['file'],
            'roi_front': best['roiFront'],
            'roi_back': best['roiBack'],
            'template': Path(rule.file).name if getattr(rule, 'file', '') else '',
        })

    if with_ocr:
        for name, rule in ocrs:
            best = {'similarity': -1.0, 'message': 'no_image', 'text': '', 'file': ''}
            for file, img in loaded:
                try:
                    result = match_ocr_detail(img, copy.deepcopy(rule))
                except Exception as e:
                    result = {'similarity': -1.0, 'message': f'ocr_error:{e}', 'text': ''}
                if result['similarity'] > best['similarity']:
                    best = dict(result, file=file.name)
            score = best['similarity'] if best['similarity'] >= 0 else 0.0
            rows.append({
                'type': 'ocr',
                'name': name,
                'threshold': '',
                'score': round(score, 4),
                'status': 'CHECK' if score <= 0 else 'OK',
                'message': best['message'],
                'file': best['file'],
                'roi_front': best['roiFront'] if 'roiFront' in best else '',
                'roi_back': best['roiBack'] if 'roiBack' in best else '',
                'template': best['text'],
            })

    return rows


def audit_templates(files, template_dir: str, threshold: float = 0.8):
    """对不走 RuleImage 的模板目录（百鬼棋局徽章/卡面等）做全图匹配体检。

    这类资产由代码按名字直接读文件匹配, assets.py 里没有对应规则,
    只能用模板在整张截图上滑动求最高分来判断改版后是否还认得出。
    """
    templates = sorted(p for p in Path(template_dir).rglob('*') if p.suffix.lower() in IMAGE_SUFFIX)
    logger.info(f'模板目录 {template_dir}: {len(templates)} 张模板, 截图 {len(files)} 张')

    loaded = []
    for file in files:
        img = load_image(str(file), strict_size=False)
        if img is None:
            continue
        loaded.append((file, cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)))

    rows = []
    for template in templates:
        mat = cv2.imdecode(fromfile(str(template), dtype=uint8), -1)
        if mat is None:
            rows.append({'type': 'template', 'name': template.name, 'threshold': threshold, 'score': 0.0,
                         'status': 'MISSING', 'message': 'decode_failed', 'file': '',
                         'roi_front': '', 'roi_back': '', 'template': str(template)})
            continue
        tpl = cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY) if mat.ndim == 3 else mat
        best_val, best_file = 0.0, ''
        for file, gray in loaded:
            if gray.shape[0] < tpl.shape[0] or gray.shape[1] < tpl.shape[1]:
                continue
            res = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val, best_file = float(max_val), file.name
        rows.append({
            'type': 'template', 'name': template.stem, 'threshold': threshold, 'score': round(best_val, 4),
            'status': 'FAIL' if best_val < threshold else 'OK', 'message': 'full_image_match', 'file': best_file,
            'roi_front': '', 'roi_back': '', 'template': str(template),
        })
    return rows


def print_rows(rows, top: int):
    rows = sorted(rows, key=lambda r: (r['status'] not in ('FAIL', 'MISSING'), r['status'] != 'CHECK', r['score']))
    if top:
        rows = rows[:top]
    logger.info(f"{'状态':<6}{'类型':<6}{'规则名':<38}{'阈值':<6}{'最高分':<9}说明")
    for r in rows:
        logger.info(
            f"{r['status']:<6}{r['type']:<6}{r['name']:<38}{str(r['threshold']):<6}{r['score']:<9}"
            f"{r['message']} @{r['file']}"
        )


def write_csv(rows, csv_path: str):
    fieldnames = ['type', 'name', 'status', 'threshold', 'score', 'message', 'file', 'roi_front', 'roi_back', 'template']
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, '') for k in fieldnames})
    logger.info(f'已写出 {csv_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='游戏 UI 改版后的资产体检')
    parser.add_argument('--task', default='', help='任务目录名, 例如 WantedQuests / Chess')
    parser.add_argument('--image', default='', help='单张截图路径')
    parser.add_argument('--dir', default='', help='截图目录, 递归查找')
    parser.add_argument('--top', type=int, default=0, help='只打印前 N 条, 0 表示全部')
    parser.add_argument('--csv', default='', help='结果写出 csv 路径')
    parser.add_argument('--no-ocr', action='store_true', help='跳过 OCR 规则')
    parser.add_argument('--templates', default='',
                        help='模板目录(不走 RuleImage 的资产, 如 tasks/Chess/badge), 对该目录下每张模板做全图匹配')
    parser.add_argument('--threshold', type=float, default=0.8, help='--templates 模式下的判定阈值, 默认 0.8')
    args = parser.parse_args()

    files = list_images(args.image, args.dir)
    if not files:
        raise SystemExit('没有可用的截图, 请传 --image 或 --dir')

    if args.templates:
        rows = audit_templates(files, args.templates, args.threshold)
    else:
        if not args.task:
            raise SystemExit('缺少 --task')
        rows = audit(args.task, files, with_ocr=not args.no_ocr)
    print_rows(rows, args.top)
    if args.csv:
        write_csv(rows, args.csv)

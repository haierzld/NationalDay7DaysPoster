# -*- coding: utf-8 -*-
"""平台水印检测与清除（豆包 / 即梦等角标水印）。

用法：
  python scripts/nd7.py wm --image "outputs/day1_安溪.png" --detect
  python scripts/nd7.py wm --image "outputs/day*_安溪.png"            # 自动定位并清除
  python scripts/nd7.py wm --image "outputs/day1.png" --box 0.62,0.965,0.34,0.022   # 手动指定区域(比例)
  python scripts/nd7.py wm --image "outputs/day1.png" --suffix ""     # 直接覆盖原图

原理：在四角外缘区域找「浅色小字」连通块 → 生成掩码 → cv2.inpaint 用邻域背景重建。
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import cv2  # noqa: E402
import numpy as np  # noqa: E402

# 豆包 / 即梦角标经验区域（相对比例 x,y,w,h）：右下角最底部一条
# 只清框内「亮于背景」的像素，因此框给宽一点只会更保险，不会糊掉背景纹理
DEFAULT_WM_BOX = "0.80,0.962,0.20,0.036"

# 四角候选区：(取宽比例, 取高比例, 是否靠右, 是否靠下)
CORNERS = [
    ("bottom-full", 1.00, 0.10, False, True),
    ("bottom-right", 0.50, 0.12, True, True),
    ("bottom-left", 0.50, 0.12, False, True),
    ("top-right", 0.50, 0.12, True, False),
    ("top-left", 0.50, 0.12, False, False),
]


def _region(img: np.ndarray, fw: float, fh: float, right: bool, down: bool):
    H, W = img.shape[:2]
    w, h = max(int(W * fw), 8), max(int(H * fh), 8)
    x = W - w if right else 0
    y = H - h if down else 0
    return img[y:y + h, x:x + w], (x, y, w, h)


def detect(img: np.ndarray) -> list[dict]:
    """检测四角外缘的浅色小字块，返回候选（含置信度与相对坐标）。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    hits: list[dict] = []

    for name, fw, fh, right, down in CORNERS:
        reg, (ox, oy, rw, rh) = _region(gray, fw, fh, right, down)
        if reg.size == 0:
            continue
        med = float(np.median(reg))
        thr = max(med + 22, 120)
        mask = (reg > thr).astype(np.uint8) * 255
        # 太亮的整块区域（大面积金色/白底）视为背景，不作水印
        if mask.mean() > 140:
            continue
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
        n, labels, stats, cent = cv2.connectedComponentsWithStats(mask, 8)
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < 60:
                continue
            rx, ry = w / rw, h / rh           # 相对候选区
            ar = w / max(h, 1)                # 长宽比：横排小字
            if not (0.02 <= rx <= 0.9 and 0.004 <= ry <= 0.5):
                continue
            if not (1.2 <= ar <= 40):
                continue
            if h < 6 or w < 20:
                continue
            # 相对全图的 bbox
            bx, by = (ox + x) / W, (oy + y) / H
            bw, bh = w / W, h / H
            # 只保留贴近边缘的（距边 ≤ 12%）
            edge_x = min(bx, 1 - (bx + bw))
            edge_y = min(by, 1 - (by + bh))
            if edge_x > 0.12 or edge_y > 0.12:
                continue
            hits.append({
                "corner": name, "box": [round(bx, 4), round(by, 4), round(bw, 4), round(bh, 4)],
                "area": int(area), "ratio": round(ar, 2), "score": round(float(area) / (rw * rh) * 100, 3),
            })
    hits.sort(key=lambda d: -d["area"])
    return hits


def _expand(box, W: int, H: int, pad: int = 4):
    x = int(box[0] * W); y = int(box[1] * H)
    w = int(box[2] * W); h = int(box[3] * H)
    x = max(0, x - pad); y = max(0, y - pad)
    w = min(W - x, w + pad * 2); h = min(H - y, h + pad * 2)
    return x, y, w, h


def remove(img: np.ndarray, boxes: list[list[float]], pad: int = 4,
           text_only: bool = True) -> np.ndarray:
    """清除指定区域内的水印。

    text_only=True（默认）：框内只把「比背景亮的像素」当水印，尽量不糊掉背景纹理；
    text_only=False：整块矩形 inpaint。
    """
    H, W = img.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if text_only else None
    for b in boxes:
        x, y, w, h = _expand(b, W, H, pad)
        if text_only:
            reg = gray[y:y + h, x:x + w]
            if not reg.size:
                continue
            thr = max(float(np.median(reg)) + 22, 120)
            mask[y:y + h, x:x + w] = (reg > thr).astype(np.uint8) * 255
        else:
            mask[y:y + h, x:x + w] = 255
    if not mask.any():
        return img
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
    out = cv2.inpaint(img, mask, 6, cv2.INPAINT_TELEA)
    if out is None or out.size == 0:  # 兜底：邻域中值填充
        out = img.copy()
        out[mask > 0] = cv2.medianBlur(img, 5)[mask > 0]
    return out


def run(args: argparse.Namespace) -> int:
    files: list[Path] = []
    for pat in args.image:
        files += [Path(f) for f in glob.glob(pat, recursive=True)]
    if not files:
        print("没有匹配的图片")
        return 1

    ok = 0
    for f in files:
        img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print(f"读取失败：{f}")
            continue
        H, W = img.shape[:2]

        if args.detect:
            hits = detect(img)
            print(f"\n{f.name}  ({W}x{H})")
            if not hits:
                print("  未检测到角标水印候选")
            for i, h in enumerate(hits[:6], 1):
                b = h["box"]
                print(f"  [{h['corner']}] box={[float(v) for v in b]}  "
                      f"像素={h['area']}  长宽比={h['ratio']}  占比={h['score']}%")
                if args.dump_dir:
                    x, y, w, hh = _expand(b, W, H, pad=6)
                    crop = img[y:y + hh, x:x + w]
                    if crop.size:
                        crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                        d = Path(args.dump_dir)
                        d.mkdir(parents=True, exist_ok=True)
                        cv2.imencode(".png", crop)[1].tofile(str(d / f"{f.stem}_cand{i}.png"))
            if args.dump_dir and hits:
                print(f"  候选裁剪图已存到：{args.dump_dir}")
            continue

        db = args.default_box or DEFAULT_WM_BOX
        boxes: list[list[float]] = []
        if args.box:
            boxes.append([float(v) for v in args.box.split(",")])
        elif args.force:
            boxes.append([float(v) for v in db.split(",")])
        else:
            hits = detect(img)
            if hits:
                boxes.append(hits[0]["box"])
            boxes.append([float(v) for v in db.split(",")])  # 检测结果之外再并经验区域，防漏半个字
        if not boxes:
            print(f"{f.name}：未检测到水印，跳过（可用 --box x,y,w,h 指定）")
            continue

        out = remove(img, boxes, pad=args.pad, text_only=not args.block)
        if args.inplace:
            dest = f
        else:
            dest = f.with_name(f.stem + args.suffix + f.suffix)
        cv2.imencode(dest.suffix, out)[1].tofile(str(dest))
        print(f"  已清除水印：{dest}   区域={[ [round(v,3) for v in b] for b in boxes ]}")
        ok += 1
    return 0 if ok else 1


def build_parser(ap: argparse.ArgumentParser) -> argparse.ArgumentParser:
    ap.add_argument("--image", action="append", required=True, help="图片路径，支持通配符，可重复传入")
    ap.add_argument("--detect", action="store_true", help="只检测并打印候选区域")
    ap.add_argument("--box", default=None, help="手动指定水印区域（相对比例 x,y,w,h）")
    ap.add_argument("--default-box", default=None, help="检测不到时使用的兜底区域（相对比例）")
    ap.add_argument("--pad", type=int, default=4, help="掩码外扩像素")
    ap.add_argument("--dump-dir", default=None, help="detect 时把候选区域裁剪放大存到该目录")
    ap.add_argument("--suffix", default="_clean", help="输出文件名后缀")
    ap.add_argument("--inplace", action="store_true", help="直接覆盖原图")
    ap.add_argument("--block", action="store_true", help="整块矩形修复（默认只修复框内亮字像素）")
    ap.add_argument("--force", action="store_true", help="跳过检测，直接用 --default-box 区域清除")
    return ap


if __name__ == "__main__":
    p = build_parser(argparse.ArgumentParser(description="水印检测与清除"))
    raise SystemExit(run(p.parse_args()))

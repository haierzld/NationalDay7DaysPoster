"""把 outputs 里的成图整理成 README 用的示例图（JPG，默认长边 900）。

一个主体一套 7 张，放到 examples/<name>/day01.jpg … day07.jpg：

    python scripts/make_examples.py --out examples/national --src "outputs/day?_中国.png"
    python scripts/make_examples.py --out examples/shanghai --src "outputs/day?_上海.png"
    python scripts/make_examples.py --out examples/cqu      --src "outputs/day?_重庆大学.png"

也可以逐个文件指定（顺序无关，按文件名里的 day 号归位）：

    python scripts/make_examples.py --out examples/national \
      --src outputs/day1_中国.png examples/_old/day02.jpg ...

旧图默认移进 examples/<name>/_old/ 而不是删除。
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY_RE = re.compile(r"day\s*0*(\d)")


def pick_days(patterns: list[str]) -> dict[int, str]:
    """把 glob/文件列表按 day 号归位，后出现的覆盖先出现的。"""
    found: dict[int, str] = {}
    for pat in patterns:
        candidates = glob.glob(pat, recursive=True) if any(c in pat for c in "*?[") else [pat]
        for f in sorted(candidates):
            m = DAY_RE.search(os.path.basename(f))
            if not m:
                print("跳过（文件名里没有 day 号）：", f)
                continue
            day = int(m.group(1))
            if not 1 <= day <= 7:
                continue
            found[day] = f
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="示例目录，如 examples/cqu")
    ap.add_argument("--src", nargs="+", required=True, help="源文件或 glob，可给多个")
    ap.add_argument("--long-edge", type=int, default=900, help="JPG 长边像素，默认 900")
    ap.add_argument("--quality", type=int, default=86, help="JPG 质量，默认 86")
    ap.add_argument("--keep-old", action="store_true", help="不归档已存在的示例图")
    a = ap.parse_args()

    out_dir = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    os.makedirs(out_dir, exist_ok=True)

    days = pick_days(a.src)
    missing = [d for d in range(1, 8) if d not in days]
    if not days:
        print("没有找到任何源文件，检查 --src 路径")
        return 2

    if not a.keep_old:
        olds = sorted(glob.glob(os.path.join(out_dir, "day0*.jpg")))
        if olds:
            old_dir = os.path.join(out_dir, "_old")
            os.makedirs(old_dir, exist_ok=True)
            for f in olds:
                shutil.move(f, os.path.join(old_dir, os.path.basename(f)))
            print(f"归档 {len(olds)} 张旧示例 → {os.path.relpath(old_dir, ROOT)}")

    n = 0
    for day in range(1, 8):
        src = days.get(day)
        if not src:
            print(f"缺失：day{day}")
            continue
        if not os.path.isabs(src):
            src = os.path.join(ROOT, src)
        im = cv2.imdecode(np.fromfile(src, np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            print("读取失败：", src)
            continue
        h, w = im.shape[:2]
        scale = a.long_edge / max(h, w)
        if abs(scale - 1) > 0.01:
            interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
            im = cv2.resize(im, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=interp)
        dst = os.path.join(out_dir, f"day{day:02d}.jpg")
        cv2.imencode(".jpg", im, [int(cv2.IMWRITE_JPEG_QUALITY), a.quality])[1].tofile(dst)
        print(f"day{day:02d}  ← {os.path.relpath(src, ROOT)}  {im.shape[1]}x{im.shape[0]}  "
              f"{os.path.getsize(dst) // 1024} KB")
        n += 1

    print(f"完成 {n}/7 张 → {os.path.relpath(out_dir, ROOT)}")
    if missing:
        print("注意，以下日期没有源图：", ", ".join(f"day{d}" for d in missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""把评分达标的实景照片直接排进红金海报（不再交给模型参考生成）。

用途：某个栏目抓到的网图评分足够好（题材对得上、够大够清晰、来源可靠）时，
直接用这张实景照片填进画框——位置由 config/frames.json 的几何坐标精确决定，
不需要模型再“参考生成”。同一份版式定义也供 `prompt` / `gen` 用文字描述模型出图。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from overlay import load_font, text_w          # noqa: E402
from prompt_builder import day_events, load_events, signature_lines  # noqa: E402
from generate_browser import _keywords, _match_slug, _score_item  # noqa: E402

FRAMES = json.loads((ROOT / "config" / "frames.json").read_text(encoding="utf-8"))
GOLD = (207, 170, 96)
GOLD_LIGHT = (240, 216, 150)
DARK = (72, 10, 15)


# ---------- 版式 ----------

def day_layouts(day: int) -> dict:
    return FRAMES["days"][str(day)]["layouts"]


def day_default_layout(day: int) -> str:
    return FRAMES["days"][str(day)]["default"]


def pick_layout(day: int, key: str | None = None) -> tuple[str, dict]:
    lays = day_layouts(day)
    key = key or day_default_layout(day)
    if key not in lays:
        raise SystemExit(
            f"第 {day} 天没有版式“{key}”，可选：{'、'.join(lays)}（可用 --list-layouts 查看）")
    return key, lays[key]


def list_layouts(day: int | None = None) -> None:
    for d in range(1, 8) if day is None else [day]:
        lays = day_layouts(d)
        print(f"Day {d}（{len(lays)} 种，默认 {day_default_layout(d)}）")
        for k, v in lays.items():
            shapes = sorted({s["shape"] for s in v["slots"]})
            print(f"  {k:<20} {v['name']}　{len(v['slots'])} 框 / {'、'.join(shapes)}")


# ---------- 选图：每个画框一张最贴合的实景照片 ----------

def pick_photos(subject: str, events: list[dict], min_score: float = 5.0,
                allow_people: bool = False) -> list[dict]:
    """按画框逐一挑分最高的那张图；不达线或人物场景的画框留空（由 caller 画占位金框）。

    素材库里标了 "people": true 的画框（非遗表演、市井人等）画面主体是人，
    默认不直接采用实拍网图——合规要求不出现可识别的真实人物面部；
    确需使用时加 --allow-people（仍会对能检测到的人脸做模糊）。
    """
    base = ROOT / "assets" / subject
    idx_path = base / "_refs.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}

    out: list[dict] = []
    people_skipped: list[str] = []
    for ev in events:
        slug = _match_slug(ev, idx)
        if ev.get("people") and not allow_people:
            people_skipped.append(ev.get("title", ""))
            out.append({"path": None, "score": None, "title": "", "slug": slug,
                        "event": ev.get("title", "")})
            continue
        kws = _keywords(ev)
        best: dict | None = None
        for it in (idx.get(slug) or {}).get("items", []):
            fp = Path(it.get("file") or "")
            p = fp if fp.is_absolute() else (ROOT / fp)
            if not p.exists():
                continue
            sc = _score_item(it, kws)
            if best is None or sc > best["score"]:
                best = {"path": p, "score": sc, "title": it.get("title", ""), "slug": slug}
        if best and best["score"] >= min_score:
            best["event"] = ev.get("title", "")
            out.append(best)
        else:
            out.append({"path": None, "score": best["score"] if best else None,
                        "title": "", "slug": slug, "event": ev.get("title", "")})
    if people_skipped:
        print(f"  人物场景题材不采用实拍照片（{len(people_skipped)} 个）：{'、'.join(people_skipped)}"
              f"（合规：避免出现可识别的人物面部；需要时加 --allow-people）")
    return out


# ---------- 形状 ----------

def shape_mask(w: int, h: int, shape: str, rotate: float = 0.0) -> tuple[Image.Image, int]:
    """生成画框形状的遮罩（255=框内）与所用画布边长。

    形状按 w×h 居中画在 side×side 画布上：带旋转的框（如六花瓣）不会被裁掉，
    调用方用同一个 side 准备图片，再按槽位中心对齐贴图。
    """
    side = int(math.hypot(w, h) * 1.06) + 2
    m = Image.new("L", (side, side), 0)
    d = ImageDraw.Draw(m)
    x0, y0 = (side - w) // 2, (side - h) // 2
    x1, y1 = x0 + w, y0 + h
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    if shape in ("rect", "bar"):
        r = int(min(w, h) * (0.42 if shape == "bar" else 0.08))
        d.rounded_rectangle([x0, y0, x1, y1], radius=min(r, min(w, h) // 2), fill=255)
    elif shape == "arch":
        d.pieslice([x0, y0, x1, y0 + w], 180, 360, fill=255)
        d.rectangle([x0, y0 + w / 2, x1, y1], fill=255)
    elif shape == "triangle-up":
        d.polygon([(cx, y0), (x1, y1), (x0, y1)], fill=255)
    elif shape == "triangle-down":
        d.polygon([(x0, y0), (x1, y0), (cx, y1)], fill=255)
    elif shape == "diamond":
        d.polygon([(cx, y0), (x1, cy), (cx, y1), (x0, cy)], fill=255)
    elif shape in ("star5", "pentagon", "hexagon"):
        pts = []
        if shape == "star5":
            R, r = min(w, h) / 2, min(w, h) / 2 * 0.382
            for k in range(10):
                a = math.radians(-90 + k * 36)
                rad = R if k % 2 == 0 else r
                pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
        else:
            n = 5 if shape == "pentagon" else 6
            rx, ry = w / 2, h / 2
            for k in range(n):
                a = math.radians(-90 + k * 360 / n)
                pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        d.polygon(pts, fill=255)
    elif shape == "petal":
        d.pieslice([x0, cy - h * 0.12, x1, cy + h * 0.62], 0, 180, fill=255)

        def bez(p0, p1, p2, steps=24):
            out = []
            for i in range(steps + 1):
                t = i / steps
                out.append((
                    (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1],
                ))
            return out

        right = bez((cx, y0), (x1, y0 + h * 0.08), (x1, cy))
        left = bez((x0, cy), (x0, y0 + h * 0.08), (cx, y0))
        d.polygon(right + left, fill=255)
    else:  # 兜底按矩形处理，保证不会什么都画不出来
        d.rounded_rectangle([x0, y0, x1, y1], radius=int(min(w, h) * 0.08), fill=255)

    if rotate:
        m = m.rotate(rotate, resample=Image.BICUBIC, center=(side / 2, side / 2))
    return m, side


def _outline(mask: Image.Image, width: int = 3) -> Image.Image:
    """取遮罩边缘的一圈描边。"""
    er = mask
    for _ in range(max(1, width // 2)):
        er = er.filter(ImageFilter.MinFilter(3))
    return ImageChops.subtract(mask, er)


def _star_points(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """正五角星的 10 个顶点（第 1 个顶点朝上）。"""
    return [(cx + (r if k % 2 == 0 else r * 0.382) * math.cos(math.radians(-90 + k * 36)),
             cy + (r if k % 2 == 0 else r * 0.382) * math.sin(math.radians(-90 + k * 36)))
            for k in range(10)]


_FACE_MODELS = None


def _face_boxes(path: Path) -> list[tuple[int, int, int, int]]:
    """检测照片里的人脸框（正脸 + 侧脸）。没有 cv2 时返回空列表，不阻断流程。"""
    global _FACE_MODELS
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    try:
        if _FACE_MODELS is None:
            models = []
            for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
                xml = Path(cv2.data.haarcascades) / name
                if xml.exists():
                    c = cv2.CascadeClassifier(str(xml))
                    if not c.empty():
                        models.append(c)
            _FACE_MODELS = models
        if not _FACE_MODELS:
            return []
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return []
        h, w = img.shape[:2]
        min_side = max(20, int(w * 0.03))
        boxes = []
        flipped = cv2.flip(img, 1)
        for c in _FACE_MODELS:
            for x, y, bw, bh in c.detectMultiScale(img, 1.1, 5, minSize=(min_side, min_side)):
                boxes.append((int(x), int(y), int(bw), int(bh)))
            # 侧脸模型只认朝一个方向的侧脸，镜像后再检一遍提高召回
            for x, y, bw, bh in c.detectMultiScale(flipped, 1.1, 5, minSize=(min_side, min_side)):
                boxes.append((int(w - x - bw), int(y), int(bw), int(bh)))
        return boxes
    except Exception:
        return []


def blur_faces(im: Image.Image, path: Path) -> tuple[Image.Image, int]:
    """把照片里的人脸区域模糊掉。

    网图直接当画面主体用时，可识别的人物面部会踩到合规红线（与模型出图同样的约束）；
    模糊人脸既保住真实素材，又不出现可识别人物。返回（处理后的图, 模糊了几处）。
    """
    boxes = _face_boxes(path)
    for x, y, w, h in boxes:
        pad = int(w * 0.22)
        box = (max(0, x - pad), max(0, y - pad),
               min(im.width, x + w + pad), min(im.height, y + h + pad))
        if box[2] - box[0] < 4 or box[3] - box[1] < 4:
            continue
        im.paste(im.crop(box).filter(ImageFilter.GaussianBlur(radius=max(8.0, w * 0.16))), box)
    return im, len(boxes)


# ---------- 背景 ----------

def _vgrad(w: int, h: int, stops: list[tuple[float, tuple[int, int, int]]]) -> Image.Image:
    im = Image.new("RGB", (1, h))
    px = im.load()
    for y in range(h):
        t = y / max(1, h - 1)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t0 <= t <= t1:
                k = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                px[0, y] = tuple(int(c0[j] + (c1[j] - c0[j]) * k) for j in range(3))
                break
    return im.resize((w, h), Image.BICUBIC)


def draw_background(w: int, h: int) -> Image.Image:
    bg = _vgrad(w, h, [(0.0, (76, 10, 16)), (0.42, (128, 22, 30)),
                       (0.78, (104, 16, 24)), (1.0, (66, 8, 13))])

    # 顶部放射金光
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = w / 2, h * 0.10
    r_out = h * 0.62
    for k in range(48):
        a0 = math.radians(k * 7.5 - 3.2)
        a1 = math.radians(k * 7.5 + 3.2)
        gd.polygon([(cx, cy),
                    (cx + r_out * math.cos(a0), cy + r_out * math.sin(a0)),
                    (cx + r_out * math.cos(a1), cy + r_out * math.sin(a1))],
                   fill=(214, 176, 100, 12))
    bg = Image.alpha_composite(bg.convert("RGBA"), glow)

    # 左上角金星（一大四小）与金色撒点：让照片直排版也有国庆庆典感
    d = ImageDraw.Draw(bg, "RGBA")
    R = w * 0.040
    d.polygon(_star_points(w * 0.112, h * 0.046, R), fill=(*GOLD_LIGHT, 240))
    for cx, cy in ((w * 0.180, h * 0.026), (w * 0.226, h * 0.048),
                   (w * 0.226, h * 0.074), (w * 0.180, h * 0.096)):
        d.polygon(_star_points(cx, cy, R * 0.32), fill=(*GOLD_LIGHT, 228))
    rnd = random.Random(20261001)
    for _ in range(220):
        x, y = rnd.uniform(0, w), rnd.uniform(h * 0.02, h)
        r = rnd.uniform(w * 0.0012, w * 0.0034)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(242, 220, 156, rnd.randint(16, 64)))

    # 内框双金线 + 四角饰
    d = ImageDraw.Draw(bg, "RGBA")
    m1, m2 = int(w * 0.035), int(w * 0.052)
    d.rectangle([m1, m1, w - m1, h - m1], outline=(*GOLD, 200), width=max(2, w // 480))
    d.rectangle([m2, m2, w - m2, h - m2], outline=(*GOLD, 110), width=max(1, w // 900))
    corner = int(w * 0.075)
    for px, py, sx, sy in ((m1, m1, 1, 1), (w - m1, m1, -1, 1), (m1, h - m1, 1, -1), (w - m1, h - m1, -1, -1)):
        d.line([(px + sx * corner, py), (px, py), (px, py + sy * corner)],
               fill=(*GOLD_LIGHT, 220), width=max(2, w // 380))
    return bg          # RGBA：底座上的绸缎、标题、落款都要用半透明叠加


def draw_podium(im: Image.Image) -> None:
    """底部红色绸缎波浪 + 卷草纹金线。"""
    w, h = im.size
    d = ImageDraw.Draw(im, "RGBA")
    base_y = h * 0.905
    for layer, (amp, col, lw) in enumerate(((h * 0.030, (150, 26, 32), 3),
                                            (h * 0.022, (176, 34, 38), 2),
                                            (h * 0.014, (196, 44, 46), 2))):
        pts = []
        for x in range(0, w + 8, 8):
            t = x / w * math.pi * 2
            y = base_y + layer * h * 0.022 + amp * math.sin(t * 1.6 + layer) + amp * 0.35 * math.sin(t * 3.1)
            pts.append((x, y))
        d.polygon(pts + [(w, h), (0, h)], fill=(*col, 235))
        d.line(pts, fill=(*GOLD, 150), width=lw)


def draw_title(im: Image.Image, title: str, subtitle: str = "国庆祝福") -> None:
    w, h = im.size
    d = ImageDraw.Draw(im, "RGBA")
    fs = max(int(w * 0.052), 24)
    font = load_font(fs)
    y = h * 0.105
    tw = text_w(d, title, font)
    x = (w - tw) / 2
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2)):
        d.text((x + dx, y + dy), title, font=font, fill=(*DARK, 210))
    d.text((x, y), title, font=font, fill=(*GOLD_LIGHT, 255))

    # 标题上下两条金线 + 中间小星
    lw = max(2, w // 500)
    line_y = y + fs * 1.28
    gap = w * 0.055
    d.line([(x - gap, line_y), (x + tw + gap, line_y)], fill=(*GOLD, 180), width=lw)
    d.line([(x - gap * 0.55, line_y + fs * 0.16), (x + tw + gap * 0.55, line_y + fs * 0.16)],
           fill=(*GOLD, 110), width=max(1, lw // 2))
    star = Image.new("RGBA", (int(fs * 0.9), int(fs * 0.9)), (0, 0, 0, 0))
    ImageDraw.Draw(star).polygon(
        [(star.size[0] / 2 + star.size[0] / 2 * 0.588 * math.cos(math.radians(-90 + k * 72)),
          star.size[1] / 2 + star.size[1] / 2 * 0.588 * math.sin(math.radians(-90 + k * 72)))
         for k in range(5)], fill=(*GOLD_LIGHT, 230))
    im.paste(star, (int((w - star.size[0]) / 2), int(y - fs * 0.62)), star)

    fs2 = max(int(fs * 0.36), 14)
    f2 = load_font(fs2)
    t2 = subtitle
    d.text(((w - text_w(d, t2, f2)) / 2, line_y + fs * 0.42), t2, font=f2, fill=(245, 240, 232, 220))


def draw_signature(im: Image.Image, lines: list[str]) -> None:
    w, h = im.size
    d = ImageDraw.Draw(im, "RGBA")
    fs = max(int(w * 0.026), 16)
    font = load_font(fs)
    total = len(lines) * fs * 1.5
    y = h * 0.938 - total / 2
    for t in lines:
        d.text(((w - text_w(d, t, font)) / 2, y), t, font=font, fill=(*GOLD, 235))
        y += fs * 1.5


# ---------- 合成 ----------

def compose_day(day: int, subject: str | None = None, layout_key: str | None = None,
                min_score: float = 5.0, out_dir: Path | None = None,
                size: tuple[int, int] | None = None, photos: list[dict] | None = None,
                subtitle: str = "国庆祝福", events_file: str | None = None,
                allow_people: bool = False) -> Path:
    data = load_events(events_file, subject)
    subj = data.get("subject") or subject or "中国"
    events = day_events(data, day)
    key, lay = pick_layout(day, layout_key)
    slots = lay["slots"]
    if len(slots) != day:
        print(f"  ⚠ 版式 {key} 有 {len(slots)} 个框，与 Day {day} 的栏目数不一致")

    cv = FRAMES["canvas"]
    W, H = size or (int(cv["w"]), int(cv["h"]))

    if photos is None:
        photos = pick_photos(subj, events, min_score, allow_people)

    # 几何画框 ----
    im = draw_background(W, H)

    # 星座连线（如北斗七星）先画，避免压在照片上
    if lay.get("link"):
        d0 = ImageDraw.Draw(im, "RGBA")
        for a, b in zip(lay["link"], lay["link"][1:]):
            if b == 0:
                continue
            sa, sb = slots[a], slots[b]
            p1 = ((sa["x"] + sa["w"] / 2) * W, (sa["y"] + sa["h"] / 2) * H)
            p2 = ((sb["x"] + sb["w"] / 2) * W, (sb["y"] + sb["h"] / 2) * H)
            d0.line([p1, p2], fill=(*GOLD, 90), width=max(1, W // 700))

    used: list[str] = []
    missing: list[str] = []
    faced = 0
    for i, s in enumerate(slots):
        bw, bh = int(s["w"] * W), int(s["h"] * H)
        mask, side = shape_mask(bw, bh, s.get("shape", "rect"), float(s.get("rotate", 0)))
        ox = int(s["x"] * W + (bw - side) / 2)
        oy = int(s["y"] * H + (bh - side) / 2)
        ph = photos[i] if i < len(photos) else None

        tile = None
        if ph and ph.get("path"):
            src = Path(ph["path"])
            if src.exists():
                try:
                    im0 = Image.open(src).convert("RGB")
                    tile = ImageOps.fit(im0, (side, side), Image.LANCZOS, centering=(0.5, 0.5))
                    tile, n_face = blur_faces(tile, src)
                    faced += n_face
                    used.append(f"{i + 1}. {ph['event']} → {src.name}（{ph['score']:.1f} 分"
                                + ("，优秀·直接采用" if ph["score"] >= 9 else "")
                                + (f"，已模糊 {n_face} 处人脸" if n_face else "") + "）")
                except Exception as e:  # 坏图按无图处理
                    print(f"  ⚠ 图片无法读取，改画空框：{src.name}（{e}）")
        if tile is None:
            tile = _vgrad(side, side, [(0.0, (112, 18, 24)), (1.0, (64, 8, 14))])
            gd = ImageDraw.Draw(tile, "RGBA")
            for k in range(10):
                x = side * (k + 0.5) / 10
                gd.line([(x, 0), (x - side * 0.25, side)], fill=(214, 176, 100, 18), width=2)
            used.append(f"{i + 1}. {events[i].get('title', '')} → 未找到达标实景图，画金色留空框")
            missing.append(events[i].get("title", ""))

        im.paste(tile, (ox, oy), mask)
        # 金色描边：内圈实心金 + 外圈半透明金（做出浮雕卷草的立体感）
        edge = _outline(mask, width=max(3, int(min(bw, bh) * 0.018)))
        im.paste(Image.new("RGB", (side, side), GOLD), (ox, oy), edge.point(lambda v: 255 if v else 0))
        halo = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(5)), mask)
        im.paste(Image.new("RGB", (side, side), GOLD_LIGHT), (ox, oy),
                 halo.point(lambda v: 70 if v else 0))

    # 版式中心装饰（六花瓣的花心、蜂巢环的几何花心等）
    dec = lay.get("deco")
    if dec:
        dd = ImageDraw.Draw(im, "RGBA")
        dcx, dcy, dr = dec["cx"] * W, dec["cy"] * H, dec.get("r", 0.05) * W
        dd.ellipse([dcx - dr, dcy - dr, dcx + dr, dcy + dr],
                   outline=(*GOLD, 210), width=max(3, int(dr * 0.20)))
        dd.ellipse([dcx - dr * 0.46, dcy - dr * 0.46, dcx + dr * 0.46, dcy + dr * 0.46],
                   outline=(*GOLD_LIGHT, 150), width=max(2, int(dr * 0.12)))

    draw_podium(im)
    meta = next((d for d in data["days"] if int(d["day"]) == day), {})
    draw_title(im, meta.get("title") or "辉煌七十七载·扬帆再出发", subtitle)
    draw_signature(im, signature_lines(data, day))

    # 与模型出图同一个主体目录，但放进 compose/ 子目录，避免和模型出的图混在一起
    out_dir = Path(out_dir or ROOT / "outputs" / subj / "compose")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"day{day}.png"
    im.convert("RGB").save(dest)
    print(f"\nDay {day} · 版式「{lay['name']}」（{key}）")
    for u in used:
        print(f"  {u}")
    if faced:
        print(f"  已模糊 {faced} 处人物面部（合规：画面不出现可识别的真实人物面部）")
    if missing:
        print(f"  提示：{len(missing)} 个栏目没有达到 {min_score} 分的实景图（已画金色留空框）；"
              f"可降低 --min-score，或补采这些题材：{'、'.join(missing)}")
    print(f"  已保存：{dest}  ({W}x{H})")
    return dest


def build_parser(p) -> argparse.ArgumentParser:
    """在已创建的子命令 parser 上挂参数（与其它子命令的注册方式保持一致）。"""
    p.add_argument("--day", type=int, default=None, help="单日 1-7")
    p.add_argument("--all", action="store_true", help="7 天全量")
    p.add_argument("--subject", default=None)
    p.add_argument("--events-file", default=None)
    p.add_argument("--layout", default=None, help="版式 key，如 five-star / six-petal / seven-bars")
    p.add_argument("--min-score", type=float, default=5.0,
                   help="直接采用实景照片的最低评分（≥9 会标注为“优秀·直接采用”）")
    p.add_argument("--allow-people", action="store_true",
                   help="允许人物场景题材也用实拍照片（默认跳过，避免出现可识别人物面部）")
    p.add_argument("--out-dir", default=None, help="输出目录（默认 outputs/<主体>）")
    p.add_argument("--size", default=None, help="画布尺寸，如 1520x2720")
    p.add_argument("--subtitle", default="国庆祝福", help="主标题下方的小字")
    p.add_argument("--list-layouts", action="store_true", help="列出可用版式")
    return p


def run(args) -> int:
    if args.list_layouts:
        list_layouts(args.day)
        return 0
    if not args.subject and not args.events_file:
        print("请指定 --subject 或 --events-file")
        return 2
    days = list(range(1, 8)) if args.all or not args.day else [args.day]
    size = None
    if args.size:
        w, h = args.size.lower().split("x")
        size = (int(w), int(h))
    saved = []
    for d in days:
        saved.append(compose_day(d, args.subject, args.layout, args.min_score,
                                 Path(args.out_dir) if args.out_dir else None, size,
                                 subtitle=args.subtitle, events_file=args.events_file,
                                 allow_people=args.allow_people))
    print(f"\n完成 {len(saved)}/{len(days)} 张。")
    return 0 if saved else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="compose", description="实景照片直排海报")
    build_parser(ap)
    raise SystemExit(run(ap.parse_args()))

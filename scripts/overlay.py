# -*- coding: utf-8 -*-
"""海报后处理：把真实二维码与机构名叠加到生成好的海报上。

AI 直接画二维码通常会画出不可扫描的乱码方块，因此正确做法是：
  提示词里预留留白（--qr）+ 出图后在这里叠加可扫描的真实二维码。
"""
from __future__ import annotations

import glob
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/STZHONGS.TTF",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for fp in FONT_CANDIDATES:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def ensure_qrlib() -> None:
    try:
        import qrcode  # noqa: F401
        return
    except ImportError:
        pass
    try:
        import segno  # noqa: F401
        return
    except ImportError:
        pass
    print("缺少二维码库，正在尝试安装 segno（纯 Python，无依赖）…")
    subprocess.run([sys.executable, "-m", "pip", "install", "segno", "-q"], check=False)
    try:
        import segno  # noqa: F401
    except ImportError:
        raise SystemExit("无法安装二维码库，请手动执行：pip install segno")


def make_qr(content: str, px: int, color: str = "#111111") -> Image.Image:
    try:
        import qrcode

        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_H,
                           box_size=10, border=2)
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image(fill_color=color, back_color="white").convert("RGB")
        return img.resize((px, px), Image.LANCZOS)
    except ImportError:
        import io

        import segno

        buf = io.BytesIO()
        segno.make(content, error="h").save(buf, kind="png", scale=10, border=2, dark=color, light="white")
        buf.seek(0)
        return Image.open(buf).convert("RGB").resize((px, px), Image.LANCZOS)


def text_w(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    try:
        return draw.textlength(text, font=font)
    except Exception:
        return font.getlength(text)


def run(args) -> int:
    files = sorted(glob.glob(args.image))
    if not files:
        print(f"没有匹配到图片：{args.image}")
        return 1
    if not args.qr and not args.org and not args.date:
        print("没有指定 --qr / --org / --date，无需叠加")
        return 0

    ensure_qrlib()
    ok = 0
    for f in files:
        src = Path(f)
        im = Image.open(src).convert("RGB")
        W, H = im.size
        qr_px = int(W * args.scale)

        card_pad = int(qr_px * 0.12)
        qr_img = make_qr(args.qr, qr_px) if args.qr else None

        fs_org = max(int(qr_px * 0.20), 14)
        fs_sub = max(int(qr_px * 0.15), 12)
        font_org = load_font(fs_org)
        font_sub = load_font(fs_sub)

        lines = []
        if args.org:
            lines.append((args.org, font_org))
        if args.slogan:
            lines.append((args.slogan, font_sub))
        if args.date:
            lines.append((args.date, font_sub))

        tmp = ImageDraw.Draw(im)
        text_block_h = sum((font.size + int(font.size * 0.45)) for _, font in lines) if lines else 0
        card_w = qr_px + card_pad * 2 if qr_img else 0
        if lines:
            card_w = max(card_w, int(max(text_w(tmp, t, f) for t, f in lines)) + card_pad * 2)
        card_h = (qr_px + card_pad * 2 if qr_img else 0) + text_block_h + (card_pad if lines and qr_img else 0)

        margin = int(W * 0.045)
        if args.position == "bottom-right":
            x = W - card_w - margin
            y = H - card_h - margin
        elif args.position == "bottom-left":
            x, y = margin, H - card_h - margin
        else:
            x = (W - card_w) // 2
            y = H - card_h - margin

        card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, card_w - 1, card_h - 1], radius=int(card_pad * 0.9),
                             fill=(255, 255, 255, 235), outline=(198, 160, 88, 200), width=2)
        cy = card_pad
        if qr_img:
            card.paste(qr_img, ((card_w - qr_px) // 2, cy))
            cy += qr_px + int(card_pad * 0.6)
        for text, font in lines:
            w = text_w(cd, text, font)
            cd.text(((card_w - w) / 2, cy), text, font=font, fill=(140, 28, 19, 255))
            cy += int(font.size * 1.45)

        im.paste(card, (x, y), card)

        dest = Path(args.out) if args.out and len(files) == 1 else src.with_name(f"{src.stem}_final.png")
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest)
        print(f"已叠加：{dest}")
        ok += 1
    print(f"处理完成 {ok} 张。")
    return 0 if ok else 1

# -*- coding: utf-8 -*-
"""提示词拼装：全局基底 + 当日版式 + 事件 + 落款 + 可选项 + 负面词。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

DEFAULT_BASE = (
    "9:16竖版国庆宣传海报，恢弘大气红金国风庆典设计；"
    "顶部背景巨大飘扬五星红旗，金色闪耀星光粒子放射光芒；"
    "顶部金色书法主标题“辉煌七十七载·扬帆再出发”，白色副标题“国庆祝福”；"
    "流动红色绸缎波浪底部装饰；辉煌暖金色光影，烟花祥云点缀，"
    "8K高清精致商业海报，无水印画面干净"
)

DEFAULT_NEGATIVE = (
    "画框内部禁止任何文字标签、图注、汉字，不要物体表面乱生成文字，无乱码，不要水印；"
    "不要多余文字，不要错别字，不要英文单词，不要编号角标；"
    "不要低清晰度、不要畸变、不要多余的肢体与手指，不要拼接错位；"
    "不要灰色暗淡，不要过度曝光，不要塑料感"
)

# 主体相关的社会合规负面词（学校 / 公司 / 城市主题时自动追加）
SUBJECT_NEGATIVE = (
    "不要出现可识别的真实人物面部肖像，不要出现真实校徽、商标、品牌logo与二维码图案，"
    "不要出现地图边界线、国界线等敏感元素，不要出现任何绝对化宣传用语"
)


def load_json(path: str | Path) -> Any:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"找不到配置文件：{p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_events(events_file: str | Path | None = None, subject: str | None = None) -> dict:
    """加载素材库。未指定时使用内置国家级素材库；也可读取 config/subjects/<slug>.json。"""
    if events_file:
        return load_json(events_file)
    if subject and subject != "中国":
        candidates = [c for c in (CONFIG / "subjects").glob("*.json") if not c.name.startswith("_")]
        for c in candidates:
            data = load_json(c)
            if data.get("subject") == subject:
                return data
        raise FileNotFoundError(
            f"素材库中没有“{subject}”的资料，请先联网检索并写入 config/subjects/ 下的 JSON（见 SKILL.md 第 3 步）"
        )
    return load_json(CONFIG / "events_national.json")


def slugify(text: str) -> str:
    """把主体名转成安全文件名（中文保留，空格与符号转成 -）。"""
    import re

    s = re.sub(r"[\\/:*?\"<>|\s]+", "-", text.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "subject"


def day_events(data: dict, day: int, custom_events: list[str] | None = None) -> list[dict]:
    if custom_events:
        return [{"title": e, "scene": e} for e in custom_events]
    for d in data["days"]:
        if int(d["day"]) == day:
            return d["events"]
    raise ValueError(f"素材库中缺少第 {day} 天的事件")


def day_meta(data: dict, day: int) -> dict:
    for d in data["days"]:
        if int(d["day"]) == day:
            return d
    return {}


def signature_of(data: dict, day: int, default_sig: str | None = None) -> str:
    meta = day_meta(data, day)
    return meta.get("signature") or default_sig or f"10.{day} 祝福祖国"


def signature_lines(data: dict, day: int) -> list[str]:
    """落款支持两行（如 10.1：第一行日期，第二行“庆祝中华人民共和国成立77周年”）。"""
    meta = day_meta(data, day)
    lines = [meta["signature"]] if meta.get("signature") else []
    if meta.get("signature2"):
        lines.append(meta["signature2"])
    return lines or [signature_of(data, day)]


def layout_desc(day: int, key: str | None) -> str | None:
    """取 config/frames.json 里某个形状版式的文字描述（供模型出图）。

    与 compose（照片直排）共用同一份版式定义，保证两种出图方式看得是同一个版式。
    """
    if not key:
        return None
    frames = load_json(CONFIG / "frames.json")
    lays = frames["days"][str(day)]["layouts"]
    if key not in lays:
        raise SystemExit(
            f"第 {day} 天没有版式“{key}”，可选：{'、'.join(lays)}"
            f"（用 python scripts/nd7.py compose --list-layouts 查看）")
    return lays[key]["desc"]


FRAME_STYLE_BY_SHAPE = {
    "arch": "竖弧形（顶部拱形）",
    "rect": "圆角矩形",
    "bar": "窄而高的圆角竖条",
    "triangle-up": "正三角形（尖角朝上）",
    "triangle-down": "倒三角形（尖角朝下）",
    "diamond": "菱形（由两个三角形合成）",
    "star5": "正五角星形",
    "pentagon": "正五边形",
    "petal": "花瓣形（上端尖、下端圆）",
    "hexagon": "正六边形",
}


def layout_shapes(day: int, key: str | None) -> list[str]:
    """指定版式用到的形状（去重）。"""
    if not key:
        return []
    frames = load_json(CONFIG / "frames.json")
    lays = frames["days"][str(day)]["layouts"]
    if key not in lays:
        raise SystemExit(f"第 {day} 天没有版式“{key}”，可选：{'、'.join(lays)}")
    seen: list[str] = []
    for s in lays[key]["slots"]:
        sh = s.get("shape")
        if sh and sh not in seen:
            seen.append(sh)
    return seen


def frame_style_for_shapes(shapes: list[str]) -> str:
    """按版式形状生成画框样式描述，避免版式说五角星、框形还写拱形。"""
    names = [FRAME_STYLE_BY_SHAPE[s] for s in shapes if s in FRAME_STYLE_BY_SHAPE]
    if not names:
        return ""
    return ("每个画框为" + "、".join(names) +
            "，金色浮雕细边框、线条纤细精致，框内是写实摄影质感的工程/风景实景，"
            "框外保持红金庆典背景；画框下方可加入金色台阶或卷草纹基座，"
            "底部由流动红色绸缎海浪托起，视觉重心稳定")


def build_events_block(events: list[dict], triangular: bool = False) -> str:
    lines = []
    for i, ev in enumerate(events, 1):
        title = ev.get("title", "").strip()
        scene = ev.get("scene", "").strip()
        body = f"{title}：{scene}" if scene and scene != title else title
        suffix = "（画面按三角形裁切构图，主体居中）" if triangular else ""
        lines.append(f"{i}. {body}{suffix}")
    return "\n".join(lines)


def build_prompt(
    day: int,
    events_file: str | Path | None = None,
    subject: str | None = None,
    custom_title: str | None = None,
    custom_events: list[str] | None = None,
    qr: bool = False,
    org: str | None = None,
    base: str | None = None,
    negative: str | None = None,
    size: str = "1080x1920",
    layout: str | None = None,
) -> dict:
    """组装单日海报提示词，返回结构化字典。"""
    if not 1 <= int(day) <= 7:
        raise ValueError("day_num 必须是 1-7")

    data = load_events(events_file, subject)
    layouts = load_json(CONFIG / "layouts.json")
    day = int(day)

    events = day_events(data, day, custom_events)
    if custom_events and len(custom_events) != day:
        # 允许不一致，但提示用户：栏目数应等于日期号
        pass

    layout_key = layout
    layout_tpl = layout_desc(day, layout) or layouts["layouts"][str(day)]
    triangular = day == 7
    events_block = build_events_block(events, triangular)
    layout = layout_tpl.replace("{events}", events_block)
    if triangular:
        layout += "\n" + layouts["day7_extra"]

    meta = day_meta(data, day)
    title = custom_title or meta.get("title") or "辉煌七十七载·扬帆再出发"
    base_text = (base or DEFAULT_BASE).replace("辉煌七十七载·扬帆再出发", title)
    frame_style = layouts["frame_style"]
    if triangular:
        frame_style = layouts.get("day7_frame_style", frame_style)
    elif layouts.get("base_podium"):
        frame_style += "；" + layouts["base_podium"]
    # 选了非拱形版式（五角星 / 三角 / 菱形 …）时，框形描述也要跟着形状走
    shape_style = frame_style_for_shapes(layout_shapes(day, layout_key))
    if shape_style:
        frame_style = shape_style

    sig_lines = signature_lines(data, day)
    signature = sig_lines[0]
    if len(sig_lines) > 1:
        sig_desc = "底部居中两行极小的金色文字落款：第一行“%s”，第二行“%s”，居中对称，清晰可读但不过分抢眼" % (
            sig_lines[0], sig_lines[1])
    else:
        sig_desc = f'底部居中一行极小的金色文字落款“{sig_lines[0]}”，清晰可读但不过分抢眼'

    extras = []
    if qr:
        extras.append(
            "画面右下角预留一块干净的纯色方形留白（边长约占画面宽度 12%），"
            "留白区域内不得出现任何图案、纹理与文字，用于后期叠加真实二维码"
        )
    if org:
        extras.append(f"底部落款上方居中一行极小的金色楷体文字“{org}”，字号极小不抢主体")

    positive_parts = [
        "【画面基底】\n" + base_text,
        "【画框样式】\n" + frame_style,
        "【当日版式】\n" + layout,
        "【落款】\n" + sig_desc,
    ]
    if extras:
        positive_parts.append("【可选项】\n" + "；".join(extras))
    positive_parts.append("【画质】\n竖版 9:16 构图，比例严谨，主体清晰，商业级精修，层次丰富")

    neg = negative or DEFAULT_NEGATIVE
    if triangular and layouts.get("day7_negative"):
        neg = neg + "；" + layouts["day7_negative"]
    if data.get("type") in ("school", "company", "city"):
        neg = neg + "；" + SUBJECT_NEGATIVE

    positive = "\n\n".join(positive_parts)
    full = positive + "\n\n【负面约束】\n" + neg

    return {
        "day": day,
        "subject": data.get("subject", "中国"),
        "type": data.get("type", "nation"),
        "title": title,
        "size": size,
        "events": events,
        "signature": signature,
        "signature_lines": sig_lines,
        "layout": layout,
        "positive": positive,
        "negative": neg,
        "full": full,
        "qr": qr,
        "org": org,
    }


def build_all(
    events_file: str | Path | None = None,
    subject: str | None = None,
    custom_title: str | None = None,
    qr: bool = False,
    org: str | None = None,
    layout: str | None = None,
) -> list[dict]:
    data = load_events(events_file, subject)
    return [
        build_prompt(
            day=d["day"],
            events_file=events_file,
            subject=subject,
            custom_title=custom_title,
            qr=qr,
            org=org,
            layout=layout,
        )
        for d in sorted(data["days"], key=lambda x: int(x["day"]))
    ]

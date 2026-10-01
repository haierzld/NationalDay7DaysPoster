# -*- coding: utf-8 -*-
"""NationalDay7DaysPoster 命令行入口。

用法示例：
  python scripts/nd7.py subject 中国福州
  python scripts/nd7.py prompt --day 1
  python scripts/nd7.py plan --subject 中国 --out outputs/prompts.md
  python scripts/nd7.py gen --day 1 --engine api --provider siliconflow
  python scripts/nd7.py gen --all --engine browser --platform doubao
  python scripts/nd7.py overlay --image outputs/day1.png --qr https://example.com --org 某某集团
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:  # Windows 控制台中文输出
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from prompt_builder import build_all, build_prompt, load_events  # noqa: E402
from subject_resolver import resolve  # noqa: E402


def cmd_subject(args: argparse.Namespace) -> int:
    info = resolve(args.text)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    if info["needs_research"]:
        print("\n需要检索的 7 大主题：")
        for i, t in enumerate(info["topics"], 1):
            print(f"  {i}. {t}")
        print("\n合规提醒：")
        for n in info["notes"]:
            print(f"  - {n}")
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    p = build_prompt(
        day=args.day,
        events_file=args.events_file,
        subject=args.subject,
        custom_title=args.title,
        custom_events=args.event or None,
        qr=args.qr,
        org=args.org,
        layout=getattr(args, "layout", None),
    )
    if args.json:
        print(json.dumps(p, ensure_ascii=False, indent=2))
    else:
        print(p["full"])
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    plans = build_all(
        events_file=args.events_file,
        subject=args.subject,
        custom_title=args.title,
        qr=args.qr,
        org=args.org,
        layout=getattr(args, "layout", None),
    )
    if args.json:
        print(json.dumps(plans, ensure_ascii=False, indent=2))
        return 0

    lines = [f"# {plans[0]['subject']} · 国庆 7 天连更海报提示词\n"]
    for p in plans:
        lines.append(f"\n## Day {p['day']}（{p['size']}）\n")
        lines.append("```text")
        lines.append(p["full"])
        lines.append("```\n")
    text = "\n".join(lines)
    # 未指定路径时，提示词与该主体的成品图放在同一个目录：outputs/<主体>/prompts.md
    out = Path(args.out) if args.out else ROOT / "outputs" / plans[0]["subject"] / "prompts.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"已写入：{out}")
    return 0


def subject_out_dir(args: argparse.Namespace) -> None:
    """输出统一归档到 outputs/<主体>/：该主体的 7 张图与提示词放在同一个目录里。"""
    if getattr(args, "out_dir", None) and args.out_dir != "outputs":
        return
    try:
        data = load_events(args.events_file, args.subject)
        subj = data.get("subject") or args.subject or "中国"
    except Exception:
        subj = args.subject or "中国"
    args.out_dir = str(ROOT / "outputs" / subj)


def cmd_gen(args: argparse.Namespace) -> int:
    subject_out_dir(args)
    if args.engine == "api":
        from generate_api import run as run_api

        return run_api(args)
    if args.engine == "browser":
        from generate_browser import run as run_browser

        return run_browser(args)
    print("未指定 --engine（api / browser），仅生成提示词请用 `prompt` 或 `plan` 子命令。")
    return 2


def cmd_overlay(args: argparse.Namespace) -> int:
    from overlay import run as run_overlay

    return run_overlay(args)


def cmd_compose(args: argparse.Namespace) -> int:
    from compose import run as run_compose

    return run_compose(args)


def cmd_wm(args: argparse.Namespace) -> int:
    from watermark import run as run_wm

    return run_wm(args)


def cmd_refs(args: argparse.Namespace) -> int:
    from fetch_refs import run as run_refs

    return run_refs(args)


def cmd_browsers(_args: argparse.Namespace) -> int:
    from generate_browser import detect_browsers

    found = detect_browsers()
    if not found:
        print("未检测到 Chrome / Edge，请先安装浏览器。")
        return 1
    for b in found:
        print(json.dumps(b, ensure_ascii=False, indent=2))
    return 0


LAYOUT_HELP = ("形状版式 key（five-star 五角星 / five-pentagon 五边形 / six-petal 六花瓣 / "
               "six-hex 蜂巢环 / seven-bars 七竖条 / seven-tri-quad 倒三角+菱形 / seven-dipper 北斗七星 …），"
               "可用 `nd7 compose --list-layouts` 查看全部")


def main() -> int:
    ap = argparse.ArgumentParser(prog="nd7", description="国庆 7 天连更海报生成器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("subject", help="解析主体类型并输出检索清单")
    p.add_argument("text", help="例如：中国 / 中国福州 / 某某大学 / 某某集团")
    p.set_defaults(func=cmd_subject)

    p = sub.add_parser("prompt", help="生成单日完整提示词")
    p.add_argument("--day", type=int, required=True, help="1-7")
    p.add_argument("--subject", default=None, help="主体名（默认中国）")
    p.add_argument("--events-file", default=None, help="自定义素材库 JSON 路径")
    p.add_argument("--title", default=None, help="覆盖主标题")
    p.add_argument("--event", action="append", default=None, help="临时覆盖当日事件，可重复传入")
    p.add_argument("--qr", action="store_true", help="预留二维码留白（配合 overlay 叠加真实二维码）")
    p.add_argument("--org", default=None, help="画面中显示的机构/公司名（默认不显示）")
    p.add_argument("--layout", default=None, help=LAYOUT_HELP)
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("plan", help="生成 7 天全部提示词")
    p.add_argument("--subject", default=None)
    p.add_argument("--events-file", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--qr", action="store_true")
    p.add_argument("--org", default=None)
    p.add_argument("--layout", default=None, help=LAYOUT_HELP)
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", default=None, help="写入 Markdown 文件路径")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("gen", help="调用生图引擎出图")
    p.add_argument("--day", type=int, default=None, help="单日 1-7")
    p.add_argument("--all", action="store_true", help="7 天全量")
    p.add_argument("--engine", choices=["api", "browser"], required=True)
    p.add_argument("--provider", default="auto", help="api: auto|siliconflow|dashscope|openai")
    p.add_argument("--model", default=None)
    p.add_argument("--api-key", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--platform", default="doubao", help="browser: doubao|qianwen|jimeng")
    p.add_argument("--subject", default=None)
    p.add_argument("--events-file", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--qr", action="store_true")
    p.add_argument("--org", default=None)
    p.add_argument("--out-dir", default="outputs")
    p.add_argument("--browser", default="Chrome", help="browser: Chrome（默认，找不到则用 Edge）| Edge")
    p.add_argument("--live-profile", action="store_true",
                   help="直接使用真实浏览器用户数据目录（新版 Chrome 可能拒绝远程调试，默认使用登录态副本）")
    p.add_argument("--prompt-prefix",
                   default="请严格按照以下提示词生成一张 9:16 竖版图片，直接输出图片，不要解释：",
                   help="浏览器引擎提交前加的引导语，传空串关闭")
    p.add_argument("--headless", action="store_true", help="浏览器无头模式（登录态不足时请去掉）")
    p.add_argument("--no-clean", action="store_true", help="出图后不自动清除平台角标水印")
    p.add_argument("--ref", action="append", default=None,
                   help="真实实景照片路径，可重复传入；上传给平台作为参考（图生图）")
    p.add_argument("--ref-auto", action="store_true",
                   help="按当天题材自动匹配 assets/<主体>/ 下已采集的实景照片")
    p.add_argument("--layout", default=None, help=LAYOUT_HELP)
    p.add_argument("--dry-run", action="store_true", help="只打印将提交的文本，不启动浏览器")
    p.add_argument("--timeout", type=int, default=180, help="等待出图秒数")
    p.set_defaults(func=cmd_gen)

    p = sub.add_parser("overlay", help="二维码 / 机构名叠加后处理")
    p.add_argument("--image", required=True, help="海报图片路径，支持通配符")
    p.add_argument("--qr", default=None, help="二维码内容（网址或文字）")
    p.add_argument("--org", default=None, help="机构/公司名")
    p.add_argument("--slogan", default=None, help="机构名下方小字")
    p.add_argument("--date", default=None, help="落款日期，如 2026.10.01")
    p.add_argument("--position", default="bottom-right", choices=["bottom-right", "bottom-left", "bottom-center"])
    p.add_argument("--scale", type=float, default=0.12, help="二维码边长占画面宽度的比例")
    p.add_argument("--out", default=None, help="输出路径（默认覆盖原图旁的 *_final.png）")
    p.set_defaults(func=cmd_overlay)

    from watermark import build_parser as wm_parser

    p = wm_parser(sub.add_parser("wm", help="检测并清除平台角标水印"))
    p.set_defaults(func=cmd_wm)

    from fetch_refs import build_parser as refs_parser

    p = refs_parser(sub.add_parser("refs", help="采集实景参考照片"))
    p.set_defaults(func=cmd_refs)

    from compose import build_parser as compose_parser

    p = compose_parser(sub.add_parser("compose", help="把达标实景照片直接排成海报（不走模型）"))
    p.set_defaults(func=cmd_compose)

    p = sub.add_parser("browsers", help="探测本地 Chrome / Edge")
    p.set_defaults(func=cmd_browsers)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

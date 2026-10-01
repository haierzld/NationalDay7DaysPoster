# -*- coding: utf-8 -*-
"""实景参考图采集：抓取公开网络上的真实照片，作为出图参考 / 合成素材。

用法：
  python scripts/fetch_refs.py --query "安溪清水岩 帝字形 主殿" --slug qingshuiyan --limit 8
  python scripts/fetch_refs.py --config config/refs_安溪.json
  python scripts/fetch_refs.py --url https://.../a.jpg --slug wenmiao --note "来源：xxx"

输出：
  assets/<subject>/<slug>/01.jpg ...       真实照片
  assets/<subject>/_refs.json              来源清单（URL / 标题 / 尺寸）

合规：只抓公开可检索的资讯与图片，记录来源便于核对；商用前请自行确认版权与肖像权。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from generate_browser import detect_browsers, _score_item  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36")


def _slugify(text: str) -> str:
    keep = []
    for ch in text.strip():
        if ch.isalnum() or ch in "-_":
            keep.append(ch)
        elif ord(ch) > 127:
            keep.append(ch)
    return "".join(keep) or "ref"


def _search_bing(page, query: str, limit: int) -> list[dict]:
    """在 Bing 图片搜索页抽取原图地址（a.iusc 的 m 属性内含 murl / purl / t）。"""
    urls = [
        "https://www.bing.com/images/search?q=" + query.replace(" ", "+") + "&form=HDRSC2&first=1",
        "https://cn.bing.com/images/search?q=" + query.replace(" ", "+") + "&form=HDRSC2&first=1",
    ]
    out: list[dict] = []
    for u in urls:
        try:
            page.goto(u, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            for _ in range(3):  # 滚动加载更多结果
                page.mouse.wheel(0, 2400)
                time.sleep(1.2)
            raw = page.eval_on_selector_all(
                "a.iusc", "els => els.map(e => e.getAttribute('m'))",
            )
            for r in raw or []:
                if not r:
                    continue
                try:
                    d = json.loads(r)
                except Exception:
                    continue
                murl = d.get("murl")
                if not murl:
                    continue
                out.append({
                    "image": murl,
                    "page": d.get("purl") or u,
                    "title": (d.get("t") or "").replace("\u200b", "").strip(),
                })
            if out:
                break
        except Exception as e:
            print(f"  搜索页失败：{e}")
    return out[: max(limit * 3, 12)]


def _download(ctx, url: str, dest: Path, referer: str = "https://www.bing.com/") -> bool:
    try:
        resp = ctx.request.get(url, headers={"Referer": referer, "User-Agent": UA}, timeout=60000)
        if not resp.ok:
            return False
        data = resp.body()
        if len(data) < 20 * 1024:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        try:
            from PIL import Image

            with Image.open(dest) as im:
                im.load()
                if min(im.size) < 480:
                    dest.unlink(missing_ok=True)
                    return False
                return True
        except Exception:
            dest.unlink(missing_ok=True)
            return False
    except Exception:
        return False


def fetch(query: str, slug: str, subject: str, limit: int = 8,
          min_ratio: float = 0.0) -> list[dict]:
    """抓一组真实照片，返回记录（含本地路径与来源）。"""
    brs = detect_browsers()
    if not brs:
        print("未检测到 Chrome / Edge，无法抓取。")
        return []
    br = brs[0]
    out_dir = ROOT / "assets" / subject / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    saved: list[dict] = []
    seen: set[str] = set()
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(Path(__import__("tempfile").gettempdir()) / "nd7-refs-profile"),
            executable_path=br["exe"],
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            viewport={"width": 1440, "height": 900},
            user_agent=UA,
        )
        try:
            page = ctx.new_page()
            print(f"[{slug}] 检索：{query}")
            cands = _search_bing(page, query, limit)
            print(f"  候选 {len(cands)} 张，开始下载…")
            for c in cands:
                if len(saved) >= limit:
                    break
                url = c["image"]
                key = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
                if key in seen:
                    continue
                seen.add(key)
                dest = out_dir / f"{len(saved) + 1:02d}_{key}.jpg"
                if _download(ctx, url, dest):
                    try:
                        from PIL import Image

                        w, h = Image.open(dest).size
                    except Exception:
                        w, h = 0, 0
                    saved.append({
                        "file": str(dest.relative_to(ROOT)).replace("\\", "/"),
                        "width": w, "height": h,
                        "source_image": url,
                        "source_page": c["page"],
                        "title": c["title"],
                        "query": query,
                    })
                    print(f"  已保存 {dest.name}  ({w}x{h})  {c['title'][:40]}")
            page.close()
        finally:
            ctx.close()

    _merge_index(subject, slug, query, saved)
    return saved


def _merge_index(subject: str, slug: str, query: str, items: list[dict]) -> None:
    idx_path = ROOT / "assets" / subject / "_refs.json"
    idx = {}
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding="utf-8"))
        except Exception:
            idx = {}
    idx[slug] = {"query": query, "fetched": time.strftime("%Y-%m-%d %H:%M"), "items": items}
    idx_path.parent.mkdir(parents=True, exist_ok=True)
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  来源清单：{idx_path.relative_to(ROOT)}")


def add_url(url: str, slug: str, subject: str, note: str = "") -> list[dict]:
    brs = detect_browsers()
    if not brs:
        return []
    from playwright.sync_api import sync_playwright

    dest = ROOT / "assets" / subject / slug / f"{int(time.time()) % 100000}.jpg"
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(Path(__import__("tempfile").gettempdir()) / "nd7-refs-profile"),
            executable_path=brs[0]["exe"], headless=True, viewport={"width": 1280, "height": 800},
            user_agent=UA,
        )
        try:
            ok = _download(ctx, url, dest)
        finally:
            ctx.close()
    if not ok:
        print("下载失败：", url)
        return []
    try:
        from PIL import Image

        w, h = Image.open(dest).size
    except Exception:
        w, h = 0, 0
    items = [{"file": str(dest.relative_to(ROOT)).replace("\\", "/"), "width": w, "height": h,
              "source_image": url, "source_page": url, "title": note or "手动添加", "query": note}]
    _merge_index(subject, slug, url, items)
    print(f"  已保存：{dest}")
    return items


def _topic_best(subject: str, slug: str, query: str) -> float | None:
    """该题材已采到的图里的最高评分（用检索词自评），用于判断要不要换词重采。"""
    idx_path = ROOT / "assets" / subject / "_refs.json"
    if not idx_path.exists():
        return None
    try:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    items = (idx.get(slug) or {}).get("items", [])
    if not items:
        return None
    return max(_score_item(it, [query]) for it in items)


def run(args: argparse.Namespace) -> int:
    if args.config:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        subject = cfg.get("subject", "refs")
        total = 0
        weak: list[str] = []
        for item in cfg.get("topics", []):
            q = item["query"]
            slug = item.get("slug") or _slugify(q)
            # 取量优先级：题材自带 limit > 配置顶层 limit > 命令行 --limit
            limit = int(item.get("limit", cfg.get("limit", args.limit)))
            total += len(fetch(q, slug, subject, limit))
            # 弱题材重采：最高分不够就换检索词再来一轮
            if getattr(args, "min_score", 0) > 0:
                best = _topic_best(subject, slug, q)
                tries = 0
                while best is not None and best < args.min_score and tries < getattr(args, "retry", 1):
                    tries += 1
                    alt = (item.get("alt") or f"{q} 实景 高清 全景").strip()
                    print(f"  ⚠ 题材 {slug} 最高分 {best:.1f} < {args.min_score}，换词重采：{alt}")
                    more = fetch(alt, slug, subject, limit)
                    total += len(more)
                    if not more:
                        break
                    nb = _topic_best(subject, slug, q)
                    if nb is None or nb <= best:
                        break
                    best = nb
                if best is None or best < args.min_score:
                    weak.append(f"{slug}({best:.1f})" if best is not None else f"{slug}(无图)")
        print(f"\n共采集 {total} 张，目录：{ROOT / 'assets' / subject}")
        if weak:
            print("建议人工补采（分数仍不足）：" + "、".join(weak))
        return 0 if total else 1
    if args.url:
        return 0 if add_url(args.url, args.slug or _slugify(args.url), args.subject, args.note) else 1
    if not args.query:
        print("需要 --query / --config / --url 之一")
        return 2
    slug = args.slug or _slugify(args.query)
    items = fetch(args.query, slug, args.subject, args.limit)
    return 0 if items else 1


def build_parser(ap: argparse.ArgumentParser) -> argparse.ArgumentParser:
    ap.add_argument("--query", default=None, help="检索词，如：安溪清水岩 帝字形 主殿")
    ap.add_argument("--slug", default=None, help="本地目录名（默认按检索词生成）")
    ap.add_argument("--subject", default="安溪", help="主体名，作为 assets 下的一级目录")
    ap.add_argument("--limit", type=int, default=8, help="每个题材最多保存几张")
    ap.add_argument("--config", default=None, help="批量配置 JSON")
    ap.add_argument("--url", default=None, help="直接下载单张图片 URL")
    ap.add_argument("--note", default="", help="图片备注/来源说明")
    ap.add_argument("--min-score", type=float, default=4.5,
                    help="弱题材重采阈值：题材最高分低于此值就换检索词再采一轮（0 关闭）")
    ap.add_argument("--retry", type=int, default=1, help="每个弱题材最多重采几轮")
    return ap


if __name__ == "__main__":
    p = build_parser(argparse.ArgumentParser(description="实景参考图采集"))
    raise SystemExit(run(p.parse_args()))

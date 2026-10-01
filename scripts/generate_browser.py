# -*- coding: utf-8 -*-
"""本地浏览器生图引擎：复用 Chrome / Edge 已登录的账号（豆包 / 通义千问 / 即梦）。

思路：
  1. 优先 Chrome，其次 Edge（可用 --browser 指定）
  2. 用 Playwright 的持久化上下文直接加载浏览器原用户数据目录 → 自带登录态
  3. 自动填 prompt 发送；定位失败则把 prompt 复制到剪贴板，等用户手动粘贴发送，
     脚本继续轮询并把新出现的图片下载到输出目录

依赖：pip install playwright（不需要下载 Playwright 自带浏览器，直接驱动本地 Chrome/Edge）
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PLATFORMS = {
    "doubao": {
        "name": "豆包",
        "url": "https://www.doubao.com/chat/",
        "inputs": [
            "div[contenteditable='true']",
            "textarea",
            "[data-testid='chat-input']",
            "#chat-input",
        ],
        "image_mode_texts": ["图像生成", "图片生成", "生成图片"],
        "send": "enter",
    },
    "qianwen": {
        "name": "通义千问 / 通义万相",
        "url": "https://tongyi.aliyun.com/wanxiang/",
        "inputs": ["textarea", "div[contenteditable='true']", "input[type='text']"],
        "image_mode_texts": ["文生图", "图像生成"],
        "send": "enter",
    },
    "jimeng": {
        "name": "即梦",
        "url": "https://jimeng.jianying.com/ai-tool/image/generate",
        "inputs": ["textarea", "div[contenteditable='true']"],
        "image_mode_texts": [],
        "send": "enter",
    },
}

LOGIN_WORDS = ("扫码登录", "登录后使用", "请登录", "立即登录", "Sign in", "登录/注册")


def _candidate_browsers() -> list[dict]:
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", "")
    pf86 = os.environ.get("ProgramFiles(x86)", "")
    cands = [
        {
            "name": "Chrome",
            "exe": [
                Path(local) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(pf) / "Google" / "Chrome" / "Application" / "chrome.exe",
                Path(pf86) / "Google" / "Chrome" / "Application" / "chrome.exe",
            ],
            "user_data_dir": Path(local) / "Google" / "Chrome" / "User Data",
        },
        {
            "name": "Edge",
            "exe": [
                Path(pf86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                Path(local) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ],
            "user_data_dir": Path(local) / "Microsoft" / "Edge" / "User Data",
        },
    ]
    found = []
    for c in cands:
        exe = next((str(p) for p in c["exe"] if p.exists()), None)
        if exe and Path(c["user_data_dir"]).exists():
            found.append({"name": c["name"], "exe": exe, "user_data_dir": str(c["user_data_dir"])})
    return found


def detect_browsers() -> list[dict]:
    return _candidate_browsers()


def _profile_busy(profile: str) -> bool:
    p = Path(profile)
    return (p / "SingletonLock").exists() or (p / "SingletonCookie").exists()


# 缓存类目录直接跳过，只保留账号与站点数据
IGNORE_DIRS = {
    "Cache", "Code Cache", "GPUCache", "DawnCache", "DawnGraphiteCache", "GrShaderCache",
    "ShaderCache", "GraphiteDawnCache", "Service Worker", "CacheStorage", "Crashpad",
    "component_crx_cache", "extensions_crx_cache", "blob_storage", "Shared Dictionary",
    "Safe Browsing", "BrowserMetrics", "OptimizationGuidePredictionModels",
    "optimization_guide_hint_cache_store", "Download Service", "WebRTC Logs",
    "Segmentation Platform", "PersistentOriginTrials", "Crash Reports",
}


def profile_cache_dir(br: dict) -> Path:
    return Path(os.environ.get("TEMP", ".")) / f"nd7-{br['name'].lower()}-profile"


def _copy_file_incr(src: Path, dst: Path) -> None:
    try:
        if dst.exists():
            s, d = src.stat(), dst.stat()
            if s.st_size == d.st_size and d.st_mtime >= s.st_mtime:
                return
        shutil.copy2(src, dst)
    except Exception:
        pass


def _copy_tree_incr(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name.startswith("Singleton") or item.name in IGNORE_DIRS:
            continue
        try:
            if item.is_dir():
                _copy_tree_incr(item, dst / item.name)
            else:
                _copy_file_incr(item, dst / item.name)
        except Exception:
            continue


def _copy_profile(src: str, dst: Path) -> str:
    """把浏览器用户数据复制成一份登录态副本（跳过缓存目录，支持增量复用）。

    Chrome 136+ 禁止在默认用户数据目录上开启远程调试，因此浏览器引擎默认走副本；
    副本是独立目录，登录态（Cookies / Local Storage）随复制保留。
    """
    dst.mkdir(parents=True, exist_ok=True)
    for item in Path(src).iterdir():
        if item.name.startswith("Singleton") or item.name in IGNORE_DIRS:
            continue
        try:
            if item.is_dir():
                _copy_tree_incr(item, dst / item.name)
            else:
                _copy_file_incr(item, dst / item.name)
        except Exception:
            continue
    return str(dst)


def _set_clipboard(text: str) -> bool:
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Set-Clipboard -Value ([Console]::Out.Encoding.GetString([Convert]::FromBase64String('{base64.b64encode(text.encode('utf-8')).decode()}')))"],
            check=False, timeout=20,
        )
        return True
    except Exception:
        return False


def _collect_imgs(page) -> list[dict]:
    """页面内所有较大图片及其显示尺寸/位置。"""
    try:
        return page.evaluate(
            """() => Array.from(document.querySelectorAll('img')).map(i => {
                const r = i.getBoundingClientRect();
                return {src: i.currentSrc || i.src || '', w: i.naturalWidth, h: i.naturalHeight,
                        top: Math.round(r.top), vw: Math.round(r.width), vh: Math.round(r.height)};
            }).filter(o => o.src.startsWith('http') && o.w >= 512 && o.h >= 512 && o.vw >= 200)"""
        )
    except Exception:
        return []


REF_HINT = ("\n（我已上传该题材的真实实景照片，请严格参照照片中的建筑造型、屋顶形式、"
            "环境色调与拍摄视角来还原画面，不要引入照片之外的地标，"
            "整体保持国庆红金国风海报风格）")


def _auto_clean(dest: Path) -> None:
    """出图后清掉平台角标水印（豆包/即梦等固定在右下角）。"""
    try:
        import cv2
        import numpy as np
        from watermark import detect, remove

        img = cv2.imdecode(np.fromfile(str(dest), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return
        from watermark import DEFAULT_WM_BOX

        # 角标位置由平台固定，只用经验区域：自动检测容易把落款/星光误判成水印
        box = [float(v) for v in DEFAULT_WM_BOX.split(",")]
        out = remove(img, [box])
        cv2.imencode(dest.suffix, out)[1].tofile(str(dest))
        print(f"  已清除平台角标水印（{[round(v, 3) for v in box]}）")
    except Exception as e:
        print(f"  水印清除跳过：{e}")


def _ensure_sent(page, box) -> None:
    """Enter 未生效时（上传面板/焦点问题），兜底点击发送按钮。"""
    try:
        if not box or not box.count():
            return
        val = box.evaluate("el => (el.value !== undefined ? el.value : el.innerText) || ''")
        if not val.strip():
            return
        for sel in ["button[aria-label*='发送']", "button[aria-label*='Send']",
                    "[data-testid*='send-button']", "[data-testid*='send_btn']"]:
            try:
                b = page.locator(sel).first
                if b.count() and b.is_visible():
                    b.click(timeout=4000)
                    print("  已点击发送按钮")
                    return
            except Exception:
                continue
    except Exception:
        pass


def _norm(s: str) -> str:
    return re.sub(r"[\s，,、·\-—_()（）【】\[\]]", "", s or "")


# 来源可信度：权威站点加分，图库水印站减分（水印图只作兜底）
GOOD_HOST_HINTS = ("gov.cn", "edu.cn", "news.cn", "xinhua", "people.com.cn", "cctv",
                   "thepaper", "chinanews", "cqnews", "cas.cn")
STOCK_HOST_HINTS = ("699pic", "huaban", "pixabay", "veer", "quanjing", "58pic",
                    "昵图", "千图", "包图", "摄图", "stock", "shutterstock", "istock")


def _keywords(event: dict) -> list[str]:
    """一条画框事件用于匹配参考图的关键词：标题 + 去城市前缀的核心词 + 场景短语。"""
    title = event.get("title") or ""
    kws = [title]
    core = title
    for prefix in ("安溪", "泉州", "上海", "中国"):
        if core.startswith(prefix) and len(core) > len(prefix) + 1:
            core = core[len(prefix):]
            break
    if core != title:
        kws.append(core)
    for seg in re.split(r"[，,。；;、]", event.get("scene") or "")[:3]:
        seg = seg.strip()
        if 4 <= len(seg) <= 14:
            kws.append(seg)
    return [k for k in kws if k]


def _score_item(item: dict, keywords: list[str]) -> float:
    """给一张候选参考图打分：题材贴合 > 分辨率 > 构图 > 来源可信度。"""
    score = 0.0
    q = _norm(item.get("query") or "")
    t = _norm(item.get("title") or "")
    for kw in keywords:
        k = _norm(kw)
        if not k:
            continue
        # 图片标题才是画面内容的证据（「泉州 西湖公园」也会搜回杭州西湖的图），权重给足；
        # 检索词只是查询意图，命中不代表图里真有这个题材，权重压低。
        if k in t:
            score += 3.0
        elif len(k) >= 2 and k[:2] in t:
            score += 1.0
        if k in q:
            score += 1.5
        elif len(k) >= 2 and k[:2] in q:
            score += 0.6

    w = int(item.get("width") or 0)
    h = int(item.get("height") or 0)
    px = w * h
    if px >= 2_000_000:
        score += 3.0
    elif px >= 1_000_000:
        score += 2.2
    elif px >= 500_000:
        score += 1.4
    elif px >= 200_000:
        score += 0.6
    if w and h:
        if h / w >= 1.15:
            score += 1.2              # 竖图更贴合海报画框
        elif w / h >= 2.2:
            score -= 1.5              # 超宽全景裁切损失太大
        elif w / h >= 1.8:
            score -= 0.6
        if max(w, h) >= 1200:
            score += 0.8

    page = ((item.get("source_page") or "") + " " + (item.get("source_image") or "")).lower()
    if any(s in page for s in GOOD_HOST_HINTS):
        score += 1.5
    if any(s in page for s in STOCK_HOST_HINTS):
        score -= 1.2

    # 非实拍（效果图 / 素材图 / 插画）重罚：这类图会把模型的画面质感带偏
    raw_title = item.get("title") or ""
    for bad in ("效果图", "素材", "模板", "手绘", "插画", "合成", "设计图", "平面广告", "海报", "矢量"):
        if bad in raw_title:
            score -= 2.0
            break
    return round(score, 2)


def _match_slug(event: dict, idx: dict) -> str | None:
    """按画框标题匹配采集时的题材目录（slug）。"""
    title = event.get("title", "")
    core = title
    for prefix in ("安溪", "泉州", "上海", "中国"):
        if core.startswith(prefix) and len(core) > len(prefix) + 1:
            core = core[len(prefix):]
            break
    # 只用检索词匹配（搜索结果的标题噪声太大，容易串到别的题材）
    q = {slug: _norm(meta.get("query") or "") for slug, meta in idx.items()}
    core_n, title_n = _norm(core), _norm(title)
    for round_k in (0, 4):  # 完整串 → 前 4 字
        for s, blob_n in q.items():
            cands = [core_n, title_n] if round_k == 0 else [core_n[:4], title_n[:4]]
            if any(c and len(c) >= round_k and c in blob_n for c in cands):
                return s
    # 兜底：取检索词与画框标题的最长公共子串最大的那个题材。
    # 早先按「前 2 字」匹配，会被「泉州」这种城市名带到一堆无关题材上。
    best_slug, best_len = None, 0
    for s, blob_n in q.items():
        hit = max(_lcs_len(core_n, blob_n), _lcs_len(title_n, blob_n))
        if hit > best_len:
            best_slug, best_len = s, hit
    return best_slug if best_len >= 3 else None


def _lcs_len(a: str, b: str) -> int:
    """最长公共子序列长度（中文短串，直接 DP）。

    「晋江智能制鞋工厂」与检索词「晋江制鞋智能工厂…」字序不同但显然是同一题材，
    子串匹配会漏，子序列不会。
    """
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for ch in a:
        cur = [0] * (len(b) + 1)
        for j, c2 in enumerate(b, 1):
            cur[j] = prev[j - 1] + 1 if ch == c2 else max(prev[j], cur[j - 1])
        prev = cur
    return prev[-1]


REF_MIN_SCORE = 4.0   # 参考图合格线：低于此分的图不进模型


def _auto_refs(subject: str, events: list[dict], per_topic: int = 1,
               max_refs: int | None = None, min_score: float = REF_MIN_SCORE) -> list[str]:
    """按当天画框（事件）挑参考图：先给每张候选图评分，再取最贴合的前 N 张。

    N 默认 == 当日栏目数（Day2 取 2 张、Day7 取 7 张），一个画框对应一张参考图，
    不再把采集到的图整包丢给模型。评分维度：题材贴合 > 分辨率 > 竖构图 > 来源可信度。

    min_score 是硬门槛：分数不够的图宁可不给参考，也不把模型往错误地标上带
    （题目对不上、图太小或来自图库水印站的图会把画面带偏）。
    """
    base = ROOT / "assets" / subject
    idx_path = base / "_refs.json"
    if not idx_path.exists():
        return []
    try:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    need = max_refs or len(events)
    if need <= 0:
        return []

    def path_of(item: dict) -> Path:
        p = Path(item.get("file") or "")
        return p if p.is_absolute() else (ROOT / p)

    picked: list[tuple[str, float, str, str]] = []   # (文件, 分数, 画框标题, 尺寸)
    used: set[str] = set()
    skipped = 0

    # 第一轮：每个画框配一张自己题材里评分最高的图
    for ev in events:
        if len(picked) >= need:
            break
        slug = _match_slug(ev, idx)
        if not slug:
            continue
        kws = _keywords(ev)
        cands = []
        for it in (idx.get(slug) or {}).get("items", []):
            p = path_of(it)
            if not p.exists() or str(p) in used:
                continue
            sc = _score_item(it, kws)
            if sc < min_score:
                skipped += 1
                continue
            cands.append((sc, p, it))
        cands.sort(key=lambda x: -x[0])
        for sc, p, it in cands[:per_topic]:
            used.add(str(p))
            picked.append((str(p), sc, ev.get("title", ""),
                           f"{it.get('width') or '?'}×{it.get('height') or '?'}"))
            if len(picked) >= need:
                break

    # 第二轮：没配上图/没采到的题材，用其余高分图补齐（分数取与任一画框的最贴合度）
    if len(picked) < need:
        pool = []
        for slug, meta in idx.items():
            for it in (meta or {}).get("items", []):
                p = path_of(it)
                if not p.exists() or str(p) in used:
                    continue
                sc = max((_score_item(it, _keywords(ev)) for ev in events), default=0.0)
                if sc < min_score:
                    skipped += 1
                    continue
                pool.append((sc, p, it))
        pool.sort(key=lambda x: -x[0])
        for sc, p, it in pool[:need - len(picked)]:
            used.add(str(p))
            picked.append((str(p), sc, "补充",
                           f"{it.get('width') or '?'}×{it.get('height') or '?'}"))

    if picked:
        print(f"  参考图评分（当日 {need} 个画框，取 {len(picked)} 张，合格线 {min_score} 分）：")
        for f, sc, title, wh in picked:
            print(f"    {sc:>5.1f} 分  {title}  {wh}  {Path(f).name}")
        if skipped:
            print(f"    （{skipped} 张未达合格线未采用：题材对不上 / 图太小 / 图库水印站）")
    elif skipped:
        print(f"  参考图：当日 {need} 个画框，没有达到 {min_score} 分合格线的图，本次不带参考图出图")
    return [f for f, _, _, _ in picked]


UPLOAD_ENTRIES = [
    "button:has-text('添加图片')", "button:has-text('上传图片')", "button:has-text('本地上传')",
    "[aria-label*='上传']", "[aria-label*='添加图片']", "[aria-label*='图片']",
    "text=添加图片", "text=上传图片", "text=参考图", "text=图片",
]


def _upload_refs(page, refs: list[str]) -> bool:
    """上传真实照片作为参考（图生图）。

    豆包的上传控件是动态渲染的：先试直接给 input[type=file] 注入文件，
    找不到再点击可能的上传入口，用文件选择器兜底。
    """
    files = [str(Path(r).resolve()) for r in refs if Path(r).exists()]
    if not files:
        return False

    # 1) 页面已有 file input
    try:
        loc = page.locator("input[type='file']")
        if loc.count():
            loc.first.set_input_files(files, timeout=15000)
            time.sleep(4)
            print(f"  已上传 {len(files)} 张实景参考图")
            return True
    except Exception as e:
        print(f"  直接注入失败：{e}")

    # 2) 点击上传入口，等文件选择器弹出
    for sel in UPLOAD_ENTRIES:
        try:
            el = page.locator(sel).first
            if not el.count() or not el.is_visible():
                continue
            with page.expect_file_chooser(timeout=8000) as fc:
                el.click(timeout=4000)
            fc.value.set_files(files)
            time.sleep(4)
            print(f"  已上传 {len(files)} 张实景参考图（经「{sel}」入口）")
            return True
        except Exception:
            continue

    print("  参考图未能自动上传（未找到上传入口）")
    return False


def _set_ratio(page, ratio_text: str = "9:16") -> None:
    """在生成面板上切换图片比例（找不到就忽略，靠提示词强约束）。"""
    try:
        loc = page.get_by_text(ratio_text, exact=False)
        for i in range(min(loc.count(), 8)):
            try:
                el = loc.nth(i)
                if el.is_visible():
                    el.click(timeout=3000)
                    time.sleep(1.2)
                    print(f"  已切换图片比例：{ratio_text}")
                    return
            except Exception:
                continue
    except Exception:
        pass


def _wait_new_image(page, known: set, timeout: int, ratio: float = 9 / 16) -> dict | None:
    """轮询新出现的生成结果图。

    优先级 1：与 9:16 接近的竖图（容差 9%）立即采用；
    优先级 2：放宽到明显竖图（宽高比 ≥ 1.3 且高 ≥ 900）作为兜底候选，但不再死等
    「超时过半」，而是候选出现后短暂观察（比例接近竖版海报的等 8s，否则等 20s）：
    期间若出现更接近 9:16、或比例相同但分辨率更高的图就顺延，直到窗口内没有更优的
    才收工 —— 出图通常 30~60s 就好，没必要蹲满超时。
    """
    time.sleep(4)
    deadline = time.time() + timeout
    best = None
    best_at = 0.0
    last_log = time.time()
    while time.time() < deadline:
        for im in _collect_imgs(page):
            src = im.get("src") or ""
            if not src or src in known or src.startswith("data:"):
                continue
            r = im["h"] / max(im["w"], 1)
            if abs(r - ratio) <= 0.09:
                known.add(src)
                return im
            if r >= 1.3 and im["h"] >= 900:
                score = abs(r - ratio)
                if best is None:
                    best, best_at = im, time.time()
                else:
                    best_score = abs(best["h"] / max(best["w"], 1) - ratio)
                    # 比例更接近优先；比例相同时取分辨率更高的那张（预览图会被正片顶掉）
                    if (score, -im["h"]) < (best_score, -best["h"]):
                        best, best_at = im, time.time()
        if best is not None:
            rb = best["h"] / max(best["w"], 1)
            grace = 8 if 1.6 <= rb <= 2.0 else 20
            if time.time() - best_at >= grace:
                known.add(best["src"])
                return best
        if time.time() - last_log > 30:
            last_log = time.time()
            print(f"  等待出图… 已 {int(timeout - (deadline - time.time()))}s，候选竖图 {1 if best else 0} 张")
        time.sleep(2)
    if best:
        known.add(best["src"])
    else:
        try:
            tail = page.inner_text("body")[-260:].replace("\n", " ")
            print(f"  诊断（页面尾部）：{tail}")
        except Exception:
            pass
    return best


def _save_image(ctx, page, src: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if src.startswith("blob:"):
            b64 = page.evaluate(
                """async (u) => {
                    const r = await fetch(u); const b = await r.blob();
                    return await new Promise(res => { const fr = new FileReader();
                        fr.onload = () => res(fr.result.split(',')[1]); fr.readAsDataURL(b); });
                }""", src)
            dest.write_bytes(base64.b64decode(b64))
            return True
        if src.startswith("data:"):
            dest.write_bytes(base64.b64decode(src.split(",", 1)[1]))
            return True
        resp = ctx.request.get(src, timeout=120000)
        if resp.ok:
            dest.write_bytes(resp.body())
            return True
    except Exception as e:
        print(f"  下载失败：{e}")
    return False


def run(args) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright，请先安装：\n  pip install playwright\n（无需下载浏览器，脚本直接驱动本地 Chrome / Edge）")
        return 2

    from prompt_builder import build_all, build_prompt, slugify

    platform = PLATFORMS.get(args.platform) or PLATFORMS.get(args.platform.lower())
    if not platform:
        print(f"未知平台 {args.platform}，可选：{', '.join(PLATFORMS)}")
        return 2

    browsers = detect_browsers()
    if not browsers:
        print("未检测到本地 Chrome / Edge。")
        return 1
    br = next((b for b in browsers if args.browser.lower() in b["name"].lower()), browsers[0])
    print(f"使用浏览器：{br['name']}  {br['exe']}")

    if args.all:
        plans = build_all(events_file=args.events_file, subject=args.subject,
                          custom_title=args.title, qr=args.qr, org=args.org,
                          layout=getattr(args, "layout", None))
    elif args.day:
        plans = [build_prompt(day=args.day, events_file=args.events_file, subject=args.subject,
                              custom_title=args.title, qr=args.qr, org=args.org,
                              layout=getattr(args, "layout", None))]
    else:
        print("请指定 --day N 或 --all")
        return 2

    if getattr(args, "dry_run", False):
        for p in plans:
            print(f"\n===== Day {p['day']} · {platform['name']} =====")
            print(p["full"])
        print("\n[dry-run] 未启动浏览器。")
        return 0

    live = br["user_data_dir"]
    busy = _profile_busy(live)
    if getattr(args, "live_profile", False) and not busy:
        profile = live
        print("使用真实浏览器用户数据目录（--live-profile；Chrome 136+ 可能拒绝远程调试）")
    else:
        if busy:
            print(f"检测到 {br['name']} 正在运行，改用登录态副本（首次复制需数十秒，之后增量复用）")
        else:
            print("使用登录态副本运行（Chrome 136+ 拒绝在默认用户数据目录开启远程调试）")
        profile = _copy_profile(live, profile_cache_dir(br))
        print(f"登录态副本目录：{profile}")
        print("提示：副本里若没有登录态，请先在原浏览器登录豆包/千问/即梦，再重新运行。")

    # 输出目录由 nd7 统一指定为 outputs/<主体>/，同一主体的图与提示词放在一个目录
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=profile,
            executable_path=br["exe"],
            headless=bool(args.headless),
            args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"],
            viewport={"width": 1280, "height": 900},
        )
        try:
            for p in plans:
                prefix = getattr(args, "prompt_prefix", None)
                prompt_text = f"{prefix}\n{p['full']}" if prefix else p["full"]
                refs = list(getattr(args, "ref", None) or [])
                if getattr(args, "ref_auto", False):
                    refs += _auto_refs(plans[0]["subject"], p.get("events", []))
                if refs:
                    prompt_text += REF_HINT
                page = ctx.new_page()
                page.goto(platform["url"], wait_until="domcontentloaded", timeout=120000)
                time.sleep(6)

                _dismiss_overlays(page)
                page = _enter_image_mode(ctx, page, platform)
                _set_ratio(page, "9:16")
                box = _find_input(page, platform["inputs"])
                if box is None:
                    body = ""
                    try:
                        body = page.inner_text("body")[:4000]
                    except Exception:
                        pass
                    reason = "似乎未登录" if any(w in body for w in LOGIN_WORDS) else "未定位到输入框"
                    print(f"[{platform['name']}] {reason}。请在打开的浏览器窗口中登录 / 进入生成页，然后回来按回车继续…")
                    input()
                    page.reload(wait_until="domcontentloaded")
                    time.sleep(8)
                    page = _enter_image_mode(ctx, page, platform)
                    box = _find_input(page, platform["inputs"])

                known = set()
                try:
                    for im in page.evaluate("() => Array.from(document.images).map(i => i.currentSrc || i.src)"):
                        known.add(im)
                except Exception:
                    pass
                for im in _collect_imgs(page):  # 把生成前已存在的图也计入
                    known.add(im["src"])

                if box:
                    try:
                        try:
                            box.fill(prompt_text)  # textarea / contenteditable 均支持，且不受遮罩影响
                        except Exception:
                            _dismiss_overlays(page)
                            box.click(timeout=8000, force=True)
                            time.sleep(0.5)
                            page.keyboard.insert_text(prompt_text)
                        time.sleep(1)
                        if refs and not _upload_refs(page, refs):
                            print("  参考图未能自动上传，请在浏览器窗口中手动粘贴图片后再继续。")
                        time.sleep(1)
                        page.keyboard.press("Enter")
                        time.sleep(2)
                        _ensure_sent(page, box)
                        print(f"[{platform['name']}] Day {p['day']} 已提交，等待出图…")
                    except Exception as e:
                        print(f"  自动填入失败：{e}")
                        box = None
                if not box:
                    ok = _set_clipboard(prompt_text)
                    print("  未定位到输入框。提示词已" + ("复制到剪贴板" if ok else "保存到 outputs/_prompt_day%d.txt" % p["day"]))
                    if not ok:
                        (out_dir / f"_prompt_day{p['day']}.txt").write_text(prompt_text, encoding="utf-8")
                    print("  请在浏览器中粘贴并发送，脚本会自动等待并下载结果…")

                im = _wait_new_image(page, known, args.timeout)
                if im:
                    dest = out_dir / f"day{p['day']}.png"
                    if _save_image(ctx, page, im["src"], dest):
                        print(f"  已保存：{dest}  ({im['w']}x{im['h']})")
                        if not getattr(args, "no_clean", False):
                            _auto_clean(dest)
                        saved.append(str(dest))
                else:
                    print(f"  Day {p['day']} 等待超时，未捕获图片")
                page.close()
        finally:
            ctx.close()

    print(f"\n完成 {len(saved)}/{len(plans)} 张，目录：{out_dir.resolve()}")
    return 0 if saved else 1


def _dismiss_overlays(page) -> None:
    """移除纯遮盖层（不删除对话框本身），避免遮罩拦截点击。"""
    try:
        page.evaluate(
            """() => document.querySelectorAll("[data-slot='dialog-overlay']").forEach(e => e.remove())"""
        )
    except Exception:
        pass


def _enter_image_mode(ctx, page, platform):
    """尝试点击「图像生成 / 文生图」入口，切换到图像生成模式；失败则保持原页面。"""
    for t in platform.get("image_mode_texts") or []:
        try:
            loc = page.get_by_text(t, exact=True)
            if not loc.count():
                continue
            before = len(ctx.pages)
            loc.first.click(timeout=5000)
            time.sleep(3)
            if len(ctx.pages) > before:  # 点击后打开了新标签页
                page = ctx.pages[-1]
                page.wait_for_load_state("domcontentloaded")
            print(f"  已进入「{t}」模式")
            return page
        except Exception:
            continue
    return page


def _find_input(page, selectors: list[str]):
    for sel in selectors:
        try:
            loc = page.locator(sel).last
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    return None

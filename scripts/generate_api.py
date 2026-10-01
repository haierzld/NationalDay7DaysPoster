# -*- coding: utf-8 -*-
"""API 生图引擎：SiliconFlow / 阿里百炼（通义万相）/ OpenAI 兼容接口。

密钥来源（优先级从高到低）：
  1) --api-key 参数
  2) 环境变量 IMAGE_API_KEY
  3) 厂商专属环境变量：SILICONFLOW_API_KEY / DASHSCOPE_API_KEY / OPENAI_API_KEY
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODELS = {
    "siliconflow": "Kwai-Kolors/Kolors",
    "dashscope": "wanx2.1-t2i-turbo",
    "openai": "gpt-image-1",
}

DEFAULT_BASE_URL = {
    "siliconflow": "https://api.siliconflow.cn/v1",
    "dashscope": "https://dashscope.aliyuncs.com/api/v1",
    "openai": "https://api.openai.com/v1",
}

ENV_KEYS = {
    "siliconflow": "SILICONFLOW_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "openai": "OPENAI_API_KEY",
}

SIZE_MAP = {  # 9:16 竖版在各家的写法
    "siliconflow": "1080x1920",
    "dashscope": "1080*1920",
    "openai": "1024x1536",
}


def _detect_provider(args) -> str:
    if args.provider and args.provider != "auto":
        return args.provider
    for name, env in ENV_KEYS.items():
        if os.environ.get(env):
            return name
    if os.environ.get("IMAGE_API_KEY"):
        return os.environ.get("IMAGE_PROVIDER", "siliconflow")
    return "siliconflow"


def _api_key(provider: str, args) -> str:
    key = args.api_key or os.environ.get("IMAGE_API_KEY") or os.environ.get(ENV_KEYS.get(provider, ""))
    if not key:
        raise SystemExit(
            f"缺少 API Key。请传 --api-key，或设置环境变量 {ENV_KEYS.get(provider, 'IMAGE_API_KEY')}。\n"
            "（本技能不内置任何密钥，也不会把密钥写入仓库）"
        )
    return key


def _post(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, headers: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path, headers: dict | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dest.write_bytes(resp.read())
    return dest


def _save_b64(b64: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(base64.b64decode(b64))
    return dest


def siliconflow(prompt: str, key: str, model: str, size: str, base_url: str) -> list[str]:
    payload = {
        "model": model,
        "prompt": prompt,
        "image_size": size,
        "batch_size": 1,
        "num_inference_steps": 25,
        "guidance_scale": 7.5,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    res = _post(f"{base_url}/images/generations", payload, headers)
    return [img["url"] for img in res.get("images", []) if img.get("url")]


def dashscope(prompt: str, key: str, model: str, size: str, base_url: str, timeout: int) -> list[str]:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    payload = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {"size": size, "n": 1},
    }
    res = _post(f"{base_url}/services/aigc/text2image/image-synthesis", payload, headers)
    task_id = res.get("output", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"通义万相提交失败：{res}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _get(f"{base_url}/tasks/{task_id}", {"Authorization": f"Bearer {key}"})
        status = r.get("output", {}).get("task_status")
        if status == "SUCCEEDED":
            return [u["url"] for u in r["output"].get("results", []) if u.get("url")]
        if status in ("FAILED", "CANCELED"):
            raise RuntimeError(f"通义万相生成失败：{r}")
        time.sleep(5)
    raise TimeoutError("通义万相任务等待超时")


def openai_compat(prompt: str, key: str, model: str, size: str, base_url: str) -> list[str]:
    payload = {"model": model, "prompt": prompt, "size": size, "n": 1}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    res = _post(f"{base_url}/images/generations", payload, headers)
    out = []
    for item in res.get("data", []):
        if item.get("url"):
            out.append(item["url"])
        elif item.get("b64_json"):
            out.append("b64:" + item["b64_json"])
    return out


def generate_one(prompt: str, provider: str, key: str, model: str | None,
                 size: str, base_url: str | None, timeout: int) -> list[str]:
    model = model or DEFAULT_MODELS[provider]
    base_url = (base_url or os.environ.get("IMAGE_BASE_URL") or DEFAULT_BASE_URL[provider]).rstrip("/")
    if provider == "siliconflow":
        return siliconflow(prompt, key, model, size, base_url)
    if provider == "dashscope":
        return dashscope(prompt, key, model, size, base_url, timeout)
    if provider == "openai":
        return openai_compat(prompt, key, model, size, base_url)
    raise SystemExit(f"未知 provider：{provider}")


def run(args) -> int:
    from prompt_builder import build_all, build_prompt, slugify

    provider = _detect_provider(args)
    key = _api_key(provider, args)
    size = SIZE_MAP.get(provider, "1080x1920")

    if args.all:
        plans = build_all(events_file=args.events_file, subject=args.subject,
                          custom_title=args.title, qr=args.qr, org=args.org,
                          layout=getattr(args, "layout", None))
    elif args.day:
        plans = [build_prompt(day=args.day, events_file=args.events_file, subject=args.subject,
                              custom_title=args.title, qr=args.qr, org=args.org,
                              layout=getattr(args, "layout", None))]
    else:
        raise SystemExit("请指定 --day N 或 --all")

    # 输出目录由 nd7 统一指定为 outputs/<主体>/
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for p in plans:
        print(f"[API] Day {p['day']} · {provider} · {size} 生成中…")
        urls = generate_one(p["full"], provider, key, args.model, size, args.base_url, args.timeout)
        if not urls:
            print(f"  Day {p['day']} 未返回图片")
            continue
        dest = out_dir / f"day{p['day']}.png"
        if urls[0].startswith("b64:"):
            _save_b64(urls[0][4:], dest)
        else:
            _download(urls[0], dest)
        print(f"  已保存：{dest}")
        saved.append(str(dest))
    print(f"\n完成 {len(saved)}/{len(plans)} 张，目录：{out_dir.resolve()}")
    return 0 if saved else 1

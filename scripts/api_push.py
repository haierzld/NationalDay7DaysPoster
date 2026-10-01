# -*- coding: utf-8 -*-
"""通过 GitHub API 推送当前工作区（git 协议端口被阻断时的替代通道）。

做两件事：
  1. 读取工作区文件（默认用 `git ls-files`，失败则按排除规则遍历）
  2. 用 GitHub Git Data API 一次性建 blob → tree → commit，并把分支强制指向该 commit

用法：
  python scripts/api_push.py                                   # 用 git remote 推断仓库
  python scripts/api_push.py --repo owner/repo --branch main
  python scripts/api_push.py --message "feat: xxx"             # 自定义提交信息

凭据：环境变量 GH_TOKEN，或本机已登录的 `gh`（自动取 `gh auth token`）。
说明：会覆盖远程分支（force），适合单人维护或小仓库；公共协作仓库请谨慎。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {".git", "outputs", "__pycache__", "nd7-profile", "国庆"}
EXCLUDE_FILES = {"*.pyc", ".DS_Store"}

sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None


def get_token() -> str:
    token = os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                              timeout=30).stdout.strip()
    except Exception:
        return ""


def detect_repo() -> str:
    try:
        url = subprocess.run(["git", "config", "--get", "remote.origin.url"], cwd=ROOT,
                             capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        url = ""
    if url.startswith("git@github.com:"):
        return url.split(":", 1)[1].removesuffix(".git")
    if "github.com/" in url:
        return url.split("github.com/", 1)[1].removesuffix(".git")
    return ""


def list_files() -> list[str]:
    try:
        # -z 输出原始路径（NUL 分隔），避免中文被转义成 "assets\344\270\212..."
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, timeout=60)
        if out.returncode == 0:
            files = [p for p in out.stdout.decode("utf-8").split("\0") if p.strip()]
            if files:
                return sorted(files)
    except Exception:
        pass
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            if any(name.endswith(p.lstrip("*")) for p in EXCLUDE_FILES):
                continue
            files.append(str(Path(dirpath, name).relative_to(ROOT)).replace("\\", "/"))
    return sorted(files)


def api(method: str, path: str, token: str, payload: dict | None = None, retries: int = 3) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request("https://api.github.com" + path, data=data, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "national-day-7days-poster",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:400]
            print(f"  [API {e.code}] {method} {path}\n  {detail}")
            raise
        except Exception as e:  # 网络抖动 / RemoteDisconnected
            if attempt == retries:
                raise
            wait = 3 * attempt
            print(f"  [重试 {attempt}/{retries}] {method} {path} → {type(e).__name__}: {e}，{wait}s 后重试")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="", help="owner/repo，默认从 git remote 推断")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="chore: 通过 GitHub API 同步工作区")
    args = ap.parse_args()

    repo = args.repo or detect_repo()
    token = get_token()
    if not repo or not token:
        print("缺少仓库或凭据。设置 GH_TOKEN（或先 gh auth login），并用 --repo owner/repo 指定仓库。")
        return 2

    files = list_files()
    print(f"仓库：{repo}  分支：{args.branch}  文件：{len(files)}")

    # 空仓库不允许 Git Data API，先用 Contents API 建出分支
    try:
        readme = (ROOT / "README.md").read_bytes()
        api("PUT", f"/repos/{repo}/contents/README.md", token,
            {"message": "chore: init", "content": base64.b64encode(readme).decode(), "branch": args.branch})
        print("  已初始化分支")
    except Exception:
        pass

    tree = []
    for f in files:
        data = (ROOT / f).read_bytes()
        blob = api("POST", f"/repos/{repo}/git/blobs", token,
                   {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})
        tree.append({"path": f, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  blob {f} ({len(data)} bytes)")

    t = api("POST", f"/repos/{repo}/git/trees", token, {"tree": tree})
    c = api("POST", f"/repos/{repo}/git/commits", token,
            {"message": args.message, "tree": t["sha"], "parents": []})
    try:
        api("POST", f"/repos/{repo}/git/refs", token,
            {"ref": f"refs/heads/{args.branch}", "sha": c["sha"]})
    except Exception:
        api("PATCH", f"/repos/{repo}/git/refs/heads/{args.branch}", token,
            {"sha": c["sha"], "force": True})

    print(f"\n已推送：{c.get('html_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

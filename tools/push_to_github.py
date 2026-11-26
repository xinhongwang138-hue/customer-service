# -*- coding: utf-8 -*-
"""用 GitHub Git Data API 推送当前仓库（`git push` 不可用时的替代方案）。

为什么需要这个脚本：本机网络只有 `api.github.com` 可达，`github.com:443`
直连和走代理都会超时，因此 `git push` / `git fetch` 全部失败。Git Data API
走的是 api.github.com，可以绕过这个问题。

用法：
    python tools/push_to_github.py                 # 追加一次提交到远端默认分支
    python tools/push_to_github.py --orphan        # 用当前内容重建为单条提交
    python tools/push_to_github.py --message "..."  # 自定义提交信息
    python tools/push_to_github.py --dry-run       # 只打印将要上传的文件

Token 来源：环境变量 GH_TOKEN / GITHUB_TOKEN，或本机 `gh auth token`。

注意：远端提交由 API 重建，sha 与本地提交不同（作者时间、父提交都不一样），
但每个文件的 blob sha 与本地完全一致，clone 下来内容逐字节相同。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


# ---------- 基础工具 ----------

def run(*args: str) -> str:
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} 失败：{out.stderr.strip()}")
    return out.stdout


def project_root() -> str:
    return run("git", "rev-parse", "--show-toplevel").strip()


def parse_remote(root: str) -> tuple[str, str]:
    """从 origin 的 URL 里解析 owner/repo。"""
    url = run("git", "-C", root, "remote", "get-url", "origin").strip()
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        raise RuntimeError(f"无法从 remote 解析 owner/repo：{url}")
    return match.group(1), match.group(2)


def get_token() -> str:
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    raise RuntimeError("没有可用的 GitHub token（设置 GH_TOKEN 或先 gh auth login）")


class Client:
    def __init__(self, token: str) -> None:
        self.token = token

    def call(self, method: str, path: str, payload: dict | None = None,
             *, retries: int = 6, allow_empty: bool = False) -> dict:
        url = path if path.startswith("http") else API + path
        body = json.dumps(payload).encode() if payload is not None else None
        last = ""
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header("Authorization", f"Bearer {self.token}")
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("X-GitHub-Api-Version", "2022-11-28")
            req.add_header("User-Agent", "push-to-github")
            if body:
                req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                if allow_empty and exc.code in (404, 409):
                    return {}
                # 4xx 是请求本身的问题，重试没意义
                if exc.code < 500 and exc.code != 429:
                    raise RuntimeError(f"{method} {path} -> {exc.code} {detail}") from None
                last = f"{exc.code} {detail}"
            except Exception as exc:  # 连接被掐断 / 超时
                last = f"{type(exc).__name__}: {exc}"
            wait = min(2 ** attempt, 30)
            print(f"    ↻ 第 {attempt} 次失败（{last[:90]}），{wait}s 后重试")
            time.sleep(wait)
        raise RuntimeError(f"{method} {path} 连续 {retries} 次失败：{last}")


# ---------- 主要流程 ----------

def collect_files(root: str) -> list[dict]:
    out = run("git", "-C", root, "ls-files", "-s", "-z")
    files = []
    for row in out.split("\0"):
        if not row.strip():
            continue
        meta, path = row.split("\t", 1)
        mode = meta.split()[0]
        data = open(os.path.join(root, path), "rb").read()
        try:
            text, encoding = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, encoding = base64.b64encode(data).decode("ascii"), "base64"
        files.append({"path": path, "mode": mode, "text": text,
                      "encoding": encoding, "size": len(data)})
    return files


def create_tree(client: Client, owner: str, repo: str, files: list[dict]) -> str:
    """优先把全部文件塞进一个 tree 请求（内容内联），失败再逐个上传 blob。"""
    tree = [{"path": f["path"], "mode": f["mode"], "type": "blob",
             "content": f["text"], "encoding": f["encoding"]} for f in files]
    try:
        print(f"→ 一次性创建整棵树（{len(files)} 个文件）…")
        return client.call("POST", f"/repos/{owner}/{repo}/git/trees", {"tree": tree},
                           retries=3)["sha"]
    except Exception as exc:
        print(f"  单请求失败（{str(exc)[:150]}），回退到逐个上传")

    entries = []
    for idx, f in enumerate(files, 1):
        blob = client.call("POST", f"/repos/{owner}/{repo}/git/blobs",
                           {"content": f["text"], "encoding": f["encoding"]})
        entries.append({"path": f["path"], "mode": f["mode"],
                        "type": "blob", "sha": blob["sha"]})
        if idx % 10 == 0 or idx == len(files):
            print(f"  blob {idx}/{len(files)}")
    return client.call("POST", f"/repos/{owner}/{repo}/git/trees", {"tree": entries})["sha"]


def main() -> int:
    parser = argparse.ArgumentParser(description="用 GitHub API 推送当前仓库")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--message", default=None)
    parser.add_argument("--orphan", action="store_true", help="重建为不含历史的单条提交")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = project_root()
    owner, repo = parse_remote(root)
    files = collect_files(root)
    total = sum(f["size"] for f in files)
    print(f"仓库 {owner}/{repo}，{len(files)} 个文件，{total / 1024:.0f} KB")

    if args.dry_run:
        for f in files:
            print(f"  {f['mode']} {f['size']:>7}  {f['path']}")
        return 0

    message = args.message
    if not message:
        message = run("git", "-C", root, "log", "-1", "--pretty=%B").strip()

    client = Client(get_token())
    head = client.call("GET", f"/repos/{owner}/{repo}/git/ref/heads/{args.branch}",
                       allow_empty=True)
    previous = head.get("object", {}).get("sha")
    parents = [previous] if previous and not args.orphan else []

    tree = create_tree(client, owner, repo, files)
    print(f"✓ tree {tree[:10]}")

    commit = client.call("POST", f"/repos/{owner}/{repo}/git/commits",
                         {"message": message, "tree": tree, "parents": parents})
    print(f"✓ commit {commit['sha'][:10]}（父提交 {len(parents)} 个）")

    if previous:
        client.call("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{args.branch}",
                    {"sha": commit["sha"], "force": True})
    else:
        client.call("POST", f"/repos/{owner}/{repo}/git/refs",
                    {"ref": f"refs/heads/{args.branch}", "sha": commit["sha"]})
    print(f"✓ {args.branch} → {commit['sha'][:10]}")
    print(f"完成：https://github.com/{owner}/{repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

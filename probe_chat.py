# -*- coding: utf-8 -*-
"""探测指定 CPA 文件的 chat 端点状态。

先 refresh（除非 --no-refresh），再打 cli-chat-proxy.grok.com/v1/chat/completions，
区分三类：200 / 403(账号无 free 额度) / 其它(token/网络问题)。

Usage:
    python probe_chat.py cpa_auth/xai-1x92tlqhwq@a.bdbdjx.top.json
    python probe_chat.py --dir cpa_auth --dir cpa_auth_403   # 批量
    python probe_chat.py --no-refresh cpa_auth/xai-xxx.json
"""
import argparse, json, os, sys, time

# Windows GBK 控制台会吞掉 ✓✗ 等 Unicode，强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from xai_oauth import refresh_access_token, save_cliproxyapi_auth_record


def _load_proxy() -> str:
    try:
        with open(os.path.join(os.path.dirname(__file__), "config.json"), encoding="utf-8") as f:
            p = str(json.load(f).get("proxy", "") or "").strip()
            if p:
                return p
    except Exception:
        pass
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "http://127.0.0.1:7890"


PROXY = _load_proxy()
CHAT_URL = "https://cli-chat-proxy.grok.com/v1/chat/completions"


def _expired(d: dict) -> bool:
    exp = d.get("expired")
    if exp:
        from datetime import datetime, timezone
        try:
            now = datetime.now(timezone.utc)
            return datetime.fromisoformat(exp.replace("Z", "+00:00")) <= now
        except Exception:
            return True
    return True


def refresh_one(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"  ✗ read fail: {e}")
        return False
    rt = d.get("refresh_token", "")
    if not rt:
        print(f"  ✗ no refresh_token")
        return False
    email = d.get("email", "?")
    print(f"  ~ refresh {email}...", end=" ", flush=True)
    try:
        new_token = refresh_access_token(refresh_token=rt, timeout=30.0, proxy=PROXY)
        save_cliproxyapi_auth_record(
            new_token,
            userinfo={"email": email, "sub": d.get("sub", "")},
            auth_dir=os.path.dirname(path),
            redirect_uri=d.get("redirect_uri", ""),
            base_url=d.get("base_url", "https://cli-chat-proxy.grok.com/v1"),
            headers=d.get("headers"),
        )
        print("✓")
        return True
    except Exception as e:
        print(f"FAIL " + str(e)[:120])
        return False


def probe_chat(path: str) -> dict:
    """返回 {'status': int, 'code': str, 'model': str, 'raw': str}"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    token = d.get("access_token", "")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    headers.update(d.get("headers") or {})
    body = {
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "max_tokens": 4,
    }
    import urllib.request, urllib.error
    proxies = {"http": PROXY, "https": PROXY}
    proxy_handler = urllib.request.ProxyHandler(proxies)
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(CHAT_URL, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with opener.open(req, timeout=40) as resp:
            raw = resp.read().decode("utf-8", "replace")
            code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        code = e.code
    except Exception as e:
        return {"status": -1, "code": "NET", "model": "", "raw": str(e)[:200]}
    parsed = {"status": code, "code": "", "model": "", "raw": raw[:300]}
    try:
        j = json.loads(raw)
        parsed["code"] = j.get("code") or j.get("error", {}).get("code") or ""
        if "model" in j:
            parsed["model"] = j.get("model", "")
        # chat completion 非 stream 的成功体可能不含 model，看 choices
    except Exception:
        pass
    return parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--dir", action="append", default=[], help="可多次，扫整个目录")
    ap.add_argument("--no-refresh", action="store_true")
    args = ap.parse_args()

    paths = list(args.files)
    for d in args.dir:
        for f in sorted(os.listdir(d)):
            if f.startswith("xai-") and f.endswith(".json"):
                paths.append(os.path.join(d, f))
    if not paths:
        ap.print_help()
        return 1

    print(f"proxy={PROXY} | {len(paths)} file(s)\n")
    summary = {"200": [], "403": [], "other": []}
    for i, p in enumerate(paths):
        email = os.path.basename(p)[4:-5]
        print(f"[{i+1}/{len(paths)}] {email}")
        if not args.no_refresh:
            refresh_one(p)
        r = probe_chat(p)
        tag = "OK" if r["status"] == 200 else ("403" if r["status"] == 403 else f"{r['status']}/{r['code']}")
        print(f"  → {tag}  model={r.get('model','')}  {r['raw'][:140]}")
        if r["status"] == 200:
            summary["200"].append(email)
        elif r["status"] == 403:
            summary["403"].append(email)
        else:
            summary["other"].append((email, tag))
        if i < len(paths) - 1:
            time.sleep(2)

    print("\n=== 汇总 ===")
    print(f"200 可用: {len(summary['200'])}")
    print(f"403 无额度: {len(summary['403'])}  -> {', '.join(summary['403'])}")
    print(f"其它: {len(summary['other'])}  -> {summary['other']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Refresh expired CPA tokens using refresh_token.

Usage: python refresh_cpa.py            # refresh all expired CPA files
       python refresh_cpa.py --force     # force refresh all
"""
import sys, os, json, time, argparse
from xai_oauth import refresh_access_token, build_cliproxyapi_auth_record, save_cliproxyapi_auth_record

CPA_DIR = "cpa_auth"


def _load_proxy() -> str:
    """CPA 刷新走代理：config.proxy → 环境变量 → 本机 7890。

    auth.x.ai 在 Cloudflare 后面，国内直连会被逐个 reset（"第1个能过、后面
    ERR_CONNECTION_CLOSED"的根因不是 headless IP 限流，而是没走代理）。
    """
    try:
        with open(os.path.join(os.path.dirname(__file__), "config.json"), encoding="utf-8") as f:
            proxy = str(json.load(f).get("proxy", "") or "").strip()
            if proxy:
                return proxy
    except Exception:
        pass
    for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return "http://127.0.0.1:7890"


PROXY = _load_proxy()
# 同一出口 IP 高频打 token endpoint 仍可能被 Cloudflare 节流，请求之间留间隔；
# 失败时指数退避重试（连接重置往往是瞬时的）。
INTERVAL_SEC = 3.0
MAX_RETRIES = 3

def is_expired(cpa_path: str) -> bool:
    """Check if CPA file's access_token is expired."""
    try:
        with open(cpa_path) as f:
            d = json.load(f)
        if d.get("expired"):
            return True
        expires_in = d.get("expires_in", 0) or 0
        last_refresh = d.get("last_refresh", "")
        if last_refresh:
            from datetime import datetime, timezone
            try:
                last = datetime.fromisoformat(last_refresh)
                now = datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
                elapsed = (now - last).total_seconds()
                return elapsed > expires_in * 0.8  # 80% of lifetime
            except:
                pass
        return False
    except:
        return True

def refresh_cpa(cpa_path: str, force: bool = False) -> bool:
    """Refresh one CPA file. Returns True on success."""
    try:
        with open(cpa_path) as f:
            d = json.load(f)
    except Exception as e:
        print(f"  ✗ {cpa_path}: can't read ({e})")
        return False

    if not force and not is_expired(cpa_path):
        print(f"  - {d.get('email','?')}: still valid, skip")
        return True

    refresh_token = d.get("refresh_token", "")
    if not refresh_token:
        print(f"  ✗ {d.get('email','?')}: no refresh_token")
        return False

    email = d.get("email", d.get("email", "?"))
    print(f"  ~ {email}: refreshing...", end=" ")
    sys.stdout.flush()

    try:
        last_err = None
        new_token = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                new_token = refresh_access_token(
                    refresh_token=refresh_token,
                    timeout=30.0,
                    proxy=PROXY,
                )
                break
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                transient = any(k in msg for k in ("reset", "timed out", "timeout", "connection", "503", "502", "429"))
                if attempt < MAX_RETRIES and transient:
                    backoff = 2 ** (attempt - 1) * 5
                    print(f"↻ retry {attempt}/{MAX_RETRIES} after {backoff}s ({msg[:60]})", end=" ", flush=True)
                    time.sleep(backoff)
                    continue
                raise
        # Save back
        redirect_uri = d.get("redirect_uri", "")
        save_cliproxyapi_auth_record(
            new_token,
            userinfo={"email": email, "sub": d.get("sub", "")},
            auth_dir=CPA_DIR,
            redirect_uri=redirect_uri,
            base_url=d.get("base_url", "https://cli-chat-proxy.grok.com/v1"),
            headers=d.get("headers"),
        )
        print("✓")
        return True
    except Exception as e:
        print(f"✗ {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Refresh expired CPA tokens")
    parser.add_argument("--force", action="store_true", help="Force refresh all")
    args = parser.parse_args()

    if not os.path.isdir(CPA_DIR):
        print(f"CPA directory '{CPA_DIR}' not found")
        return

    files = sorted(os.listdir(CPA_DIR))
    cpa_files = [f for f in files if f.startswith("xai-") and f.endswith(".json")]
    print(f"Found {len(cpa_files)} CPA files")

    success = 0
    fail = 0
    skipped = 0

    print(f"Using proxy: {PROXY} | interval={INTERVAL_SEC}s retries={MAX_RETRIES}")

    for i, fname in enumerate(cpa_files):
        path = os.path.join(CPA_DIR, fname)
        if args.force:
            if refresh_cpa(path, force=True):
                success += 1
            else:
                fail += 1
        else:
            if not is_expired(path):
                skipped += 1
                continue
            if refresh_cpa(path):
                success += 1
            else:
                fail += 1
        # 请求间隔，避免同出口 IP 高频打 token endpoint 被节流
        if i < len(cpa_files) - 1:
            time.sleep(INTERVAL_SEC)

    print(f"\nDone: {success} refreshed, {fail} failed, {skipped} skipped")

if __name__ == "__main__":
    main()
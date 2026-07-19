# -*- coding: utf-8 -*-
"""Convert registered accounts (no CPA yet) to CPA tokens via Playwright.

修复要点：
- 走代理（config.proxy → 环境变量 → 本机 7890）。auth.x.ai 在 Cloudflare 后面，
  国内直连逐个 reset，浏览器和 token 交换都必须走代理。
- 账号之间留间隔，避免同出口 IP 高频打 authorize 被节流。
- 失败时重试（瞬时 reset 常见）。
"""
import sys, os, json, time, argparse

from xai_oauth import login_with_playwright

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

CPA_DIR = "cpa_auth"
os.makedirs(CPA_DIR, exist_ok=True)


def _load_proxy() -> str:
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


INTERVAL_SEC = 5.0
MAX_RETRIES = 2  # 浏览器流程重试代价高，少试几次


def _parse_args():
    ap = argparse.ArgumentParser(description="Convert registered accounts → CPA via Playwright")
    ap.add_argument("--proxy", default="", help="覆盖代理，默认 config.proxy/7890")
    ap.add_argument("--only", default="", help="只转指定 email（调试用）")
    ap.add_argument("--headless", default="1", help="0=有头浏览器（调试Cloudflare）")
    ap.add_argument("--force", action="store_true", help="即使已有 CPA 文件也重新生成（建议配合 --only）")
    return ap.parse_args()


_args = _parse_args()
PROXY = _args.proxy.strip() or _load_proxy()
HEADLESS = _args.headless != "0"


# Collect all accounts from all accounts files (根目录 + accounts/ 子目录)
accounts = []
_accounts_dirs = ["", "accounts"]
for _adir in _accounts_dirs:
    try:
        names = os.listdir(_adir if _adir else ".")
    except OSError:
        continue
    for fname in sorted(names):
        if not fname.startswith("accounts_") or not fname.endswith(".txt"):
            continue
        path = os.path.join(_adir, fname) if _adir else fname
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("----")
                if len(parts) >= 3:
                    accounts.append({"email": parts[0], "password": parts[1], "sso": parts[2]})

# Deduplicate by email
seen = set()
unique = []
for a in accounts:
    if a["email"] not in seen:
        seen.add(a["email"])
        unique.append(a)
accounts = unique

# Only keep accounts without a CPA file yet
to_convert = []
for a in accounts:
    out = os.path.join(CPA_DIR, f"xai-{a['email']}.json")
    if _args.force or not os.path.exists(out):
        to_convert.append(a)

print(f"Total unique accounts: {len(accounts)}")
print(f"Already have CPA: {len(accounts) - len(to_convert)}")
print(f"To convert: {len(to_convert)}")
print(f"Using proxy: {PROXY} | headless={HEADLESS} | interval={INTERVAL_SEC}s retries={MAX_RETRIES}")
if _args.only:
    to_convert = [a for a in to_convert if a["email"] == _args.only]
    print(f"--only: filtered to {len(to_convert)}")
if not to_convert:
    print("Nothing to do.")
    sys.exit(0)

success = 0
fail = 0

for i, acct in enumerate(to_convert):
    email = acct["email"]
    pw = acct["password"]
    sso = acct["sso"]
    print(f"\n[{i+1}/{len(to_convert)}] {email}...", flush=True)

    done = False
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            login_with_playwright(
                email=email,
                password=pw,
                headless=HEADLESS,
                timeout=180.0,
                proxy=PROXY,
                session_cookies={"sso": sso},
                cliproxyapi_auth_dir=CPA_DIR,
                cliproxyapi_base_url="https://cli-chat-proxy.grok.com/v1",
            )
            print(f"  ✓ {email} — CPA saved")
            success += 1
            done = True
            break
        except Exception as e:
            msg = str(e)
            print(f"  ✗ attempt {attempt}/{MAX_RETRIES} — {msg[:150]}", flush=True)
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    if not done:
        fail += 1

    if i < len(to_convert) - 1:
        time.sleep(INTERVAL_SEC)

print(f"\n=== Done: {success} success, {fail} failed ===")

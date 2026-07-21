# -*- coding: utf-8 -*-
"""SSO → CPA 转换（device flow + DrissionPage 浏览器）。

与 convert_device.py 功能完全相同，但浏览器确认步骤用 DrissionPage
（真实 Chrome）代替 Playwright，避免被 accounts.x.ai 的 Cloudflare 检测。

用法：
    python convert_device_dp.py
    python convert_device_dp.py --only <email>
"""

import sys, os, json, time, argparse

from DrissionPage import Chromium, ChromiumOptions
from urllib.parse import urlparse

# 复用 convert_device 的 HTTP 函数
from convert_device import (
    discover, start_device_flow, poll_token, _jwt_subject, _load_proxy,
    CPA_DIR, LOOP_DEADLINE_SEC, POLL_WAIT_MS, CONSENT_WAIT_MS,
)
from xai_oauth import save_cliproxyapi_auth_record


def _click_visible(tab, texts):
    for t in texts:
        try:
            ele = tab.ele(t, timeout=2)
            if ele:
                ele.click()
                return True
        except Exception:
            continue
    return False


def confirm_in_browser_dp(verification_url: str, sso: str, proxy: str, timeout: float, user_code: str = "") -> None:
    """DrissionPage 版：打开 verification_url，注入 sso，自动点允许。"""
    options = ChromiumOptions()
    options.auto_port()
    options.set_argument("--disable-blink-features=AutomationControlled")
    options.set_argument("--window-size=1280,900")
    options.set_timeouts(base=1)
    if proxy:
        options.set_proxy(proxy)

    browser = Chromium(options)
    deadline = time.time() + timeout
    try:
        tab = browser.latest_tab

        # 先访问 x.ai 域，再注入 cookie（DrissionPage 需要先在同域下才能 set cookies）
        tab.get("https://accounts.x.ai/")
        time.sleep(1)
        tab.set.cookies([
            {"name": "sso", "value": sso, "domain": "accounts.x.ai", "path": "/", "secure": True, "httpOnly": True},
            {"name": "sso", "value": sso, "domain": ".x.ai", "path": "/", "secure": True, "httpOnly": True},
        ])
        time.sleep(0.5)

        # 抹掉 webdriver 标记
        tab.run_js("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")

        tab.get(verification_url)
        print(f"  [browser] 打开 verification_url: {verification_url[:90]}", flush=True)
        time.sleep(5)  # 等 Next.js 渲染

        consent_submitted = False
        code_submitted = False
        while time.time() < deadline:
            try:
                url = tab.url
                parsed = urlparse(url)
                # 用 JS 获取实际渲染文本
                text = ""
                try:
                    text = tab.run_js("return document.body.innerText;") or ""
                except Exception:
                    pass
                text_lower = (text or "").lower()

                # CF 拦截
                if "sorry, you have been blocked" in text_lower or "unable to access x.ai" in text_lower:
                    raise RuntimeError("Cloudflare 拦截 (blocked)，换节点")
                if "rate limit" in text_lower or "too many requests" in text_lower or "请求过于频繁" in text_lower:
                    raise RuntimeError("rate_limited")

                # 完成
                if "/oauth2/device/done" in parsed.path or "/oauth2/device/done" in url or "device authorized" in text_lower or "设备已授权" in text_lower or "登录成功" in text or "sign-in successful" in text_lower:
                    print(f"  [browser] ✓ device authorized", flush=True)
                    return

                # cookie 弹窗（优先处理）
                if _click_visible(tab, ("全部拒绝", "拒绝全部", "Reject all", "Reject All")):
                    time.sleep(0.5)
                    continue

                # consent 页 → 点允许
                if "/oauth2/device/consent" in parsed.path or "authorize grok build" in text_lower or "授权 grok build" in text_lower:
                    if not consent_submitted:
                        if _click_visible(tab, ("允许", "Allow", "Authorize", "Approve")):
                            consent_submitted = True
                            print(f"  [browser] 已点允许，等待 done…", flush=True)
                            time.sleep(CONSENT_WAIT_MS / 1000)
                            continue
                    time.sleep(POLL_WAIT_MS / 1000)
                    continue

                # device code 输入页（「输入终端中显示的代码」→ 点继续）
                if "输入终端中显示的代码" in text or "enter the code" in text_lower or "输入代码" in text:
                    if not code_submitted:
                        if _click_visible(tab, ("继续", "Continue", "Next", "提交")):
                            code_submitted = True
                            print(f"  [browser] 已点继续，等待 consent…", flush=True)
                            time.sleep(CONSENT_WAIT_MS / 1000)
                            continue
                    time.sleep(POLL_WAIT_MS / 1000)
                    continue

                time.sleep(POLL_WAIT_MS / 1000)
            except RuntimeError:
                raise
            except Exception:
                time.sleep(POLL_WAIT_MS / 1000)
        raise RuntimeError(f"browser confirm 超时 ({timeout}s)，最后 url={tab.url[:100]}")
    finally:
        try:
            browser.quit()
        except Exception:
            pass


def convert_one(email: str, password: str, sso: str, proxy: str) -> bool:
    print(f"  [1] discover…", flush=True)
    device_endpoint, token_endpoint = discover(proxy)

    print(f"  [2] start device authorization（带 sso）…", flush=True)
    flow = start_device_flow(device_endpoint, sso, proxy)
    print(f"      user_code={flow['user_code']}  interval={flow['interval']}s  expires_in={flow['expires_in']}s", flush=True)

    print(f"  [3] 浏览器确认 device flow (DrissionPage)…", flush=True)
    confirm_in_browser_dp(flow["verification_url"], sso, proxy, timeout=LOOP_DEADLINE_SEC, user_code=flow["user_code"])

    print(f"  [4] 轮询 token…", flush=True)
    token = poll_token(token_endpoint, flow, timeout=max(30.0, flow["expires_in"]), proxy=proxy)

    sub = _jwt_subject(token.get("id_token")) or _jwt_subject(token.get("access_token")) or token.get("sub", "")

    save_cliproxyapi_auth_record(
        token,
        userinfo={"email": email, "sub": sub},
        auth_dir=CPA_DIR,
        redirect_uri="",
        base_url="https://cli-chat-proxy.grok.com/v1",
        headers={
            "X-XAI-Token-Auth": "xai-grok-cli",
            "x-grok-client-version": "0.2.93",
            "x-grok-client-identifier": "grok-shell",
        },
    )
    print(f"  ✓ {email} — CPA saved (sub={sub})", flush=True)
    return True


def main():
    ap = argparse.ArgumentParser(description="SSO → CPA via OAuth device flow (DrissionPage)")
    ap.add_argument("--proxy", default="", help="覆盖代理")
    ap.add_argument("--only", default="", help="只转指定 email")
    args = ap.parse_args()

    proxy = args.proxy.strip() or _load_proxy()
    print(f"Using proxy: {proxy} | browser=DrissionPage | flow=device")

    accounts = []
    for adir in ("", "accounts"):
        try:
            names = os.listdir(adir if adir else ".")
        except OSError:
            continue
        for fname in sorted(names):
            if not fname.startswith("accounts_") or not fname.endswith(".txt"):
                continue
            path = os.path.join(adir, fname) if adir else fname
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("----")
                    if len(parts) >= 3:
                        accounts.append({"email": parts[0], "password": parts[1], "sso": parts[2]})

    seen = set()
    unique = []
    for a in accounts:
        if a["email"] not in seen:
            seen.add(a["email"])
            unique.append(a)

    to_convert = []
    for a in unique:
        if not os.path.exists(os.path.join(CPA_DIR, f"xai-{a['email']}.json")):
            to_convert.append(a)
    if args.only:
        to_convert = [a for a in to_convert if a["email"] == args.only]

    total = len(to_convert)
    already = len(unique) - total
    print(f"Total unique: {len(unique)} | Already CPA: {already} | To convert: {total}")

    success = 0
    for i, a in enumerate(to_convert, 1):
        print(f"\n[{i}/{total}] {a['email']}…", flush=True)
        try:
            if convert_one(a["email"], a["password"], a["sso"], proxy):
                success += 1
        except Exception as e:
            print(f"  ✗ {e}", flush=True)

    print(f"\n=== Done: {success} success, {total - success} failed ===")


if __name__ == "__main__":
    main()

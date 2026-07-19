# -*- coding: utf-8 -*-
"""SSO → CPA 转换（device flow）。

为什么另写一个：原 `convert_new4.py` 走 authorization-code flow（authorize → 点 Allow
→ 127.0.0.1/callback 收 code），但 xAI 已对该 client_id 的 redirect_uri 流程降级，
consent 页的 "Allow" 经常点不动（xAI 实际期望 device flow）。

本工具参考 grok-free-register-oss 的 xai_enroller，改用 OAuth device flow：
  1. HTTP POST /oauth2/device_authorization（带 sso cookie）→ 拿 device_code + user_code
     + verification_uri_complete（自带 user_code，浏览器打开无需手输）
  2. Playwright 打开 verification_uri_complete（注入 sso cookie + 走代理）
  3. 自动点「允许 / Allow」，直到 /oauth2/device/done 或「设备已授权」
  4. 轮询 /oauth2/token（grant_type=device_code）→ access_token + refresh_token
  5. 复用 xai_oauth.save_cliproxyapi_auth_record 输出 cpa_auth/xai-<email>.json

用法：
    python convert_device.py                 # 转所有还没 CPA 的账号
    python convert_device.py --only <email>  # 只转指定账号
    python convert_device.py --headless 0    # 有头浏览器（调试）
"""
import sys, os, json, time, argparse, base64, binascii
from urllib.parse import urlparse, urlencode

import requests

from xai_oauth import (
    ISSUER,
    TOKEN_ENDPOINT,
    DEFAULT_CLIENT_ID,
    DEFAULT_SCOPES,
    save_cliproxyapi_auth_record,
)

CPA_DIR = "cpa_auth"
os.makedirs(CPA_DIR, exist_ok=True)

DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

# 浏览器 confirm 循环时限（device flow 浏览器侧通常 <30s 完成）
LOOP_DEADLINE_SEC = 60.0
POLL_WAIT_MS = 250
CONSENT_WAIT_MS = 350


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


def _proxies(proxy: str):
    return {"http": proxy, "https": proxy} if proxy else None


def _jwt_subject(token: str) -> str:
    if not isinstance(token, str) or not token:
        return ""
    parts = token.split(".")
    if len(parts) != 3 or not parts[1]:
        return ""
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""
    if not isinstance(claims, dict):
        return ""
    for k in ("sub", "principal_id"):
        v = claims.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _allowed_url(url: str) -> bool:
    p = urlparse(url)
    return bool(p.hostname) and p.scheme == "https" and (
        p.hostname == "x.ai" or p.hostname.endswith(".x.ai")
    )


def discover(proxy: str) -> tuple:
    """返回 (device_authorization_endpoint, token_endpoint)。"""
    r = requests.get(DISCOVERY_URL, proxies=_proxies(proxy), timeout=30)
    if r.status_code // 100 != 2:
        raise RuntimeError(f"discovery rejected: HTTP {r.status_code}: {r.text[:200]}")
    doc = r.json()
    de = doc.get("device_authorization_endpoint")
    te = doc.get("token_endpoint", TOKEN_ENDPOINT)
    if not de or not te or not _allowed_url(de) or not _allowed_url(te):
        raise RuntimeError(f"discovery endpoints invalid: de={de} te={te}")
    return de, te


def start_device_flow(device_endpoint: str, sso: str, proxy: str) -> dict:
    """发起 device authorization，返回 {device_code, user_code, verification_url, interval, expires_in}。"""
    r = requests.post(
        device_endpoint,
        data={"client_id": DEFAULT_CLIENT_ID, "scope": " ".join(DEFAULT_SCOPES)},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": f"sso={sso}",
        },
        proxies=_proxies(proxy),
        timeout=30,
    )
    if r.status_code // 100 != 2:
        raise RuntimeError(f"device authorization rejected: HTTP {r.status_code}: {r.text[:300]}")
    doc = r.json()
    device_code = doc["device_code"]
    user_code = doc["user_code"]
    base_url = doc.get("verification_uri") or doc["verification_uri_complete"]
    if not _allowed_url(base_url):
        raise RuntimeError(f"verification url not allowed: {base_url}")
    verification_url = doc.get("verification_uri_complete")
    if not verification_url:
        sep = "&" if "?" in base_url else "?"
        verification_url = f"{base_url}{sep}{urlencode({'user_code': user_code})}"
    if not _allowed_url(verification_url):
        raise RuntimeError(f"verification complete url not allowed: {verification_url}")
    return {
        "device_code": device_code,
        "user_code": user_code,
        "verification_url": verification_url,
        "interval": float(doc.get("interval", 5.0)),
        "expires_in": int(doc.get("expires_in", 900)),
    }


def poll_token(token_endpoint: str, flow: dict, timeout: float, proxy: str) -> dict:
    """轮询 token endpoint 直到拿到 token 或超时。"""
    deadline = time.monotonic() + timeout
    interval = max(0.0, flow["interval"])
    last_err = None
    while time.monotonic() < deadline:
        try:
            r = requests.post(
                token_endpoint,
                data={
                    "client_id": DEFAULT_CLIENT_ID,
                    "device_code": flow["device_code"],
                    "grant_type": DEVICE_GRANT_TYPE,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                proxies=_proxies(proxy),
                timeout=30,
            )
            if r.status_code // 100 == 2:
                doc = r.json()
                if doc.get("access_token") and doc.get("refresh_token"):
                    return doc
                last_err = f"2xx but missing tokens: {doc}"
            else:
                try:
                    doc = r.json()
                except Exception:
                    doc = {"error": r.text[:200]}
                err = doc.get("error")
                if err in ("authorization_pending", "slow_down"):
                    if err == "slow_down":
                        interval += 1
                    time.sleep(interval)
                    continue
                if err == "access_denied":
                    raise RuntimeError("oauth_denied (用户拒绝)")
                if err == "expired_token":
                    raise RuntimeError("oauth_expired (device_code 过期)")
                last_err = f"HTTP {r.status_code}: {doc}"
        except requests.RequestException as e:
            last_err = f"network: {e}"
        time.sleep(max(interval, 1.0))
    raise RuntimeError(f"poll_token 超时: {last_err}")


def _click_visible_exact(page, names) -> bool:
    """点可见按钮（按 role=button + 精确文本）。"""
    for name in names:
        try:
            loc = page.get_by_role("button", name=name, exact=True)
            cnt = loc.count()
        except Exception:
            try:
                loc = page.get_by_role("button", name=name)
                cnt = loc.count()
            except Exception:
                continue
        for i in range(cnt):
            try:
                cand = loc.nth(i)
                if cand.is_visible():
                    cand.click(timeout=2000)
                    return True
            except Exception:
                continue
    return False


def confirm_in_browser(verification_url: str, sso: str, proxy: str, headless: bool, timeout: float, user_code: str = "") -> None:
    """打开 verification_url，注入 sso，自动点允许，直到 device done。"""
    from playwright.sync_api import sync_playwright

    # 优先用真实 Chrome（channel=chrome）而非 Playwright bundled Chromium，
    # 后者的自动化指纹容易被 accounts.x.ai 的 Cloudflare 直接 block。
    # 同时加反自动化启动参数。
    launch_kwargs = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    }
    # 系统装了真实 Chrome 就用它
    if os.name == "nt" and os.path.exists(r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        launch_kwargs["channel"] = "chrome"
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}

    deadline = time.time() + timeout
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
            )
            # 抹掉 navigator.webdriver 标记（CF 检测项之一）
            try:
                context.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                )
            except Exception:
                pass
            # sso cookie 注入到 accounts.x.ai + .x.ai 两个域
            cookies = []
            for name, value in (("sso", sso),):
                if not value:
                    continue
                cookies.append({"name": name, "value": value, "domain": "accounts.x.ai", "path": "/", "secure": True, "httpOnly": True})
                cookies.append({"name": name, "value": value, "domain": ".x.ai", "path": "/", "secure": True, "httpOnly": True})
            if cookies:
                try:
                    context.add_cookies(cookies)
                except Exception:
                    pass
            page = context.new_page()
            page.goto(verification_url, wait_until="domcontentloaded", timeout=60000)
            print(f"  [browser] 打开 verification_url: {verification_url[:90]}", flush=True)

            consent_submitted = False
            code_submitted = False
            while time.time() < deadline:
                try:
                    url = page.url
                    parsed = urlparse(url)
                    text = ""
                    try:
                        text = page.locator("body").inner_text(timeout=2000)
                    except Exception:
                        pass
                    text_lower = (text or "").lower()

                    # CF 拦截
                    if "sorry, you have been blocked" in text_lower or "unable to access x.ai" in text_lower:
                        raise RuntimeError("Cloudflare 拦截 (blocked)，换节点")
                    # rate limit
                    if "rate limit" in text_lower or "too many requests" in text_lower or "请求过于频繁" in text_lower:
                        raise RuntimeError("rate_limited")

                    # 完成
                    if "/oauth2/device/done" in parsed.path or "device authorized" in text_lower or "设备已授权" in text_lower:
                        print(f"  [browser] ✓ device authorized", flush=True)
                        return

                    # consent 页 → 点允许
                    if "/oauth2/device/consent" in parsed.path or "authorize grok build" in text_lower or "授权 grok build" in text_lower:
                        if not consent_submitted:
                            if _click_visible_exact(page, ("允许", "Allow", "Authorize", "Approve")):
                                consent_submitted = True
                                print(f"  [browser] 已点允许，等待 done…", flush=True)
                                page.wait_for_timeout(CONSENT_WAIT_MS)
                                continue
                        page.wait_for_timeout(POLL_WAIT_MS)
                        continue

                    # 需要输入 user_code（verification_uri_complete 一般自带，跳过这步）
                    code_input = page.locator('input[name="user_code"]')
                    try:
                        cnt = code_input.count()
                    except Exception:
                        cnt = 0
                    if cnt and code_input.first.is_visible():
                        if not code_submitted:
                            try:
                                cur = code_input.first.input_value()
                            except Exception:
                                cur = ""
                            want = (user_code or "").replace("-", "")
                            if want and want not in cur.replace("-", ""):
                                try:
                                    code_input.first.fill(user_code, timeout=2000)
                                except Exception:
                                    pass
                            submit = page.locator('button[type="submit"], input[type="submit"]')
                            if submit.count():
                                try:
                                    submit.first.click(timeout=2000)
                                    code_submitted = True
                                except Exception:
                                    pass
                        page.wait_for_timeout(POLL_WAIT_MS)
                        continue

                    # cookie 弹窗
                    if _click_visible_exact(page, ("全部拒绝", "拒绝全部", "Reject all", "Reject All")):
                        page.wait_for_timeout(250)
                        continue

                    page.wait_for_timeout(POLL_WAIT_MS)
                except RuntimeError:
                    raise
                except Exception:
                    page.wait_for_timeout(POLL_WAIT_MS)
            raise RuntimeError(f"browser confirm 超时 ({timeout}s)，最后 url={page.url[:100]}")
        finally:
            try:
                browser.close()
            except Exception:
                pass


def convert_one(email: str, password: str, sso: str, proxy: str, headless: bool) -> bool:
    print(f"  [1] discover…", flush=True)
    device_endpoint, token_endpoint = discover(proxy)

    print(f"  [2] start device authorization（带 sso）…", flush=True)
    flow = start_device_flow(device_endpoint, sso, proxy)
    print(f"      user_code={flow['user_code']}  interval={flow['interval']}s  expires_in={flow['expires_in']}s", flush=True)

    print(f"  [3] 浏览器确认 device flow…", flush=True)
    confirm_in_browser(flow["verification_url"], sso, proxy, headless, timeout=LOOP_DEADLINE_SEC, user_code=flow["user_code"])

    print(f"  [4] 轮询 token…", flush=True)
    token = poll_token(token_endpoint, flow, timeout=max(30.0, flow["expires_in"]), proxy=proxy)

    # sub
    sub = _jwt_subject(token.get("id_token")) or _jwt_subject(token.get("access_token")) or token.get("sub", "")

    save_cliproxyapi_auth_record(
        token,
        userinfo={"email": email, "sub": sub},
        auth_dir=CPA_DIR,
        redirect_uri="",  # device flow 无 redirect_uri
        base_url="https://cli-chat-proxy.grok.com/v1",
        headers={
            "X-XAI-Token-Auth": "xai-grok-cli",
            "x-grok-client-version": "0.2.93",
            "x-grok-client-identifier": "grok-shell",
        },
    )
    print(f"  ✓ {email} — CPA saved (sub={sub})", flush=True)
    return True


def _parse_args():
    ap = argparse.ArgumentParser(description="SSO → CPA via OAuth device flow")
    ap.add_argument("--proxy", default="", help="覆盖代理（默认 config.proxy/7890）")
    ap.add_argument("--only", default="", help="只转指定 email")
    ap.add_argument("--headless", default="1", help="0=有头浏览器（调试）")
    return ap.parse_args()


def main():
    args = _parse_args()
    proxy = args.proxy.strip() or _load_proxy()
    headless = args.headless != "0"
    print(f"Using proxy: {proxy} | headless={headless} | flow=device")

    # 扫描账号（根目录 + accounts/ 子目录），同 convert_new4.py
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
    # 去重
    seen = set()
    unique = []
    for a in accounts:
        if a["email"] not in seen:
            seen.add(a["email"])
            unique.append(a)
    # 只转没 CPA 的
    to_convert = []
    for a in unique:
        if not os.path.exists(os.path.join(CPA_DIR, f"xai-{a['email']}.json")):
            to_convert.append(a)
    if args.only:
        to_convert = [a for a in to_convert if a["email"] == args.only]

    print(f"Total unique: {len(unique)} | Already CPA: {len(unique)-len(to_convert)} | To convert: {len(to_convert)}")
    if not to_convert:
        print("Nothing to do.")
        return

    success = fail = 0
    for i, acct in enumerate(to_convert):
        print(f"\n[{i+1}/{len(to_convert)}] {acct['email']}…", flush=True)
        try:
            convert_one(acct["email"], acct["password"], acct["sso"], proxy, headless)
            success += 1
        except Exception as e:
            print(f"  ✗ {e}", flush=True)
            fail += 1
        if i < len(to_convert) - 1:
            time.sleep(3.0)
    print(f"\n=== Done: {success} success, {fail} failed ===")


if __name__ == "__main__":
    main()

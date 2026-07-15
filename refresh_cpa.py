#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用账号密码重新登录 x.ai，获取新 SSO cookie → OAuth token → 刷新 CPA 凭证
"""

import sys, os, json, hashlib, base64, secrets, re, time, urllib.parse
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

# ── 配置 ──────────────────────────────────────────────────
ACCOUNTS_FILE = "all_accounts.txt"
CPA_AUTH_DIR = "./cpa_auth"
PROXY = "http://127.0.0.1:7890"

# OAuth
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
OIDC_ISSUER = "https://auth.x.ai"
REDIRECT_URI = "http://127.0.0.1:56121/callback"
GROK_VERSION = "0.2.93"
GROK_TOKEN_UA = f"grok-pager/{GROK_VERSION} grok-shell/{GROK_VERSION} (linux; x86_64)"
TOKEN_ENDPOINT = f"{OIDC_ISSUER}/oauth2/token"

# ── YYDS Email API ────────────────────────────────────────
YYDS_API_KEY = ""
YYDS_BASE = "https://maliapi.215.im/v1"

def _load_config():
    global YYDS_API_KEY
    with open("config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    YYDS_API_KEY = cfg.get("yyds_api_key", "")

def yyds_get_otp(email: str, timeout: int = 60) -> str | None:
    """从 YYDS 邮箱获取最新验证码（x.ai 格式: XXX-XXX）"""
    from curl_cffi import requests
    headers = {"X-API-Key": YYDS_API_KEY, "Content-Type": "application/json"}
    yyds_proxies = None  # 直连

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{YYDS_BASE}/messages", headers=headers, proxies=yyds_proxies,
                                params={"address": email, "limit": 5}, timeout=15)
            if resp.status_code != 200:
                time.sleep(5)
                continue
            data = resp.json()
            if not data.get("success"):
                time.sleep(5)
                continue
            msgs = data.get("data", {}).get("messages", [])
            if not msgs:
                time.sleep(5)
                continue
            for mail in msgs:
                code = mail.get("verificationCode", "")
                if code and len(code) >= 5:
                    print(f"  [OTP] 从邮件「{mail.get('subject','')}」获取验证码: {code}")
                    return code
                # 读详情
                msg_id = mail.get("id")
                if msg_id:
                    try:
                        rd = requests.get(f"{YYDS_BASE}/messages/{msg_id}", headers=headers, proxies=yyds_proxies, timeout=10)
                        if rd.status_code == 200:
                            detail = rd.json().get("data", {})
                            code = detail.get("verificationCode", "")
                            if code and len(code) >= 5:
                                print(f"  [OTP] 从详情获取验证码: {code}")
                                return code
                            text = detail.get("text", "") or ""
                            html = detail.get("html", "") or ""
                            if isinstance(text, list): text = " ".join(str(x) for x in text)
                            if isinstance(html, list): html = " ".join(str(x) for x in html)
                            content = text + html
                            # XXX-XXX 格式
                            m = re.search(r'[A-Za-z0-9]{3}[- ][A-Za-z0-9]{3}', content)
                            if m:
                                code = m.group(0).replace(" ", "-")
                                print(f"  [OTP] 从内容提取验证码: {code}")
                                return code
                    except:
                        pass
        except Exception as e:
            print(f"  [OTP] 请求异常: {e}")
        time.sleep(5)
    return None

# ── OAuth 工具函数 ─────────────────────────────────────────
def pkce_challenge() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge

def exchange_code_for_token(code: str, verifier: str) -> dict | None:
    from curl_cffi import requests
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": verifier,
    })
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": GROK_TOKEN_UA,
        "X-Grok-Client-Version": GROK_VERSION,
        "Accept": "*/*",
    }
    proxies = {"http": PROXY, "https": PROXY} if PROXY else None
    try:
        r = requests.post(TOKEN_ENDPOINT, data=data, headers=headers,
                          impersonate="chrome", timeout=15, proxies=proxies)
        if r.status_code == 200:
            return r.json()
        print(f"  [ERROR] 换 token 失败 HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  [ERROR] 换 token 异常: {e}")
    return None

def decode_jwt(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    try:
        payload = parts[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except:
        return {}

# ── 登录 → 拿 OAuth token ─────────────────────────────────
def login_and_get_token(email: str, password: str) -> dict | None:
    """通过浏览器登录 x.ai，拿到 OAuth token"""
    from DrissionPage import Chromium, ChromiumOptions

    options = ChromiumOptions()
    options.auto_port()
    options.set_proxy(PROXY)
    browser = Chromium(options)
    tab = browser.new_tab()

    try:
        # 1. 打开注册页
        print("  [1] 打开 accounts.x.ai ...")
        tab.get("https://accounts.x.ai/sign-up?redirect=grok-com")
        time.sleep(5)

        # 2. 拒绝 Cookie
        tab.run_js('document.querySelectorAll("button").forEach(b => { if(b.innerText.includes("全部拒绝")) b.click(); })')
        time.sleep(2)

        # 3. 点击「使用邮箱注册」
        tab.run_js('document.querySelectorAll("button").forEach(b => { const t = (b.innerText||"").replace(/\\s+/g,""); if(t.includes("使用邮箱注册")) b.click(); })')
        time.sleep(3)

        # 4. 输入邮箱
        print(f"  [2] 输入邮箱: {email}")
        tab.run_js('const input = document.querySelector("input[name=email]"); if(input) { const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set; setter.call(input, arguments[0]); input.dispatchEvent(new Event("input", {bubbles:true})); input.dispatchEvent(new Event("change", {bubbles:true})); }', email)
        time.sleep(1)

        # 5. 点击「注册」
        tab.run_js('const btn = Array.from(document.querySelectorAll("button")).find(b => { const t = (b.innerText||"").replace(/\\s+/g,""); return t.includes("注册") && !t.includes("使用"); }); if(btn) { btn.click(); }')
        print("  [3] 等待 OTP 验证码邮件...")

        # 6. 等 OTP 邮件
        otp = yyds_get_otp(email, timeout=90)
        if not otp:
            print("  [ERROR] 未获取到 OTP 验证码")
            return None
        print(f"  [4] 输入验证码: {otp}")

        # 7. 输入 OTP
        time.sleep(2)
        tab.run_js('const inputs = document.querySelectorAll("input"); for(const inp of inputs) { if(inp.type === "text" || inp.type === "tel" || !inp.type) { inp.value = ""; }}')
        for i, ch in enumerate(otp):
            tab.run_js(f'const inputs = document.querySelectorAll("input"); for(const inp of inputs) {{ if(inp.type === "text" || inp.type === "tel" || !inp.type) {{ if(inp.value === "" || inp.value.length === {i}) {{ inp.value = arguments[0]; inp.dispatchEvent(new Event("input", {{bubbles:true}})); break; }} }} }}', ch)
            time.sleep(0.3)

        # 8. 等待登录完成
        time.sleep(5)
        current_url = tab.url
        print(f"  [5] 登录后 URL: {current_url}")

        # 9. 提取新 SSO cookie
        cookies = tab.cookies()
        sso_cookie = ""
        for c in cookies:
            if c.get("name") == "__Secure-xai-sso":
                sso_cookie = c.get("value", "")
                break
        if not sso_cookie:
            print("  [ERROR] 未获取到 SSO cookie")
            return None
        print(f"  [6] 获取到新 SSO cookie (前20字): {sso_cookie[:20]}...")

        # 10. 验证 SSO 有效，导航到 grok
        tab.get("https://grok.com/")
        time.sleep(5)

        # 11. 从浏览器获取 grok.com 的 SSO cookie
        cookies = tab.cookies()
        grok_sso = ""
        for c in cookies:
            if c.get("name") == "__Secure-xai-sso":
                grok_sso = c.get("value", "")
                break
        if grok_sso:
            sso_cookie = grok_sso
            print(f"  [7] grok.com SSO cookie: {sso_cookie[:20]}...")

        # 12. 通过浏览器完成授权码流程
        # 构建 authorize URL
        verifier, challenge = pkce_challenge()
        params = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "refresh_state",
            "referrer": "grok-build",
        })
        auth_url = f"{OIDC_ISSUER}/oauth2/authorize?{params}"
        print(f"  [8] 访问 authorize ...")
        tab.get(auth_url)
        time.sleep(5)

        # 检查是否被重定向到 redirect_uri（有 code）
        final_url = tab.url
        print(f"  [9] authorize 后 URL: {final_url}")

        auth_code = ""
        if final_url.startswith(REDIRECT_URI):
            qs = urllib.parse.urlparse(final_url).query
            qp = urllib.parse.parse_qs(qs)
            auth_code = qp.get("code", [""])[0]
        else:
            # 可能页面上有确认按钮
            print("  [10] 尝试点击授权确认...")
            # 找「确认」「允许」「Authorize」等按钮
            tab.run_js('document.querySelectorAll("button, input[type=submit], a").forEach(el => { const t = (el.innerText||el.value||"").toLowerCase(); if(t.includes("confirm") || t.includes("allow") || t.includes("authorize") || t.includes("同意") || t.includes("确认") || t.includes("注册")) { el.click(); } })')
            time.sleep(5)
            final_url = tab.url
            print(f"  [11] 点击后 URL: {final_url}")
            if final_url.startswith(REDIRECT_URI):
                qs = urllib.parse.urlparse(final_url).query
                qp = urllib.parse.parse_qs(qs)
                auth_code = qp.get("code", [""])[0]

        if not auth_code:
            # 尝试从页面内容提取
            body_text = tab("tag:body").text or ""
            print(f"  [12] 页面内容: {body_text[:500]}")
            browser.quit()
            return None

        print(f"  [13] 获取到 authorization code: {auth_code[:20]}...")

        # 13. 换 token
        token = exchange_code_for_token(auth_code, verifier)
        if token:
            print(f"  [14] ✅ 获取到新 token, expires_in={token.get('expires_in')}")
        return token

    finally:
        browser.quit()

# ── 主流程 ──────────────────────────────────────────────────
def main():
    _load_config()

    if not os.path.exists(ACCOUNTS_FILE):
        print(f"❌ 未找到 {ACCOUNTS_FILE}")
        return

    with open(ACCOUNTS_FILE, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    success = 0
    for line in lines:
        parts = line.split("----")
        if len(parts) < 2:
            continue
        email = parts[0]
        password = parts[1]
        print(f"\n{'='*50}")
        print(f"处理: {email}")

        token = login_and_get_token(email, password)
        if not token:
            print(f"  ❌ {email} 失败")
            continue

        # 构建 CPA record
        access = token.get("access_token") or token.get("key") or ""
        refresh = token.get("refresh_token") or ""
        payload = decode_jwt(access)
        user_id = payload.get("sub") or payload.get("principal_id") or ""
        principal_id = payload.get("principal_id") or user_id
        principal_type = payload.get("principal_type") or "User"
        expires_in = token.get("expires_in", 21600)
        expired = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z") if not token.get("expired") else token["expired"]

        record = {
            "email": email,
            "access_token": access,
            "refresh_token": refresh,
            "token_type": token.get("token_type", "Bearer"),
            "expires_in": expires_in,
            "expired": expired,
            "principal_id": principal_id,
            "principal_type": principal_type,
            "user_id": user_id,
            "oidc_issuer": OIDC_ISSUER,
            "oidc_client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "token_endpoint": TOKEN_ENDPOINT,
            "referrer": "grok-build",
        }

        # 写 CPA 文件
        os.makedirs(CPA_AUTH_DIR, exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', email)
        filepath = os.path.join(CPA_AUTH_DIR, f"xai-{safe_name}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        print(f"  ✅ 已保存: {filepath}")
        success += 1

    print(f"\n{'='*50}")
    print(f"完成: {success}/{len(lines)} 成功")

if __name__ == "__main__":
    main()
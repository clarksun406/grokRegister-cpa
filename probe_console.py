# -*- coding: utf-8 -*-
"""注入 sso+sso-rw 打开 grok.com，浏览器保持开着供人工通过 CF 挑战 + 点激活。

用法: python probe_console.py <email> [url] [minutes]
"""
import sys, os, time

email = sys.argv[1] if len(sys.argv) > 1 else "q0f5lwdubq@91.txvlogvip.top"
url = sys.argv[2] if len(sys.argv) > 2 else "https://grok.com/"
minutes = int(sys.argv[3]) if len(sys.argv) > 3 else 10

sso = None
for adir in ("", "accounts"):
    try:
        names = os.listdir(adir if adir else ".")
    except OSError:
        continue
    for fn in names:
        if fn.startswith("accounts_") and fn.endswith(".txt"):
            with open(os.path.join(adir, fn) if adir else fn, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("----")
                    if len(parts) >= 3 and parts[0] == email:
                        sso = parts[2]
                        break
            if sso: break
    if sso: break

if not sso:
    print(f"找不到 {email} 的 sso"); sys.exit(1)
print(f"email={email}  url={url}  保持 {minutes} 分钟")
print(">>> 浏览器打开后，请在窗口里手动通过 Cloudflare 挑战，然后去点 Grok Build 激活 <<<")

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(
        headless=False,
        channel="chrome" if os.path.exists(r"C:\Program Files\Google\Chrome\Application\chrome.exe") else None,
        proxy={"server": "http://127.0.0.1:7890"},
        args=["--disable-blink-features=AutomationControlled"],
    )
    c = b.new_context(viewport={"width": 1280, "height": 900})
    c.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
    cookies = []
    for name in ("sso", "sso-rw"):
        cookies.append({"name": name, "value": sso, "domain": "accounts.x.ai", "path": "/", "secure": True, "httpOnly": True})
        cookies.append({"name": name, "value": sso, "domain": ".x.ai", "path": "/", "secure": True, "httpOnly": True})
    c.add_cookies(cookies)
    page = c.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    print(f"初始 URL: {page.url} | title: {page.title()}")
    time.sleep(minutes * 60)
    b.close()

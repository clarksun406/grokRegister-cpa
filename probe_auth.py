# -*- coding: utf-8 -*-
"""探针：测当前出口 IP 能否通过 auth.x.ai 的 Cloudflare 浏览器挑战。

用途：Clash 切节点后，先跑这个确认节点是否"干净"（authorize 页面 200），
再批量跑 convert_new4.py，避免一次把 3 个账号都撞在脏 IP 上失败。

Usage:
    python probe_auth.py                 # 用 config.proxy / 7890
    python probe_auth.py --proxy http://127.0.0.1:7890
"""
import argparse, json, os


def load_proxy(override: str = "") -> str:
    if override.strip():
        return override.strip()
    try:
        with open(os.path.join(os.path.dirname(__file__), "config.json"), encoding="utf-8") as f:
            p = str(json.load(f).get("proxy", "") or "").strip()
            if p:
                return p
    except Exception:
        pass
    return "http://127.0.0.1:7890"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", default="")
    args = ap.parse_args()
    proxy = load_proxy(args.proxy)
    print(f"proxy = {proxy}")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, proxy={"server": proxy})
        ctx = b.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"),
            viewport={"width": 1280, "height": 900},
        )
        pg = ctx.new_page()
        url = ("https://auth.x.ai/oauth2/authorize?client_id=b1a00492-073a-47ea-816f-4c329264a828"
               "&response_type=code&redirect_uri=http://127.0.0.1:8765/callback&scope=openid")
        try:
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = resp.status if resp else None
            title = pg.title()
            print(f"status = {status}")
            print(f"title  = {title}")
            print(f"url    = {pg.url[:100]}")
            # 判断是否被 Cloudflare 浏览器挑战拦截：
            #   被拦 → 403 + title 含 "cloudflare" / "Attention Required"
            #   没被拦 → 重定向到本地回调（127.0.0.1:port）或显示登录/consent 页，
            #            status 可能是 200/302/4xx(OAuth 参数错误)，但都不是 Cloudflare 挑战页
            blocked = (status == 403) or ("cloudflare" in title.lower()) or ("attention required" in title.lower())
            if not blocked:
                print("\n✅ 节点干净（未被 Cloudflare 挑战拦截），可以跑 convert_new4.py")
                return 0
            else:
                print("\n❌ 被 Cloudflare 拦截（403/挑战），换个节点再来")
                return 1
        except Exception as e:
            print(f"ERR {str(e)[:200]}")
            print("\n❌ 连接失败，检查代理是否通 / 节点是否活")
            return 1
        finally:
            b.close()


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""补救 7 个 refresh_token 被吊销但 sso 仍有效的账号：
删旧 CPA → device flow 重转 → 测 chat 确认复活。

Usage:
    python rescue_revoked.py              # 跑默认 7 个
    python rescue_revoked.py --headless 0 # 有头浏览器看流程
"""
import argparse, os, sys, subprocess, time
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# 07-19 晚补齐、refresh 已被吊销但 sso 验证有效的 7 个
TARGETS = [
    "1x92tlqhwq@a.bdbdjx.top",
    "2tnyaej7er@a.bdbdjx.top",
    "93glvafgw3@215.singledog.net",
    "i2ejrugnjz@215.singledog.net",
    "kco5k6m8t1@91.txvlogvip.top",
    "kswqjx63h2@91.txvlogvip.top",
    "ztngd6lx6y@215.singledog.net",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", default="1")
    args = ap.parse_args()
    py = sys.executable
    cpa_dir = "cpa_auth"
    rescued = []
    failed = []
    for i, email in enumerate(TARGETS):
        print(f"\n========== [{i+1}/{len(TARGETS)}] {email} ==========", flush=True)
        cpa_file = os.path.join(cpa_dir, f"xai-{email}.json")
        if os.path.exists(cpa_file):
            os.remove(cpa_file)
            print(f"  deleted old CPA: {cpa_file}")
        # device flow 重转
        r = subprocess.run([py, "convert_device.py", "--only", email, "--headless", args.headless],
                           cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
                           encoding="utf-8", errors="replace")
        if r.returncode != 0 or not os.path.exists(cpa_file):
            print(f"  ✗ convert failed for {email}")
            failed.append(email)
            continue
        # 测 chat（先刷新一次确保用新 token，再 probe）
        print(f"  convert ok, probing chat...", flush=True)
        r2 = subprocess.run([py, "probe_chat.py", "--no-refresh", cpa_file],
                            cwd=os.path.dirname(os.path.abspath(__file__)) or ".",
                            capture_output=True, encoding="utf-8", errors="replace")
        out = (r2.stdout or "") + (r2.stderr or "")
        # 取最后一行汇总里的状态
        line = [l for l in out.splitlines() if l.strip().startswith("→ ")]
        status = line[-1].strip() if line else "(no status line)"
        print(f"  {status}")
        if "200" in status:
            rescued.append(email)
        else:
            failed.append((email, status))
        if i < len(TARGETS) - 1:
            time.sleep(3)
    print("\n========== 汇总 ==========")
    print(f"复活成功 ({len(rescued)}): {rescued}")
    print(f"失败 ({len(failed)}): {failed}")


if __name__ == "__main__":
    main()

# 使用手册 — grokRegister-cpa

> 日常操作速查。完整背景/根因/交接看 `HANDOFF_20260719.md`，总流程看 `FLOW.md`。

## 前置

1. **Clash/Mihomo 开着**，代理 `http://127.0.0.1:7890`（`config.json` 的 `proxy`），选**住宅 IP 节点**最佳
2. 真实 Chrome 装在默认路径（`C:\Program Files\Google\Chrome\Application\chrome.exe`）——device flow 转换要用
3. 所有命令加 `PYTHONIOENCODING=utf-8`，否则 Windows GBK 会让中文日志崩

---

## 三个核心命令

### 1. 注册账号 → 拿 SSO

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u grok_register_ttk.py cli
```
- 数量由 `config.json` 的 `register_count` 控制（跑前改）
- 域名自动从白名单轮换：`215.singledog.net` / `91.txvlogvip.top` / `a.bdbdjx.top`
- 交互式，启动后输入 `start`
- 输出：`accounts/accounts_<日期>_<时间>.txt`，每行 `email----password----sso_cookie`
- NSFW（`set_birth_date`）常被 grok.com CF 403，**不影响账号**，sso 照拿

### 2. SSO → CPA（device flow，**生产用**）

```bash
# 转所有还没 CPA 的账号（推荐有头）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u convert_device.py --headless 0

# 只转指定账号
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u convert_device.py --only <email> --headless 0
```
- **必须 `--headless 0`**，headless 必被 Cloudflare block
- 输出：`cpa_auth/xai-<email>.json`
- 每个账号 ~8-13s（有头真实 Chrome）
- 自动扫 `accounts/` 子目录 + 根目录所有 `accounts_*.txt`，去重，只转没 CPA 的

### 3. 日常刷新 token（纯 HTTP，不走浏览器）

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u refresh_cpa.py          # 只刷过期的
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u refresh_cpa.py --force  # 强制全刷
```
- 用 refresh_token POST `/oauth2/token`，1 秒/个
- access_token 6 小时有效，建议每 4-6 小时刷一次

---

## 报错处理速查

| 报错 | 处理 |
|---|---|
| `Cloudflare 拦截 (blocked)`（device flow 浏览器侧） | **换节点**（住宅 IP） |
| `ConnectionResetError 10054` / `SSL EOF` / `Max retries exceeded`（refresh 或 device 请求侧） | **冷却 60s 再跑**，通常继续就成功 |
| refresh `invalid_grant: Refresh token has been revoked` | sso 还在就能复活：删掉该 CPA 文件，`convert_device.py --only <email> --headless 0` 重转 |
| `probe_auth.py` 说"节点干净"但转换仍被 block | probe 不可信（只测 authorize 能否到达，测不出 device/consent 提交级拦截），以实际转换为 |

---

## 批量转换遇到 ConnectionReset 怎么办

`convert_device.py` / `refresh_cpa.py --force` 批量跑时，代理出口被高频打 reset 是常态。**不要换节点**，直接：
```bash
sleep 60  # 冷却
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u convert_device.py --headless 0
# 它会自动只转还没 CPA 的，已成功的跳过
```
反复跑直到 `To convert: 0`。

---

## 复活被吊销的账号

xAI 会批量吊销早期账号的 refresh_token（`refresh_cpa.py` 报 `revoked`）。只要 sso cookie 还在 `accounts/` 文件里，就能用 device flow 重转拿全新 token：

```bash
# 找出 refresh 被吊销的账号（refresh_cpa --force 看报错）
# 删掉它们的 CPA 文件
rm "cpa_auth/xai-<email>.json"
# 重转
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u convert_device.py --headless 0
```

实测 07-14 注册（5 天前）的 sso 仍有效，17 个被吊销账号全部复活。

---

## 目录结构

```
grokRegister-cpa/
├── grok_register_ttk.py   # 注册账号
├── convert_device.py       # SSO→CPA（device flow，生产用）★
├── refresh_cpa.py          # CPA 日常刷新
├── probe_auth.py           # 节点探针（仅参考，不可信）
├── probe_console.py        # 注入 sso 打开 console/grok 的诊断脚本
├── xai_oauth.py            # OAuth 核心模块 + CPA 文件读写
├── config.json             # proxy / register_count / yyds 配置
├── accounts/accounts_*.txt # 注册记录（email----password----sso）
├── cpa_auth/xai-*.json     # ★可用 CPA（chat 200，grok-4.5-build-free）
├── cpa_auth_403/xai-*.json # 10 个废号（chat 403，无 free 额度，搁置）
├── HANDOFF_20260719.md     # 交接文档（背景/根因/改动清单）
├── CHAT_403_20260719.md    # 10 个 chat 403 废号调查记录
├── USAGE.md                # 本文件
└── FLOW.md                 # 总流程图
```

> **`cpa_auth/` vs `cpa_auth_403/`**：上游网关只加载 `cpa_auth/`（38 个可用）。403 废号挪到 `cpa_auth_403/` 避免误调触发告警；其 token 本身有效（models 接口 200），只是账号无 Grok Build free 额度（chat 403）。若日后用住宅 IP 在 grok.com 手工激活成功，可挪回 `cpa_auth/`。

## 废弃脚本（勿用，保留作参考）

- `convert_new4.py` — 旧 auth-code flow，consent 卡死，被 device flow 取代
- `manual_convert_cpa.py` — 07-18 人工点 Allow 的工具，同上废弃

## 当前状态（2026-07-19）

- 账号 33 / CPA 33 / 待转 0
- 所有 CPA 带 `grok-build` referrer + `conversations:read/write` + `grok-cli:access` + `api:access`

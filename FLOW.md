# Grok Register CPA — 完整流程说明

## 总览

```
注册账号 ──→ 获取 SSO cookie ──→ 转换为 CPA token ──→ 日常刷新
```

## ⚠️ 必须走代理

`auth.x.ai` 在 Cloudflare 后面，国内**直连会被逐个 reset**——表现是"第1个请求能过、后面同 IP `ERR_CONNECTION_CLOSED`"。
这不是 headless 浏览器被限流，而是没走代理、出口被 Cloudflare/GFW 干扰。

- **token endpoint**（`/oauth2/token`，refresh 用）：纯 POST，不跑 JS 挑战 → 走代理后稳定通过
- **authorize 页面**（`/oauth2/authorize`，新转 CPA 用）：受 Cloudflare 浏览器挑战保护 → 需要**干净出口 IP**（住宅节点最佳，机房 IP 易被 403）

所有脚本统一从 `config.json` 的 `proxy` 读代理（默认 `http://127.0.0.1:7890`），fallback 到环境变量 `HTTPS_PROXY`，再 fallback 到本机 7890。
**确保 Clash/Mihomo 已开并选好节点再跑。**

---

## 第一步：注册账号（获取 SSO）

**脚本：** `grok_register_ttk.py`

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u grok_register_ttk.py
```

**输出：** `accounts_<日期>_<时间>.txt`

格式：每行一个账号，`email----password----sso_cookie`

**注意：**
- 注册时自动走 TURNSTILE / 邮箱验证码
- 如需代理，在 `config.json` 中设置 `proxy`（默认 `http://127.0.0.1:7890`）
- 邮箱提供商在 `config.json` 中设置 `email_provider`（如 `yyds`）

---

## 第二步：SSO 转 CPA（必须运行一次）

**脚本：** `batch_convert_cpa.py`（批量）或 `convert_new4.py`（只转缺 CPA 的）

```bash
# 批量：转所有 accounts_*.txt
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u batch_convert_cpa.py

# 只转还没 CPA 的（推荐，自动去重 + 接代理 + 重试）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u convert_new4.py

# 调试单个账号
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u convert_new4.py --only <email>
# 有头浏览器看 Cloudflare 拦截情况
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u convert_new4.py --only <email> --headless 0
```

**作用：** 读取所有 `accounts_*.txt`，将每个账号的 SSO cookie 通过 Playwright 浏览器转换为 CPA token。

**输出：** `cpa_auth/xai-<email>.json`

**原理：**
1. 启动本地 HTTP 回调服务器
2. 用 Playwright 打开无头 Chromium（**走代理**）
3. 注入 SSO cookie 到浏览器
4. 自动导航到 OAuth authorize 页面
5. 自动点击"允许"按钮（consent）
6. 获取 authorization code
7. 交换为 access_token + refresh_token
8. 保存为 CPA JSON 文件

**前置：authorize 页面受 Cloudflare 浏览器挑战保护，出口 IP 被标记会直接 403。**
转之前先跑节点探针确认干净：

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u probe_auth.py
# ✅ 节点干净 → 可转
# ❌ 被 Cloudflare 拦截 → Clash 换节点（优先住宅 IP）再测
```

**注意：** 首次运行需要安装 Playwright 浏览器（已安装）。

### consent 卡住时人工转换

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -u manual_convert_cpa.py <email>
```

需要明确绕过 `config.json` 的代理、直接使用系统网络/WARP 时：

```powershell
.\.venv\Scripts\python.exe -u manual_convert_cpa.py <email> --direct
```

脚本打开有头浏览器后，等待 consent 页面稳定 2–3 秒，只手动点击一次
“允许 / Allow”。该入口禁用硬编码 Server Action 和自动连点，成功后会校验
`referrer=grok-build` 及 `conversations:read/write` scopes。详细故障判断见
`HANDOFF_CPA_20260718.md`。

`--direct` 只用于网络诊断，不代表 WARP 一定能通过 consent。2026-07-18 实测
WARP 可打开 consent，但点击“允许”后仍可能进入 Cloudflare
`Attention Required`，此时需要换干净的住宅出口。

---

## 第三步：日常刷新（快速续期）

**脚本：** `refresh_cpa.py`

```bash
# 只刷新过期/快过期的
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u refresh_cpa.py

# 强制全部刷新
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u refresh_cpa.py --force
```

**作用：** 用 refresh_token 直接 HTTP POST 换新 token，**不需要浏览器**，1秒/个。
自动走代理 + 请求间隔 3s + 瞬时 reset 指数退避重试 3 次。

**输出：** 更新 `cpa_auth/xai-<email>.json`

---

## 完整一句话流程

```bash
# 1. 注册
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u grok_register_ttk.py

# 2. 转 CPA（首次）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u batch_convert_cpa.py

# 3. 日常刷新（每天/每6小时跑一次）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u refresh_cpa.py
```

---

## 文件结构

```
grokRegister-cpa/
├── grok_register_ttk.py   # 注册账号（已有）
├── xai_oauth.py            # OAuth 核心模块（从 grok-reg 拷贝）
├── batch_convert_cpa.py    # SSO → CPA 批量转换
├── convert_new4.py         # 只转缺 CPA 的账号（接代理+重试）
├── probe_auth.py           # 节点探针：测 authorize 是否被 Cloudflare 拦
├── refresh_cpa.py          # CPA 日常刷新（接代理+重试）
├── config.json             # 配置（邮箱提供商、代理等）
├── cpa_auth/               # CPA 文件输出目录
│   ├── xai-xxx@xxx.json
│   └── ...
└── accounts_*.txt          # 注册账号记录
```

---

## CPA 文件格式

```json
{
  "access_token": "eyJ...",
  "refresh_token": "Aaqy...",
  "expires_in": 21600,
  "token_type": "Bearer",
  "email": "xxx@xxx",
  "base_url": "https://cli-chat-proxy.grok.com/v1",
  "headers": {
    "X-XAI-Token-Auth": "xai-grok-cli",
    "x-grok-client-version": "0.2.93",
    "x-grok-client-identifier": "grok-shell"
  }
}
```

**有效期：** access_token 6小时，refresh_token 可用于续期。

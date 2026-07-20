# xAI OAuth 授权流程设计文档

> 基于 `xai_oauth.py` 和 `sso_to_auth_json.py` 实现整理。
> 最后更新：2026-07-20

---

## 1. 总览

xAI 使用标准 **OIDC Authorization Code Flow + PKCE**，适用于 Grok CLI / Build 等客户端。

```
┌─────────┐    ┌───────────┐    ┌─────────┐    ┌───────────┐    ┌──────────┐
│ 生成PKCE │───▶│ Authorize │───▶│ Consent │───▶│   Token   │───▶│ UserInfo │
│  参数    │    │  页面跳转  │    │ 授权确认 │    │   交换    │    │  拉取    │
└─────────┘    └───────────┘    └─────────┘    └───────────┘    └──────────┘
```

### 端点一览

| 端点 | 地址 |
|---|---|
| Issuer | `https://auth.x.ai` |
| Authorize | `https://auth.x.ai/oauth2/authorize` |
| Token | `https://auth.x.ai/oauth2/token` |
| UserInfo | `https://auth.x.ai/oauth2/userinfo` |
| Consent | `https://accounts.x.ai/oauth2/consent` |
| Client ID | `b1a00492-073a-47ea-816f-4c329264a828`（公开 CLI 客户端） |
| Chat Proxy | `https://cli-chat-proxy.grok.com/v1`（Build token 必须走此通道） |

### 默认 Scopes

```
openid profile email offline_access grok-cli:access api:access conversations:read conversations:write
```

---

## 2. 流程详解

### Step 1：生成 PKCE 参数

```python
code_verifier  = base64url(random_bytes(48))   # 43-128 字符，RFC 7636
code_challenge = base64url(sha256(verifier))    # S256 方法
state           = hex(random_bytes(16))          # CSRF 防护
nonce           = hex(random_bytes(16))          # 重放防护
```

### Step 2：构建 Authorize URL

```
GET https://auth.x.ai/oauth2/authorize?
    client_id=b1a00492-073a-47ea-816f-4c329264a828
  & code_challenge=<S256 hash>
  & code_challenge_method=S256
  & nonce=<random>
  & plan=generic
  & redirect_uri=http://127.0.0.1:<port>/callback
  & referrer=grok-build
  & response_type=code
  & scope=openid profile email offline_access grok-cli:access api:access conversations:read conversations:write
  & state=<random>
```

**关键参数说明：**

| 参数 | 说明 |
|---|---|
| `referrer=grok-build` | **必须**。决定 access_token 中 `referrer` claim；缺失则 `cli-chat-proxy` 返回 403 |
| `plan=generic` | 对齐 grok-build-auth 官方流程 |
| `redirect_uri` | 本地回环地址，如 `http://127.0.0.1:56121/callback` |

服务端收到后自动重定向到 `accounts.x.ai/oauth2/consent`。

### Step 3：Consent 授权确认

xAI 的 consent 使用 **Next.js Server Action** 提交，不是普通 HTML form。

**请求：**

```http
POST https://accounts.x.ai/oauth2/consent?client_id=...&redirect_uri=...&...
Content-Type: text/plain;charset=UTF-8
Accept: text/x-component
Next-Action: 4005315a1d7e426de592990bb54bb37471f39dd6d2
Origin: https://accounts.x.ai
```

**Body（JSON 数组）：**

```json
[{
  "action": "allow",
  "clientId": "b1a00492-073a-47ea-816f-4c329264a828",
  "redirectUri": "http://127.0.0.1:56121/callback",
  "scope": "openid profile email offline_access grok-cli:access api:access conversations:read conversations:write",
  "state": "<state>",
  "codeChallenge": "<code_challenge>",
  "codeChallengeMethod": "S256",
  "nonce": "<nonce>",
  "principalType": "User",
  "principalId": "",
  "referrer": "grok-build"
}]
```

**响应解析：**

返回 `text/x-component`（Next.js RSC 格式），逐行查找含 `code` 字段的 JSON：

```json
{"success": true, "code": "<authorization_code>"}
```

> `Next-Action` ID 固定为 `4005315a1d7e426de592990bb54bb37471f39dd6d2`，来自 xAI 前端构建产物。

### Step 4：Token 交换

```http
POST https://auth.x.ai/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
& code=<authorization_code>
& redirect_uri=http://127.0.0.1:56121/callback
& client_id=b1a00492-073a-47ea-816f-4c329264a828
& code_verifier=<code_verifier>
```

**返回：**

```json
{
  "access_token": "eyJhbGci...",
  "refresh_token": "eyJhbGci...",
  "id_token": "eyJhbGci...",
  "token_type": "Bearer",
  "expires_in": 21600,
  "scope": "openid profile email offline_access grok-cli:access api:access conversations:read conversations:write"
}
```

**校验：** 解码 access_token JWT payload，确认 `referrer` 字段为 `grok-build`：

```python
payload = jwt_decode(access_token)
assert payload["referrer"] == "grok-build"
```

### Step 5：拉取 UserInfo（可选）

```http
GET https://auth.x.ai/oauth2/userinfo
Authorization: Bearer <access_token>
```

返回用户 profile 信息（email、sub 等）。

---

## 3. Token 刷新

```http
POST https://auth.x.ai/oauth2/token
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
& client_id=b1a00492-073a-47ea-816f-4c329264a828
& refresh_token=<refresh_token>
```

返回新的 access_token。如果响应不含 refresh_token，沿用旧的。

---

## 4. 三种登录方式

```
complete_build_oauth()
  │
  ├─ 1. Protocol（纯 HTTP）        ← 优先，复用 SSO cookie
  │     curl_cffi impersonate chrome，绕 Cloudflare
  │
  ├─ 2. Playwright（无头浏览器）    ← 备选，自动填写表单
  │     chromium headless，consent 可用 Server Action 直接提交
  │
  └─ 3. 系统浏览器（交互式）       ← 最终兜底
        webbrowser.open()，用户手动操作
```

### 方式对比

| 方式 | 速度 | 依赖 | 适用场景 |
|---|---|---|---|
| Protocol | 快 | curl_cffi | 有 SSO cookie 或能自动登录 |
| Playwright | 中 | playwright + chromium | Cloudflare 拦截严重时 |
| 系统浏览器 | 慢 | 无 | 开发调试 |

---

## 5. 输出格式

### 5.1 CLIProxyAPI (CPA) 扁平格式

> 对齐 `internal/auth/xai/token.go` 的 `TokenStorage`，主要使用格式。

文件名：`xai-<email>.json`

```json
{
  "type": "xai",
  "auth_kind": "oauth",
  "email": "user@example.com",
  "sub": "user-uuid",
  "access_token": "eyJhbGci...",
  "refresh_token": "eyJhbGci...",
  "id_token": "eyJhbGci...",
  "token_type": "Bearer",
  "expires_in": 21600,
  "expired": "2026-07-10T07:00:00Z",
  "last_refresh": "2026-07-10T01:00:00Z",
  "redirect_uri": "http://127.0.0.1:56121/callback",
  "token_endpoint": "https://auth.x.ai/oauth2/token",
  "base_url": "https://cli-chat-proxy.grok.com/v1",
  "disabled": false,
  "headers": {
    "User-Agent": "grok-pager/0.2.93 grok-shell/0.2.93 (linux; x86_64)",
    "X-XAI-Token-Auth": "xai-grok-cli",
    "x-authenticateresponse": "authenticate-response",
    "x-grok-client-identifier": "grok-pager",
    "x-grok-client-version": "0.2.93"
  }
}
```

**可选字段：** `sso`（原始 SSO cookie，供后续刷新使用）。

### 5.2 Grok CLI 格式（~/.grok/auth.json）

文件名：`auth.json`，key 为 `issuer::client_id`。

```json
{
  "https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828": {
    "key": "<access_token>",
    "auth_mode": "oidc",
    "create_time": "2026-07-10T01:00:00.000000000Z",
    "user_id": "user-uuid",
    "email": "user@example.com",
    "principal_type": "User",
    "principal_id": "user-uuid",
    "refresh_token": "eyJhbGci...",
    "expires_at": "2026-07-10T07:00:00.000000000Z",
    "oidc_issuer": "https://auth.x.ai",
    "oidc_client_id": "b1a00492-073a-47ea-816f-4c329264a828"
  }
}
```

---

## 6. 注意事项与踩坑

### 关键约束

| 项 | 说明 |
|---|---|
| `referrer` 必须在 authorize 阶段注入 | consent 时设置无效；JWT claim 来自 authorize 请求参数 |
| `base_url` 必须是 `cli-chat-proxy.grok.com` | `api.x.ai/v1` 是 API 计费通道，Build token 走会返回 402 |
| Consent 是 Next.js Server Action | 需要 `Next-Action` header + `text/plain` Content-Type + `text/x-component` Accept |
| Token 请求需要 Grok CLI UA | `grok-pager/0.2.93 grok-shell/0.2.93 (linux; x86_64)` |
| headers 中 `X-XAI-Token-Auth: xai-grok-cli` | 对齐官方 Grok CLI 行为 |

### Cloudflare 防护

- 纯 HTTP 请求可能被 Cloudflare 拦截
- 解决方案：`curl_cffi` 的 `impersonate="chrome"` 或 Playwright 浏览器
- SSO cookie 需同时设置在 `.x.ai`、`accounts.x.ai`、`auth.x.ai` 三个域

### Scopes 与权限

| Scope | 作用 |
|---|---|
| `openid` | OIDC 标准，返回 id_token |
| `profile` | 用户基本信息 |
| `email` | 用户邮箱 |
| `offline_access` | 允许获取 refresh_token |
| `grok-cli:access` | Grok CLI / Build 专用权限 |
| `api:access` | API 访问权限 |
| `conversations:read` | 读取对话 |
| `conversations:write` | 写入对话 |

---

## 7. 流程图

```
用户/客户端                    xAI Auth                     xAI Accounts
    │                            │                              │
    │  1. 生成 PKCE 参数          │                              │
    │  (verifier, challenge,     │                              │
    │   state, nonce)            │                              │
    │                            │                              │
    │  2. GET /oauth2/authorize  │                              │
    │ ──────────────────────────▶│                              │
    │                            │  302 重定向到 consent         │
    │                            │ ────────────────────────────▶│
    │                            │                              │
    │  3. POST consent (allow)   │                              │
    │ ─────────────────────────────────────────────────────────▶│
    │                            │                              │
    │  4. 返回 authorization_code│                              │
    │ ◀─────────────────────────────────────────────────────────│
    │                            │                              │
    │  5. POST /oauth2/token     │                              │
    │     (code + verifier)      │                              │
    │ ──────────────────────────▶│                              │
    │                            │                              │
    │  6. 返回 tokens            │                              │
    │     (access/refresh/id)    │                              │
    │ ◀──────────────────────────│                              │
    │                            │                              │
    │  7. GET /oauth2/userinfo   │                              │
    │ ──────────────────────────▶│                              │
    │  8. 返回用户信息            │                              │
    │ ◀──────────────────────────│                              │
    │                            │                              │
    ▼                            ▼                              ▼
 保存 token                   Token 端点                    Consent 页面
 (CPA JSON / auth.json)
```

---

## 8. 代码入口

| 函数 | 文件 | 说明 |
|---|---|---|
| `login_with_browser()` | `xai_oauth.py` | 交互式浏览器登录 |
| `login_with_playwright()` | `xai_oauth.py` | Playwright 自动登录 |
| `complete_build_oauth()` | `xai_oauth.py` | 统一入口，按优先级尝试三种方式 |
| `sso_to_token()` | `sso_to_auth_json.py` | SSO cookie → token（纯 HTTP） |
| `sso_to_token_browser()` | `sso_to_auth_json.py` | SSO cookie → token（浏览器 consent） |
| `exchange_code_for_token()` | `xai_oauth.py` | code → token 交换 |
| `refresh_access_token()` | `xai_oauth.py` | 刷新 token |
| `save_cliproxyapi_auth_record()` | `xai_oauth.py` | 写 CPA 格式 auth 文件 |
| `token_to_cpa_record()` | `sso_to_auth_json.py` | token → CPA 记录对象 |
| `write_cpa_auth()` | `sso_to_auth_json.py` | 写 CPA auth 文件（原子替换） |
| `upload_cpa_auth_remote()` | `sso_to_auth_json.py` | 通过 Management API 上传到远程 CPA |

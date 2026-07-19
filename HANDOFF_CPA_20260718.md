# CPA 转换人工交接 — 2026-07-18

## 当前状态

- 已登记账号：33
- `cpa_auth/xai-*.json`：28
- 待转 CPA：5
  - `aaalmst78q@215.singledog.net`
  - `zx2njny2hk@91.txvlogvip.top`
  - `91v2bhr01x@a.bdbdjx.top`
  - `8v58pchxfz@215.singledog.net`
  - `dlttdcd5dq@91.txvlogvip.top`
- 新增 5 个账号保存在 `accounts/accounts_20260718_223144.txt`，已校验每条均有密码和 SSO。
- 本轮注册结果：5 成功、0 失败。
- 注册后的 `set_birth_date` 均被 `grok.com` Cloudflare 返回 403，仅影响 NSFW 设置，不影响账号和 SSO。
- 本轮原先卡住的 4 个账号均已转换成功：
  - `2ltczbg4cq@215.singledog.net`
  - `kp9iqa3v4w@91.txvlogvip.top`
  - `qdou7sx2eb@91.txvlogvip.top`
  - `rlmm9g4l70@a.bdbdjx.top`
- 上述 4 个 token 已确认：
  - `referrer=grok-build`
  - scope 包含 `conversations:read conversations:write`
  - `base_url=https://cli-chat-proxy.grok.com/v1`

## 推荐的人工转换脚本

当自动 consent 卡住时，运行：

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -u manual_convert_cpa.py <email>
```

系统已启用 WARP、需要绕过 `config.json` 中的显式代理时：

```powershell
.\.venv\Scripts\python.exe -u manual_convert_cpa.py <email> --direct
```

例如：

```powershell
.\.venv\Scripts\python.exe -u manual_convert_cpa.py 2ltczbg4cq@215.singledog.net
```

脚本会：

1. 从根目录及 `accounts/` 下的 `accounts_*.txt` 查找账号 SSO。
2. 从 `config.json` 读取代理，默认回退 `http://127.0.0.1:7890`。
3. 启动有头 Playwright Chromium。
4. 注入 `sso` / `sso-rw` cookie。
5. 打开带 PKCE、`referrer=grok-build` 和完整 scopes 的 authorize URL。
6. 停在 consent 页面，等待人工点击。
7. 获取 authorization code，交换 access/refresh token。
8. 覆盖写入 `cpa_auth/xai-<email>.json`。
9. 自动校验 referrer 和 conversations scopes。

该人工脚本明确禁用：

- 硬编码 Next.js Server Action；
- 自动点击“允许”；
- 循环连点。

## 人工点击步骤

1. 页面进入 `https://accounts.x.ai/oauth2/consent?...`。
2. 等待 2–3 秒，让 React 页面和请求处理器完全就绪。
3. 只点击一次“允许 / Allow”。
4. 若出现 “Enter this code to finish signing in”，不要关闭页面，等待脚本接收回调。
5. 终端出现以下信息即完成：

```text
成功：CPA 已保存，grok-build referrer 与 conversations scopes 校验通过。
```

## 故障判断

### 按钮一直转圈

打开开发者工具 Network，筛选 `consent`：

- `200`：提交成功，继续等待回调。
- `404`：Next.js Server Action/页面版本不匹配。人工脚本不会主动调用硬编码 Action；关闭旧页面后重新运行。
- `403`：当前出口 IP、Cloudflare 或会话被拒绝。换代理节点，重新生成全新的 OAuth 页面。
- `Pending`：代理链路或上游响应卡住，等待 10–15 秒后仍不恢复就换节点。

以下埋点接口返回 403 通常可以忽略：

```text
/mp/engage
/mp/track
/mp/flags
```

真正影响授权的是：

```text
/oauth2/consent
/account
/?_rsc=...
```

### 页面跳到登录页

说明账号文件里的 SSO 已失效，需要重新登录/注册获取新 SSO，随后再运行人工脚本。

### consent 反复 403

1. `Ctrl+C` 停止脚本并关闭本轮浏览器。
2. 在 Clash/Mihomo 换节点，优先住宅 IP。
3. 重新运行脚本，不要刷新或复用旧 consent URL。

## 2026-07-18 晚间实测结论

### 当前网络状态

- Cloudflare One Client/WARP 状态已确认：`Connected`、`Network: healthy`、模式为 `Warp`。
- `auth.x.ai:443` 通过 `CloudflareWARP` 接口的 TCP 连接成功。
- `config.json` 仍配置 `http://127.0.0.1:7890`，但本轮探测该端口没有监听。
- 经 `7890` 运行 `probe_auth.py` 返回 `ERR_PROXY_CONNECTION_FAILED`。
- 因此启用 WARP 后，原脚本默认配置并不会自动直连 WARP；仍会先尝试已经失效的 7890。

### WARP 直连 OAuth 实测

使用以下命令绕过 7890：

```powershell
.\.venv\Scripts\python.exe -u manual_convert_cpa.py aaalmst78q@215.singledog.net --direct
```

实测过程：

1. authorize 和 consent 页面可以正常打开。
2. SSO 注入有效，页面显示“拒绝 / 允许”，没有跳登录页。
3. 人工点击一次“允许”后按钮持续转圈。
4. 页面最终标题变为 `Attention Required! | Cloudflare`。
5. 本地 OAuth callback 未触发，最终超时。
6. CPA 文件未生成。

结论：WARP 只能证明基础网络和 consent GET 可达，不能通过 x.ai 的 consent 提交级风控。
人工点击不会绕过出口 IP 风控；本次失败不是自动点击、SSO 或本地 callback 的问题。

### 下一步人工操作

1. 断开 Cloudflare One Client/WARP，避免 WARP 共享出口和 Clash 形成叠加链路。
2. 启动 Clash/Mihomo Mixed Port，确认 `127.0.0.1:7890` 正在监听。
3. 选择新的干净住宅节点。
4. 先运行 `probe_auth.py` 检查 authorize 基础可达性。
5. 只对第一个待转账号运行人工流程，等待 2–3 秒后只点一次“允许”。
6. 第一个成功并完成 token 校验后，再批量转换剩余 4 个。

注意：`probe_auth.py` 只能检测 authorize 页面，不能保证 consent POST 一定通过。
任何失败 OAuth URL 的 `state`、PKCE、nonce 和本地 callback 端口都是一次性的，不要刷新或复用旧链接。

## 自动转换入口

只转换缺少 CPA 的账号：

```powershell
.\.venv\Scripts\python.exe -u convert_new4.py
```

强制覆盖指定账号：

```powershell
.\.venv\Scripts\python.exe -u convert_new4.py --only <email> --force
```

有头调试：

```powershell
.\.venv\Scripts\python.exe -u convert_new4.py --only <email> --headless 0 --force
```

自动流程仍可能受 consent 时序和出口 IP 风控影响；遇到卡顿优先切换到 `manual_convert_cpa.py`。

## 本轮代码修复

- authorize 默认 `referrer` 从 `cli-proxy-api` 改为 `grok-build`。
- OAuth scopes 补齐 `conversations:read/write`。
- 注册浏览器恢复使用 `config.proxy`。
- 主程序真正复用注册页执行 CPA 转换。
- `convert_new4.py` 支持扫描 `accounts/` 和 `--force` 覆盖。
- Playwright 保留自动回退，但人工脚本禁用 Server Action 和自动点击。
- `convert_new4.py` 强制将重定向日志设为 UTF-8，失败时不再因 Windows GBK 无法输出 `✓/✗` 而中断整批。
- `manual_convert_cpa.py` 新增 `--direct`，用于显式禁用 `config.json` 代理并走系统网络/WARP。

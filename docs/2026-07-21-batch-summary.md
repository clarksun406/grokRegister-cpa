# 2026-07-21 晚间批量注册 & CPA 转换记录

## 概览

| 项目 | 数量 |
|------|------|
| 注册目标 | 20 |
| 注册成功 | 19 |
| 注册失败 | 1（页面卡住） |
| CPA 转换成功 | 19/19（含多轮补跑） |

---

## 第一轮注册（21:20 - 21:34）

- 目标：10 个
- 结果：成功 9，失败 1
- 失败原因：第 5 个账号点击"使用邮箱注册"后页面卡在"您正在登录"，邮箱输入框未出现
- 账号文件：`accounts/accounts_20260721_212028.txt`

### 第一轮 CPA 转换

首次运行 `convert_device_dp.py` 时扫描了所有历史账号文件，共 30 个待转换（含历史遗留 21 个 + 今晚新注册 9 个）。

今晚 9 个账号首轮结果：5 成功，4 失败（rate_limited / 超时）。

补跑 4 个失败账号后全部成功，第一轮 9/9 CPA 完成。

---

## 第二轮注册（22:25 - 22:40）

- 目标：10 个
- 结果：成功 10，失败 0
- 账号文件：`accounts/accounts_20260721_222532.txt`

### 第二轮 CPA 转换

首轮：7 成功，3 失败（rate_limited / 超时）。

第一次补跑：2 成功，1 失败（n9yftex6rv@a.bdbdjx.top 超时）。

第二次补跑：1 成功。

第二轮 10/10 CPA 完成。

---

## 今晚注册账号清单

### 第一轮（9 个）

| # | 邮箱 | CPA |
|---|------|-----|
| 1 | 4fhfqkaifm@215.singledog.net | OK |
| 2 | uh916a3wvd@91.txvlogvip.top | OK |
| 3 | rz16z3sgtv@a.bdbdjx.top | OK |
| 4 | gb7d18q6hb@215.singledog.net | OK |
| 5 | jiy9cm3ndd@a.bdbdjx.top | OK |
| 6 | fan3k4izlu@215.singledog.net | OK |
| 7 | z82fdgo1qc@91.txvlogvip.top | OK |
| 8 | 3ge58qidda@a.bdbdjx.top | OK |
| 9 | n6a93vbfbz@215.singledog.net | OK |

### 第二轮（10 个）

| # | 邮箱 | CPA |
|---|------|-----|
| 1 | 5i3uaic8kr@215.singledog.net | OK |
| 2 | k52bo71f2w@91.txvlogvip.top | OK |
| 3 | nnwinadxkd@a.bdbdjx.top | OK |
| 4 | wqnx5n75ds@215.singledog.net | OK |
| 5 | l7hjo36j5y@91.txvlogvip.top | OK |
| 6 | n9yftex6rv@a.bdbdjx.top | OK |
| 7 | bpc8rw9w00@215.singledog.net | OK |
| 8 | p8ahwbnior@91.txvlogvip.top | OK |
| 9 | 65x2pjyz44@a.bdbdjx.top | OK |
| 10 | r9ki777s2j@215.singledog.net | OK |

---

## 已知问题

1. **NSFW 开启失败**：所有账号的 `set_birth_date` 接口被 grok.com Cloudflare 403 拦截，NSFW 均未开启。账号本身注册成功不受影响。
2. **CPA 转换限流**：连续请求 device flow 容易触发 429 rate_limited，补跑间隔后均可恢复。
3. **done 页超时**：浏览器已到达 `/oauth2/device/done` 但脚本检测逻辑未及时识别完成，导致超时。实际授权可能已成功，补跑即可。
4. **注册偶发卡住**：个别轮次点击"使用邮箱注册"后页面停留在"您正在登录"状态，邮箱输入框不出现，需重启浏览器。

---

## 使用的脚本

- 注册：`python grok_register_ttk.py cli`（CLI 模式，config.json 中 register_count=10）
- CPA 转换：`python convert_device_dp.py [--only <email>]`（device flow + DrissionPage）
- 邮箱服务：YYDS API
- 代理：http://127.0.0.1:7890

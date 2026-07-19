# 新机从零部署 — grokRegister-cpa

> 换台电脑照这个文档做，就能从零跑通「注册账号 → 转 CPA → 用 Grok」。

## 前置条件

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10/11（脚本默认走 Windows 路径找 Chrome；Linux/macOS 需改 `convert_device.py` 的 Chrome 路径） |
| Python | 3.9+（实测 3.13 可用） |
| 代理 | Clash/Mihomo 开着，监听 `127.0.0.1:7890`，选**住宅 IP 节点**（机房 IP 易被 Cloudflare 拦） |
| 浏览器 | **Google Chrome 装到默认路径**（`C:\Program Files\Google\Chrome\Application\chrome.exe`）——device flow 转换必须用真实 Chrome，headless/Playwright bundled Chromium 会被 CF block |

## 1. clone + 虚拟环境 + 依赖

```bash
git clone https://github.com/clarksun406/grokRegister-cpa.git
cd grokRegister-cpa
python -m venv .venv
.venv/Scripts/python.exe -m pip install -U pip
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

## 2. 装 Playwright 浏览器（关键，文档常漏）

`convert_device.py` 用 Playwright 驱动真实 Chrome，必须装一次：

```bash
.venv/Scripts/python.exe -m playwright install chromium
```

## 3. 配置 config.json

```bash
cp config.example.json config.json
```

编辑 `config.json`，**必填**：

```jsonc
{
  "proxy": "http://127.0.0.1:7890",        // 必填，走代理
  "email_provider": "yyds",                // 用 yyds 邮箱（最稳）
  "yyds_api_key": "你的 yyds api key",      // 必填，去 maliapi 申请
  "register_count": 1,                     // 注册数量，按需改
  "enable_nsfw": true
}
```

> `yyds_api_key` 不入库（config.json 被 .gitignore 忽略），需自己申请。
> 域名已内置白名单轮换（`215.singledog.net` / `91.txvlogvip.top` / `a.bdbdjx.top`），不用配。

## 4. 跑通验证（注册 1 个 → 转 CPA → 测 chat）

```bash
# 4.1 注册 1 个账号（交互式，输入 start）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u grok_register_ttk.py cli
#   输出 accounts/accounts_<日期>_<时间>.txt，每行 email----password----sso

# 4.2 转 CPA（device flow，有头真实 Chrome，~10s/个）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u convert_device.py --headless 0
#   输出 cpa_auth/xai-<email>.json

# 4.3 测 chat 是否可用
.venv/Scripts/python.exe -c "
import json,glob,requests
d=json.load(open(sorted(glob.glob('cpa_auth/xai-*.json'))[-1],encoding='utf-8'))
h=dict(d.get('headers',{})); h['Authorization']='Bearer '+d['access_token']; h['Content-Type']='application/json'
p={'http':'http://127.0.0.1:7890','https':'http://127.0.0.1:7890'}
r=requests.post('https://cli-chat-proxy.grok.com/v1/chat/completions',headers=h,proxies=p,timeout=25,json={'model':'grok-4.5','messages':[{'role':'user','content':'hi'}],'max_tokens':3})
print(r.status_code, r.text[:150])
"
#   期望: 200 {"...model":"grok-4.5-build-free"...}
```

通过即环境就绪。

## 5. 日常使用

见 `USAGE.md`，三个核心命令：

```bash
# 注册（改 config.json 的 register_count 控制数量）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u grok_register_ttk.py cli

# 转 CPA（必须 --headless 0）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u convert_device.py --headless 0

# 日常刷新（access_token 6h 过期，按需刷，~1s/个）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u refresh_cpa.py
```

## 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `convert_device.py` 报 `Cloudflare 拦截 (blocked)` | 出口 IP 被 CF 标记，**换住宅节点**。`probe_auth.py` 不可信（测不出提交级拦截） |
| `ConnectionResetError 10054` / `SSL EOF` | 代理出口被高频打 reset，**冷却 60s 再跑**，不必换节点 |
| `convert_device.py` headless 全 block | headless 必被 CF 拦，**必须 `--headless 0`** |
| 注册失败、撞乱七八糟子域 | 域名白名单已内置；若白名单全 403，回退打分轮换 |
| chat 403 `permission-denied` | 账号无 Grok Build free 额度（07-17 23:42~07-18 注册的那批），换账号；新注册账号正常可用 |
| refresh 报 `invalid_grant: revoked` | refresh_token 被 xAI 吊销，用 `convert_device.py` 重转可复活（sso 还在的话） |

## 转移凭证到另一台电脑

`cpa_auth/` 是纯文件（access_token + refresh_token），换机时直接拷贝整个目录过去，跑 `refresh_cpa.py` 即续用。**不要把 cpa_auth/ 提交到 GitHub**（含 refresh_token 长期密钥，泄露会被盗用额度）。

加密拷贝：
```bash
# 源机
.venv/Scripts/python.exe -c "import shutil; shutil.make_archive('cpa_backup','zip','cpa_auth')"  # 或用 7z 加密码

# 目标机：解压到 cpa_auth/，然后
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u refresh_cpa.py --force
```

## 相关文档

- `USAGE.md` — 日常命令速查
- `HANDOFF_20260719.md` — 完整背景/根因/改动历史
- `CHAT_403_20260719.md` — chat 403 废号调查
- `FLOW.md` — 流程图（注：FLOW.md 部分内容描述旧 auth-code flow，以 `convert_device.py` device flow 为准）
- `README.md` — 原作者总览

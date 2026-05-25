# Boss 直聘自动化简历投递

这是一个 Windows 桌面工具原型，用于在用户手动登录 Boss 直聘后，根据岗位关键词、城市和最大投递数量自动检索岗位，并尝试打招呼/投递简历。

## 功能

- 手动登录 Boss 直聘，登录状态保存在本机用户目录。
- 支持登录态和页面诊断，先检查当前登录状态、岗位列表提取和页面标题/URL。
- 支持多个岗位关键词和多个城市，使用逗号、分号或换行分隔。
- 支持最大成功投递数量，到达后自动停止。
- 支持每组关键词/城市设置最大翻页数，不只处理第一页岗位。
- 支持最低薪资、经验关键词、学历关键词和岗位排除词筛选。
- 支持 HR 活跃/在线关键词筛选，优先处理近期活跃岗位。
- 支持跳过猎头、代招、RPO 和人力资源服务类岗位。
- 支持预览模式，先筛出符合条件的岗位但不点击打招呼/投递。
- 支持单独控制是否自动确认投递简历。
- 支持自定义打招呼文案，多条模板会随机选择。
- 支持公司黑名单。
- 支持随机等待，降低连续点击速度。
- 记录已处理岗位，避免重复投递同一公司/岗位/链接。
- 在界面中显示成功目标进度、已访问、跳过、失败、公司、岗位、薪资、原因。
- 支持将历史记录导出为 CSV。
- 支持失败时自动保存页面截图和 HTML，便于后续按真实页面修选择器。
- 支持清空历史记录，便于重新测试同一岗位。
- 支持一键打开数据目录和失败证据目录。
- 支持本轮同公司只处理一次，减少对同一家公司重复沟通。

## 新建 conda 环境

```powershell
cd D:\xhs\boss
$env:HTTP_PROXY="http://127.0.0.1:7891"
$env:HTTPS_PROXY="http://127.0.0.1:7891"
conda create -y -n boss_sender python=3.12
conda run -n boss_sender python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 开发运行

```powershell
cd D:\xhs\boss
$env:PLAYWRIGHT_BROWSERS_PATH="D:\xhs\boss\ms-playwright"
conda run -n boss_sender python -m playwright install chromium
conda run -n boss_sender python main.py
```

## 使用流程

1. 点击 `手动登录/保存状态`。
2. 在打开的浏览器里手动完成 Boss 直聘登录、扫码或验证。
3. 回到工具窗口，点击 `停止` 关闭登录窗口。
4. 填写岗位关键词、城市、最大投递数量、最大翻页数、筛选条件、黑名单和打招呼文案。
5. 点击 `检查登录/页面`，确认日志里能看到岗位数、页面标题和首个岗位。
6. 先保持 `预览模式` 开启，点击 `开始投递` 跑一轮预览。
7. 确认记录符合预期后，再关闭 `预览模式` 执行真实打招呼/投递。

筛选规则：

- `最低薪资(K)` 填 `0` 表示不限；例如 `20` 表示岗位薪资上限至少要达到 20K。
- `每组最大翻页数` 控制每个关键词和城市组合最多扫描多少页，到达最大成功投递数量会提前停止。
- `经验关键词` 和 `学历关键词` 支持多个候选词，命中任意一个即可；为空表示不限。
- `HR活跃/在线关键词` 为空表示不限；可填写 `活跃,在线,刚刚`，岗位详情或卡片文本未命中时会跳过。
- `岗位排除词` 命中后会跳过，例如外包、培训、销售等。
- `公司黑名单` 只匹配公司名称。
- `本轮同公司只处理一次` 默认开启，同一次运行里遇到同一家公司多个岗位会跳过后续岗位。
- `跳过猎头/人力资源服务岗位` 默认开启，会根据岗位和公司文本里的猎头、RPO、代招、人力资源服务等词跳过。
- `预览模式` 默认开启，只记录符合筛选的岗位，不点击任何沟通或投递按钮。
- 预览记录不会加入真实去重历史，后续关闭预览模式后仍可继续处理同一岗位。
- 开启预览模式时，`最大投递数量` 会作为最大预览数量使用。
- `自动确认投递简历` 默认关闭；关闭时只尝试打招呼/沟通，不主动点击确认投递。
- `打招呼文案` 支持多条模板，使用换行、逗号或分号分隔；每次沟通会随机选一条。
- `导出记录` 会把历史 JSONL 记录导出为 UTF-8 BOM CSV，方便用 Excel 打开。
- `清空历史` 会删除历史 JSONL，并清空界面表格；清空后同一岗位可以重新处理。
- `失败时保存截图和 HTML` 默认开启，文件保存在 `%USERPROFILE%\.boss_resume_sender\evidence`，CSV 中会带上证据路径。
- `打开数据目录` 和 `打开证据目录` 会用资源管理器打开本机保存位置。

登录态、配置和历史记录默认保存在：

```text
%USERPROFILE%\.boss_resume_sender
```

## ?? exe

???????????????????? release ??? zip?????? `dist`?????? exe ???????????????

```powershell
cd D:\xhs\boss
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

?????

```text
D:\xhs\boss\release_20260522-140000\BossResumeSender\BossResumeSender.exe
D:\xhs\boss\BossResumeSender-windows-20260522-140000.zip
```

????????????

```powershell
cd D:\xhs\boss
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

???????

```text
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe
```

?????????????????? `BossResumeSender` ?????????? `BossResumeSender.exe`????? Python ??Playwright ??? Chromium ????????? `_internal` ??

## 验证命令

```powershell
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-browser
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-login
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-evidence
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-flow
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-diagnose
```

- `--smoke-browser` 验证随包 Chromium 能启动。
- `--smoke-login` 验证手动登录入口不会停留在空白页。
- `--smoke-evidence` 验证截图和 HTML 留证能写入本机目录。
- `--smoke-flow` 使用本地模拟岗位页验证岗位提取、筛选、详情打开和预览记录链路。
- `--smoke-diagnose` 使用本地模拟列表页验证登录/页面诊断链路。

## 参考调研

同类项目常见功能包括：

- 浏览器持久化登录态。
- 批量投递和最大数量控制。
- 黑名单、已投递历史和失败日志。
- 投递间隔随机化。
- 关键词、城市、薪资、经验、学历筛选。
- HR 活跃状态、猎头/RPO 排除和同公司去重。
- 风控提示和人工接管能力。

当前版本已实现以上基础能力。后续可继续加入薪资区间、公司规模、行业、融资阶段、AI 个性化招呼语、消息通知和已读不回复跟进等更细能力。

## 反检测说明

Boss 直聘会对自动化浏览器进行多层检测，导致登录页面不断闪烁跳转（`_security_check` 重定向）。本版本已加入以下反检测措施：

### 检测机制

Boss 直聘使用三层检测：

1. **TLS/JA3 指纹检测（服务端）**：Playwright 自带的 Chromium 与用户日常使用的 Chrome 在 TLS 握手阶段的指纹不同（密码套件顺序、扩展等），服务端可直接识别为自动化浏览器。
2. **CDP 协议检测（客户端 JS）**：Playwright 通过 Chrome DevTools Protocol 控制浏览器，会注入 `Runtime.enable` 等指令，页面 JS 可检测到这些信号。
3. **JS 属性检测（客户端 JS）**：包括 `navigator.webdriver`、`console.table` 计时攻击、`performance.now` 篡改检测、`Function.prototype.toString` 检测、`window.chrome` 缺失、`navigator.plugins` 为空等。

### 解决方案

#### 1. CDP 连接本机 Chrome（网络层）

不再使用 Playwright 自带的 Chromium，改为通过 `subprocess.Popen` 启动本机安装的 Chrome，并加上 `--remote-debugging-port` 参数，再用 Playwright 的 `connect_over_cdp()` 连接。

- 本机 Chrome 的 TLS 指纹是真实的，不会被服务端识别为自动化浏览器。
- Chrome 不是由 Playwright 启动的，不会带 `--enable-automation` 等自动化标志。
- 如果本机没有 Chrome/Edge，自动回退到 Playwright 启动方式。

相关代码：`main.py` 中的 `_launch_context()` 和 `_find_system_browser_executable()`。

#### 2. JavaScript 隐身脚本（页面层）

注入 `STEALTH_JS` 脚本，在每个页面加载前执行，覆盖以下检测点：

| 检测点 | 处理方式 |
|--------|----------|
| `navigator.webdriver` | 设为 `undefined` |
| `window.chrome` | 模拟 `chrome.runtime` 对象 |
| `navigator.plugins` | 模拟 3 个常见插件 |
| `navigator.languages` | 设为 `['zh-CN', 'zh', 'en']` |
| `console.table` 计时攻击 | 替换为空函数，绕过 disable-devtool 库 |
| `performance.now` 篡改检测 | 用 `Date.now() - timeOrigin` 替代，保持单调递增 |
| `Function.prototype.toString` | 对被 hook 的函数返回 `[native code]` |
| CDP 注入的 `window.cdc_*` 变量 | 自动删除 |
| WebGL 指纹 | 统一为 Intel Iris 显卡 |
| `deviceMemory` / `hardwareConcurrency` | 设为 8 |

#### 3. Chrome 启动参数

- `--disable-blink-features=AutomationControlled`：隐藏 `navigator.webdriver`
- `ignore_default_args=["--enable-automation"]`：移除 Playwright 默认的自动化标志
- `--disable-infobars`、`--disable-background-timer-throttling` 等：减少自动化特征

#### 4. 登录窗口

手动登录窗口也使用本机 Chrome，并加上 `--disable-blink-features=AutomationControlled` 参数，避免登录页面被检测。

### 注意事项

- 首次使用或旧版本升级后，需要重新手动登录一次（点击"打开登录窗口"），因为旧的浏览器 profile 可能已被标记。
- 如果本机没有安装 Chrome 或 Edge，会自动回退到 Playwright 自带的 Chromium，此时反检测效果会降低。
- 本工具只做浏览器自动化，不绕过验证码。Boss 直聘页面结构可能变化，如果按钮或列表选择器失效，需要按最新页面结构更新 `main.py` 中的选择器。

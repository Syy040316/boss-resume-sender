# Boss 直聘自动化简历投递

基于 Playwright 的 Windows 桌面工具，支持自动检索岗位并批量打招呼/投递简历。

## 功能特性

### 搜索与投递
- 支持多个岗位关键词和多个城市，使用逗号、分号或换行分隔
- 支持最大成功投递数量，到达后自动停止
- 支持每组关键词/城市设置最大翻页数
- 支持预览模式：先筛出符合条件的岗位但不点击打招呼/投递
- 支持单独控制是否自动确认投递简历
- 支持自定义打招呼文案，多条模板会随机选择

### 筛选规则
- 最低薪资筛选（K），填 0 表示不限
- 经验关键词和学历关键词，支持多个候选词，命中任意一个即可
- HR 活跃/在线关键词筛选，优先处理近期活跃岗位
- 岗位排除词，命中后跳过（如外包、培训、销售等）
- 跳过猎头、代招、RPO 和人力资源服务类岗位
- 公司黑名单
- 本轮同公司只处理一次，减少重复沟通

### 安全与记录
- 登录态保存在本机用户目录，无需重复登录
- 支持登录态和页面诊断
- 记录已处理岗位，避免重复投递
- 失败时自动保存页面截图和 HTML，便于排查
- 支持将历史记录导出为 CSV（UTF-8 BOM，Excel 可直接打开）
- 支持随机等待，降低连续点击速度

### 反检测
- 通过 CDP 连接本机 Chrome，绕过 TLS/JA3 指纹检测
- 注入 Stealth JS 脚本，覆盖 `navigator.webdriver`、`console.table` 计时攻击、`performance.now` 篡改检测、WebGL 指纹等十余个检测点
- 如果本机没有 Chrome/Edge，自动回退到 Playwright 自带 Chromium

## 安装

### 新建 conda 环境

```powershell
cd D:\xhs\boss
conda create -y -n boss_sender python=3.12
conda run -n boss_sender python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 安装浏览器

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH="D:\xhs\boss\ms-playwright"
conda run -n boss_sender python -m playwright install chromium
```

## 运行

```powershell
cd D:\xhs\boss
$env:PLAYWRIGHT_BROWSERS_PATH="D:\xhs\boss\ms-playwright"
conda run -n boss_sender python main.py
```

## 使用流程

1. 点击 **手动登录/保存状态**，在打开的浏览器里完成 Boss 直聘登录（扫码或验证）
2. 回到工具窗口，点击 **停止** 关闭登录窗口
3. 填写岗位关键词、城市、最大投递数量、筛选条件、黑名单和打招呼文案
4. 点击 **检查登录/页面**，确认日志里能看到岗位数和页面信息
5. 先保持 **预览模式** 开启，点击 **开始投递** 跑一轮预览
6. 确认记录符合预期后，关闭 **预览模式** 执行真实打招呼/投递

## 打包为 exe

```powershell
cd D:\xhs\boss
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

输出：

```text
release_YYYYMMDD-HHMMSS\BossResumeSender\BossResumeSender.exe
BossResumeSender-windows-YYYYMMDD-HHMMSS.zip
```

也可只打包 exe（不含 zip）：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

输出：

```text
dist\BossResumeSender\BossResumeSender.exe
```

打包后的文件夹可整体复制到其他 Windows 机器运行，无需安装 Python 或 Playwright。双击 `BossResumeSender.exe` 即可启动。

## 验证命令

```powershell
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-browser
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-login
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-evidence
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-flow
D:\xhs\boss\dist\BossResumeSender\BossResumeSender.exe --smoke-diagnose
```

| 命令 | 说明 |
|------|------|
| `--smoke-browser` | 验证随包 Chromium 能启动 |
| `--smoke-login` | 验证手动登录入口不会停留在空白页 |
| `--smoke-evidence` | 验证截图和 HTML 留证能写入本机目录 |
| `--smoke-flow` | 使用本地模拟岗位页验证岗位提取、筛选、详情打开和预览记录链路 |
| `--smoke-diagnose` | 使用本地模拟列表页验证登录/页面诊断链路 |

## 数据目录

登录态、配置和历史记录默认保存在：

```text
%USERPROFILE%\.boss_resume_sender
```

## 配置说明

| 配置项 | 说明 |
|--------|------|
| 最低薪资(K) | 填 0 表示不限；例如 20 表示岗位薪资上限至少要达到 20K |
| 每组最大翻页数 | 控制每个关键词和城市组合最多扫描多少页 |
| 经验/学历关键词 | 支持多个候选词，命中任意一个即可；为空表示不限 |
| HR 活跃/在线关键词 | 为空表示不限；可填写 `活跃,在线,刚刚` |
| 岗位排除词 | 命中后跳过，如外包、培训、销售等 |
| 公司黑名单 | 只匹配公司名称 |
| 本轮同公司只处理一次 | 默认开启，同一次运行里遇到同一家公司多个岗位会跳过后续岗位 |
| 跳过猎头/人力资源服务岗位 | 默认开启 |
| 预览模式 | 默认开启，只记录符合筛选的岗位，不点击沟通或投递按钮 |
| 自动确认投递简历 | 默认关闭；关闭时只尝试打招呼，不主动点击确认投递 |
| 打招呼文案 | 支持多条模板，使用换行、逗号或分号分隔；每次沟通随机选一条 |
| 失败时保存截图和 HTML | 默认开启，保存在 `%USERPROFILE%\.boss_resume_sender\evidence` |

## 反检测说明

Boss 直聘对自动化浏览器进行多层检测，本工具已加入以下应对措施：

### 检测机制

1. **TLS/JA3 指纹检测（服务端）**：Playwright 自带的 Chromium 与用户日常使用的 Chrome 在 TLS 握手阶段的指纹不同，服务端可直接识别为自动化浏览器。
2. **CDP 协议检测（客户端 JS）**：Playwright 通过 Chrome DevTools Protocol 控制浏览器，页面 JS 可检测到 `Runtime.enable` 等信号。
3. **JS 属性检测（客户端 JS）**：包括 `navigator.webdriver`、`console.table` 计时攻击、`performance.now` 篡改检测、`Function.prototype.toString` 检测、`window.chrome` 缺失、`navigator.plugins` 为空等。

### 解决方案

**CDP 连接本机 Chrome**：不再使用 Playwright 自带的 Chromium，改为通过 `subprocess.Popen` 启动本机 Chrome 并加上 `--remote-debugging-port`，再用 Playwright 的 `connect_over_cdp()` 连接。本机 Chrome 的 TLS 指纹是真实的，不会被服务端识别。

**JavaScript 隐身脚本**：在每个页面加载前注入脚本，覆盖以下检测点：

| 检测点 | 处理方式 |
|--------|----------|
| `navigator.webdriver` | 设为 `undefined` |
| `window.chrome` | 模拟 `chrome.runtime` 对象 |
| `navigator.plugins` | 模拟 3 个常见插件 |
| `navigator.languages` | 设为 `['zh-CN', 'zh', 'en']` |
| `console.table` 计时攻击 | 替换为空函数 |
| `performance.now` 篡改检测 | 用 `Date.now() - timeOrigin` 替代 |
| `Function.prototype.toString` | 对被 hook 的函数返回 `[native code]` |
| `window.cdc_*` 变量 | 自动删除 |
| WebGL 指纹 | 统一为 Intel Iris 显卡 |
| `deviceMemory` / `hardwareConcurrency` | 设为 8 |

### 注意事项

- 首次使用或旧版本升级后，需要重新手动登录一次
- 如果本机没有安装 Chrome 或 Edge，会自动回退到 Playwright 自带的 Chromium，反检测效果会降低
- Boss 直聘页面结构可能变化，如果按钮或列表选择器失效，需要更新 `main.py` 中的选择器

## 后续可扩展

- 薪资区间、公司规模、行业、融资阶段筛选
- AI 个性化招呼语
- 消息通知
- 已读不回复跟进

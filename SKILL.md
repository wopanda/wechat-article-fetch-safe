---
name: wechat-article-fetch-safe
description: 从微信公众号文章 URL 安全提取标题、封面、正文与图片，按 HTTP → Browser → OCR 决策链输出 Markdown 或 JSON。适用于分析、归档、摘要、素材沉淀，不写入飞书、不读取本地敏感配置、不自动调用外部办公 API。
---

# WeChat Article Fetch Safe

用于安全抓取微信公众号文章内容，并整理成适合后续摘要、保存、改写或发布前处理的结构化结果。

## 当前阶段定位

当前版本定位为 **公众号文章抓取底座 v1**：
- 已支持 HTTP 主链、browser fallback、OCR 条件兜底、失败分类、debug artifacts、最小回归
- 适合接入上层 Agent / Skill / MCP
- 不追求任意文章 100% 成功率
- 不自动突破 verify / anti-bot / 已删除页面

## 适用范围

当用户出现这些需求时使用：
- 给一篇微信公众号文章链接，想拿到正文
- 想把公众号文章转成 Markdown
- 想保留标题、封面图、正文图片链接
- 想做后续摘要、知识库沉淀、Obsidian 保存、二次改写

不做这些事：
- 不读取本机 OpenClaw 配置或密钥
- 不自行连接 Feishu / 企业 API / 数据库
- 不自动发布文章
- 不绕过登录、鉴权或付费墙

## 工作思路

核心决策链是：

1. **HTTP 优先**：先用微信移动 UA / 桌面 UA 抓静态 HTML
2. **Browser fallback**：HTTP 质量不足时，切 Playwright 移动端浏览器
3. **OCR 最后兜底**：Browser 页面视觉可见但 DOM 提取仍明显不足时，尝试 OCR
4. **异常状态优先识别**：verify / captcha / anti-bot / deleted / not_found
5. **统一输出结构化结果**：成功状态、失败状态、决策路径、质量指标

## 首选脚本

优先使用：`scripts/fetch_wechat_article.py`

示例：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx"
```

输出 JSON：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --format json
```

保存 Markdown 到文件：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --format markdown --output /tmp/article.md
```

输出调试产物：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --debug --artifacts-dir ./artifacts
```

## 关键输出字段

JSON 模式默认输出：
- `success`
- `status`
- `title`
- `author`
- `publish_time`
- `cover_image`
- `content_markdown`
- `images`
- `fetch_method`
- `decision_path`
- `page_status`
- `page_signals`
- `quality_metrics`
- `used_browser_fallback`
- `used_ocr_fallback`
- `attempts`

## 成功状态

- `success_http`
- `success_browser`
- `success_ocr`

## 常见失败状态

- `verify_required`
- `captcha_or_env_check`
- `anti_bot_suspected`
- `article_deleted`
- `content_not_found`
- `all_strategies_failed`

## 决策链说明

### 第 1 层：HTTP
适用：普通可公开文章页。

若命中正文容器且质量达标，直接返回 `success_http`。

### 第 2 层：Browser
适用：
- HTTP 正文过短
- 图片过少
- 段落过少
- 页面需要渲染 / 懒加载

若 Browser 结果最优，则返回 `success_browser`。

### 第 3 层：OCR
适用：
- 已经跑过 Browser
- 页面视觉上能看到内容
- 但 DOM 提取仍明显不足
- 且页面不属于 verify / anti-bot / deleted / not_found

若 OCR 结果达到阈值，则返回 `success_ocr`；否则保留前面最佳结果，并把 OCR 失败记录进 `attempts` / `errors`。

## 一个真实例子

真实样例：
`https://mp.weixin.qq.com/s/1GWJoOLp4zpOs7SZk2ra1Q`

这条链接实际跑出的决策路径是：
- `wechat-mobile`
- `chrome-desktop`
- `playwright-mobile`
- `ocr-fallback`

最终结果：
- `status = success_browser`
- Browser 拿到了更完整的标题 / 作者 / 发布时间
- OCR 也被触发了，但 OCR 结果过短，没有覆盖 Browser 结果

这说明：
- 决策链已经完整执行
- OCR 已经接入且会真实触发
- 但 OCR 不是万能补丁，只有结果足够好时才会升级为最终结果

## 失败时的处理顺序

1. 先确认 URL 是否可公开访问
2. 再确认是否命中微信正文容器
3. 若页面异常，优先看 `status` / `page_signals`
4. 遇到 `verify_required` / `captcha_or_env_check` / `anti_bot_suspected` 时，不建议死循环自动重试
5. 需要排查时，使用 `--debug --artifacts-dir` 输出 HTML / screenshot

## 相关文档

- `README.md`
- `docs/stage-summary-v1.md`
- `docs/integration.md`
- `docs/decision-flow-v1.md`

## 说明

这是安全版抓取 Skill。
保留的是“公众号页面抓取与提取”能力，不保留任何本地密钥读取、自动办公系统写入、或越权调用逻辑。

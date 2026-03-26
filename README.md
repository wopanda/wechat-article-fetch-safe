# wechat-article-fetch-safe

一个安全版的微信公众号文章抓取 Skill / 脚本包。

它只做一件事：**把公众号文章 URL 提取成标题、封面、正文 Markdown 和图片链接**。

不做这些事：
- 不读取本地 OpenClaw 配置
- 不读取飞书密钥
- 不自动写飞书文档
- 不做越权调用

## 当前阶段定位

当前版本应视为一个 **公众号文章抓取底座 v1**：
- 已具备 HTTP 主链、browser fallback、失败分类、debug artifacts、最小回归能力
- 可以作为上层 Agent / Skill / MCP 的文章提取组件使用
- 但**不追求任意文章 100% 成功率**，也**不默认启用 OCR**

建议先把它用于真实上层场景，再根据高频问题定点补强，而不是继续无限细抠抓取规则。

更多说明见：
- `docs/stage-summary-v1.md`
- `docs/integration.md`
- `docs/decision-flow-v1.md`

## 适合谁用

适合想把公众号文章：
- 拉成 Markdown
- 做摘要
- 存进知识库 / Obsidian
- 做二次改写或结构化整理

## 你怎么安装

### 最简单的方式
把这个仓库链接发给小龙虾，让它安装这个 Skill。

> 一般来说，小龙虾会引导或在对应环境里完成依赖安装；但如果目标环境本身没有浏览器依赖或系统 OCR 依赖，完整能力仍可能降级。

### 环境前置说明
要想让这个 Skill 在别人的 OpenClaw 环境里“完整可用”，建议至少满足：

#### 基础必需
- Python 3
- 能执行 `python3 -m pip install -r requirements.txt`

#### Browser fallback 必需
- `playwright` Python 包
- 已执行：

```bash
python3 -m playwright install chromium
```

如果缺少这一步，Skill 仍可能安装成功，但 **Browser fallback 不可用**，能力会退化为以 HTTP 主链为主。

#### OCR 兜底可选但推荐
- 系统已安装 `tesseract`

如果缺少 `tesseract`，Skill 仍可安装和使用，但 **OCR fallback 不可用**。

### 手动使用脚本
先准备 Python 依赖：

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

如需 OCR 兜底，还需保证系统已安装 `tesseract`。

然后运行：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx"
```

输出 Markdown：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --format markdown
```

只跑 HTTP：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --mode http
```

强制浏览器模式：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --mode browser
```

保存到文件：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --format markdown --output ./article.md
```

输出调试产物（HTML / meta / screenshot）：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --debug --artifacts-dir ./artifacts
```

运行环境预检：

```bash
python3 scripts/check_env.py
```

## 抓取思路

现在这套实现已经改成三层抓取：

1. 先用 **微信移动 UA** 直接请求页面 HTML
2. 优先匹配微信公众号常见正文容器
3. 把 `data-src` / `data-actualsrc` 图片补成 `src`
4. 提取标题、作者、封面、发布时间
5. 如果静态结果太短、图片过少、段落过少，自动切到 **Playwright 真浏览器渲染**
6. 浏览器模式会等待正文节点出现，并按页面状态自动滚动，尽量触发懒加载
7. 自动识别一部分异常状态：`verify_required`、`captcha_or_env_check`、`article_deleted`、`content_not_found`、`anti_bot_suspected`
8. 如果浏览器页面可见、但 DOM 提取仍明显不足，会尝试 **OCR 兜底**
9. 把正文转成 Markdown
10. 清掉常见微信尾部噪音
11. 输出 JSON / Markdown

一句话说，就是：

**HTTP 优先 + Browser fallback + OCR 最后兜底 + 微信 DOM 定向提取 + 失败分类 + Markdown 输出**

## 当前限制

- 仍然不能承诺对任意文章 100% 成功
- 如果目标页面要求人工过验证码 / verify，浏览器模式和 OCR 都可能失败
- 如果微信页面 DOM 结构继续变化，需要补选择器
- 如果文章本身不可公开访问，也会失败
- OCR 兜底只适用于“页面视觉可见但 DOM 提取不足”的场景，不适合用来绕过 verify / anti-bot
- `publish_time` 等元数据在部分文章上仍可能缺失

## 输出结果

默认 JSON 会包含这些关键字段：
- `success`
- `status`
- `url`
- `final_url`
- `title`
- `author`
- `publish_time`
- `cover_image`
- `content_markdown`
- `images`
- `fetch_method`
- `page_status`
- `page_signals`
- `quality_metrics`
- `used_browser_fallback`
- `used_ocr_fallback`
- `decision_path`
- `attempts`

失败时也会返回结构化状态，而不是只打印一句报错。

## 回归测试

已经补了最小回归框架：

- 样例集：`tests/fixtures/urls.json`
- 回归脚本：`scripts/run_regression.py`
- 输出目录：`tests/results/`

运行：

```bash
python3 scripts/run_regression.py --debug
```

## 定位

这是一个**安全版、纯抓取版**实现。
如果后面要接摘要、入库、发布，建议由上层 Agent 再调用官方受控工具，不要把外部办公系统写入逻辑直接塞回抓取脚本里。

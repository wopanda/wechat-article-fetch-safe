# 集成说明 v1

## 目标

本仓库当前作为 **公众号文章抓取底座** 使用。
上层系统只应把它当作“抓取与结构化提取”组件，而不是完整内容生产系统。

## 推荐调用入口

优先使用：

```bash
python3 scripts/fetch_wechat_article.py "<wechat_url>" --format json
```

也可以在 Python 中调用 `extract()`：

```python
from scripts.fetch_wechat_article import extract
result = extract(url, debug=False, mode="auto")
```

## 推荐上层调用策略

### 1. 默认模式
- 默认使用 `mode=auto`
- 让脚本自己按 **HTTP → Browser → OCR** 决策

### 2. 上层应该读取的关键字段
- `success`
- `status`
- `fetch_method`
- `decision_path`
- `page_status`
- `page_signals`
- `content_markdown`
- `images`
- `quality_metrics`
- `attempts`

### 3. 上层遇到这些状态时的处理建议

#### 可以继续下游处理
- `success_http`
- `success_browser`
- `success_ocr`

#### 建议直接上报 / 转人工，不要死循环重试
- `verify_required`
- `captcha_or_env_check`
- `anti_bot_suspected`

#### 建议记为失败并结束
- `article_deleted`
- `content_not_found`
- `all_strategies_failed`

## 不建议上层做的事

- 不要对 `verify_required` 反复自动重试
- 不要把 OCR 当作默认第二步
- 不要假设 `publish_time` 永远存在
- 不要依赖某一篇文章的特定 DOM 结构

## 调试建议

当出现失败或结果异常时，优先开启：

```bash
python3 scripts/fetch_wechat_article.py "<wechat_url>" --debug --artifacts-dir ./artifacts
```

再查看：
- `page.html`
- `meta.json`
- `browser_final.png`（若有）

## 当前建议边界

这份能力更适合放在：
- 内容抓取前置层
- 摘要 / 改写 / 入库的上游
- Agent 调用的文章提取工具

不建议直接把发布、飞书写入、数据库写入等逻辑塞进这个仓库。

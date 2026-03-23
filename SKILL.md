---
name: wechat-article-fetch-safe
description: 从微信公众号文章 URL 安全提取标题、封面、正文与图片，输出 Markdown 或 JSON。适用于分析、归档、摘要、素材沉淀，不写入飞书、不读取本地敏感配置、不自动调用外部办公 API。
---

# WeChat Article Fetch Safe

用于安全抓取微信公众号文章内容，并整理成适合后续摘要、保存、改写或发布前处理的结构化结果。

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

核心思路是：
1. 请求目标 URL 的静态 HTML
2. 针对微信公众号页面优先匹配常见正文 DOM
3. 修正微信图片常见的 `data-src`
4. 解析标题与封面图
5. 把正文 HTML 转为 Markdown
6. 清理微信页面尾部噪音
7. 输出 Markdown 或 JSON

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

## 输出字段

JSON 模式默认输出：
- `url`
- `title`
- `cover_image`
- `content_markdown`
- `images`
- `source`

## 失败时的处理顺序

1. 先确认 URL 是否可公开访问
2. 再确认是否命中微信正文容器
3. 若正文为空，检查页面是否被重定向、限流或返回异常 HTML
4. 若结构变化明显，再补充选择器，而不是去接入高风险浏览器脚本

## 说明

这是安全版抓取 Skill。
保留的是“公众号页面抓取与提取”能力，不保留任何本地密钥读取、自动办公系统写入、或越权调用逻辑。

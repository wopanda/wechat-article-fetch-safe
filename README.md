# wechat-article-fetch-safe

一个安全版的微信公众号文章抓取 Skill / 脚本包。

它只做一件事：**把公众号文章 URL 提取成标题、封面、正文 Markdown 和图片链接**。

不做这些事：
- 不读取本地 OpenClaw 配置
- 不读取飞书密钥
- 不自动写飞书文档
- 不做越权调用

## 适合谁用

适合想把公众号文章：
- 拉成 Markdown
- 做摘要
- 存进知识库 / Obsidian
- 做二次改写或结构化整理

## 你怎么安装

### 最简单的方式
把这个仓库链接发给小龙虾，让它安装这个 Skill。

### 手动使用脚本
先准备 Python 依赖：

```bash
python3 -m pip install requests beautifulsoup4
```

然后运行：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx"
```

输出 Markdown：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --format markdown
```

保存到文件：

```bash
python3 scripts/fetch_wechat_article.py "https://mp.weixin.qq.com/s/xxxx" --format markdown --output ./article.md
```

## 抓取思路

这套实现保留的是一个相对克制、可维护的思路：

1. 先请求页面 HTML
2. 优先匹配微信公众号常见正文容器
3. 把 `data-src` 图片补成 `src`
4. 提取标题与封面
5. 把正文转成 Markdown
6. 清掉常见微信尾部噪音
7. 输出 JSON / Markdown

一句话说，就是：

**静态抓取 + 微信 DOM 定向提取 + 图片修正 + Markdown 输出**

## 当前限制

- 如果目标页面强依赖 JS，这种静态方式可能抓不全
- 如果微信页面 DOM 结构变化，需要补选择器
- 如果文章本身不可公开访问，也会失败

## 输出结果

默认 JSON 字段：
- `url`
- `title`
- `cover_image`
- `content_markdown`
- `images`
- `source`

## 定位

这是一个**安全版、纯抓取版**实现。
如果后面要接摘要、入库、发布，建议由上层 Agent 再调用官方受控工具，不要把外部办公系统写入逻辑直接塞回抓取脚本里。

# 抓取决策链说明 v1

## 目标

当输入一个微信公众号文章链接时，系统不靠临时拍脑袋，而是按固定顺序执行：

**HTTP → Browser → OCR（最后兜底）**

并在每一步都输出可解释的状态。

---

## 总决策图

### 输入：公众号文章 URL

1. 先跑 HTTP 提取
2. 若 HTTP 质量足够，直接返回 `success_http`
3. 若 HTTP 质量不足，进入 Browser fallback
4. 若 Browser 质量足够，返回 `success_browser`
5. 若 Browser 后仍明显不足，但页面视觉可见且不属于 verify / anti-bot / deleted，则尝试 OCR
6. 若 OCR 达到阈值，返回 `success_ocr`
7. 否则保留前面最优结果，或输出异常状态

---

## 第 1 层：HTTP 提取

### 当前策略
- `wechat-mobile`
- `chrome-desktop`

### 主要动作
- 请求 HTML
- 命中公众号正文容器
- 提取标题 / 作者 / 发布时间 / 封面 / 图片
- HTML 转 Markdown
- 清理尾部噪音
- 计算质量指标

### 质量指标
- `content_length`
- `image_count`
- `paragraph_count`
- `noise_hit_count`
- `body_selector`

### HTTP 直接成功条件（概念上）
当正文长度、图片数、段落数、页面状态等都达到基本要求时，直接返回。

### HTTP 不足时
满足任一情况，会进入 Browser：
- 正文过短
- 图片过少
- 段落过少
- 页面状态异常

---

## 第 2 层：Browser fallback

### 当前策略
- `playwright-mobile`

### 主要动作
- 用移动端浏览器打开页面
- 等待正文选择器
- 自动滚动触发懒加载
- 观察页面高度 / 文本长度 / 图片数量是否稳定
- 提取渲染后的 DOM
- 再次进行正文抽取与质量评估

### Browser 直接成功条件
Browser 结果优于 HTTP，并达到可用标准。

### Browser 之后为什么还可能进入 OCR
因为有些页面会出现：
- DOM 中正文很少
- 页面视觉上能看到更多内容
- 正文可能主要在图片或特殊卡片结构中

这类情况就会进入 OCR 候选。

---

## 第 3 层：OCR 最后兜底

### 当前策略
- `ocr-fallback`
- 依赖：`tesseract` + `Pillow`

### OCR 的定位
OCR 不是默认第二步，也不是用来突破 verify。
它只负责：

> 当浏览器页面视觉上已经有内容，但 DOM 提取明显不足时，作为最后兜底拿文本。

### OCR 触发条件（当前）
必须同时满足：
1. 已经跑过 Browser
2. 有浏览器截图
3. 页面状态不是以下几类：
   - `verify_required`
   - `captcha_or_env_check`
   - `anti_bot_suspected`
   - `article_deleted`
   - `content_not_found`
4. Browser 结果正文仍明显偏短

### OCR 当前处理方式
- 使用浏览器整页截图
- 先裁掉顶部 / 底部明显噪音区
- 调用 tesseract 做 OCR
- 清理 OCR 文本
- 若 OCR 文本长度低于阈值，则判为 `ocr_failed`
- 若达到阈值，则生成 `success_ocr`

### OCR 明确不解决的问题
- verify / captcha 页面
- anti-bot 页面
- 已删除 / 不存在页面
- 页面根本没显示正文的场景

---

## 异常状态判断

系统会优先识别这些状态：
- `verify_required`
- `captcha_or_env_check`
- `anti_bot_suspected`
- `article_deleted`
- `content_not_found`
- `all_strategies_failed`

这些状态下，不应该盲目无限重试。

---

## 输出字段解释

建议重点看这些字段：
- `status`：最终状态
- `fetch_method`：最终采用的方法
- `decision_path`：这次走过哪些策略
- `used_browser_fallback`：是否走了浏览器
- `used_ocr_fallback`：是否最终使用了 OCR
- `page_status`：页面状态判断
- `page_signals`：识别到的异常信号
- `quality_metrics`：质量指标
- `attempts`：每一步尝试结果

---

## 一个真实例子

某条链接的结果可能是：
- HTTP：内容太短
- Browser：拿到更多内容，但仍偏短
- OCR：尝试过，但识别结果仍太短
- 最终返回：`success_browser`

这说明：
- 决策链已经完整执行
- OCR 也被尝试过
- 但 OCR 不足以超过 Browser 结果

这种结果是合理的，不代表链路失败。

---

## 当前结论

当前版本已经具备：

**输入链接 → 按规则分流 → 必要时逐层降级 / 兜底 → 输出可解释结果**

这就是本仓库当前最核心的能力边界。

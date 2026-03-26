#!/usr/bin/env python3
import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image
from playwright.sync_api import sync_playwright

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0 Safari/537.36"
)

WECHAT_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Mobile/15E148 MicroMessenger/8.0.40 NetType/WIFI Language/zh_CN"
)

FETCH_STRATEGIES = [
    ("wechat-mobile", WECHAT_MOBILE_USER_AGENT),
    ("chrome-desktop", DESKTOP_USER_AGENT),
]

COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://mp.weixin.qq.com/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

WECHAT_CONTENT_SELECTORS = [
    "#js_content",
    ".rich_media_content",
    ".rich_media_area_primary",
    "article",
    "main",
    ".post-content",
    "[class*='body']",
]

TITLE_SELECTORS = [
    "#activity-name",
    ".rich_media_title",
    "h1",
]

AUTHOR_SELECTORS = [
    "#js_name",
    ".account_nickname_inner",
    ".rich_media_meta_nickname",
    ".wx_tap_link.js_wx_tap_highlight.nickname",
]

PUBLISH_TIME_SELECTORS = [
    "#publish_time",
    ".publish_time",
    "em.rich_media_meta_text#publish_time",
]

NOISE_PATTERNS = [
    r"微信扫一扫可打开此内容.*",
    r"轻触阅读原文.*",
    r"预览时标签不可点.*",
    r"继续滑动看下一个.*",
    r"请长按识别下方二维码.*",
    r"转载请按以下格式注明来源.*",
    r"喜欢此内容的人还喜欢.*",
    r"推荐阅读.*",
    r"账号迁移.*",
]

TAIL_CUT_PATTERNS = [
    r"怕你直接划到底.*",
    r"喜欢此内容的人还喜欢.*",
    r"继续滑动看下一个.*",
    r"相关阅读[：:].*",
    r"推荐阅读[：:].*",
]

TAIL_LINE_DROP_PATTERNS = [
    r"^👉\s*内测申请.*$",
    r"^👉\s*立即申请.*$",
    r"^👉\s*点击.*申请.*$",
]

REMOVE_SELECTORS = [
    "script",
    "style",
    "noscript",
    ".js_uneditable.custom_select_card_wrp",
    ".weui-loadmore",
    ".original_area_primary",
    ".mpda_bottom_container",
    ".wx_profile_card_inner",
    ".recommend_area",
    ".related_article_area",
    ".rich_media_tool",
    ".rich_media_area_extra",
    ".mp_profile_iframe_wrp",
    ".js_uneditable.custom_select_card",
]

BROWSER_WAIT_SELECTOR = "#js_content, .rich_media_content, #activity-name"
MAX_MARKDOWN_CHARS = 60000
DEFAULT_BROWSER_SCROLL_ROUNDS = 10
DEFAULT_BROWSER_SETTLE_ROUNDS = 2
DEFAULT_BROWSER_PAUSE_MS = 500
OCR_MIN_TEXT_LENGTH = 300
OCR_LANG = "chi_sim+eng"

PAGE_SIGNAL_RULES = [
    (
        "verify_required",
        [
            "请输入验证码",
            "安全验证",
            "请完成验证",
            "请在微信客户端打开链接",
            "你的访问过于频繁",
        ],
    ),
    (
        "captcha_or_env_check",
        [
            "环境异常",
            "当前环境异常",
            "请在微信中打开",
            "访问过于频繁",
            "操作过于频繁",
            "异常访问",
            "请稍后再试",
        ],
    ),
    (
        "article_deleted",
        [
            "该内容已被发布者删除",
            "此内容已被发布者删除",
            "此内容因违规无法查看",
            "内容已被删除",
            "该内容已不可访问",
            "根据投诉",
        ],
    ),
    (
        "content_not_found",
        [
            "链接已过期",
            "文章不存在",
            "内容不存在",
            "页面不存在",
            "已停止访问该网页",
        ],
    ),
    (
        "anti_bot_suspected",
        [
            "访问太频繁",
            "请稍后重试",
            "访问受限",
            "异常流量",
        ],
    ),
]


class ExtractFailure(RuntimeError):
    def __init__(self, status, message, attempts=None, errors=None, page_signals=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.attempts = attempts or []
        self.errors = errors or []
        self.page_signals = page_signals or []

    def to_dict(self):
        return {
            "success": False,
            "status": self.status,
            "message": self.message,
            "attempts": self.attempts,
            "errors": self.errors,
            "page_signals": self.page_signals,
        }


class SimpleHTMLToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.href_stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"p", "div", "section", "li", "blockquote"}:
            if self.parts and not self.parts[-1].endswith("\n\n"):
                self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag in {"h1", "h2", "h3", "h4"}:
            if self.parts and not self.parts[-1].endswith("\n\n"):
                self.parts.append("\n\n")
            level = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### "}[tag]
            self.parts.append(level)
        elif tag == "a":
            self.href_stack.append(attrs.get("href", ""))
            self.parts.append("[")
        elif tag == "img":
            src = attrs.get("src") or attrs.get("data-src") or attrs.get("data-actualsrc")
            alt = attrs.get("alt", "")
            if src:
                if self.parts and not self.parts[-1].endswith("\n"):
                    self.parts.append("\n")
                self.parts.append(f"![{alt}]({src})\n")

    def handle_endtag(self, tag):
        if tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "a":
            href = self.href_stack.pop() if self.href_stack else ""
            self.parts.append(f"]({href})")
        elif tag in {"p", "div", "section", "li", "blockquote", "h1", "h2", "h3", "h4"}:
            if not self.parts or not self.parts[-1].endswith("\n\n"):
                self.parts.append("\n\n")

    def handle_data(self, data):
        text = unescape(data)
        if text.strip():
            self.parts.append(text)

    def get_markdown(self):
        text = "".join(self.parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\*\*\s+", "**", text)
        text = re.sub(r"\s+\*\*", "**", text)
        return text.strip()


def pick_first(soup: BeautifulSoup, selectors):
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return node, selector
    return None, None


def dedupe_keep_order(values):
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def make_headers(user_agent: str):
    headers = dict(COMMON_HEADERS)
    headers["User-Agent"] = user_agent
    return headers


def stable_slug(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def ensure_dir(path: str):
    if path:
        os.makedirs(path, exist_ok=True)


def write_text(path: str, text: str):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def get_page_text(soup: BeautifulSoup) -> str:
    body = soup.body or soup
    return normalize_text(body.get_text(" ", strip=True))


def detect_page_signals(html: str, page_title: str = "", final_url: str = ""):
    soup = BeautifulSoup(html, "html.parser")
    page_text = get_page_text(soup)
    combined = f"{page_title} {final_url} {page_text}"
    signals = []
    for status, keywords in PAGE_SIGNAL_RULES:
        matched = [kw for kw in keywords if kw in combined]
        if matched:
            signals.append({"status": status, "matched": matched})

    if not signals and "mp.weixin.qq.com" not in (final_url or ""):
        signals.append({"status": "redirected_outside_wechat", "matched": [final_url]})

    return signals


def primary_page_status(signals):
    if not signals:
        return "ok"
    priority = {
        "verify_required": 100,
        "captcha_or_env_check": 90,
        "article_deleted": 80,
        "content_not_found": 70,
        "anti_bot_suspected": 60,
        "redirected_outside_wechat": 50,
    }
    best = max(signals, key=lambda item: priority.get(item["status"], 0))
    return best["status"]


def fetch_html(url: str, strategy_name: str, user_agent: str):
    resp = requests.get(url, headers=make_headers(user_agent), timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    html = resp.text
    return {
        "html": html,
        "final_url": resp.url,
        "status_code": resp.status_code,
        "page_title": "",
        "browser_trace": None,
        "transport": strategy_name,
    }


def collect_browser_metrics(page):
    return page.evaluate(
        """
        () => {
          const body = document.body;
          const docEl = document.documentElement;
          const text = (body?.innerText || '').trim();
          const imageCount = Array.from(document.images || []).filter(img => {
            const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
            return !!src;
          }).length;
          return {
            height: Math.max(body?.scrollHeight || 0, docEl?.scrollHeight || 0),
            text_length: text.length,
            image_count: imageCount,
            title: document.title || '',
            url: location.href,
          };
        }
        """
    )


def fetch_html_by_browser(url: str, user_agent: str, artifacts_dir: str = ""):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=user_agent,
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            device_scale_factor=3,
            locale="zh-CN",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(BROWSER_WAIT_SELECTOR, timeout=15000)
        except Exception:
            pass

        history = []
        stable_rounds = 0
        previous = None
        for _ in range(DEFAULT_BROWSER_SCROLL_ROUNDS):
            metrics = collect_browser_metrics(page)
            history.append(metrics)
            if previous:
                if (
                    metrics["height"] == previous["height"]
                    and metrics["text_length"] <= previous["text_length"] + 50
                    and metrics["image_count"] == previous["image_count"]
                ):
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                if stable_rounds >= DEFAULT_BROWSER_SETTLE_ROUNDS:
                    break
            page.mouse.wheel(0, 2200)
            page.wait_for_timeout(DEFAULT_BROWSER_PAUSE_MS)
            previous = metrics

        page.wait_for_timeout(800)
        html = page.content()
        final_metrics = collect_browser_metrics(page)
        history.append(final_metrics)
        final_url = page.url
        page_title = page.title()

        if artifacts_dir:
            ensure_dir(artifacts_dir)
            screenshot_path = os.path.join(artifacts_dir, "browser_final.png")
        else:
            fd, screenshot_path = tempfile.mkstemp(prefix="wechat-browser-", suffix=".png")
            os.close(fd)
        page.screenshot(path=screenshot_path, full_page=True)

        browser.close()
        return {
            "html": html,
            "final_url": final_url,
            "status_code": 200,
            "page_title": page_title,
            "browser_trace": history,
            "transport": "playwright-mobile",
            "screenshot_path": screenshot_path,
        }


def crop_center_image(input_path: str, output_path: str, top_ratio: float = 0.14, bottom_ratio: float = 0.92):
    with Image.open(input_path) as img:
        width, height = img.size
        top = int(height * top_ratio)
        bottom = int(height * bottom_ratio)
        if bottom <= top:
            top = 0
            bottom = height
        cropped = img.crop((0, top, width, bottom))
        cropped.save(output_path)


def run_tesseract_ocr(image_path: str):
    base = image_path
    if base.lower().endswith('.png'):
        base = base[:-4]
    txt_path = base + ".txt"
    cmd = ["tesseract", image_path, base, "-l", OCR_LANG]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "tesseract failed")
    if not os.path.exists(txt_path):
        raise RuntimeError("tesseract output missing")
    with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    return text


def normalize_ocr_text(text: str):
    text = text.replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    merged = []
    for line in lines:
        if merged and len(line) < 3 and len(merged[-1]) < 80:
            merged[-1] = merged[-1] + line
        else:
            merged.append(line)
    text = "\n\n".join(merged)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def should_try_ocr(best_candidate, page_signals, screenshot_path: str = ""):
    if not screenshot_path or not os.path.exists(screenshot_path):
        return False
    status = primary_page_status(page_signals)
    if status in {"verify_required", "captcha_or_env_check", "anti_bot_suspected", "article_deleted", "content_not_found"}:
        return False
    if best_candidate is None:
        return True
    metrics = best_candidate.get("quality_metrics", {})
    return (
        best_candidate.get("fetch_method") == "playwright-mobile"
        and metrics.get("content_length", 0) < 2500
    )


def build_ocr_candidate(url: str, screenshot_path: str, base_candidate: dict, attempt_name: str = "ocr-fallback"):
    with tempfile.TemporaryDirectory(prefix="wechat-ocr-") as tmpdir:
        cropped_path = os.path.join(tmpdir, "ocr_crop.png")
        crop_center_image(screenshot_path, cropped_path)
        text = run_tesseract_ocr(cropped_path)
        markdown = normalize_ocr_text(text)

    if len(markdown) < OCR_MIN_TEXT_LENGTH:
        raise ExtractFailure(status="ocr_failed", message="OCR 结果过短，未达到可用阈值")

    title = (base_candidate or {}).get("title", "")
    if title and title not in markdown[:200]:
        markdown = f"# {title}\n\n" + markdown

    return {
        "url": url,
        "final_url": (base_candidate or {}).get("final_url", url),
        "title": title,
        "author": (base_candidate or {}).get("author", ""),
        "publish_time": (base_candidate or {}).get("publish_time", ""),
        "cover_image": (base_candidate or {}).get("cover_image", ""),
        "content_markdown": markdown[:MAX_MARKDOWN_CHARS],
        "images": (base_candidate or {}).get("images", []),
        "source": "wechat-official-account",
        "fetch_method": attempt_name,
        "page_status": (base_candidate or {}).get("page_status", "ok"),
        "page_signals": (base_candidate or {}).get("page_signals", []),
        "quality_metrics": {
            "content_length": len(markdown),
            "image_count": len((base_candidate or {}).get("images", [])),
            "paragraph_count": paragraph_count_from_markdown(markdown),
            "noise_hit_count": 0,
            "body_selector": "ocr_screenshot",
        },
        "browser_trace": (base_candidate or {}).get("browser_trace"),
        "score": len(markdown) + 150,
        "ocr_used": True,
    }


def pick_best_image_src(img) -> str:
    candidates = [
        img.get("data-src"),
        img.get("data-actualsrc"),
        img.get("src"),
    ]
    for src in candidates:
        if src and not str(src).startswith("data:"):
            return src
    return ""


def normalize_images(node: BeautifulSoup, base_url: str):
    images = []
    for img in node.select("img"):
        src = pick_best_image_src(img)
        if not src:
            continue
        full_src = urljoin(base_url, src)
        img["src"] = full_src
        images.append(full_src)
    return dedupe_keep_order(images)


def extract_title(soup: BeautifulSoup) -> str:
    node, _ = pick_first(soup, TITLE_SELECTORS)
    if node:
        title = node.get_text(" ", strip=True)
        if title:
            return title

    for meta_key, attr in [
        ("meta[property='og:title']", "content"),
        ("meta[name='twitter:title']", "content"),
    ]:
        meta = soup.select_one(meta_key)
        if meta and meta.get(attr):
            return meta.get(attr).strip()

    if soup.title and soup.title.text:
        return soup.title.text.strip()
    return ""


def extract_author(soup: BeautifulSoup) -> str:
    node, _ = pick_first(soup, AUTHOR_SELECTORS)
    if node:
        author = node.get_text(" ", strip=True)
        if author:
            return author
    return ""


def extract_publish_time(soup: BeautifulSoup) -> str:
    node, _ = pick_first(soup, PUBLISH_TIME_SELECTORS)
    if node:
        publish_time = node.get_text(" ", strip=True)
        if publish_time:
            return publish_time
    return ""


def extract_cover(soup: BeautifulSoup, body_node: BeautifulSoup):
    thumb = soup.select_one(".rich_media_thumb")
    if thumb:
        style = thumb.get("style", "")
        m = re.search(r"url\((.*?)\)", style)
        if m:
            return m.group(1).strip("'\"")
        for key in ["data-src", "data-actualsrc", "src"]:
            if thumb.get(key):
                return thumb.get(key)

    og = soup.select_one("meta[property='og:image']")
    if og and og.get("content"):
        return og.get("content").strip()

    first_img = body_node.select_one("img") if body_node else None
    if first_img:
        return pick_best_image_src(first_img)
    return ""


def html_to_markdown(html: str) -> str:
    parser = SimpleHTMLToMarkdown()
    parser.feed(html)
    return parser.get_markdown()


def clean_noise(markdown: str):
    text = markdown
    noise_hits = []
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, text, flags=re.S):
            noise_hits.append(pattern)
        text = re.sub(pattern, "", text, flags=re.S)

    tail_cut_applied = False
    for pattern in TAIL_CUT_PATTERNS:
        match = re.search(pattern, text, flags=re.S)
        if match:
            noise_hits.append(pattern)
            text = text[: match.start()].rstrip()
            tail_cut_applied = True
            break

    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(re.match(pattern, stripped) for pattern in TAIL_LINE_DROP_PATTERNS):
            noise_hits.append(f"line:{stripped[:40]}")
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    if tail_cut_applied:
        text = re.sub(r"(\n\s*!\[[^\]]*\]\([^\)]+\)\s*){1,6}$", "", text, flags=re.S)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), dedupe_keep_order(noise_hits)


def prepare_body_node(body_node: BeautifulSoup):
    body_copy = copy.copy(body_node)
    for selector in REMOVE_SELECTORS:
        for node in body_copy.select(selector):
            node.decompose()
    return body_copy


def paragraph_count_from_markdown(markdown: str) -> int:
    return len([block for block in markdown.split("\n\n") if normalize_text(block)])


def quality_from_metrics(content_length: int, image_count: int, paragraph_count: int, noise_hit_count: int):
    score = content_length + image_count * 80 + paragraph_count * 50 - noise_hit_count * 60
    return score


def should_browser_fallback(candidate):
    if candidate is None:
        return True
    metrics = candidate.get("quality_metrics", {})
    page_status = candidate.get("page_status", "ok")
    return (
        metrics.get("content_length", 0) < 4000
        or metrics.get("image_count", 0) <= 2
        or metrics.get("paragraph_count", 0) < 8
        or page_status != "ok"
    )


def build_candidate(url: str, html: str, strategy_name: str, final_url: str = "", page_title: str = "", browser_trace=None):
    soup = BeautifulSoup(html, "html.parser")
    body_node, body_selector = pick_first(soup, WECHAT_CONTENT_SELECTORS)
    signals = detect_page_signals(html, page_title=page_title or extract_title(soup), final_url=final_url or url)
    page_status = primary_page_status(signals)
    if not body_node:
        raise ExtractFailure(
            status=page_status if page_status != "ok" else "content_not_found",
            message="未找到正文区域",
            page_signals=signals,
        )

    body_node = prepare_body_node(body_node)
    images = normalize_images(body_node, final_url or url)
    title = extract_title(soup)
    author = extract_author(soup)
    publish_time = extract_publish_time(soup)
    cover = extract_cover(soup, body_node)

    body_html = str(body_node)
    markdown_raw = html_to_markdown(body_html)
    markdown, noise_hits = clean_noise(markdown_raw)
    if cover and cover not in markdown:
        markdown = f"![cover]({cover})\n\n" + markdown

    content_length = len(markdown)
    paragraph_count = paragraph_count_from_markdown(markdown)
    image_count = len(images)
    score = quality_from_metrics(content_length, image_count, paragraph_count, len(noise_hits))
    if title:
        score += 400
    if author:
        score += 120
    if publish_time:
        score += 80

    return {
        "url": url,
        "final_url": final_url or url,
        "title": title,
        "author": author,
        "publish_time": publish_time,
        "cover_image": cover,
        "content_markdown": markdown[:MAX_MARKDOWN_CHARS],
        "images": images,
        "source": "wechat-official-account",
        "fetch_method": strategy_name,
        "page_status": page_status,
        "page_signals": signals,
        "quality_metrics": {
            "content_length": content_length,
            "image_count": image_count,
            "paragraph_count": paragraph_count,
            "noise_hit_count": len(noise_hits),
            "body_selector": body_selector,
        },
        "browser_trace": browser_trace,
        "score": score,
    }


def collect_attempt_summary(item, success: bool, message: str = ""):
    summary = {
        "fetch_method": item.get("fetch_method"),
        "success": success,
        "message": message,
    }
    for key in ["title", "author", "publish_time", "page_status"]:
        if item.get(key) is not None:
            summary[key] = item.get(key)
    metrics = item.get("quality_metrics") or {}
    if metrics:
        summary.update(metrics)
    if item.get("score") is not None:
        summary["score"] = item.get("score")
    if item.get("page_signals"):
        summary["page_signals"] = item.get("page_signals")
    return summary


def save_debug_artifacts(base_dir: str, attempt_name: str, payload: dict):
    if not base_dir:
        return {}
    attempt_dir = os.path.join(base_dir, attempt_name)
    ensure_dir(attempt_dir)
    html_path = os.path.join(attempt_dir, "page.html")
    meta_path = os.path.join(attempt_dir, "meta.json")
    if payload.get("html"):
        write_text(html_path, payload["html"])
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in payload.items() if k != "html"}, f, ensure_ascii=False, indent=2)
    return {"html_path": html_path, "meta_path": meta_path}


def extract(url: str, debug: bool = False, mode: str = "auto", artifacts_dir: str = ""):
    candidates = []
    errors = []
    attempts = []
    page_signals = []
    run_dir = ""
    last_browser_screenshot = ""
    browser_candidate = None

    if artifacts_dir:
        run_dir = os.path.join(artifacts_dir, f"{int(time.time())}_{stable_slug(url)}")
        ensure_dir(run_dir)

    if mode in {"auto", "http"}:
        for strategy_name, user_agent in FETCH_STRATEGIES:
            try:
                fetched = fetch_html(url, strategy_name, user_agent)
                artifact_paths = save_debug_artifacts(run_dir, strategy_name, fetched) if debug and run_dir else {}
                candidate = build_candidate(
                    url,
                    fetched["html"],
                    strategy_name,
                    final_url=fetched.get("final_url", url),
                    page_title=fetched.get("page_title", ""),
                )
                if artifact_paths:
                    candidate["artifacts"] = artifact_paths
                candidates.append(candidate)
                attempts.append(collect_attempt_summary(candidate, True))
                page_signals.extend(candidate.get("page_signals") or [])
            except ExtractFailure as e:
                errors.append(f"{strategy_name}: {e.message}")
                attempts.append({
                    "fetch_method": strategy_name,
                    "success": False,
                    "status": e.status,
                    "message": e.message,
                    "page_signals": e.page_signals,
                })
                page_signals.extend(e.page_signals)
            except Exception as e:
                errors.append(f"{strategy_name}: {e}")
                attempts.append({
                    "fetch_method": strategy_name,
                    "success": False,
                    "status": "request_failed",
                    "message": str(e),
                })

    http_best = max(candidates, key=lambda item: item["score"]) if candidates else None
    need_browser_fallback = mode == "browser" or (mode == "auto" and should_browser_fallback(http_best))

    if need_browser_fallback:
        try:
            browser_artifacts_dir = os.path.join(run_dir, "playwright-mobile") if run_dir else ""
            fetched = fetch_html_by_browser(url, WECHAT_MOBILE_USER_AGENT, artifacts_dir=browser_artifacts_dir if debug else "")
            artifact_paths = save_debug_artifacts(run_dir, "playwright-mobile", fetched) if debug and run_dir else {}
            candidate = build_candidate(
                url,
                fetched["html"],
                "playwright-mobile",
                final_url=fetched.get("final_url", url),
                page_title=fetched.get("page_title", ""),
                browser_trace=fetched.get("browser_trace"),
            )
            if artifact_paths:
                candidate["artifacts"] = artifact_paths
            if fetched.get("screenshot_path"):
                candidate.setdefault("artifacts", {})["screenshot_path"] = fetched["screenshot_path"]
                last_browser_screenshot = fetched["screenshot_path"]
            browser_candidate = candidate
            candidates.append(candidate)
            attempts.append(collect_attempt_summary(candidate, True))
            page_signals.extend(candidate.get("page_signals") or [])
        except ExtractFailure as e:
            errors.append(f"playwright-mobile: {e.message}")
            attempts.append({
                "fetch_method": "playwright-mobile",
                "success": False,
                "status": e.status,
                "message": e.message,
                "page_signals": e.page_signals,
            })
            page_signals.extend(e.page_signals)
        except Exception as e:
            errors.append(f"playwright-mobile: {e}")
            attempts.append({
                "fetch_method": "playwright-mobile",
                "success": False,
                "status": "browser_failed",
                "message": str(e),
            })

    best_before_ocr = max(candidates, key=lambda item: item["score"]) if candidates else browser_candidate or http_best
    if mode in {"auto", "browser"} and should_try_ocr(best_before_ocr, page_signals, screenshot_path=last_browser_screenshot):
        try:
            ocr_candidate = build_ocr_candidate(url, last_browser_screenshot, best_before_ocr, attempt_name="ocr-fallback")
            if debug and run_dir:
                ocr_candidate["artifacts"] = {"screenshot_path": last_browser_screenshot}
            candidates.append(ocr_candidate)
            attempts.append(collect_attempt_summary(ocr_candidate, True))
        except ExtractFailure as e:
            errors.append(f"ocr-fallback: {e.message}")
            attempts.append({
                "fetch_method": "ocr-fallback",
                "success": False,
                "status": e.status,
                "message": e.message,
            })
        except Exception as e:
            errors.append(f"ocr-fallback: {e}")
            attempts.append({
                "fetch_method": "ocr-fallback",
                "success": False,
                "status": "ocr_failed",
                "message": str(e),
            })

    if not candidates:
        joined = "; ".join(errors) if errors else "unknown error"
        status = primary_page_status(page_signals)
        if status == "ok":
            status = "all_strategies_failed"
        raise ExtractFailure(
            status=status,
            message=f"抓取失败，所有策略都未拿到可用正文：{joined}",
            attempts=attempts,
            errors=errors,
            page_signals=page_signals,
        )

    best = max(candidates, key=lambda item: item["score"])
    fetch_method = best.get("fetch_method")
    if fetch_method == "playwright-mobile":
        final_status = "success_browser"
    elif fetch_method == "ocr-fallback":
        final_status = "success_ocr"
    else:
        final_status = "success_http"
    used_browser_fallback = fetch_method == "playwright-mobile"
    result = {
        "success": True,
        "status": final_status,
        "url": best["url"],
        "final_url": best.get("final_url", best["url"]),
        "title": best["title"],
        "author": best["author"],
        "publish_time": best["publish_time"],
        "cover_image": best["cover_image"],
        "content_markdown": best["content_markdown"],
        "images": best["images"],
        "source": best["source"],
        "fetch_method": fetch_method,
        "page_status": best.get("page_status", "ok"),
        "page_signals": dedupe_keep_order([json.dumps(item, ensure_ascii=False, sort_keys=True) for item in best.get("page_signals", [])]),
        "quality_metrics": best.get("quality_metrics", {}),
        "used_browser_fallback": used_browser_fallback,
        "used_ocr_fallback": fetch_method == "ocr-fallback",
        "attempts": attempts,
        "decision_path": [item.get("fetch_method") for item in attempts if item.get("fetch_method")],
    }
    result["page_signals"] = [json.loads(item) for item in result["page_signals"]]
    if best.get("browser_trace"):
        result["browser_trace"] = best["browser_trace"]
    if debug:
        result["errors"] = errors
        if best.get("artifacts"):
            result["artifacts"] = best["artifacts"]
        if run_dir:
            result["artifacts_dir"] = run_dir
    return result


def main():
    parser = argparse.ArgumentParser(description="Fetch WeChat article content safely.")
    parser.add_argument("url", help="微信公众号文章 URL")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--mode", choices=["auto", "http", "browser"], default="auto", help="抓取模式：自动 / 仅HTTP / 仅浏览器")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--debug", action="store_true", help="输出调试信息")
    parser.add_argument("--artifacts-dir", help="调试产物输出目录（HTML / meta / screenshot）")
    args = parser.parse_args()

    try:
        result = extract(args.url, debug=args.debug, mode=args.mode, artifacts_dir=args.artifacts_dir or "")
        exit_code = 0
    except ExtractFailure as e:
        result = e.to_dict()
        exit_code = 1
    except Exception as e:
        result = {
            "success": False,
            "status": "unexpected_error",
            "message": str(e),
        }
        exit_code = 1

    if args.format == "markdown" and result.get("success"):
        output = f"# {result['title']}\n\n{result['content_markdown']}\n"
    else:
        output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        ensure_dir(os.path.dirname(args.output) or ".")
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

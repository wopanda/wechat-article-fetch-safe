#!/usr/bin/env python3
import argparse
import json
import re
import sys
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0 Safari/537.36"
)

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

NOISE_PATTERNS = [
    r"微信扫一扫可打开此内容.*",
    r"轻触阅读原文.*",
    r"预览时标签不可点.*",
    r"继续滑动看下一个.*",
]


class SimpleHTMLToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.href_stack = []
        self.in_paragraph = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"p", "div", "section"}:
            if self.parts and not self.parts[-1].endswith("\n\n"):
                self.parts.append("\n\n")
            self.in_paragraph = True
        elif tag in {"br"}:
            self.parts.append("\n")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("*")
        elif tag == "a":
            self.href_stack.append(attrs.get("href", ""))
            self.parts.append("[")
        elif tag == "img":
            src = attrs.get("src") or attrs.get("data-src")
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
        elif tag in {"p", "div", "section"}:
            if not self.parts or not self.parts[-1].endswith("\n\n"):
                self.parts.append("\n\n")
            self.in_paragraph = False

    def handle_data(self, data):
        text = unescape(data)
        if text.strip():
            self.parts.append(text)

    def get_markdown(self):
        text = "".join(self.parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def pick_first(soup: BeautifulSoup, selectors):
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return node
    return None


def normalize_images(node: BeautifulSoup, base_url: str):
    images = []
    for img in node.select("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        full_src = urljoin(base_url, src)
        img["src"] = full_src
        images.append(full_src)
    return images


def extract_title(soup: BeautifulSoup) -> str:
    node = pick_first(soup, TITLE_SELECTORS)
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


def extract_cover(soup: BeautifulSoup, body_node: BeautifulSoup):
    thumb = soup.select_one(".rich_media_thumb")
    if thumb:
        style = thumb.get("style", "")
        m = re.search(r"url\((.*?)\)", style)
        if m:
            return m.group(1).strip("'\"")
        for key in ["data-src", "src"]:
            if thumb.get(key):
                return thumb.get(key)

    og = soup.select_one("meta[property='og:image']")
    if og and og.get("content"):
        return og.get("content").strip()

    first_img = body_node.select_one("img") if body_node else None
    if first_img:
        return first_img.get("src") or first_img.get("data-src") or ""
    return ""


def html_to_markdown(html: str) -> str:
    parser = SimpleHTMLToMarkdown()
    parser.feed(html)
    return parser.get_markdown()


def clean_noise(markdown: str) -> str:
    text = markdown
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract(url: str):
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    body_node = pick_first(soup, WECHAT_CONTENT_SELECTORS)
    if not body_node:
        raise RuntimeError("未找到正文区域，可能页面结构已变化，或目标页面不是可直接抓取的公众号文章。")

    images = normalize_images(body_node, url)
    title = extract_title(soup)
    cover = extract_cover(soup, body_node)

    body_html = str(body_node)
    markdown = clean_noise(html_to_markdown(body_html))

    if cover and cover not in markdown:
        markdown = f"![cover]({cover})\n\n" + markdown

    return {
        "url": url,
        "title": title,
        "cover_image": cover,
        "content_markdown": markdown[:30000],
        "images": images,
        "source": "wechat-official-account",
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch WeChat article content safely.")
    parser.add_argument("url", help="微信公众号文章 URL")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--output", help="输出文件路径")
    args = parser.parse_args()

    try:
        result = extract(args.url)
    except Exception as e:
        print(f"抓取失败：{e}", file=sys.stderr)
        sys.exit(1)

    if args.format == "markdown":
        output = f"# {result['title']}\n\n{result['content_markdown']}\n"
    else:
        output = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import shutil
import subprocess
import sys


def check_python_package(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def main():
    results = []

    results.append(("python3", sys.executable or "python3", True))
    results.append(("requests", "python import", check_python_package("requests")))
    results.append(("bs4", "python import", check_python_package("bs4")))
    results.append(("playwright", "python import", check_python_package("playwright")))
    results.append(("PIL", "python import", check_python_package("PIL")))

    tesseract_path = shutil.which("tesseract")
    results.append(("tesseract", tesseract_path or "missing", bool(tesseract_path)))

    chromium_ok = False
    chromium_detail = "unknown"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--help"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        chromium_ok = proc.returncode == 0
        chromium_detail = "playwright cli ok" if chromium_ok else (proc.stderr.strip() or proc.stdout.strip() or "playwright cli unavailable")
    except Exception as e:
        chromium_detail = str(e)
    results.append(("playwright-cli", chromium_detail, chromium_ok))

    print("wechat-article-fetch-safe 环境预检")
    print("=" * 40)
    for name, detail, ok in results:
        print(f"[{ 'OK' if ok else 'WARN' }] {name}: {detail}")

    print("\n能力判断：")
    has_playwright = any(r[0] == "playwright" and r[2] for r in results)
    has_tesseract = any(r[0] == "tesseract" and r[2] for r in results)
    if has_playwright:
        print("- Browser fallback：理论可用（仍需目标环境已安装 chromium）")
    else:
        print("- Browser fallback：不可用，将退化为 HTTP 主链")
    if has_tesseract:
        print("- OCR fallback：可用")
    else:
        print("- OCR fallback：不可用，但 HTTP / Browser 仍可工作")

    print("\n建议：")
    print("1. 先执行: python3 -m pip install -r requirements.txt")
    print("2. 再执行: python3 -m playwright install chromium")
    print("3. 如需 OCR 兜底，请确保系统已安装 tesseract")


if __name__ == "__main__":
    main()

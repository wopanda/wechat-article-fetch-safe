#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURES = ROOT / "tests" / "fixtures" / "urls.json"
DEFAULT_RESULTS = ROOT / "tests" / "results"
FETCH_SCRIPT = ROOT / "scripts" / "fetch_wechat_article.py"


def expectation_matches(expectation, payload):
    status = payload.get("status")
    success = payload.get("success")

    if expectation == "success":
        return bool(success)
    if expectation == "success_or_verify":
        return bool(success) or status in {"verify_required", "captcha_or_env_check", "anti_bot_suspected"}
    if expectation == "content_not_found_or_deleted":
        return status in {"content_not_found", "article_deleted", "all_strategies_failed", "anti_bot_suspected", "captcha_or_env_check", "verify_required"}
    return True


def compact_payload(payload):
    return {
        "success": payload.get("success"),
        "status": payload.get("status"),
        "fetch_method": payload.get("fetch_method"),
        "title": payload.get("title"),
        "page_status": payload.get("page_status"),
        "used_browser_fallback": payload.get("used_browser_fallback"),
        "quality_metrics": payload.get("quality_metrics"),
    }


def run_one(entry, debug=False):
    url = entry["url"]
    name = entry["name"]
    out_dir = DEFAULT_RESULTS / name
    out_dir.mkdir(parents=True, exist_ok=True)
    output_json = out_dir / "result.json"
    cmd = [
        sys.executable,
        str(FETCH_SCRIPT),
        url,
        "--format",
        "json",
        "--output",
        str(output_json),
    ]
    if debug:
        cmd += ["--debug", "--artifacts-dir", str(out_dir / "artifacts")]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    result = {
        "name": name,
        "url": url,
        "expectation": entry.get("expectation", "unknown"),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "output_json": str(output_json),
    }

    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            result.update(compact_payload(payload))
            result["expectation_matched"] = expectation_matches(result["expectation"], payload)
            result["attempts"] = payload.get("attempts", [])
        except Exception as e:
            result["parse_error"] = str(e)
            result["expectation_matched"] = False
    else:
        result["expectation_matched"] = False

    return result


def build_overview(results):
    status_counter = Counter()
    fetch_method_counter = Counter()
    success_count = 0
    matched_count = 0
    browser_fallback_count = 0
    content_lengths = []
    image_counts = []

    for item in results:
        if item.get("status"):
            status_counter[item["status"]] += 1
        if item.get("fetch_method"):
            fetch_method_counter[item["fetch_method"]] += 1
        if item.get("success"):
            success_count += 1
        if item.get("expectation_matched"):
            matched_count += 1
        if item.get("used_browser_fallback"):
            browser_fallback_count += 1
        qm = item.get("quality_metrics") or {}
        if qm.get("content_length") is not None:
            content_lengths.append(qm.get("content_length", 0))
        if qm.get("image_count") is not None:
            image_counts.append(qm.get("image_count", 0))

    case_count = len(results)
    return {
        "case_count": case_count,
        "success_count": success_count,
        "success_rate": round(success_count / case_count, 4) if case_count else 0,
        "expectation_matched_count": matched_count,
        "expectation_match_rate": round(matched_count / case_count, 4) if case_count else 0,
        "browser_fallback_count": browser_fallback_count,
        "status_distribution": dict(status_counter),
        "fetch_method_distribution": dict(fetch_method_counter),
        "avg_content_length": round(sum(content_lengths) / len(content_lengths), 1) if content_lengths else 0,
        "avg_image_count": round(sum(image_counts) / len(image_counts), 1) if image_counts else 0,
    }


def main():
    parser = argparse.ArgumentParser(description="Run regression tests for wechat article fetcher.")
    parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURES), help="fixtures json path")
    parser.add_argument("--debug", action="store_true", help="save html/screenshot artifacts")
    parser.add_argument("--summary", default=str(DEFAULT_RESULTS / "summary.json"), help="summary output path")
    args = parser.parse_args()

    fixtures_path = Path(args.fixtures)
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    entries = fixtures.get("cases", [])

    DEFAULT_RESULTS.mkdir(parents=True, exist_ok=True)
    results = []
    for entry in entries:
        results.append(run_one(entry, debug=args.debug))

    summary = {
        "fixtures": str(fixtures_path),
        "overview": build_overview(results),
        "results": results,
    }

    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

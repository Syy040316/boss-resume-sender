from __future__ import annotations

import json
import os
import queue
import random
import re
import shutil
import sys
import tempfile
import threading
import time
import csv
import contextlib
import functools
import http.server
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright
except ImportError:  # pragma: no cover - handled by GUI startup
    BrowserContext = object  # type: ignore
    Page = object  # type: ignore
    PlaywrightTimeoutError = Exception  # type: ignore
    sync_playwright = None  # type: ignore


APP_DIR = Path.home() / ".boss_resume_sender"
PROFILE_DIR = APP_DIR / "browser_profile"
CONFIG_PATH = APP_DIR / "config.json"
HISTORY_PATH = APP_DIR / "history.jsonl"
EVIDENCE_DIR = APP_DIR / "evidence"
BOSS_HOME = "https://www.zhipin.com/web/geek/job"
LOGIN_ENTRY_URL = BOSS_HOME
LOGIN_ENTRY_URLS = [
    BOSS_HOME,
    "https://www.zhipin.com/web/geek/jobs",
    "https://www.zhipin.com/",
]
CITY_CODES = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "天津": "101030100",
    "重庆": "101040100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "武汉": "101200100",
    "南京": "101190100",
    "苏州": "101190400",
    "西安": "101110100",
    "郑州": "101180100",
    "长沙": "101250100",
    "青岛": "101120200",
    "济南": "101120100",
    "合肥": "101220100",
    "福州": "101230100",
    "厦门": "101230200",
    "宁波": "101210400",
    "无锡": "101190200",
    "东莞": "101281600",
    "佛山": "101280800",
    "珠海": "101280700",
    "大连": "101070200",
    "沈阳": "101070100",
    "哈尔滨": "101050100",
    "长春": "101060100",
    "石家庄": "101090100",
    "太原": "101100100",
    "南昌": "101240100",
    "南宁": "101300100",
    "昆明": "101290100",
    "贵阳": "101260100",
    "海口": "101310100",
}

# -- Anti-detection stealth JS (BOSS Zhipin specific) --
# Addresses: navigator.webdriver, console.table timing, performance.now tampering detection,
# Function.prototype.toString leak, missing chrome object, empty plugins, CDP artifacts.
STEALTH_JS = """
(() => {
    "use strict";

    // 1. Hide navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });

    // 2. Simulate window.chrome
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = {};
    }

    // 3. Simulate plugins (normal Chrome has at least a few)
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const arr = [
                { name: 'Chrome PDF Plugin', description: 'Portable Document Format', filename: 'internal-pdf-viewer', length: 1,
                  item: i => ({ type: 'application/x-google-chrome-pdf' }),
                  namedItem: n => ({ type: 'application/x-google-chrome-pdf' }) },
                { name: 'Chrome PDF Viewer', description: '', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', length: 0,
                  item: () => null, namedItem: () => null },
                { name: 'Native Client', description: '', filename: 'internal-nacl-plugin', length: 2,
                  item: i => ({ type: 'application/x-nacl' }),
                  namedItem: n => ({ type: 'application/x-pnacl' }) },
            ];
            arr.length = 3;
            arr.refresh = () => {};
            return arr;
        },
        configurable: true,
    });

    // 4. Simulate languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en'],
        configurable: true,
    });

    // 5. Fix permissions.query for notifications
    if (navigator.permissions) {
        const origQuery = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = (params) => {
            if (params.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission });
            }
            return origQuery(params);
        };
    }

    // 6. deviceMemory
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8,
        configurable: true,
    });

    // 7. hardwareConcurrency
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
        configurable: true,
    });

    // 8. Hook console.table to defeat disable-devtool timing attack
    const origConsoleTable = console.table;
    console.table = function() {};

    // 9. Hook performance.now - keep monotonic but realistic
    const perfOrigin = (typeof performance !== 'undefined' && performance.timeOrigin)
        ? performance.timeOrigin
        : Date.now();
    performance.now = function() {
        return Date.now() - perfOrigin;
    };

    // 10. Protect hooked functions from Function.prototype.toString detection
    const origToString = Function.prototype.toString;
    const nativeTag = fn => `function ${fn}() { [native code] }`;
    Function.prototype.toString = function() {
        if (this === Function.prototype.toString) return nativeTag('toString');
        if (this === console.table) return nativeTag('table');
        if (this === performance.now) return nativeTag('now');
        return origToString.call(this);
    };
    Function.prototype.toString.toString = function() {
        return nativeTag('toString');
    };

    // 11. Remove CDP-injected artifacts
    for (const key of Object.keys(window)) {
        if (/^cdc_[a-zA-Z0-9]+_$/.test(key)) {
            try { delete window[key]; } catch (e) {}
        }
    }

    // 12. Override WebGL vendor/renderer to look normal
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.call(this, param);
    };
})();
"""


def bundled_browser_candidates() -> list[Path]:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        return [base / "ms-playwright", base / "_internal" / "ms-playwright"]
    return [Path(__file__).resolve().parent / "ms-playwright"]


def find_bundled_browsers_dir() -> Path | None:
    for candidate in bundled_browser_candidates():
        if candidate.exists():
            return candidate
    return None


def prepare_playwright_environment() -> Path | None:
    bundled_browsers_dir = find_bundled_browsers_dir()
    if bundled_browsers_dir:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled_browsers_dir)
    return bundled_browsers_dir


def find_browser_executable() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    bundled = find_bundled_browsers_dir()
    if bundled:
        for path in bundled.glob("chromium-*/chrome-win64/chrome.exe"):
            if path.exists():
                return path
    return None


def _find_system_browser_channel() -> str | None:
    """Return Playwright channel name for a system-installed Chrome/Edge, or None."""
    chrome_paths = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for p in chrome_paths:
        if p.exists():
            return "chrome"
    edge_paths = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for p in edge_paths:
        if p.exists():
            return "msedge"
    return None


def _find_system_browser_executable() -> Path | None:
    """Return the path to a system-installed Chrome or Edge exe, or None."""
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def temporary_app_paths(prefix: str):
    global APP_DIR, PROFILE_DIR, CONFIG_PATH, HISTORY_PATH, EVIDENCE_DIR
    old_paths = (APP_DIR, PROFILE_DIR, CONFIG_PATH, HISTORY_PATH, EVIDENCE_DIR)
    temp_app_dir = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        APP_DIR = temp_app_dir
        PROFILE_DIR = APP_DIR / "browser_profile"
        CONFIG_PATH = APP_DIR / "config.json"
        HISTORY_PATH = APP_DIR / "history.jsonl"
        EVIDENCE_DIR = APP_DIR / "evidence"
        ensure_app_dir()
        yield temp_app_dir
    finally:
        APP_DIR, PROFILE_DIR, CONFIG_PATH, HISTORY_PATH, EVIDENCE_DIR = old_paths
        shutil.rmtree(temp_app_dir, ignore_errors=True)


def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def split_words(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，\n;；、|]+", value) if item.strip()]


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


BOSS_PRIVATE_DIGIT_TRANSLATION = str.maketrans(
    {
        chr(0xE031): "0",
        chr(0xE032): "1",
        chr(0xE033): "2",
        chr(0xE034): "3",
        chr(0xE035): "4",
        chr(0xE036): "5",
        chr(0xE037): "6",
        chr(0xE038): "7",
        chr(0xE039): "8",
        chr(0xE03A): "9",
    }
)


def decode_boss_private_digits(value: str) -> str:
    # BOSS uses a custom salary font where private-use chars render as digits.
    return (value or "").translate(BOSS_PRIVATE_DIGIT_TRANSLATION)


def normalize_salary_text(value: str) -> str:
    text = normalize_text(decode_boss_private_digits(value))
    if not text:
        return ""
    text = text.replace("Ｋ", "K").replace("ｋ", "K")
    patterns = (
        r"\d+(?:\.\d+)?\s*[kK]\s*[-~—–至]\s*\d+(?:\.\d+)?\s*[kK](?:\s*[·/]\s*\d+\s*薪)?",
        r"\d+(?:\.\d+)?\s*[-~—–至]\s*\d+(?:\.\d+)?\s*[kK](?:\s*[·/]\s*\d+\s*薪)?",
        r"\d+(?:\.\d+)?\s*[kK](?:\s*[·/]\s*\d+\s*薪)?",
        r"\d+(?:\.\d+)?\s*[-~—–至]\s*\d+(?:\.\d+)?\s*元\s*/\s*(?:天|日)",
        r"\d+(?:\.\d+)?\s*元\s*/\s*(?:天|日)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", "", match.group(0)).replace("—", "-").replace("–", "-").replace("至", "-")
    return ""


def salary_matches(value: str, expected_min_k: int) -> bool:
    if expected_min_k <= 0:
        return True
    salary = normalize_salary_text(value)
    if not salary:
        return True
    if "k" not in salary.lower():
        return True
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", salary)]
    if not numbers:
        return True
    return max(numbers) >= expected_min_k


def any_word_in_text(words: list[str], text: str) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words if word)


def normalize_experience_text(text: str) -> str:
    return normalize_text(decode_boss_private_digits(text)).lower().replace(" ", "")


def experience_categories(text: str) -> set[str]:
    value = normalize_experience_text(text)
    categories: set[str] = set()
    if not value:
        return categories
    if re.search(r"(在校|实习|实习生|学生)", value):
        categories.add("student")
    if re.search(r"(应届|校招|校园招聘|毕业生|届)", value):
        categories.add("fresh")
    if re.search(r"(无经验|接受无经验|无需经验|不限经验|经验不限)", value):
        categories.update({"no_experience", "junior", "under_1_year"})
    if re.search(r"(初级|助理|入门)", value):
        categories.update({"junior", "under_1_year"})
    if re.search(r"(1年以内|1年以下|一年以内|一年以下|0-1年|0至1年|0~1年|0－1年|0–1年|0—1年)", value):
        categories.update({"under_1_year", "junior"})
    return categories


def experience_keywords_match(keywords: list[str], text: str) -> bool:
    if any_word_in_text(keywords, text):
        return True
    text_categories = experience_categories(text)
    if not text_categories:
        return False
    return any(experience_categories(keyword) & text_categories for keyword in keywords)


def text_has_any_experience_signal(text: str) -> bool:
    if not text:
        return False
    return bool(
        re.search(
            r"(在校|实习|应届|校招|校园招聘|毕业生|经验|年以内|年以下|年以上|\d+\s*[-~—–至]\s*\d+\s*年|\d+\s*年|不限经验|经验不限|无经验|初级)",
            text,
            flags=re.IGNORECASE,
        )
    )


def text_has_any_education_signal(text: str) -> bool:
    if not text:
        return False
    return any(word in text for word in ("学历", "本科", "大专", "硕士", "博士", "高中", "中专", "不限"))


def text_has_any_active_signal(text: str) -> bool:
    if not text:
        return False
    return any(word.lower() in text.lower() for word in ("活跃", "在线", "刚刚", "今日", "3日内", "本周", "本月"))


def choose_greeting_template(value: str) -> str:
    templates = split_words(value)
    if not templates and value.strip():
        templates = [value.strip()]
    return random.choice(templates) if templates else ""


@dataclass
class AppConfig:
    keywords: str = "Python"
    cities: str = "上海"
    max_count: int = 20
    max_pages: int = 5
    greet_message: str = "您好，我对这个岗位很感兴趣，方便的话想进一步沟通一下。"
    blacklist: str = ""
    exclude_keywords: str = "外包,培训"
    experience_keywords: str = ""
    education_keywords: str = ""
    active_keywords: str = ""
    min_salary_k: int = 0
    preview_only: bool = True
    auto_confirm_resume: bool = False
    save_failure_evidence: bool = True
    unique_company_per_run: bool = True
    skip_headhunter: bool = True
    min_delay: float = 2.0
    max_delay: float = 5.0
    headless: bool = False

    @classmethod
    def load(cls) -> "AppConfig":
        ensure_app_dir()
        if not CONFIG_PATH.exists():
            return cls()
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception:
            return cls()

    def save(self) -> None:
        ensure_app_dir()
        CONFIG_PATH.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class JobItem:
    title: str
    company: str
    href: str
    salary: str = ""
    tags: str = ""
    detail: str = ""
    city: str = ""
    keyword: str = ""

    @property
    def history_key(self) -> str:
        return f"{self.company}|{self.title}|{self.href}".lower()

    @property
    def searchable_text(self) -> str:
        return " ".join((self.title, self.company, self.salary, self.tags, self.detail))


@dataclass
class RunOptions:
    keywords: list[str]
    cities: list[str]
    max_count: int
    max_pages: int
    greet_message: str
    blacklist: list[str]
    exclude_keywords: list[str]
    experience_keywords: list[str]
    education_keywords: list[str]
    active_keywords: list[str]
    min_salary_k: int
    preview_only: bool
    auto_confirm_resume: bool
    save_failure_evidence: bool
    unique_company_per_run: bool
    skip_headhunter: bool
    min_delay: float
    max_delay: float


@dataclass
class RunStats:
    success: int = 0
    skipped: int = 0
    failed: int = 0
    visited: int = 0
    preview: int = 0
    rows: list[dict[str, str]] = field(default_factory=list)


class BossAutomation:
    def __init__(self, emit: Callable[[str, str, dict | None], None], stop_event: threading.Event) -> None:
        self.emit = emit
        self.stop_event = stop_event
        self.playwright = None
        self.context: BrowserContext | None = None
        self._chrome_process: subprocess.Popen | None = None

    def open_login(self) -> None:
        self.emit("log", "????????????????????????????????????", None)
        self._open_login_with_external_browser()
        self.emit("log", f"?????: {PROFILE_DIR}", None)

    def run(self, options: RunOptions) -> RunStats:
        if sync_playwright is None:
            raise RuntimeError("缺少 playwright，请先运行: py -3 -m pip install -r requirements.txt")
        stats = RunStats()
        prepare_playwright_environment()
        self.playwright = sync_playwright().start()
        self.context = self._launch_context(viewport={"width": 1366, "height": 900})
        page = self._first_page()
        sent_keys = self._load_history()
        try:
            self._run_search_loop(page, options, stats, sent_keys)
        finally:
            self.emit("status", "任务结束", None)
        return stats

    def _run_search_loop(self, page: Page, options: RunOptions, stats: RunStats, sent_keys: set[str]) -> None:
        seen_companies: set[str] = set()
        for city in options.cities:
            city_success = 0
            city_preview = 0
            self.emit("log", f"开始处理城市: {city}，目标: {options.max_count}", None)
            for keyword in options.keywords:
                if self.stop_event.is_set() or self._city_target_reached(city_success, city_preview, options):
                    break
                self._emit_progress(stats, options, city, city_success, city_preview)
                self.emit("status", f"搜索: {city} / {keyword}", None)
                self.emit("log", f"开始搜索关键词: {keyword}，城市: {city}", None)
                for page_index, jobs in self.iter_search_pages(page, keyword, city, options.max_pages):
                    self.emit("log", f"{city} / {keyword} 第 {page_index} 页找到 {len(jobs)} 个候选岗位。", None)
                    if self.stop_event.is_set() or self._city_target_reached(city_success, city_preview, options):
                        break
                    for job in jobs:
                        if self.stop_event.is_set() or self._city_target_reached(city_success, city_preview, options):
                            break
                        job.keyword = keyword
                        job.city = city
                        company_key = normalize_text(job.company).lower()
                        if options.unique_company_per_run and company_key and company_key in seen_companies:
                            self._record(job, "跳过", "本轮已处理同公司")
                            result = "skipped"
                        else:
                            result = self.handle_job(page, job, options, sent_keys)
                            if options.unique_company_per_run and company_key and result in {"success", "preview"}:
                                seen_companies.add(company_key)
                        stats.visited += 1
                        if result == "success":
                            stats.success += 1
                            city_success += 1
                            sent_keys.add(job.history_key)
                        elif result == "preview":
                            stats.preview += 1
                            city_preview += 1
                            stats.skipped += 1
                        elif result == "skipped":
                            stats.skipped += 1
                        else:
                            stats.failed += 1
                        self._emit_progress(stats, options, city, city_success, city_preview)
                        self._random_sleep(options)
                self.emit("log", f"关键词处理完成: {keyword}，城市: {city}", None)
            self._emit_progress(stats, options, city, city_success, city_preview)
            self.emit("log", f"城市处理完成: {city}，成功 {city_success}，预览 {city_preview}，目标 {options.max_count}", None)

    def _city_target_reached(self, city_success: int, city_preview: int, options: RunOptions) -> bool:
        if options.preview_only:
            return city_preview >= options.max_count
        return city_success >= options.max_count

    def _emit_progress(self, stats: RunStats, options: RunOptions, city: str, city_success: int, city_preview: int) -> None:
        self.emit(
            "progress",
            "",
            {
                "success": stats.success,
                "skipped": stats.skipped,
                "failed": stats.failed,
                "preview": stats.preview,
                "visited": stats.visited,
                "max_count": options.max_count,
                "city": city,
                "city_success": city_success,
                "city_preview": city_preview,
            },
        )

    def diagnose(self, keyword: str, city: str) -> dict[str, str | int | bool]:
        if sync_playwright is None:
            raise RuntimeError("缺少 playwright，请先运行: py -3 -m pip install -r requirements.txt")
        prepare_playwright_environment()
        self.playwright = sync_playwright().start()
        self.context = self._launch_context(viewport={"width": 1366, "height": 900})
        page = self._first_page()
        try:
            self.emit("status", f"诊断: {city} / {keyword}", None)
            jobs_by_page = list(self.iter_search_pages(page, keyword, city, 1))
            jobs = jobs_by_page[0][1] if jobs_by_page else []
            logged_out = self._looks_logged_out(page)
            result: dict[str, str | int | bool] = {
                "url": page.url,
                "title": page.title(),
                "logged_out": logged_out,
                "job_count": len(jobs),
                "first_job": f"{jobs[0].company} - {jobs[0].title} - {jobs[0].salary}" if jobs else "",
            }
            self.emit("log", f"诊断结果: 未登录={logged_out}，岗位数={len(jobs)}，标题={result['title']}", None)
            if jobs:
                self.emit("log", f"首个岗位: {result['first_job']}", None)
            self.emit("log", f"当前页面: {page.url}", None)
            return result
        except Exception as exc:
            self.emit("log", f"诊断失败: {exc}", None)
            raise
        finally:
            self.emit("status", "诊断结束", None)

    def iter_search_pages(self, page: Page, keyword: str, city: str, max_pages: int) -> Iterable[tuple[int, list[JobItem]]]:
        city_code = CITY_CODES.get(city)
        if city_code:
            page.goto(f"{BOSS_HOME}?query={quote(keyword, safe='')}&city={city_code}", wait_until="domcontentloaded", timeout=60000)
        else:
            page.goto(BOSS_HOME, wait_until="domcontentloaded", timeout=60000)
        self._accept_popups(page)
        if not city_code:
            self._fill_search(page, keyword)
            self._choose_city(page, city)
            self._click_search(page)
        self._wait_job_list(page)
        seen_page_keys: set[str] = set()
        for page_index in range(1, max(1, max_pages) + 1):
            self._scroll_job_list(page)
            jobs = self._extract_jobs(page)
            jobs = [job for job in jobs if job.history_key not in seen_page_keys]
            for job in jobs:
                seen_page_keys.add(job.history_key)
            if not jobs:
                page.wait_for_timeout(1500)
                jobs = self._extract_jobs(page)
                jobs = [job for job in jobs if job.history_key not in seen_page_keys]
                for job in jobs:
                    seen_page_keys.add(job.history_key)
            yield page_index, jobs
            if self.stop_event.is_set() or page_index >= max_pages:
                return
            if not self._go_next_page(page):
                return
            self._wait_job_list(page)

    def handle_job(self, page: Page, job: JobItem, options: RunOptions, sent_keys: set[str]) -> str:
        if job.history_key in sent_keys:
            self._record(job, "跳过", "历史已处理")
            return "skipped"
        skip_reason = self._filter_job(job, options, detail_loaded=False)
        if skip_reason:
            self._record(job, "跳过", skip_reason)
            return "skipped"
        if any_word_in_text(options.blacklist, job.company):
            self._record(job, "跳过", "命中公司黑名单")
            return "skipped"
        if not job.href:
            self._record(job, "失败", "岗位链接为空")
            return "failed"

        self.emit("status", f"处理: {job.company} - {job.title}", None)
        detail = page.context.new_page()
        try:
            detail.goto(job.href, wait_until="domcontentloaded", timeout=60000)
            self._accept_popups(detail)
            self._merge_detail_info(detail, job)
            detail_skip_reason = self._filter_job(job, options, detail_loaded=True)
            if detail_skip_reason:
                self._record(job, "跳过", detail_skip_reason)
                return "skipped"
            if self._looks_logged_out(detail):
                self._record(job, "失败", "登录态失效，请重新手动登录", self._save_evidence(detail, job, options, "logged_out"))
                self.emit("log", "检测到可能未登录，任务会继续尝试下一个岗位。", None)
                return "failed"
            if self._already_communicated(detail):
                self._record(job, "跳过", "页面显示已沟通或按钮不可投递")
                return "skipped"
            if options.preview_only:
                self._record(job, "预览", "符合筛选条件，未执行打招呼/投递")
                return "preview"
            clicked = self._click_greet_or_apply(detail)
            if not clicked:
                self._record(job, "失败", "未找到打招呼/立即沟通/投递按钮", self._save_evidence(detail, job, options, "button_missing"))
                return "failed"
            greeting = choose_greeting_template(options.greet_message)
            self._send_greeting_if_possible(detail, greeting)
            if greeting:
                self.emit("log", f"使用打招呼文案: {greeting[:40]}", None)
            if options.auto_confirm_resume:
                self._confirm_resume_if_possible(detail)
                self._record(job, "成功", "已点击沟通并自动确认投递")
            else:
                self._record(job, "成功", "已点击沟通，未自动确认投递")
            return "success"
        except PlaywrightTimeoutError:
            self._record(job, "失败", "页面超时", self._save_evidence(detail, job, options, "timeout"))
            return "failed"
        except Exception as exc:
            self._record(job, "失败", str(exc)[:120], self._save_evidence(detail, job, options, "exception"))
            return "failed"
        finally:
            detail.close()

    def _filter_job(self, job: JobItem, options: RunOptions, detail_loaded: bool = True) -> str | None:
        # Use title + company + tags for keyword matching.  The full page body
        # (detail) is too broad — common words like "培训" appear in job
        # descriptions (e.g. "入职培训") and cause false positives.
        short_text = f"{job.title} {job.company} {job.tags}"
        full_text = job.searchable_text
        if options.skip_headhunter and self._looks_like_headhunter(job):
            return "疑似猎头或人力资源服务岗位"
        if any_word_in_text(options.exclude_keywords, short_text):
            return "命中岗位排除词"
        if options.experience_keywords and not experience_keywords_match(options.experience_keywords, full_text):
            if not detail_loaded and not text_has_any_experience_signal(full_text):
                return None
            return "不符合经验筛选"
        if options.education_keywords and not any_word_in_text(options.education_keywords, full_text):
            if not detail_loaded and not text_has_any_education_signal(full_text):
                return None
            return "不符合学历筛选"
        if options.active_keywords and not any_word_in_text(options.active_keywords, full_text):
            if not detail_loaded and not text_has_any_active_signal(full_text):
                return None
            return "不符合 HR 活跃筛选"
        if not salary_matches(job.salary, options.min_salary_k):
            return f"薪资低于 {options.min_salary_k}K"
        return None

    def _looks_like_headhunter(self, job: JobItem) -> bool:
        # Only match against the company name — matching against the full page
        # body (detail) causes false positives because words like "人才发展" or
        # "管理咨询" commonly appear in normal job descriptions.
        company = job.company.lower()
        words = (
            "猎头",
            "代招",
            "rpo",
            "人力资源服务",
            "人力资源管理",
            "劳务派遣",
            "企业管理咨询",
            "管理咨询有限公司",
            "人才服务",
            "人才发展",
            "招聘服务",
        )
        return any(word in company for word in words)

    def _save_evidence(self, page: Page, job: JobItem, options: RunOptions, label: str) -> str:
        if not options.save_failure_evidence:
            return ""
        ensure_app_dir()
        safe_company = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", job.company or "unknown")[:40]
        safe_title = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", job.title or "job")[:40]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = EVIDENCE_DIR / f"{stamp}_{label}_{safe_company}_{safe_title}"
        png_path = base.with_suffix(".png")
        html_path = base.with_suffix(".html")
        try:
            page.screenshot(path=str(png_path), full_page=True, timeout=8000)
        except Exception:
            png_path = Path("")
        try:
            html_path.write_text(page.content(), encoding="utf-8")
        except Exception:
            html_path = Path("")
        paths = [str(path) for path in (png_path, html_path) if str(path)]
        evidence = " | ".join(paths)
        if evidence:
            self.emit("log", f"失败现场已保存: {evidence}", None)
        return evidence

    def close(self) -> None:
        if self.context is not None:
            self.context.close()
            self.context = None
        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None
        if self._chrome_process is not None:
            try:
                self._chrome_process.kill()
            except OSError:
                pass
            self._chrome_process = None

    def _launch_context(self, viewport: dict | None = None) -> BrowserContext:
        assert self.playwright is not None
        ensure_app_dir()

        # --- Strategy 1: CDP to a real Chrome launched externally ---
        # This avoids ALL Playwright automation flags and CDP detection.
        # BOSS detects Playwright's bundled Chromium via TLS/JA3 fingerprint
        # and CDP Runtime.enable — launching Chrome natively bypasses both.
        browser_exe = _find_system_browser_executable()
        if browser_exe:
            import socket as _socket
            free_port = 0
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                free_port = s.getsockname()[1]
            cdp_url = f"http://127.0.0.1:{free_port}"
            self.emit("log", f"启动本机 Chrome (CDP 端口 {free_port}) 以通过安全检测...", None)
            self._chrome_process = subprocess.Popen([
                str(browser_exe),
                f"--user-data-dir={PROFILE_DIR}",
                "--profile-directory=Default",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                f"--remote-debugging-port={free_port}",
                "--remote-debugging-address=127.0.0.1",
            ])
            # Wait for CDP endpoint to become available
            for _attempt in range(30):
                time.sleep(0.5)
                try:
                    with _socket.create_connection(("127.0.0.1", free_port), timeout=1):
                        break
                except OSError:
                    pass
            else:
                self.emit("log", "Chrome CDP 未响应，回退到 Playwright 启动。", None)
                self._chrome_process.kill()
                self._chrome_process = None
                return self._launch_context_fallback(viewport)
            browser = self.playwright.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            context.add_init_script(STEALTH_JS)
            if viewport:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_viewport_size(viewport)
            return context

        # --- Strategy 2: Fallback to Playwright launch ---
        return self._launch_context_fallback(viewport)

    def _launch_context_fallback(self, viewport: dict | None = None) -> BrowserContext:
        assert self.playwright is not None
        kwargs = {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
                "--disable-background-timer-throttling",
                "--disable-popup-blocking",
                "--disable-renderer-backgrounding",
            ],
            "ignore_default_args": [
                "--enable-automation",
            ],
        }
        if viewport:
            kwargs["viewport"] = viewport
        bundled_browsers_dir = prepare_playwright_environment()
        if bundled_browsers_dir:
            self.emit("log", f"使用随包浏览器: {bundled_browsers_dir}", None)
        else:
            self.emit("log", "未找到可用浏览器。", None)
        context = self.playwright.chromium.launch_persistent_context(str(PROFILE_DIR), **kwargs)
        context.add_init_script(STEALTH_JS)
        return context

    def _open_login_with_external_browser(self) -> None:
        ensure_app_dir()
        browser = find_browser_executable()
        if browser is None:
            raise RuntimeError("未找到 Chrome/Edge/随包 Chromium，无法打开手动登录窗口")
        nav_page = self._write_login_navigation_page("manual")
        debug = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "mode": "external_browser_login",
            "browser": str(browser),
            "profile_dir": str(PROFILE_DIR),
            "entry": str(nav_page),
            "note": "manual login opens a local navigation page first; user clicks Boss manually to avoid security-check loops",
        }
        (APP_DIR / "login_debug.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
        args = [
            str(browser),
            f"--user-data-dir={PROFILE_DIR}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--new-window",
            nav_page.as_uri(),
        ]
        subprocess.Popen(args)

    def _first_page(self) -> Page:
        assert self.context is not None
        return self.context.pages[0] if self.context.pages else self.context.new_page()

    def _login_page(self) -> Page:
        assert self.context is not None
        page = self.context.new_page()
        page.bring_to_front()
        self._close_extra_blank_pages(page)
        return page

    def _open_login_entry(self, page: Page) -> None:
        last_error = ""
        attempts: list[dict[str, str]] = []
        for url in LOGIN_ENTRY_URLS:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                page.bring_to_front()
                self._close_extra_blank_pages(page)
                attempts.append({"entry": url, "result_url": page.url, "status": "opened"})
                if page.url != "about:blank":
                    self.emit("log", f"???????: {page.url}", None)
                    self._write_login_debug(attempts, page.url, False, "")
                    return
                last_error = "????????"
            except Exception as exc:
                last_error = str(exc)
                attempts.append({"entry": url, "result_url": "", "status": f"error: {exc}"})
                self.emit("log", f"????????????????: {url} / {exc}", None)
        fallback = self._write_login_fallback_page(last_error)
        try:
            page = self._login_page()
        except Exception:
            if page.is_closed():
                page = self._first_page()
        html = fallback.read_text(encoding="utf-8")
        try:
            page.set_content(html, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            page.wait_for_timeout(1000)
            page.set_content(html, wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()
        self._write_login_debug(attempts, page.url, True, last_error)
        self.emit("log", f"??????????: {fallback}", None)

    def _write_login_debug(self, attempts: list[dict[str, str]], final_url: str, used_fallback: bool, error: str) -> None:
        ensure_app_dir()
        data = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "profile_dir": str(PROFILE_DIR),
            "attempts": attempts,
            "final_url": final_url,
            "used_fallback": used_fallback,
            "error": error,
        }
        (APP_DIR / "login_debug.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_login_fallback_page(self, reason: str) -> Path:
        ensure_app_dir()
        path = APP_DIR / "login_fallback.html"
        links = "\n".join(
            f'<li><a href="{url}" target="_self">{url}</a></li>'
            for url in LOGIN_ENTRY_URLS + ["https://login.zhipin.com/"]
        )
        html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Boss 登录入口</title>
  <style>
    body {{ font-family: Arial, "Microsoft YaHei", sans-serif; max-width: 760px; margin: 48px auto; line-height: 1.7; }}
    a {{ color: #0b65c2; font-size: 18px; }}
    code {{ background: #f3f4f6; padding: 2px 6px; }}
  </style>
</head>
<body>
  <h1>Boss 登录入口</h1>
  <p>自动打开登录入口失败，原因：<code>{reason}</code></p>
  <p>请点击下面任意入口进入 Boss 页面，然后在页面内完成登录。登录完成后回到工具继续检查登录状态。</p>
  <ul>{links}</ul>
</body>
</html>"""
        path.write_text(html, encoding="utf-8")
        return path

    def _write_login_navigation_page(self, reason: str) -> Path:
        ensure_app_dir()
        path = APP_DIR / "login_navigation.html"
        links = [
            ("Boss 首页", "https://www.zhipin.com/"),
            ("Boss 登录页", "https://www.zhipin.com/web/user/?ka=header-login"),
            ("求职岗位页", "https://www.zhipin.com/web/geek/jobs"),
        ]
        link_html = "\n".join(f'<li><a href="{url}">{label}</a><div class="url">{url}</div></li>' for label, url in links)
        html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Boss 手动登录导航</title>
  <style>
    body {{ font-family: Arial, "Microsoft YaHei", sans-serif; max-width: 820px; margin: 48px auto; line-height: 1.7; color: #1f2937; }}
    h1 {{ font-size: 24px; margin-bottom: 12px; }}
    li {{ margin: 14px 0; }}
    a {{ color: #0b65c2; font-size: 18px; font-weight: 600; }}
    .url {{ color: #6b7280; font-size: 13px; word-break: break-all; }}
    .tip {{ background: #f3f4f6; padding: 12px 14px; border-radius: 6px; }}
  </style>
</head>
<body>
  <h1>Boss 手动登录导航</h1>
  <p class="tip">为避免登录页自动安全检查反复跳转，本页不会自动打开 Boss。请手动点击下面入口完成登录。登录成功后关闭这个浏览器窗口，再回到工具点击“检查登录/页面”。</p>
  <ul>{link_html}</ul>
  <p class="url">reason: {reason}</p>
</body>
</html>"""
        path.write_text(html, encoding="utf-8")
        return path

    def _close_extra_blank_pages(self, keep: Page) -> None:
        assert self.context is not None
        for page in list(self.context.pages):
            if page == keep:
                continue
            if page.url == "about:blank":
                try:
                    page.close()
                except Exception:
                    pass

    def _random_sleep(self, options: RunOptions) -> None:
        delay = random.uniform(options.min_delay, max(options.min_delay, options.max_delay))
        end = time.time() + delay
        while time.time() < end and not self.stop_event.is_set():
            time.sleep(0.2)

    def _accept_popups(self, page: Page) -> None:
        for text in ("知道了", "同意", "确定", "我知道了", "暂不"):
            try:
                locator = page.get_by_text(text, exact=True)
                if locator.count() > 0 and locator.first.is_visible(timeout=600):
                    locator.first.click(timeout=800)
                    page.wait_for_timeout(300)
            except Exception:
                pass

    def _fill_search(self, page: Page, keyword: str) -> None:
        selectors = [
            "input[placeholder*='搜索']",
            "input[placeholder*='职位']",
            "input[name='query']",
            ".search-form input",
        ]
        for selector in selectors:
            loc = page.locator(selector).first
            try:
                if loc.is_visible(timeout=2500):
                    loc.fill(keyword)
                    return
            except Exception:
                continue
        raise RuntimeError("未找到岗位关键词输入框")

    def _choose_city(self, page: Page, city: str) -> None:
        if not city:
            return
        try:
            current_city = page.locator(".city-label, .city-select, .city-name").first
            if current_city.is_visible(timeout=1200):
                current_city.click()
                page.wait_for_timeout(500)
                target = page.get_by_text(city, exact=True)
                if target.count() > 0:
                    target.first.click()
                    page.wait_for_timeout(500)
                    return
        except Exception:
            pass
        try:
            url = page.url
            if "city=" not in url:
                self.emit("log", f"未能自动切换城市 {city}，将使用当前站点城市继续搜索。", None)
        except Exception:
            pass

    def _click_search(self, page: Page) -> None:
        selectors = [
            "button:has-text('搜索')",
            ".search-btn",
            "a:has-text('搜索')",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if loc.is_visible(timeout=1500):
                    loc.click()
                    return
            except Exception:
                continue
        page.keyboard.press("Enter")

    def _wait_job_list(self, page: Page) -> None:
        for selector in (".job-card-wrapper", ".job-list-box li", ".job-primary", "a[href*='/job_detail/']"):
            try:
                page.locator(selector).first.wait_for(state="visible", timeout=12000)
                return
            except Exception:
                continue

    def _scroll_job_list(self, page: Page) -> None:
        for _ in range(3):
            try:
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(500)
            except Exception:
                break

    def _go_next_page(self, page: Page) -> bool:
        selectors = [
            ".options-pages a:has-text('下一页')",
            ".page a:has-text('下一页')",
            "a[ka*='page-next']",
            "a[aria-label*='下一页']",
            "button:has-text('下一页')",
            ".pagination-next",
            ".ui-icon-arrow-right",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if loc.count() > 0 and loc.is_visible(timeout=1000):
                    class_name = (loc.get_attribute("class") or "").lower()
                    disabled = loc.get_attribute("disabled")
                    if "disabled" in class_name or disabled is not None:
                        return False
                    old_url = page.url
                    loc.click(timeout=2000)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        pass
                    page.wait_for_timeout(1200)
                    return page.url != old_url or bool(self._extract_jobs(page))
            except Exception:
                continue
        return False

    def _extract_jobs(self, page: Page) -> list[JobItem]:
        script = """
        () => {
          const anchors = Array.from(document.querySelectorAll("a[href*='/job_detail/']"));
          const seen = new Set();
          const items = [];
          for (const a of anchors) {
            const card = a.closest("li.job-card-box, .job-card-wrapper, .job-card-wrap, .job-card-body, .job-primary, [class*='job-card'], li") || a;
            const href = new URL(a.getAttribute("href"), location.origin).href;
            if (seen.has(href)) continue;
            seen.add(href);
            const titleEl = card.querySelector("a.job-name, .job-name, .job-title a, [class*='job-name'], [class*='job-title'] a") || a;
            const companyEl = card.querySelector(".boss-name, .company-name, [class*='company'] a, [class*='company-name'], [class*='boss-name']");
            const salaryEl = card.querySelector(".salary, .job-salary, [class*='salary']");
            const tagEls = Array.from(card.querySelectorAll(".tag-list li, .tag-list span, .job-labels span, .job-info span, .info-desc, [class*='tag'] li, [class*='tag'] span, [class*='label']"));
            const title = (titleEl.textContent || a.textContent || "").trim();
            const company = (companyEl && companyEl.textContent || "").trim();
            const salary = (salaryEl && salaryEl.textContent || "").trim();
            const tags = tagEls.map(el => (el.textContent || "").trim()).filter(Boolean).join(" ");
            const detail = (card.textContent || "").trim();
            if (title) items.push({title, company, href, salary, tags, detail});
          }
          return items.slice(0, 80);
        }
        """
        rows = page.evaluate(script)
        return [
            JobItem(
                title=normalize_text(row.get("title", "")),
                company=normalize_text(row.get("company", "")),
                href=row.get("href", ""),
                salary=normalize_salary_text(row.get("salary", "")) or normalize_text(decode_boss_private_digits(row.get("salary", ""))),
                tags=normalize_text(decode_boss_private_digits(row.get("tags", ""))),
                detail=normalize_text(decode_boss_private_digits(row.get("detail", ""))),
            )
            for row in rows
        ]

    def _merge_detail_info(self, page: Page, job: JobItem) -> None:
        script = """
        () => {
          const salaryEl = document.querySelector(".salary, .job-salary, [class*='salary']");
          const tagEls = Array.from(document.querySelectorAll(".job-sec-text, .job-labels span, .tag-list li, .tag-list span, .job-detail-section span, [class*='tag'] li, [class*='tag'] span, [class*='label']"));
          const body = document.body ? document.body.innerText : "";
          return {
            salary: (salaryEl && salaryEl.textContent || "").trim(),
            tags: tagEls.map(el => (el.textContent || "").trim()).filter(Boolean).join(" "),
            detail: body.slice(0, 5000),
          };
        }
        """
        try:
            row = page.evaluate(script)
        except Exception:
            return
        salary = normalize_salary_text(row.get("salary", "")) or normalize_text(decode_boss_private_digits(row.get("salary", "")))
        job.salary = salary or job.salary
        detail_tags = normalize_text(decode_boss_private_digits(row.get("tags", "")))
        if detail_tags:
            job.tags = normalize_text(f"{job.tags} {detail_tags}")
        detail_text = normalize_text(decode_boss_private_digits(row.get("detail", "")))
        if detail_text:
            job.detail = detail_text

    def _looks_logged_out(self, page: Page) -> bool:
        texts = ("扫码登录", "密码登录", "登录/注册", "微信登录")
        return any(self._has_text(page, text) for text in texts)

    def _already_communicated(self, page: Page) -> bool:
        # Only skip jobs that are truly finished — "继续沟通" means an ongoing
        # conversation that can still receive a greeting, so do NOT treat it as
        # already communicated.
        texts = ("已沟通", "已投递", "沟通过")
        return any(self._has_text(page, text) for text in texts)

    def _click_greet_or_apply(self, page: Page) -> bool:
        candidates = (
            "立即沟通",
            "打招呼",
            "继续沟通",
            "投递简历",
            "立即投递",
            "申请职位",
        )
        for text in candidates:
            try:
                button = page.get_by_text(text, exact=True)
                if button.count() > 0 and button.first.is_visible(timeout=1200):
                    button.first.click(timeout=2000)
                    page.wait_for_timeout(1200)
                    return True
            except Exception:
                continue
        return False

    def _send_greeting_if_possible(self, page: Page, message: str) -> None:
        if not message:
            return
        # BOSS opens a chat panel with textarea.input-area after clicking "立即沟通".
        # The send button is div.send-message (disabled until text is entered).
        selectors = [
            "textarea.input-area",
            "textarea",
            "[contenteditable='true']",
            ".chat-input",
            "div[contenteditable]",
        ]
        for selector in selectors:
            try:
                box = page.locator(selector).first
                if box.is_visible(timeout=1200):
                    box.click()
                    page.wait_for_timeout(200)
                    box.fill(message)
                    page.wait_for_timeout(500)
                    # Try class-based send button first (BOSS specific),
                    # then fall back to text-based matching.
                    sent = False
                    send_btn = page.locator(".send-message").first
                    try:
                        if send_btn.is_visible(timeout=800):
                            send_btn.click(timeout=1500)
                            sent = True
                    except Exception:
                        pass
                    if not sent:
                        sent = self._click_by_text(page, ("发送", "确定", "打招呼"))
                    if not sent:
                        box.press("Enter")
                    page.wait_for_timeout(600)
                    return
            except Exception:
                continue
        self.emit("log", "未找到聊天输入框，无法发送打招呼文案。", None)

    def _confirm_resume_if_possible(self, page: Page) -> None:
        self._click_by_text(page, ("确认投递", "立即投递", "发送简历", "确定", "确认"))

    def _click_by_text(self, page: Page, texts: Iterable[str]) -> bool:
        for text in texts:
            try:
                loc = page.get_by_text(text, exact=True)
                if loc.count() > 0 and loc.first.is_visible(timeout=800):
                    loc.first.click(timeout=1200)
                    page.wait_for_timeout(600)
                    return True
            except Exception:
                continue
        return False

    def _has_text(self, page: Page, text: str) -> bool:
        try:
            loc = page.get_by_text(text, exact=False)
            return loc.count() > 0 and loc.first.is_visible(timeout=500)
        except Exception:
            return False

    def _record(self, job: JobItem, status: str, reason: str, evidence: str = "") -> None:
        ensure_app_dir()
        row = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "reason": reason,
            "city": job.city,
            "keyword": job.keyword,
            "company": job.company,
            "title": job.title,
            "salary": job.salary,
            "tags": job.tags,
            "evidence": evidence,
            "url": job.href,
        }
        with HISTORY_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.emit("row", "", row)
        self.emit("log", f"{status}: {job.company} - {job.title} ({reason})", None)

    def _load_history(self) -> set[str]:
        if not HISTORY_PATH.exists():
            return set()
        keys: set[str] = set()
        for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if row.get("status") in {"成功", "已沟通", "已投递"}:
                    keys.add(f"{row.get('company','')}|{row.get('title','')}|{row.get('url','')}".lower())
            except Exception:
                continue
        return keys


class BossApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        ensure_app_dir()
        self.title("Boss 直聘自动化简历投递")
        self.geometry("1180x780")
        self.minsize(1040, 700)
        self.config_data = AppConfig.load()
        self.events: queue.Queue[tuple[str, str, dict | None]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.automation: BossAutomation | None = None
        self.success_var = tk.StringVar(value="0")
        self.preview_count_var = tk.StringVar(value="0")
        self.skipped_var = tk.StringVar(value="0")
        self.failed_var = tk.StringVar(value="0")
        self.visited_var = tk.StringVar(value="0")
        self.target_var = tk.StringVar(value="0")
        self.status_var = tk.StringVar(value="就绪")
        self._build_ui()
        self._load_config_to_ui()
        self.after(150, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # -- Left: scrollable panel --
        left_outer = ttk.Frame(self)
        left_outer.grid(row=0, column=0, sticky="nsew")
        left_outer.rowconfigure(0, weight=1)
        left_outer.columnconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_outer, highlightthickness=0, borderwidth=0)
        left_scrollbar = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)

        left_scrollbar.grid(row=0, column=1, sticky="ns")
        left_canvas.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(left_canvas, padding=12)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.columnconfigure(1, weight=1)

        def _on_left_frame_configure(event):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))

        def _on_canvas_configure(event):
            left_canvas.itemconfig(left_window, width=event.width)

        left.bind("<Configure>", _on_left_frame_configure)
        left_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(event):
            left_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(event):
            left_canvas.unbind_all("<MouseWheel>")

        left_canvas.bind("<Enter>", _bind_mousewheel)
        left_canvas.bind("<Leave>", _unbind_mousewheel)
        left.bind("<Enter>", _bind_mousewheel)
        left.bind("<Leave>", _unbind_mousewheel)

        ttk.Label(left, text="岗位关键词").grid(row=0, column=0, sticky="w")
        self.keywords_entry = ttk.Entry(left, width=34)
        self.keywords_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(3, 10))

        ttk.Label(left, text="城市").grid(row=2, column=0, sticky="w")
        self.cities_entry = ttk.Entry(left, width=34)
        self.cities_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(3, 10))

        ttk.Label(left, text="最大投递数量").grid(row=4, column=0, sticky="w")
        self.max_count_var = tk.IntVar(value=20)
        ttk.Spinbox(left, from_=1, to=500, textvariable=self.max_count_var, width=10).grid(row=5, column=0, sticky="w", pady=(3, 10))

        ttk.Label(left, text="每组最大翻页数").grid(row=6, column=0, sticky="w")
        self.max_pages_var = tk.IntVar(value=5)
        ttk.Spinbox(left, from_=1, to=50, textvariable=self.max_pages_var, width=10).grid(row=7, column=0, sticky="w", pady=(3, 10))

        ttk.Label(left, text="随机等待秒数").grid(row=8, column=0, sticky="w")
        delay_frame = ttk.Frame(left)
        delay_frame.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(3, 10))
        self.min_delay_var = tk.DoubleVar(value=2.0)
        self.max_delay_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(delay_frame, from_=0.5, to=60, increment=0.5, textvariable=self.min_delay_var, width=8).pack(side="left")
        ttk.Label(delay_frame, text=" 到 ").pack(side="left", padx=4)
        ttk.Spinbox(delay_frame, from_=0.5, to=120, increment=0.5, textvariable=self.max_delay_var, width=8).pack(side="left")

        ttk.Label(left, text="最低薪资(K，0为不限)").grid(row=10, column=0, sticky="w")
        self.min_salary_var = tk.IntVar(value=0)
        ttk.Spinbox(left, from_=0, to=200, textvariable=self.min_salary_var, width=10).grid(row=11, column=0, sticky="w", pady=(3, 10))

        ttk.Label(left, text="经验关键词").grid(row=12, column=0, sticky="w")
        self.experience_entry = ttk.Entry(left, width=34)
        self.experience_entry.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(3, 10))

        ttk.Label(left, text="学历关键词").grid(row=14, column=0, sticky="w")
        self.education_entry = ttk.Entry(left, width=34)
        self.education_entry.grid(row=15, column=0, columnspan=2, sticky="ew", pady=(3, 10))

        ttk.Label(left, text="HR活跃/在线关键词").grid(row=16, column=0, sticky="w")
        self.active_entry = ttk.Entry(left, width=34)
        self.active_entry.grid(row=17, column=0, columnspan=2, sticky="ew", pady=(3, 10))

        ttk.Label(left, text="岗位排除词").grid(row=18, column=0, sticky="w")
        self.exclude_entry = ttk.Entry(left, width=34)
        self.exclude_entry.grid(row=19, column=0, columnspan=2, sticky="ew", pady=(3, 10))

        self.preview_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(left, text="预览模式，不点击打招呼/投递", variable=self.preview_var).grid(row=20, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.auto_confirm_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="自动确认投递简历", variable=self.auto_confirm_var).grid(row=21, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.evidence_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(left, text="失败时保存截图和 HTML", variable=self.evidence_var).grid(row=22, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.unique_company_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(left, text="本轮同公司只处理一次", variable=self.unique_company_var).grid(row=23, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.skip_headhunter_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(left, text="跳过猎头/人力资源服务岗位", variable=self.skip_headhunter_var).grid(row=24, column=0, columnspan=2, sticky="w", pady=(0, 10))

        ttk.Label(left, text="公司黑名单").grid(row=25, column=0, sticky="w")
        self.blacklist_entry = ttk.Entry(left, width=34)
        self.blacklist_entry.grid(row=26, column=0, columnspan=2, sticky="ew", pady=(3, 10))

        ttk.Label(left, text="打招呼文案（多条用换行/逗号分隔）").grid(row=27, column=0, sticky="w")
        self.message_text = tk.Text(left, width=34, height=4, wrap="word")
        self.message_text.grid(row=28, column=0, columnspan=2, sticky="ew", pady=(3, 12))

        button_frame = ttk.Frame(left)
        button_frame.grid(row=29, column=0, columnspan=2, sticky="ew")
        button_frame.columnconfigure((0, 1), weight=1)
        ttk.Button(button_frame, text="手动登录/保存状态", command=self.open_login).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(button_frame, text="检查登录/页面", command=self.start_diagnose).grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ttk.Button(button_frame, text="保存配置", command=self.save_config).grid(row=1, column=0, sticky="ew", padx=(0, 5), pady=(8, 0))
        ttk.Button(button_frame, text="导出记录", command=self.export_history).grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=(8, 0))
        ttk.Button(button_frame, text="清空历史", command=self.clear_history).grid(row=2, column=0, sticky="ew", padx=(0, 5), pady=(8, 0))
        ttk.Button(button_frame, text="打开数据目录", command=lambda: self.open_folder(APP_DIR)).grid(row=2, column=1, sticky="ew", padx=(5, 0), pady=(8, 0))
        ttk.Button(button_frame, text="打开证据目录", command=lambda: self.open_folder(EVIDENCE_DIR)).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        run_frame = ttk.Frame(left)
        run_frame.grid(row=30, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        run_frame.columnconfigure((0, 1), weight=1)
        self.start_btn = ttk.Button(run_frame, text="开始投递", command=self.start_run)
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.stop_btn = ttk.Button(run_frame, text="停止", command=self.stop_run, state="disabled")
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        stats = ttk.LabelFrame(left, text="进度", padding=10)
        stats.grid(row=31, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        stats.columnconfigure(1, weight=1)
        ttk.Label(stats, text="成功/目标").grid(row=0, column=0, sticky="w")
        ttk.Label(stats, textvariable=self.success_var).grid(row=0, column=1, sticky="e", padx=(20, 0))
        ttk.Label(stats, textvariable=self.target_var).grid(row=0, column=2, sticky="e")
        ttk.Label(stats, text="已访问").grid(row=1, column=0, sticky="w")
        ttk.Label(stats, textvariable=self.visited_var).grid(row=1, column=1, sticky="e", padx=(20, 0))
        ttk.Label(stats, text="预览").grid(row=2, column=0, sticky="w")
        ttk.Label(stats, textvariable=self.preview_count_var).grid(row=2, column=1, sticky="e", padx=(20, 0))
        ttk.Label(stats, text="跳过").grid(row=3, column=0, sticky="w")
        ttk.Label(stats, textvariable=self.skipped_var).grid(row=3, column=1, sticky="e", padx=(20, 0))
        ttk.Label(stats, text="失败").grid(row=4, column=0, sticky="w")
        ttk.Label(stats, textvariable=self.failed_var).grid(row=4, column=1, sticky="e", padx=(20, 0))
        self.progress_bar = ttk.Progressbar(stats, mode="determinate", maximum=100)
        self.progress_bar.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(8, 6))
        ttk.Label(stats, text="状态").grid(row=6, column=0, sticky="w")
        ttk.Label(stats, textvariable=self.status_var, wraplength=210).grid(row=6, column=1, columnspan=2, sticky="e", padx=(20, 0))

        right = ttk.Frame(self, padding=(0, 12, 12, 12))
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=3)
        right.rowconfigure(1, weight=2)
        right.columnconfigure(0, weight=1)

        table_frame = ttk.LabelFrame(right, text="投递记录", padding=8)
        table_frame.grid(row=0, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        columns = ("time", "status", "company", "title", "salary", "reason")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)
        headings = {"time": "时间", "status": "状态", "company": "公司", "title": "岗位", "salary": "薪资", "reason": "原因"}
        widths = {"time": 80, "status": 65, "company": 170, "title": 250, "salary": 110, "reason": 230}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_scroll.set)

        log_frame = ttk.LabelFrame(right, text="运行日志", padding=8)
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=9, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _load_config_to_ui(self) -> None:
        cfg = self.config_data
        self.keywords_entry.insert(0, cfg.keywords)
        self.cities_entry.insert(0, cfg.cities)
        self.max_count_var.set(cfg.max_count)
        self.max_pages_var.set(cfg.max_pages)
        self.blacklist_entry.insert(0, cfg.blacklist)
        self.exclude_entry.insert(0, cfg.exclude_keywords)
        self.experience_entry.insert(0, cfg.experience_keywords)
        self.education_entry.insert(0, cfg.education_keywords)
        self.active_entry.insert(0, cfg.active_keywords)
        self.min_salary_var.set(cfg.min_salary_k)
        self.preview_var.set(cfg.preview_only)
        self.auto_confirm_var.set(cfg.auto_confirm_resume)
        self.evidence_var.set(cfg.save_failure_evidence)
        self.unique_company_var.set(cfg.unique_company_per_run)
        self.skip_headhunter_var.set(cfg.skip_headhunter)
        self.min_delay_var.set(cfg.min_delay)
        self.max_delay_var.set(cfg.max_delay)
        self.message_text.insert("1.0", cfg.greet_message)

    def collect_config(self) -> AppConfig:
        return AppConfig(
            keywords=self.keywords_entry.get().strip(),
            cities=self.cities_entry.get().strip(),
            max_count=max(1, int(self.max_count_var.get())),
            max_pages=max(1, int(self.max_pages_var.get())),
            greet_message=self.message_text.get("1.0", "end").strip(),
            blacklist=self.blacklist_entry.get().strip(),
            exclude_keywords=self.exclude_entry.get().strip(),
            experience_keywords=self.experience_entry.get().strip(),
            education_keywords=self.education_entry.get().strip(),
            active_keywords=self.active_entry.get().strip(),
            min_salary_k=max(0, int(self.min_salary_var.get())),
            preview_only=bool(self.preview_var.get()),
            auto_confirm_resume=bool(self.auto_confirm_var.get()),
            save_failure_evidence=bool(self.evidence_var.get()),
            unique_company_per_run=bool(self.unique_company_var.get()),
            skip_headhunter=bool(self.skip_headhunter_var.get()),
            min_delay=max(0.5, float(self.min_delay_var.get())),
            max_delay=max(float(self.min_delay_var.get()), float(self.max_delay_var.get())),
        )

    def save_config(self) -> None:
        cfg = self.collect_config()
        cfg.save()
        self.log(f"配置已保存: {CONFIG_PATH}")

    def export_history(self) -> None:
        if not HISTORY_PATH.exists():
            messagebox.showinfo("没有记录", "还没有可导出的投递记录。")
            return
        default_name = f"boss_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        target = filedialog.asksaveasfilename(
            title="导出投递记录",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
        )
        if not target:
            return
        fields = ["time", "status", "reason", "city", "keyword", "company", "title", "salary", "tags", "evidence", "url"]
        rows: list[dict[str, str]] = []
        for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
        with open(target, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        self.log(f"记录已导出: {target}")

    def clear_history(self) -> None:
        if not messagebox.askyesno("确认清空", "确认清空历史记录？清空后同一岗位可以重新处理。"):
            return
        if HISTORY_PATH.exists():
            HISTORY_PATH.unlink()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.success_var.set("0")
        self.preview_count_var.set("0")
        self.skipped_var.set("0")
        self.failed_var.set("0")
        self.visited_var.set("0")
        self.target_var.set("0")
        self.progress_bar.configure(value=0, maximum=100)
        self.log("历史记录已清空。")

    def open_folder(self, path: Path) -> None:
        ensure_app_dir()
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(path)])

    def open_login(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("正在运行", "当前已有任务在运行。")
            return
        self.save_config()
        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.worker = threading.Thread(target=self._login_worker, daemon=True)
        self.worker.start()

    def start_diagnose(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("正在运行", "当前已有任务在运行。")
            return
        cfg = self.collect_config()
        keywords = split_words(cfg.keywords)
        cities = split_words(cfg.cities)
        if not keywords or not cities:
            messagebox.showwarning("缺少配置", "请填写岗位关键词和城市。")
            return
        cfg.save()
        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.worker = threading.Thread(target=self._diagnose_worker, args=(keywords[0], cities[0]), daemon=True)
        self.worker.start()

    def start_run(self) -> None:
        cfg = self.collect_config()
        if not split_words(cfg.keywords) or not split_words(cfg.cities):
            messagebox.showwarning("缺少配置", "请填写岗位关键词和城市。")
            return
        cfg.save()
        self.success_var.set("0")
        self.preview_count_var.set("0")
        self.skipped_var.set("0")
        self.failed_var.set("0")
        self.visited_var.set("0")
        self.target_var.set(f"/ {cfg.max_count}")
        self.progress_bar.configure(value=0, maximum=max(1, cfg.max_count))
        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.worker = threading.Thread(target=self._run_worker, args=(cfg,), daemon=True)
        self.worker.start()

    def stop_run(self) -> None:
        self.stop_event.set()
        self.log("已请求停止，当前页面处理完成后退出。")

    def _login_worker(self) -> None:
        bot = BossAutomation(self._emit, self.stop_event)
        self.automation = bot
        try:
            bot.open_login()
            self._emit("log", "?????????????????????????????????????/????", None)
        except Exception as exc:
            self._emit("log", f"登录窗口启动失败: {exc}", None)
        finally:
            bot.close()
            self._emit("done", "登录窗口已关闭", None)

    def _diagnose_worker(self, keyword: str, city: str) -> None:
        bot = BossAutomation(self._emit, self.stop_event)
        self.automation = bot
        try:
            bot.diagnose(keyword, city)
        except Exception as exc:
            self._emit("log", f"诊断异常: {exc}", None)
        finally:
            bot.close()
            self._emit("done", "诊断已结束", None)

    def _run_worker(self, cfg: AppConfig) -> None:
        options = RunOptions(
            keywords=split_words(cfg.keywords),
            cities=split_words(cfg.cities),
            max_count=cfg.max_count,
            max_pages=cfg.max_pages,
            greet_message=cfg.greet_message,
            blacklist=split_words(cfg.blacklist),
            exclude_keywords=split_words(cfg.exclude_keywords),
            experience_keywords=split_words(cfg.experience_keywords),
            education_keywords=split_words(cfg.education_keywords),
            active_keywords=split_words(cfg.active_keywords),
            min_salary_k=cfg.min_salary_k,
            preview_only=cfg.preview_only,
            auto_confirm_resume=cfg.auto_confirm_resume,
            save_failure_evidence=cfg.save_failure_evidence,
            unique_company_per_run=cfg.unique_company_per_run,
            skip_headhunter=cfg.skip_headhunter,
            min_delay=cfg.min_delay,
            max_delay=cfg.max_delay,
        )
        bot = BossAutomation(self._emit, self.stop_event)
        self.automation = bot
        try:
            stats = bot.run(options)
            self._emit("log", f"任务完成: 成功 {stats.success}，跳过 {stats.skipped}，失败 {stats.failed}。", None)
        except Exception as exc:
            self._emit("log", f"任务异常: {exc}", None)
        finally:
            bot.close()
            self._emit("done", "任务已结束", None)

    def _emit(self, kind: str, message: str, data: dict | None) -> None:
        self.events.put((kind, message, data))

    def _drain_events(self) -> None:
        while True:
            try:
                kind, message, data = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log(message)
            elif kind == "status":
                self.status_var.set(message)
                self.log(message)
            elif kind == "progress" and data:
                success = int(data.get("success", 0))
                preview = int(data.get("preview", 0))
                max_count = max(1, int(data.get("max_count", 1)))
                city = str(data.get("city") or "")
                city_success = int(data.get("city_success", 0))
                city_preview = int(data.get("city_preview", 0))
                self.success_var.set(str(success))
                self.preview_count_var.set(str(preview))
                self.skipped_var.set(str(data.get("skipped", 0)))
                self.failed_var.set(str(data.get("failed", 0)))
                self.visited_var.set(str(data.get("visited", 0)))
                self.target_var.set(f"/ {max_count}")
                active_count = city_preview if preview else city_success
                self.progress_bar.configure(maximum=max_count, value=min(active_count, max_count))
                if city:
                    self.status_var.set(f"{city}: {active_count}/{max_count}")
            elif kind == "row" and data:
                self.add_row(data)
            elif kind == "done":
                self.status_var.set(message)
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")
                self.log(message)
        self.after(150, self._drain_events)

    def add_row(self, row: dict[str, str]) -> None:
        values = (
            row.get("time", "")[11:19],
            row.get("status", ""),
            row.get("company", ""),
            row.get("title", ""),
            row.get("salary", ""),
            row.get("reason", ""),
        )
        self.tree.insert("", 0, values=values)

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{now_text()}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        self.stop_event.set()
        if self.automation:
            try:
                self.automation.close()
            except Exception:
                pass
        self.destroy()


def main() -> None:
    if "--smoke-city-targets" in sys.argv:
        smoke_city_targets()
        return
    if "--smoke-browser" in sys.argv:
        smoke_browser()
        return
    if "--smoke-evidence" in sys.argv:
        smoke_evidence()
        return
    if "--smoke-flow" in sys.argv:
        smoke_flow()
        return
    if "--smoke-diagnose" in sys.argv:
        smoke_diagnose()
        return
    if "--smoke-login" in sys.argv:
        smoke_login()
        return
    if "--smoke-login-fallback" in sys.argv:
        smoke_login_fallback()
        return
    app = BossApp()
    app.mainloop()


def smoke_city_targets() -> None:
    rows: list[dict] = []

    class FakeAutomation(BossAutomation):
        def run(self, options: RunOptions) -> RunStats:
            stats = RunStats()
            try:
                self._run_search_loop(None, options, stats, set())  # type: ignore[arg-type]
            finally:
                self.emit("status", "任务结束", None)
            return stats

        def iter_search_pages(self, page: Page, keyword: str, city: str, max_pages: int) -> Iterable[tuple[int, list[JobItem]]]:
            jobs = [
                JobItem(title=f"{keyword}-{city}-{index}", company=f"{city}-{keyword}-{index}", href=f"https://example.test/{city}/{keyword}/{index}", salary="10-20K")
                for index in range(3)
            ]
            yield 1, jobs

        def handle_job(self, page: Page, job: JobItem, options: RunOptions, sent_keys: set[str]) -> str:
            return "success"

    options = RunOptions(["kw1", "kw2"], ["city1", "city2"], 2, 1, "", [], [], [], [], [], 0, False, False, False, True, False, 0.5, 0.5)
    bot = FakeAutomation(lambda kind, message, data: rows.append({"kind": kind, "message": message, "data": data}), threading.Event())
    stats = bot.run(options)
    city_done_logs = [row["message"] for row in rows if row["kind"] == "log" and row["message"].startswith("城市处理完成")]
    ok = stats.success == 4 and city_done_logs == [
        "城市处理完成: city1，成功 2，预览 0，目标 2",
        "城市处理完成: city2，成功 2，预览 0，目标 2",
    ]
    print("ok" if ok else f"failed success={stats.success} logs={city_done_logs!r}")
    if not ok:
        raise RuntimeError("smoke city targets failed")


def smoke_browser() -> None:
    if sync_playwright is None:
        raise RuntimeError("playwright is not installed")
    prepare_playwright_environment()
    temp_profile = Path(tempfile.mkdtemp(prefix="boss_sender_smoke_"))
    playwright = sync_playwright().start()
    context = None
    try:
        context = playwright.chromium.launch_persistent_context(
            str(temp_profile),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        context.add_init_script(STEALTH_JS)
        page = context.new_page()
        page.goto("data:text/html,<title>ok</title><h1>ok</h1>")
        print(page.title())
    finally:
        if context is not None:
            context.close()
        playwright.stop()
        shutil.rmtree(temp_profile, ignore_errors=True)


def smoke_login() -> None:
    if sync_playwright is None:
        raise RuntimeError("playwright is not installed")
    prepare_playwright_environment()
    logs: list[str] = []
    bot = BossAutomation(lambda kind, message, data: logs.append(message) if kind == "log" else None, threading.Event())
    with temporary_app_paths("boss_sender_login_"):
        try:
            bot.open_login()
            time.sleep(5)
            assert bot.context is not None
            urls = [page.url for page in bot.context.pages if not page.is_closed()]
            debug_path = APP_DIR / "login_debug.json"
            ok = bool(urls) and any(url != "about:blank" for url in urls) and debug_path.exists()
            print("ok" if ok else f"failed urls={urls!r} logs={logs!r}")
            if not ok:
                raise RuntimeError("login page stayed blank")
        finally:
            bot.close()


def smoke_login_fallback() -> None:
    bot = BossAutomation(lambda *args: None, threading.Event())
    with temporary_app_paths("boss_sender_login_fallback_"):
        path = bot._write_login_fallback_page("smoke")
        text = path.read_text(encoding="utf-8")
        ok = path.exists() and "<title>Boss" in text and "https://www.zhipin.com/web/geek/job" in text
        print("ok" if ok else "failed")
        if not ok:
            raise RuntimeError("fallback page invalid")


def smoke_evidence() -> None:
    if sync_playwright is None:
        raise RuntimeError("playwright is not installed")
    prepare_playwright_environment()
    with temporary_app_paths("boss_sender_evidence_app_"):
        temp_profile = Path(tempfile.mkdtemp(prefix="boss_sender_evidence_"))
        playwright = sync_playwright().start()
        context = None
        try:
            context = playwright.chromium.launch_persistent_context(
                str(temp_profile),
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )
            context.add_init_script(STEALTH_JS)
            page = context.new_page()
            page.goto("data:text/html,<title>evidence</title><h1>evidence</h1>")
            bot = BossAutomation(lambda *args: None, threading.Event())
            job = JobItem(title="Smoke", company="Evidence", href="data:text/html,evidence")
            options = RunOptions(["Smoke"], ["Shanghai"], 1, 1, "", [], [], [], [], [], 0, True, False, True, True, True, 1, 2)
            evidence = bot._save_evidence(page, job, options, "smoke")
            ok = bool(evidence) and all(Path(item.strip()).exists() for item in evidence.split("|"))
            print("ok" if ok else "failed")
            if not ok:
                raise RuntimeError("smoke evidence failed")
        finally:
            if context is not None:
                context.close()
            playwright.stop()
            shutil.rmtree(temp_profile, ignore_errors=True)


def smoke_flow() -> None:
    if sync_playwright is None:
        raise RuntimeError("playwright is not installed")
    prepare_playwright_environment()
    with temporary_app_paths("boss_sender_flow_app_"):
        temp_profile = Path(tempfile.mkdtemp(prefix="boss_sender_flow_"))
        temp_site = Path(tempfile.mkdtemp(prefix="boss_sender_site_"))
        playwright = sync_playwright().start()
        context = None
        rows: list[dict[str, str]] = []
        try:
            if choose_greeting_template("A\nB") not in {"A", "B"}:
                raise RuntimeError("greeting template selection failed")
            detail_dir = temp_site / "job_detail"
            detail_dir.mkdir()
            detail_path = detail_dir / "smoke.html"
            detail_path.write_text(
                """
                <html><head><meta charset="utf-8"><title>Python Developer</title></head>
                <body>
                  <div class="job-name">Python Developer</div>
                  <div class="company-name">Example Tech</div>
                  <span class="salary">20-35K</span>
                  <div class="job-labels"><span>3-5 years</span><span>Bachelor</span><span>active-now</span></div>
                  <button>Apply</button>
                </body></html>
                """,
                encoding="utf-8",
            )
            detail_path_2 = detail_dir / "smoke2.html"
            detail_path_2.write_text(
                """
                <html><head><meta charset="utf-8"><title>Python Backend</title></head>
                <body>
                  <div class="job-name">Python Backend</div>
                  <div class="company-name">Example Tech</div>
                  <span class="salary">22-32K</span>
                  <div class="job-labels"><span>3-5 years</span><span>Bachelor</span><span>active-today</span></div>
                  <button>Apply</button>
                </body></html>
                """,
                encoding="utf-8",
            )
            list_path = temp_site / "list.html"
            list_path.write_text(
                f"""
                <html><head><meta charset="utf-8"><title>list</title></head>
                <body>
                  <div class="job-card-wrapper">
                    <a class="job-name" href="{detail_path.as_uri()}">Python Developer</a>
                    <a class="company-name">Example Tech</a>
                    <span class="salary">20-35K</span>
                    <div class="tag-list"><span>3-5 years</span><span>Bachelor</span><span>active-now</span></div>
                  </div>
                  <div class="job-card-wrapper">
                    <a class="job-name" href="{detail_path_2.as_uri()}">Python Backend</a>
                    <a class="company-name">Example Tech</a>
                    <span class="salary">-K</span>
                    <div class="tag-list"><span>3-5 years</span><span>Bachelor</span><span>active-today</span></div>
                  </div>
                </body></html>
                """,
                encoding="utf-8",
            )
            context = playwright.chromium.launch_persistent_context(
                str(temp_profile),
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )
            context.add_init_script(STEALTH_JS)
            page = context.new_page()
            page.goto(list_path.as_uri())
            bot = BossAutomation(lambda kind, message, data: rows.append(data) if kind == "row" and data else None, threading.Event())
            jobs = bot._extract_jobs(page)
            options = RunOptions(["Python"], ["Shanghai"], 1, 1, "Hello", [], [], ["3-5 years"], ["Bachelor"], ["active"], 20, True, False, True, True, True, 1, 1)
            result = bot.handle_job(page, jobs[0], options, set()) if jobs else "missing"
            history_after_preview = bot._load_history()
            second_company_skipped = False
            if len(jobs) > 1:
                seen_companies = {normalize_text(jobs[0].company).lower()}
                second_company_skipped = normalize_text(jobs[1].company).lower() in seen_companies
            hunter_job = JobItem(
                title="Python Developer",
                company="headhunter rpo human resource service",
                href="data:text/html,hunter",
                salary="20-30K",
                tags="3-5 years Bachelor active-today",
            )
            hunter_skipped = bot._filter_job(hunter_job, options) is not None
            inactive_job = JobItem(
                title="Python Developer",
                company="Normal Tech",
                href="data:text/html,inactive",
                salary="20-30K",
                tags="3-5 years Bachelor",
            )
            inactive_skipped = bot._filter_job(inactive_job, options) is not None
            pending_detail_job = JobItem(
                title="C++ Developer",
                company="Pending Detail Tech",
                href="data:text/html,pending",
                salary="25-35K",
                tags="Bachelor active-today",
            )
            pending_detail_not_skipped = bot._filter_job(pending_detail_job, options, detail_loaded=False) is None
            known_experience_job = JobItem(
                title="C++ Developer",
                company="Known Experience Tech",
                href="data:text/html,known",
                salary="25-35K",
                tags="3-5年 Bachelor active-today",
            )
            known_experience_skipped = bot._filter_job(known_experience_job, RunOptions(["C++"], ["Shanghai"], 1, 1, "Hello", [], [], ["应届生"], ["Bachelor"], ["active"], 20, True, False, True, True, True, 1, 1), detail_loaded=False) is not None
            fresh_options = RunOptions(["C++"], ["Shanghai"], 1, 1, "Hello", [], [], ["在校生", "应届生", "1年以内"], [], [], 0, True, False, True, True, True, 1, 1)
            fresh_cases = [
                JobItem(title="C++开发工程师（校招）", company="A", href="data:text/html,a", salary="10-20K", tags="本科"),
                JobItem(title="C++开发工程师（接受无经验+线上面试）", company="B", href="data:text/html,b", salary="10-20K", tags="本科"),
                JobItem(title="C++开发工程师", company="C", href="data:text/html,c", salary="10-20K", tags="经验不限 本科"),
                JobItem(title="C++开发工程师", company="D", href="data:text/html,d", salary="10-20K", tags="在校/应届 本科"),
                JobItem(title="初级c++开发工程师", company="E", href="data:text/html,e", salary="10-20K", tags="本科"),
            ]
            fresh_cases_match = all(bot._filter_job(case, fresh_options, detail_loaded=True) is None for case in fresh_cases)
            senior_case_skipped = bot._filter_job(
                JobItem(title="C++开发工程师", company="F", href="data:text/html,f", salary="10-20K", tags="3-5年 本科"),
                fresh_options,
                detail_loaded=True,
            ) is not None
            ok = (
                len(jobs) == 2
                and result == "preview"
                and rows
                and rows[-1].get("company") == "Example Tech"
                and rows[-1].get("salary") == "20-35K"
                and jobs[1].salary == "22-32K"
                and jobs[0].history_key not in history_after_preview
                and second_company_skipped
                and hunter_skipped
                and inactive_skipped
                and pending_detail_not_skipped
                and known_experience_skipped
                and fresh_cases_match
                and senior_case_skipped
            )
            print("ok" if ok else f"failed jobs={len(jobs)} result={result} rows={rows!r}")
            if not ok:
                raise RuntimeError("smoke flow failed")
        finally:
            if context is not None:
                context.close()
            playwright.stop()
            shutil.rmtree(temp_profile, ignore_errors=True)
            shutil.rmtree(temp_site, ignore_errors=True)


def smoke_diagnose() -> None:
    global BOSS_HOME
    if sync_playwright is None:
        raise RuntimeError("playwright is not installed")
    prepare_playwright_environment()
    with temporary_app_paths("boss_sender_diag_app_"):
        _smoke_diagnose_impl()


def _smoke_diagnose_impl() -> None:
    global BOSS_HOME
    temp_site = Path(tempfile.mkdtemp(prefix="boss_sender_diag_"))
    old_home = BOSS_HOME
    logs: list[str] = []
    httpd = None
    server_thread = None
    smoke_log = APP_DIR / "smoke_diagnose.log"
    try:
        ensure_app_dir()
        smoke_log.write_text("start\n", encoding="utf-8")
        detail_dir = temp_site / "job_detail"
        detail_dir.mkdir()
        detail_path = detail_dir / "diag.html"
        detail_path.write_text("<html><body><span class='salary'>18-28K</span></body></html>", encoding="utf-8")
        list_path = temp_site / "list.html"
        list_path.write_text(
            f"""
            <html><head><title>diag</title></head><body>
              <div class="job-card-wrapper">
                <a class="job-name" href="{detail_path.as_uri()}">Python 诊断工程师</a>
                <a class="company-name">诊断科技</a>
                <span class="salary">18-28K</span>
              </div>
            </body></html>
            """,
            encoding="utf-8",
        )
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                return

        handler = functools.partial(QuietHandler, directory=str(temp_site))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        server_thread.start()
        BOSS_HOME = f"http://127.0.0.1:{port}/list.html"
        smoke_log.write_text(f"home={BOSS_HOME}\n", encoding="utf-8")
        bot = BossAutomation(lambda kind, message, data: logs.append(message) if kind == "log" else None, threading.Event())
        result = bot.diagnose("Python", "上海")
        ok = result["job_count"] == 1 and result["logged_out"] is False
        smoke_log.write_text(f"result={result!r}\nlogs={logs!r}\nok={ok}\n", encoding="utf-8")
        print("ok" if ok else f"failed job_count={result.get('job_count')} logged_out={result.get('logged_out')}")
        if not ok:
            raise RuntimeError("smoke diagnose failed")
    except Exception as exc:
        try:
            smoke_log.write_text(f"exception={type(exc).__name__}: {exc}\nlogs={logs!r}\n", encoding="utf-8")
        except Exception:
            pass
        raise
    finally:
        BOSS_HOME = old_home
        if httpd is not None:
            httpd.shutdown()
        if server_thread is not None:
            server_thread.join(timeout=5)
        try:
            bot.close()  # type: ignore[name-defined]
        except Exception:
            pass
        shutil.rmtree(temp_site, ignore_errors=True)


if __name__ == "__main__":
    main()

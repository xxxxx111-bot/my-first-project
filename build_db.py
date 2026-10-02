"""从中文维基百科下载年份页面、日期页面和“你知道吗？”存档，构建本地历史数据库 data/history.db。

用法：
    python build_db.py                   # 完整构建（几千个页面，大约需要半小时）
    python build_db.py --limit 20        # 只抓少量页面试一试
    python build_db.py --no-dyk          # 不抓“你知道吗？”存档

下载过的页面会缓存在 data/cache/，中断后重新运行会从缓存继续，不会重复下载。
数据来自维基百科，遵循 CC BY-SA 4.0 许可协议。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import wiki_parser as wp

API_URL = "https://zh.wikipedia.org/w/api.php"
USER_AGENT = "HistoryFactsBuilder/1.0 (https://github.com/xxxxx111-bot/my-first-project)"
DATA_DIR = Path(__file__).parent / "data"
DEFAULT_DB = DATA_DIR / "history.db"
DEFAULT_CACHE = DATA_DIR / "cache"
DYK_PREFIX = "新条目推荐/存档/"
PROJECT_NAMESPACE = 4  # Wikipedia: 命名空间

SCHEMA = """
CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,            -- event：年份/日期页面的大事记；dyk：“你知道吗？”
    text TEXT NOT NULL,
    answer TEXT,                   -- “你知道吗？”的答案
    year INTEGER,                  -- 公元前为负数
    month INTEGER,
    day INTEGER,
    subject TEXT,                  -- 主要相关条目
    links TEXT NOT NULL,           -- 相关条目列表（JSON）
    source_title TEXT NOT NULL     -- 来自哪个维基百科页面
);
CREATE INDEX idx_facts_year ON facts(year);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class WikiClient:
    """极简的 MediaWiki API 客户端：串行请求、带缓存、出错自动重试。"""

    def __init__(self, cache_dir: Path = DEFAULT_CACHE, delay: float = 0.3, api_url: str = API_URL):
        self.cache_dir = cache_dir
        self.delay = delay
        self.api_url = api_url
        self._last_request = 0.0

    def api(self, **params) -> dict:
        params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        url = self.api_url + "?" + urllib.parse.urlencode(params)
        for attempt in range(6):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                data = json.loads(body)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                if isinstance(e, urllib.error.HTTPError) and e.code in (403, 404):
                    raise
                if "Tunnel connection failed" in str(e):  # 被网络代理拒绝，重试也没用
                    raise
                print(f"  请求失败（{e}），{2 ** attempt} 秒后重试……", file=sys.stderr)
                time.sleep(2 ** attempt)
                continue
            if data.get("error", {}).get("code") == "maxlag":
                time.sleep(5)
                continue
            return data
        raise RuntimeError(f"多次重试后仍然失败：{url}")

    def existing_titles(self, titles: list[str]) -> list[str]:
        """批量检查页面是否存在（跟随重定向），返回存在的页面标题，保持原顺序、去重。"""
        found: list[str] = []
        for i in range(0, len(titles), 50):
            batch = titles[i:i + 50]
            data = self.api(action="query", titles="|".join(batch), redirects="1")
            query = data.get("query", {})
            rename = {n["from"]: n["to"] for n in query.get("normalized", [])}
            rename.update({r["from"]: r["to"] for r in query.get("redirects", [])})
            exists = {p["title"] for p in query.get("pages", []) if not p.get("missing") and not p.get("invalid")}
            for t in batch:
                target = rename.get(rename.get(t, t), rename.get(t, t))
                if target in exists and target not in found:
                    found.append(target)
        return found

    def all_pages(self, prefix: str, namespace: int) -> list[str]:
        titles: list[str] = []
        cont: dict = {}
        while True:
            data = self.api(action="query", list="allpages", apprefix=prefix,
                            apnamespace=str(namespace), aplimit="max", **cont)
            titles += [p["title"] for p in data["query"]["allpages"]]
            if "continue" not in data:
                return titles
            cont = data["continue"]

    def page_html(self, title: str) -> str:
        path = self.cache_dir / (hashlib.sha1(title.encode()).hexdigest() + ".html")
        if path.exists():
            return path.read_text(encoding="utf-8")
        data = self.api(action="parse", page=title, prop="text", variant="zh-cn",
                        redirects="1", disableeditsection="1", disabletoc="1")
        html = data["parse"]["text"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return html


def year_titles(first: int, last: int) -> list[str]:
    titles = []
    for y in range(first, last + 1):
        if y < 0:
            titles.append(f"前{-y}年")
        elif y > 0:
            titles.append(f"{y}年")
    return titles


def date_titles() -> list[str]:
    days = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return [f"{m}月{d}日" for m in range(1, 13) for d in range(1, days[m - 1] + 1)]


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text)


def dedupe(facts: Iterable[wp.RawFact]) -> list[wp.RawFact]:
    """同一件事常常同时出现在年份页面和日期页面上，合并重复项。"""
    seen: dict[tuple, wp.RawFact] = {}
    for f in facts:
        key = (f.kind, f.year, _norm(f.text))
        old = seen.get(key)
        if old is None:
            seen[key] = f
            continue
        old.month = old.month or f.month
        old.day = old.day or f.day
        old.links += [l for l in f.links if l not in old.links]
    return list(seen.values())


def write_db(facts: list[wp.RawFact], db_path: Path, meta: dict[str, str]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO facts (kind, text, answer, year, month, day, subject, links, source_title)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(f.kind, f.text, f.answer, f.year, f.month, f.day, f.subject,
          json.dumps(f.links, ensure_ascii=False), f.source_title) for f in facts],
    )
    conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", meta.items())
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    tmp.replace(db_path)


def collect(client: WikiClient, pages: list[tuple[str, Callable[[str, str], list[wp.RawFact]]]]) -> list[wp.RawFact]:
    facts: list[wp.RawFact] = []
    for i, (title, parse) in enumerate(pages, 1):
        try:
            facts += parse(client.page_html(title), title)
        except Exception as e:  # 单个页面出错不影响整体
            print(f"  跳过「{title}」：{e}", file=sys.stderr)
        if i % 50 == 0 or i == len(pages):
            print(f"  [{i}/{len(pages)}] 已收集 {len(facts)} 条", file=sys.stderr)
    return facts


def build(client: WikiClient, db_path: Path, first_year: int, last_year: int,
          include_dyk: bool = True, limit: int | None = None) -> dict[str, int]:
    print("检查年份和日期页面……", file=sys.stderr)
    event_titles = client.existing_titles(year_titles(first_year, last_year) + date_titles())
    pages = [(t, wp.parse_event_page) for t in event_titles]
    if include_dyk:
        print("列出“你知道吗？”存档……", file=sys.stderr)
        dyk_titles = [t for t in client.all_pages(DYK_PREFIX, PROJECT_NAMESPACE) if not t.endswith("/")]
        pages += [(t, wp.parse_dyk_page) for t in dyk_titles]
    if limit:
        pages = pages[:limit]

    print(f"下载并解析 {len(pages)} 个页面……", file=sys.stderr)
    facts = dedupe(collect(client, pages))
    counts = {"events": sum(f.kind == "event" for f in facts), "dyk": sum(f.kind == "dyk" for f in facts)}
    meta = {
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": "中文维基百科 zh.wikipedia.org",
        "license": "CC BY-SA 4.0",
        "pages": str(len(pages)),
        "total": str(len(facts)),
        **{k: str(v) for k, v in counts.items()},
    }
    write_db(facts, db_path, meta)
    return {"pages": len(pages), "total": len(facts), **counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从中文维基百科构建本地历史数据库")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--from-year", type=int, default=-1000, help="最早的年份（公元前用负数，默认 -1000）")
    parser.add_argument("--to-year", type=int, default=datetime.now().year - 1)
    parser.add_argument("--no-dyk", action="store_true", help="不抓取“你知道吗？”存档")
    parser.add_argument("--limit", type=int, help="最多处理多少个页面（试运行用）")
    parser.add_argument("--delay", type=float, default=0.3, help="两次请求之间至少间隔多少秒")
    args = parser.parse_args(argv)

    client = WikiClient(cache_dir=args.cache, delay=args.delay)
    try:
        stats = build(client, args.db, args.from_year, args.to_year, not args.no_dyk, args.limit)
    except urllib.error.URLError as e:
        print(f"无法连接维基百科：{e}", file=sys.stderr)
        return 1
    print(f"完成！处理了 {stats['pages']} 个页面，共 {stats['total']} 条"
          f"（历史事件 {stats['events']} 条，“你知道吗？” {stats['dyk']} 条），已写入 {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

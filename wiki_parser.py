"""解析中文维基百科页面的 HTML，提取历史事件和“你知道吗？”冷知识。

支持三类页面：
- 年份页面，如「1674年」「前221年」：取“大事记”一节
- 日期页面，如「12月29日」：取“大事记”一节，每条以“某某年：”开头
- “你知道吗？”存档页面：取以问号结尾、带有加粗答案链接的条目

这里只做纯解析，不联网，方便测试。联网下载见 build_db.py。
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from urllib.parse import quote

from bs4 import BeautifulSoup, Tag

WIKI_BASE = "https://zh.wikipedia.org/wiki/"

EVENT_SECTIONS = {"大事记", "大事纪", "大事", "事件", "重大事件", "大事件", "大事記"}
SKIPPED_NAMESPACES = {
    "File", "文件", "Image", "Category", "分类", "Wikipedia", "维基百科", "Help", "帮助",
    "Template", "模板", "Portal", "主题", "Special", "特殊", "Talk", "讨论", "User", "用户",
}
JUNK_SELECTORS = [
    "sup.reference", "span.mw-editsection", "style", "script", ".noprint", ".mw-ref",
    "span.mw-cite-backlink", ".metadata", "table", ".navbox", ".thumb", "figure",
]

SEP = r"[\s—–\-－−:：，,、]+"
YEAR_TITLE_RE = re.compile(r"^(?:公元)?(前)?(\d{1,4})年$")
DATE_TITLE_RE = re.compile(r"^(\d{1,2})月(\d{1,2})日$")
YEAR_PREFIX_RE = re.compile(
    rf"^(?:公元)?(前)?(\d{{1,4}})年(?:[至到~～—–\-](?:前)?\d{{1,4}}年)?(?=\d{{1,2}}月|{SEP}|$)(?:{SEP})?"
)
MONTH_DAY_PREFIX_RE = re.compile(
    rf"^(?:(\d{{1,2}})月)?(?:(\d{{1,2}})日)?(?:[至到~～—–\-](?:\d{{1,2}}月)?\d{{1,2}}日)?(?:{SEP}|$)"
)
REF_MARK_RE = re.compile(r"\[(?:注|註|note|n)?\s*\d+\]")
PICTURE_MARK_RE = re.compile(r"[（(](?:图|圖|如图|如圖|右图|左图|图片|圖片)[)）]")
YEARISH_TITLE_RE = re.compile(r"^(?:(?:公元)?前?\d+年代?|\d{1,2}月(?:\d{1,2}日)?|(?:公元)?前?\d+世纪|\d+千纪)$")

STRONG_HISTORY_WORDS = (
    "王朝", "朝代", "帝国", "皇帝", "国王", "女王", "王国", "王室", "皇室", "君主", "苏丹", "法老",
    "战争", "战役", "之战", "起义", "革命", "条约", "殖民", "中世纪", "文艺复兴", "遗址", "考古",
    "文物", "古代", "古城", "古墓", "世纪", "年间", "朝廷", "宰相", "诸侯", "将军", "史书", "史记",
)
HISTORY_RE = re.compile(
    r"[夏商周秦汉晋隋唐宋辽金元明清][朝代]|三国|春秋|战国|五代|十六国|南北朝|"
    r"古罗马|古希腊|古埃及|罗马帝国|拜占庭|奥斯曼|丝绸之路|科举|封建|皇后|太子|贵族|骑士|十字军"
)
YEAR_MENTION_RE = re.compile(r"(公元前|前)?(\d{2,4})年")


@dataclass
class RawFact:
    kind: str                       # "event"（年份/日期页面）或 "dyk"（你知道吗）
    text: str
    source_title: str
    year: int | None = None         # 公元前用负数
    month: int | None = None
    day: int | None = None
    answer: str | None = None       # “你知道吗？”的答案（条目名）
    links: list[str] = field(default_factory=list)

    @property
    def subject(self) -> str | None:
        if self.answer:
            return self.answer
        return self.links[0] if self.links else None


def wiki_url(title: str) -> str:
    return WIKI_BASE + quote(title.replace(" ", "_"), safe="")


def parse_year_title(title: str) -> int | None:
    m = YEAR_TITLE_RE.match(title)
    if not m:
        return None
    year = int(m.group(2))
    return -year if m.group(1) else year


def parse_date_title(title: str) -> tuple[int, int] | None:
    m = DATE_TITLE_RE.match(title)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    if 1 <= month <= 12 and 1 <= day <= 31:
        return month, day
    return None


def clean_text(text: str) -> str:
    text = REF_MARK_RE.sub("", text)
    text = PICTURE_MARK_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 中文之间不需要空格
    text = re.sub(r"(?<=[一-鿿，。：；、“”（）])\s+(?=[一-鿿，。：；、“”（）])", "", text)
    return text.strip(" ：:，,；;")


def _strip_junk(node: Tag) -> Tag:
    node = copy.copy(node)
    for selector in JUNK_SELECTORS:
        for junk in node.select(selector):
            junk.decompose()
    return node


def _own_part(li: Tag) -> Tag:
    """去掉嵌套列表后的 <li> 本身。"""
    li = _strip_junk(li)
    for sub in li.find_all(["ul", "ol", "dl"]):
        sub.decompose()
    return li


def _links(node: Tag) -> list[str]:
    titles: list[str] = []
    for a in node.find_all("a", href=True):
        href, title = a["href"], a.get("title", "")
        if not href.startswith("/wiki/") or not title or "redlink=1" in href:
            continue
        if ":" in title and title.split(":", 1)[0] in SKIPPED_NAMESPACES:
            continue
        if YEARISH_TITLE_RE.match(title) or title in titles:
            continue
        titles.append(title)
    return titles


def _heading(node: Tag) -> tuple[int, str] | None:
    """识别新旧两种 MediaWiki 标题结构，返回 (级别, 标题文字)。"""
    if node.name in ("h2", "h3", "h4"):
        return int(node.name[1]), clean_text(_strip_junk(node).get_text())
    if node.name == "div" and "mw-heading" in (node.get("class") or []):
        h = node.find(["h2", "h3", "h4"])
        if h:
            return int(h.name[1]), clean_text(_strip_junk(h).get_text())
    return None


def _content_root(html: str) -> Tag:
    soup = BeautifulSoup(html, "html.parser")
    return soup.select_one(".mw-parser-output") or soup


def _top_level_lists(node: Tag) -> list[Tag]:
    if node.name in ("ul", "ol"):
        return [node]
    return [lst for lst in node.find_all(["ul", "ol"]) if lst.find_parent("li") is None]


def _apply_prefix(text: str, year, month, day):
    """从文字开头读取“1675年：”“3月1日——”之类的日期前缀，返回更新后的日期和剩余文字。"""
    m = YEAR_PREFIX_RE.match(text)
    if m:
        year = -int(m.group(2)) if m.group(1) else int(m.group(2))
        text = text[m.end():]
    m = MONTH_DAY_PREFIX_RE.match(text)
    if m and (m.group(1) or m.group(2)):
        month = int(m.group(1)) if m.group(1) else month
        day = int(m.group(2)) if m.group(2) else day
        text = text[m.end():]
    return year, month, day, text.strip()


def _walk_items(lst: Tag, contexts: list[str]):
    """遍历列表，产出 (上层分组文字列表, 叶子 <li>)。"""
    for li in lst.find_all("li", recursive=False):
        nested = li.find_all(["ul", "ol"], recursive=False)
        if nested:
            own = clean_text(_own_part(li).get_text())
            for sub in nested:
                yield from _walk_items(sub, contexts + [own])
        else:
            yield contexts, li


def _is_good_event(text: str) -> bool:
    if not 8 <= len(text) <= 300:
        return False
    if text.startswith(("参见", "参看", "另见", "参考")):
        return False
    return bool(re.search(r"[一-鿿]{4,}", text))


def parse_event_page(html: str, title: str) -> list[RawFact]:
    """解析年份页面或日期页面的“大事记”。"""
    page_year = parse_year_title(title)
    page_date = parse_date_title(title)
    if page_year is None and page_date is None:
        raise ValueError(f"不是年份或日期页面：{title}")
    base_month, base_day = page_date if page_date else (None, None)

    facts: list[RawFact] = []
    in_events = False
    subheading = ""
    for node in _content_root(html).find_all(recursive=False):
        if not isinstance(node, Tag):
            continue
        heading = _heading(node)
        if heading:
            level, text = heading
            if level == 2:
                in_events = text in EVENT_SECTIONS
                subheading = ""
            elif in_events:
                subheading = text
            continue
        if not in_events:
            continue
        for lst in _top_level_lists(node):
            for contexts, li in _walk_items(lst, []):
                year, month, day = page_year, base_month, base_day
                # 小标题（如“1月”“中国”“17世纪”）只用来读取日期，不拼进正文
                if subheading:
                    year, month, day, _ = _apply_prefix(subheading, year, month, day)
                extra = []
                for ctx in contexts:
                    year, month, day, rest = _apply_prefix(ctx, year, month, day)
                    if rest and len(rest) <= 20:
                        extra.append(rest)
                own = _own_part(li)
                year, month, day, text = _apply_prefix(clean_text(own.get_text()), year, month, day)
                if page_date and year is None:
                    continue  # 日期页面里没有年份的条目没什么用
                if extra:
                    text = "：".join(extra + [text])
                if not _is_good_event(text):
                    continue
                facts.append(RawFact(
                    kind="event", text=text, source_title=title,
                    year=year, month=month, day=day, links=_links(own),
                ))
    return facts


def looks_historical(text: str) -> bool:
    for m in YEAR_MENTION_RE.finditer(text):
        if m.group(1) or int(m.group(2)) <= 1990:
            return True
    return any(word in text for word in STRONG_HISTORY_WORDS) or bool(HISTORY_RE.search(text))


def parse_dyk_page(html: str, title: str, history_only: bool = True) -> list[RawFact]:
    """解析“你知道吗？”存档页面。答案是问题里加粗链接指向的条目。"""
    facts: list[RawFact] = []
    for li in _content_root(html).find_all("li"):
        if li.find(["ul", "ol"]):
            continue
        own = _strip_junk(li)
        text = clean_text(own.get_text())
        if not text.endswith(("？", "?")) or not 8 <= len(text) <= 250:
            continue
        answer = None
        for bold in own.find_all("b"):
            bold_links = _links(bold)
            if bold_links:
                answer = bold_links[0]
                break
        if not answer:
            continue
        if history_only and not looks_historical(text):
            continue
        facts.append(RawFact(kind="dyk", text=text, source_title=title, answer=answer, links=_links(own)))
    return facts

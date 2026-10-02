"""本地模式：从维基百科构建的 SQLite 数据库里检索历史事实，并按规则生成批判性思考回应。

不需要联网，也不需要 API Key。数据库由 build_db.py 生成。
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import BaseModel

import history_facts as hf
from wiki_parser import wiki_url

DB_PATH = Path(__file__).parent / "data" / "history.db"
MAX_CANDIDATES = 3000

LOCAL_RELIABILITY_LABELS = {"well_documented": "有明确记载", "debated": "存疑 / 年代久远", "legendary": "传说"}


class LocalFact(hf.HistoryFact):
    reliability_label: str
    answer: str | None = None           # “你知道吗？”的答案
    source_title: str
    source_url: str
    read_more_title: str | None = None
    read_more_url: str | None = None


class LocalFactsResult(BaseModel):
    keyword: str
    facts: list[LocalFact]
    total_matches: int


class DatabaseMissingError(RuntimeError):
    pass


class NoMatchError(LookupError):
    pass


@dataclass
class Row:
    id: int
    kind: str
    text: str
    answer: str | None
    year: int | None
    month: int | None
    day: int | None
    subject: str | None
    links: list[str]
    source_title: str


# ---------------------------------------------------------------- 时间相关

CHINA_PERIODS = [
    (-1600, -1046, "商朝"), (-1046, -771, "西周"), (-770, -476, "春秋时期"), (-475, -221, "战国时期"),
    (-221, -207, "秦朝"), (-202, 8, "西汉"), (9, 23, "新朝"), (25, 220, "东汉"), (220, 280, "三国时期"),
    (266, 316, "西晋"), (317, 420, "东晋十六国时期"), (420, 589, "南北朝"), (581, 618, "隋朝"),
    (618, 907, "唐朝"), (907, 960, "五代十国"), (960, 1127, "北宋"), (1127, 1279, "南宋"),
    (1279, 1368, "元朝"), (1368, 1644, "明朝"), (1644, 1911, "清朝"),
]


def year_label(year: int) -> str:
    return f"公元前{-year}年" if year < 0 else f"{year}年"


def date_label(year: int | None, month: int | None, day: int | None) -> str:
    if year is None:
        return ""
    label = year_label(year)
    if month:
        label += f"{month}月" + (f"{day}日" if day else "")
    return label


def years_ago(year: int, today: int | None = None) -> int:
    today = today or date.today().year
    return today - year - (1 if year < 0 else 0)  # 没有公元 0 年


def ago_label(year: int) -> str:
    n = years_ago(year)
    return f"约 {n} 年前" if n >= 2 else "不久前"


def century_label(year: int) -> str:
    if year < 0:
        return f"公元前{(-year - 1) // 100 + 1}世纪"
    return f"{(year - 1) // 100 + 1}世纪"


def china_period(year: int) -> str | None:
    for start, end, name in CHINA_PERIODS:
        if start <= year < end or (year == end and end == 1911):
            return name
    return None


# ---------------------------------------------------------------- 分类与可信度

CATEGORY_WORDS = {
    "war": ("战争", "战役", "之战", "会战", "海战", "围城", "攻陷", "攻占", "起义", "叛乱", "入侵", "兵变",
            "屠杀", "进攻", "击败", "战败", "投降", "停战", "征服", "出兵", "军队", "舰队", "轰炸", "沦陷"),
    "politics": ("登基", "即位", "称帝", "驾崩", "退位", "条约", "宪法", "独立", "建国", "成立", "选举", "总统",
                 "首相", "议会", "改革", "变法", "废除", "颁布", "签署", "迁都", "政变", "宣布", "加冕", "政府"),
    "science": ("发明", "发现", "实验", "专利", "理论", "科学", "望远镜", "疫苗", "卫星", "火箭", "登月",
                "计算机", "电报", "电话", "蒸汽机", "首次飞行", "天文", "化学", "医学", "数学"),
    "disaster": ("地震", "洪水", "海啸", "火山", "瘟疫", "鼠疫", "霍乱", "饥荒", "大火", "火灾", "沉没",
                 "空难", "爆炸", "飓风", "台风", "旱灾", "雪崩", "疫情"),
    "exploration": ("抵达", "航行", "探险", "环球", "登陆", "航海", "远征", "横渡", "探索", "到达"),
    "economy": ("贸易", "商人", "银行", "货币", "税", "股票", "交易所", "公司", "铁路", "运河", "港口",
                "市场", "关税", "工厂", "工业"),
    "religion": ("教皇", "佛教", "基督教", "伊斯兰", "宗教", "传教", "寺庙", "僧", "教会", "主教", "道教",
                 "清真寺", "大教堂", "圣经", "佛经"),
    "culture": ("出版", "首演", "创作", "小说", "诗", "绘画", "画家", "音乐", "电影", "戏剧", "落成", "建成",
                "博物馆", "大学", "书院", "图书馆", "雕塑", "歌剧", "文学"),
}

LEGEND_WORDS = ("传说", "相传", "神话", "传闻", "民间故事")
DOUBT_WORDS = ("据说", "据称", "一说", "可能", "或许", "争议", "推测", "疑似", "据传", "未经证实")


def categorize(text: str) -> str:
    scores = {cat: sum(text.count(w) for w in words) for cat, words in CATEGORY_WORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def assess_reliability(row: Row) -> tuple[str, str]:
    text = row.text
    for w in LEGEND_WORDS:
        if w in text:
            return "legendary", f"记载里出现了“{w}”这样的字眼，它更可能来自传说，而不是可靠的史料。"
    for w in DOUBT_WORDS:
        if w in text:
            return "debated", f"记载里出现了“{w}”这样不确定的措辞，说明这个说法本身就存在疑问。"
    if row.year is not None and row.year < -500:
        return "debated", "年代非常久远，具体日期往往是后人根据有限的资料推算出来的。"
    if row.kind == "dyk":
        return "well_documented", "来自维基百科“你知道吗？”栏目精选的冷知识，可以在条目里找到支持它的参考来源。"
    return "well_documented", (
        "来自维基百科，有明确的时间记载，也没有“据说”“相传”之类的措辞。"
        "不过“百科这样写”不等于“确凿无疑”，最好点开来源看看它引用了什么。"
    )


# ---------------------------------------------------------------- 批判性思考模板
# {when} {ago} {century} 需要年份；{subject} 在没有主题时会变成“这件事”。

TEMPLATES: dict[str, dict[str, list[str]]] = {
    "source_check": {
        "general": [
            "这条记录写的是{when}的事，距今{ago}。我们今天读到的文字，很可能经过了多次转述、翻译和概括——最早写下它的人是谁？是亲历者，还是事后才整理的人？",
            "百科里的一句话，背后往往隔着好几层“转手”：原始史料 → 历史学家的研究 → 百科编者的概括。每转一次手，都可能丢掉细节，或者加进新的解读。",
            "关于{subject}的这句话写得很确定，但它的依据是什么？如果只有一个来源，就更需要小心；如果几个立场不同的来源都这么说，可信度就高得多。",
        ],
        "war": ["战争的记载常常出自胜利的一方。关于这件事，失败的一方留下了怎样的说法？兵力和伤亡数字尤其容易被夸大或缩小。"],
        "disaster": ["在没有现代统计的年代，灾难的伤亡数字大多是估算出来的，不同史料之间可能相差好几倍。我们看到的这个说法，是谁、用什么方法得出的？"],
        "science": ["“首次”“第一个”这类说法要格外小心：它往往只意味着“最早被记录下来的”。同一时期，其他地方是否也有人做过类似的事，只是没有留下记载，或者没有被这种语言的史料注意到？"],
        "politics": ["官方宣布的事情，和实际执行的情况常常有差距。除了官方文件，有没有当时普通人的日记、书信或报道可以对照？"],
        "religion": ["宗教事件的记载，常常出自信徒或反对者之手，立场鲜明。读这类记载时值得问一问：写作者想让读者相信什么？"],
        "exploration": ["探险和“发现”的故事，大多是探险者自己写的。在他们到来之前就生活在那里的人，又是怎样记录和讲述这件事的？"],
        "culture": ["关于作品、建筑或艺术家的轶事很容易越传越神。这个说法能在当时的书信、报刊或档案里找到吗？"],
        "economy": ["经济史里的“影响”常常是后人估算的。能不能找到当时的价格、账簿或贸易数据来检验这种说法？"],
    },
    "hidden_assumption": {
        "general": [
            "我们习惯用今天的道德和常识去评判过去的人。但在当时的信息、观念和条件下，他们的选择是否有另一种合理性？",
            "短短一两句的记载，读起来像是“一个人、一个决定”造就了历史。真实的过程往往牵涉更多的人，也花了更长的时间。",
            "我们为什么会觉得这件事“有趣”或“奇怪”？这种感觉本身，可能暴露了我们对过去的某些想当然。",
        ],
        "war": ["我们常把胜负归功于某位将领或某个决策，这样是否忽略了后勤、天气、疾病和运气？"],
        "science": ["我们容易假设科技总是“越来越进步”，但历史上也有技术失传、知识倒退的例子。"],
        "exploration": ["“发现”这个词本身就藏着一个假设：好像在探险者到来之前，那里不存在一个被人认识的世界。"],
        "politics": ["“某某宣布了……”的写法，容易让人以为宣布之后马上就实现了。从颁布到真正落实，中间可能隔着很长的距离。"],
    },
    "cause_effect": {
        "general": [
            "试着把这件事放进因果链条里：往前追一步，是什么条件让它在{when}发生？往后推一步，它又引发了什么？",
            "这件事是长期趋势的结果，还是一次偶然？把“根本原因”和“导火索”分开来看，常常能看得更清楚。",
        ],
        "war": [
            "一场冲突通常有长期原因（领土、资源、宗教或民族矛盾）、短期导火索，以及偶然因素。在这件事里，哪一种起了决定作用？",
            "战争的影响往往远远超出战场：赋税、人口迁徙、疾病传播、边界变化……这件事之后，普通人的生活发生了什么变化？",
        ],
        "politics": ["在这一政治变化中，谁得到了权力，谁失去了权力？它是突然发生的，还是长期矛盾积累到了临界点？"],
        "science": [
            "这项成果出现在{century}，是天才的偶然灵感，还是当时的材料、工具、资金和知识积累已经让它“呼之欲出”？",
            "一项发明或发现从诞生到真正改变社会，往往要经历很长时间。它是如何一步步传播开来的？",
        ],
        "disaster": ["自然灾害本身是天灾，但伤亡的多少往往取决于人：建筑、预警、救援和社会组织。这件事中，有哪些人为因素放大或减轻了损失？"],
        "economy": ["经济事件背后通常是供需、技术和制度的变化。这件事是谁推动的？谁从中获利，谁承担了代价？"],
        "culture": ["一部作品或一座建筑的诞生，离不开资助者、市场和时代氛围。是什么样的社会条件让它在那时出现？"],
        "exploration": ["推动这次远行的是什么？好奇心、财富、信仰还是国家间的竞争？它又给出发地和目的地分别带来了什么后果？"],
        "religion": ["宗教事件往往同时也是政治和社会事件。这件事背后，有哪些信仰之外的力量在起作用？"],
    },
    "counterfactual": {
        "general": [
            "如果这件事没有发生，或者晚了五十年，后来的历史会有什么不同？哪些变化可能无论如何都会到来？",
            "设想一个关键条件被改变——换一个人、换一个时间、换一种天气——结果还会一样吗？这能帮我们判断哪些因素真正重要。",
        ],
        "war": ["如果这场冲突的结果反过来，今天的地图、语言或文化可能会有什么不同？"],
        "science": ["如果没有这项发明或发现，人类会通过别的途径达到同样的结果吗？历史上“多人几乎同时发明”的现象说明了什么？"],
        "politics": ["如果当时的决策者做出了相反的选择，历史会走向哪里？在当时，他们手里有哪些可选的方案？"],
        "disaster": ["如果当时就有今天的预警和救援手段，结局会有多大不同？哪些损失本来是可以避免的？"],
        "exploration": ["如果这次远行失败了，或者先抵达的是另一群人，后来的世界格局会有什么不同？"],
    },
    "multiple_perspectives": {
        "general": [
            "如果让当时的一位普通农民、一位商人、一位统治者分别讲述这件事，他们的故事会有什么不同？我们今天听到的，主要是谁的版本？",
            "这件事对当时不同地区、不同身份的人，意义可能完全不同：对一些人是机遇，对另一些人也许是灾难。",
        ],
        "war": ["对胜利者、失败者、被征召的普通士兵和战场附近的平民来说，这件事分别意味着什么？教科书通常采用谁的视角？"],
        "politics": ["统治者、官员、普通百姓和邻国，会怎样看待这件事？他们的利益一致吗？谁的声音被记录了下来？"],
        "exploration": ["对探险者来说这是“发现”，对当地原本的居民来说，这可能是一场“入侵”的开始。同一件事，用词不同，立场也就不同。"],
        "economy": ["对商人、工人、消费者和国家财政来说，这件事的利弊可能截然不同。"],
        "science": ["新技术出现时，有人看到机遇，也有人因此失去生计。当时有没有人反对或担忧？他们的理由是什么？"],
        "religion": ["信徒、其他宗教的信众和世俗统治者，会怎样看待这件事？"],
        "disaster": ["同一场灾难，富人和穷人、城市和乡村、当权者和普通人承受的后果往往很不一样。"],
        "culture": ["这件作品在当时受欢迎吗？当时的评论者和今天的我们，评价标准有什么不同？"],
    },
    "present_connection": {
        "general": [
            "{ago}的这件事，今天还能找到它留下的痕迹吗？想一想制度、地名、习俗、建筑或者语言。",
            "这件事和今天的世界有什么相似之处？历史不会简单地重复，但常常“押韵”。",
            "如果这件事发生在今天，新闻和社交媒体会怎样报道它？人们的反应会有什么不同？",
        ],
        "war": ["今天的国际冲突中，还能看到类似的原因或模式吗？我们从这件事中学到了什么，又有什么没学到？"],
        "science": ["今天有哪些技术正处在当年这项成果的位置——前景巨大，但规则和后果都还不清楚？"],
        "disaster": ["今天面对类似的灾难，我们比当时多了哪些工具？又有哪些问题至今仍未解决？"],
        "politics": ["这件事涉及的权力问题——谁来做决定、如何约束权力——在今天是否依然存在？"],
        "economy": ["今天的经济生活中，还能看到这件事的影子吗？比如某种制度、某个行业或某条贸易路线。"],
        "culture": ["这件作品或建筑在今天还有影响力吗？它的意义在几百年间是否发生了变化？"],
    },
}

LEGEND_SOURCE_CHECK = (
    "这条记载里出现了“{word}”这样的字眼——它在提醒我们：这可能是后人流传的故事，而不是可靠的记录。"
    "不过传说本身也有价值：它告诉我们，后来的人希望怎样记住这段历史。"
)

QUESTIONS = {
    "general": [
        "如果你只能再查一份资料来核实这件事，你会选哪一份？为什么？",
        "这件事里，有没有哪个人或哪个群体的声音被忽略了？",
        "一百年后的人回看今天，会觉得我们的哪些做法很奇怪？",
    ],
    "war": ["有没有“正义的战争”？判断的标准应该由谁来定？"],
    "science": ["一项新技术该不该因为可能带来风险而受到限制？谁有权做这个决定？"],
    "politics": ["判断一个决定是否“正确”，应该看动机、过程，还是结果？"],
    "disaster": ["面对灾难，个人、社会和政府各自应该承担什么责任？"],
    "exploration": ["“发现”和“征服”之间的界线在哪里？"],
    "economy": ["经济发展带来的好处和代价，应该如何在不同的人之间分配？"],
    "culture": ["一件作品的价值，是由当时的人决定，还是由后来的人决定？"],
    "religion": ["当信仰和权力结合在一起时，会发生什么？"],
}

VERIFY_TIPS = {
    "general": "再找一个不同语言版本的维基百科条目，或者一本相关的学术著作，交叉核对一下。",
    "war": "对比交战双方各自的记载，特别留意兵力和伤亡数字上的差异。",
    "disaster": "查找当时的地方志、报纸或官方报告，对比不同来源给出的伤亡估计。",
    "science": "查一查同一时期其他国家或地区是否有类似的发明或发现。",
    "politics": "找到原始文件（诏书、条约、法令）的文本，看看百科的概括是否准确。",
    "culture": "找到作品本身或它的早期版本，看看今天流行的说法和原作是否一致。",
    "exploration": "对照航海日志、地图等一手资料，也找找当地原住民一方的记述。",
    "economy": "查找当时的价格、账簿或贸易数据，看看所谓的“影响”能不能量化。",
    "religion": "对比不同宗教团体和世俗史料对同一件事的叙述。",
}

ANGLE_GROUPS = [
    ("source_check", "hidden_assumption"),
    ("cause_effect", "counterfactual"),
    ("multiple_perspectives", "present_connection"),
]
YEAR_SLOTS = re.compile(r"\{(when|ago|century)\}")


def _pick_template(angle: str, category: str, has_year: bool, rng: random.Random) -> str:
    pools = TEMPLATES[angle]
    specific = pools.get(category, []) if category != "general" else []
    usable = lambda pool: [t for t in pool if has_year or not YEAR_SLOTS.search(t)]
    specific, general = usable(specific), usable(pools["general"])
    if specific and (not general or rng.random() < 0.7):
        return rng.choice(specific)
    return rng.choice(general)


def critical_responses(row: Row, category: str, reliability: str, rng: random.Random) -> list[hf.CriticalResponse]:
    slots = {"subject": "这件事" if row.kind == "dyk" or not row.subject else f"「{row.subject}」"}
    has_year = row.year is not None
    if has_year:
        slots |= {"when": date_label(row.year, row.month, row.day), "ago": ago_label(row.year),
                  "century": century_label(row.year)}

    responses = []
    for group in ANGLE_GROUPS:
        angle = rng.choice(group)
        if reliability == "legendary" and "source_check" in group:
            word = next(w for w in LEGEND_WORDS if w in row.text)
            responses.append(hf.CriticalResponse(angle="source_check", response=LEGEND_SOURCE_CHECK.format(word=word)))
            continue
        template = _pick_template(angle, category, has_year, rng)
        responses.append(hf.CriticalResponse(angle=angle, response=template.format(**slots)))
    return responses


# ---------------------------------------------------------------- 数据库

def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _title_for(row: Row) -> str:
    if row.kind == "dyk":
        return "你知道吗？"
    first = re.split(r"[，。；！？]", row.text, maxsplit=1)[0]
    return _shorten(first, 28)


def _sentence(text: str) -> str:
    return text if text.endswith(("。", "！", "？", "”", "」", "）")) else text + "。"


class LocalHistory:
    def __init__(self, path: Path = DB_PATH):
        self.path = Path(path)
        if not self.path.exists():
            raise DatabaseMissingError(
                "本地数据库还没有构建。请先运行 python build_db.py（需要能访问维基百科）。"
            )

    def _query(self, sql: str, params=()) -> list[sqlite3.Row]:
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    @staticmethod
    def _row(r: sqlite3.Row) -> Row:
        return Row(id=r["id"], kind=r["kind"], text=r["text"], answer=r["answer"], year=r["year"],
                   month=r["month"], day=r["day"], subject=r["subject"], links=json.loads(r["links"]),
                   source_title=r["source_title"])

    def stats(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self._query("SELECT key, value FROM meta")}

    @staticmethod
    def _where(keyword: str) -> tuple[str, list[str]]:
        terms = keyword.split()
        where = " AND ".join(
            "(text LIKE ? ESCAPE '\\' OR links LIKE ? ESCAPE '\\' OR answer LIKE ? ESCAPE '\\')" for _ in terms
        )
        return where, [p for t in terms for p in [f"%{_like_escape(t)}%"] * 3]

    def search(self, keyword: str) -> list[Row]:
        """最多返回 MAX_CANDIDATES 条候选（随机顺序，避免总是偏向数据库前面的记录）。"""
        where, params = self._where(keyword)
        rows = self._query(f"SELECT * FROM facts WHERE {where} ORDER BY random() LIMIT {MAX_CANDIDATES}", params)
        return sorted((self._row(r) for r in rows), key=lambda r: r.id)

    def count(self, keyword: str) -> int:
        where, params = self._where(keyword)
        return self._query(f"SELECT COUNT(*) FROM facts WHERE {where}", params)[0][0]

    def same_year(self, row: Row, rng: random.Random) -> Row | None:
        if row.year is None:
            return None
        rows = self._query(
            "SELECT * FROM facts WHERE year = ? AND id != ? AND kind = 'event' LIMIT 200", (row.year, row.id)
        )
        others = [self._row(r) for r in rows if (r["subject"] or "") != (row.subject or "")]
        return rng.choice(others) if others else None

    def generate(self, keyword: str, count: int | str = hf.DEFAULT_FACTS, seed: int | None = None) -> LocalFactsResult:
        keyword = hf.validate_keyword(keyword)
        count = hf.validate_count(count)
        rng = random.Random(seed)
        matches = self.search(keyword)
        if not matches:
            raise NoMatchError(f"本地数据库里没有找到和“{keyword}”相关的记录。试试更短、更常见的中文词，比如人名、地名或朝代。")
        chosen = _choose(matches, keyword, count, rng)
        return LocalFactsResult(
            keyword=keyword,
            facts=[self._build_fact(row, rng) for row in chosen],
            total_matches=len(matches) if len(matches) < MAX_CANDIDATES else self.count(keyword),
        )

    def _build_fact(self, row: Row, rng: random.Random) -> LocalFact:
        category = categorize(row.text)
        reliability, note = assess_reliability(row)

        interesting = []
        if row.kind == "dyk":
            interesting.append("这是维基百科“你知道吗？”栏目精选的冷知识——先别急着看答案，猜一猜？")
        if row.year is not None:
            other = self.same_year(row, rng)
            if other:
                interesting.append(f"把它放回时间线：同样在{year_label(row.year)}，{_sentence(_shorten(other.text, 70))}")
            period = china_period(row.year)
            if period:
                interesting.append(f"那时的中国正处于{period}。")
            if not interesting:
                interesting.append(f"这件事发生在{ago_label(row.year)}。")

        read_more = row.answer or row.subject
        return LocalFact(
            title=_title_for(row),
            era=date_label(row.year, row.month, row.day) if row.kind == "event" else "冷知识问答",
            place="",
            fact=_sentence(row.text),
            why_interesting="".join(interesting),
            reliability=reliability,
            reliability_label=LOCAL_RELIABILITY_LABELS[reliability],
            reliability_note=note,
            critical_responses=critical_responses(row, category, reliability, rng),
            discussion_question=rng.choice(QUESTIONS.get(category, []) + QUESTIONS["general"]),
            how_to_verify="打开下面的来源链接，看看这句话在条目里有没有引用标注，参考文献是一手史料还是后人的研究。"
                          + VERIFY_TIPS[category],
            answer=row.answer,
            source_title=row.source_title,
            source_url=wiki_url(row.source_title),
            read_more_title=read_more,
            read_more_url=wiki_url(read_more) if read_more else None,
        )


def _choose(rows: list[Row], keyword: str, count: int, rng: random.Random) -> list[Row]:
    """按“有趣程度”加权随机抽取，并尽量让结果分布在不同的世纪。"""
    terms = keyword.split()

    def weight(row: Row) -> float:
        w = 1.0
        if row.kind == "dyk":
            w += 1.5
        if any(t in (row.subject or "") or t in (row.answer or "") for t in terms):
            w += 1.0
        if 15 <= len(row.text) <= 150:
            w += 0.5
        return w

    pool = list(rows)
    chosen: list[Row] = []
    used_centuries: set[int] = set()
    while pool and len(chosen) < count:
        weights = []
        for row in pool:
            w = weight(row)
            if row.year is not None and row.year // 100 in used_centuries:
                w *= 0.2
            weights.append(w)
        pick = rng.choices(range(len(pool)), weights=weights)[0]
        row = pool.pop(pick)
        chosen.append(row)
        if row.year is not None:
            used_centuries.add(row.year // 100)
    return chosen

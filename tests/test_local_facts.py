from pathlib import Path

import pytest

import app as web
import build_db
import cli
import history_facts as hf
import local_facts as lf
import wiki_parser as wp

FIXTURES = Path(__file__).parent / "fixtures"
PAGES = {
    "1674年": "year_1674.html",
    "12月29日": "date_12_29.html",
    "Wikipedia:新条目推荐/存档/2024年1月": "dyk_archive.html",
}


def fixture(title: str) -> str:
    return (FIXTURES / PAGES[title]).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 解析

def test_parse_year_page():
    facts = wp.parse_event_page(fixture("1674年"), "1674年")
    assert [(f.year, f.month, f.day) for f in facts] == [(1674, 2, 19), (1674, 6, 6), (1674, None, None)]
    treaty, crowning, petition = facts
    assert treaty.text == "英国与荷兰签订威斯敏斯特条约，结束第三次英荷战争。"
    assert treaty.links == ["威斯敏斯特条约 (1674年)", "第三次英荷战争"]
    assert crowning.text.startswith("希瓦吉在莱加德加冕")
    assert petition.subject == "咖啡馆"
    assert not any("出生" in f.text or "信息框" in f.text for f in facts)


def test_parse_date_page():
    facts = wp.parse_event_page(fixture("12月29日"), "12月29日")
    assert [(f.year, f.month, f.day) for f in facts] == [(1675, 12, 29), (1911, 12, 29)]
    assert facts[0].text.startswith("英格兰国王查理二世下令取缔咖啡馆")
    assert facts[0].links == ["英格兰", "查理二世 (英格兰)", "咖啡馆"]
    assert "固特异" not in "".join(f.text for f in facts)  # “出生”一节不收录


def test_parse_dyk_page():
    facts = wp.parse_dyk_page(fixture("Wikipedia:新条目推荐/存档/2024年1月"), "存档")
    assert [f.answer for f in facts] == ["劳合社", "郑和"]  # 蘑菇不算历史，没有加粗答案的跳过
    assert facts[1].text == "哪位明朝航海家曾七次率领船队远航，最远到达东非沿岸？"


@pytest.mark.parametrize("title, expected", [("1674年", 1674), ("前221年", -221), ("公元1年", 1), ("1674", None)])
def test_parse_year_title(title, expected):
    assert wp.parse_year_title(title) == expected


@pytest.mark.parametrize("text, expected", [
    ("1675年：查理二世下令", (1675, None, None, "查理二世下令")),
    ("公元前44年——凯撒遇刺", (-44, None, None, "凯撒遇刺")),
    ("1911年12月29日：某事发生", (1911, 12, 29, "某事发生")),
    ("3月1日——某事发生", (None, 3, 1, "某事发生")),
    ("3月革命爆发", (None, None, None, "3月革命爆发")),
])
def test_date_prefix(text, expected):
    assert wp._apply_prefix(text, None, None, None) == expected


def test_dedupe_merges_year_and_date_pages():
    a = wp.RawFact(kind="event", text="某事发生。", source_title="1675年", year=1675, links=["甲"])
    b = wp.RawFact(kind="event", text="某事发生", source_title="12月29日", year=1675, month=12, day=29, links=["乙"])
    (merged,) = build_db.dedupe([a, b])
    assert (merged.month, merged.day, merged.links) == (12, 29, ["甲", "乙"])


# ---------------------------------------------------------------- 构建数据库

class FakeWiki:
    def existing_titles(self, titles):
        return [t for t in titles if t in PAGES]

    def all_pages(self, prefix, namespace):
        return [t for t in PAGES if t.startswith("Wikipedia:")]

    def page_html(self, title):
        return fixture(title)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "history.db"
    stats = build_db.build(FakeWiki(), path, first_year=1600, last_year=1700)
    assert stats == {"pages": 3, "total": 7, "events": 5, "dyk": 2}
    return path


@pytest.fixture
def local(db_path):
    return lf.LocalHistory(db_path)


def test_build_writes_meta(local):
    stats = local.stats()
    assert stats["total"] == "7"
    assert stats["license"] == "CC BY-SA 4.0"


# ---------------------------------------------------------------- 本地生成

def test_search_matches_text_links_and_answers(local):
    assert {r.text[:6] for r in local.search("咖啡")} == {"伦敦出现小册", "英格兰国王查", "哪一家起源于"}
    assert [r.answer for r in local.search("郑和")] == ["郑和"]
    assert [r.year for r in local.search("咖啡 查理")] == [1675]
    assert local.search("100%") == []
    assert local.count("咖啡") == 3


def test_total_matches_counts_beyond_candidate_limit(local, monkeypatch):
    monkeypatch.setattr(lf, "MAX_CANDIDATES", 2)
    result = local.generate("咖啡", 1, seed=0)
    assert result.total_matches == 3


def test_generate_builds_complete_facts(local):
    result = local.generate("咖啡", 3, seed=1)
    assert result.total_matches == 3
    assert len(result.facts) == 3
    for fact in result.facts:
        assert fact.title and fact.fact and fact.how_to_verify and fact.discussion_question
        assert fact.source_url.startswith("https://zh.wikipedia.org/wiki/")
        assert len(fact.critical_responses) == 3
        assert len({r.angle for r in fact.critical_responses}) == 3
        assert all("{" not in r.response for r in fact.critical_responses)


def test_generate_is_reproducible_with_seed(local):
    assert local.generate("咖啡", 2, seed=7) == local.generate("咖啡", 2, seed=7)


def test_event_fact_details(local):
    fact = local.generate("查理二世", 1, seed=0).facts[0]
    assert fact.era == "1675年12月29日"
    assert "清朝" in fact.why_interesting
    assert fact.reliability == "well_documented"
    assert fact.source_title == "12月29日"
    assert fact.read_more_title == "英格兰"


def test_dyk_fact_hides_answer_in_responses(local):
    fact = local.generate("郑和", 1, seed=0).facts[0]
    assert fact.title == "你知道吗？"
    assert fact.answer == "郑和"
    assert all("郑和" not in r.response for r in fact.critical_responses)


def test_no_match(local):
    with pytest.raises(lf.NoMatchError):
        local.generate("不存在的关键词")


def test_missing_database(tmp_path):
    with pytest.raises(lf.DatabaseMissingError):
        lf.LocalHistory(tmp_path / "nope.db")


def test_reliability_rules():
    row = lambda text, year=1900: lf.Row(1, "event", text, None, year, None, None, None, [], "x")
    assert lf.assess_reliability(row("相传某人在此飞升"))[0] == "legendary"
    assert lf.assess_reliability(row("据说某人在此出生"))[0] == "debated"
    assert lf.assess_reliability(row("某王即位", -1200))[0] == "debated"
    assert lf.assess_reliability(row("某王即位"))[0] == "well_documented"


def test_legend_gets_matching_source_check():
    row = lf.Row(1, "event", "相传某人在此飞升", None, 1500, None, None, None, [], "x")
    import random
    responses = lf.critical_responses(row, "general", "legendary", random.Random(0))
    assert responses[0].angle == "source_check"
    assert "相传" in responses[0].response


@pytest.mark.parametrize("year, label, period", [
    (1674, "1674年", "清朝"), (-221, "公元前221年", "秦朝"), (1911, "1911年", "清朝"), (1950, "1950年", None),
])
def test_time_helpers(year, label, period):
    assert lf.year_label(year) == label
    assert lf.china_period(year) == period


def test_years_ago_skips_year_zero():
    assert lf.years_ago(-1, today=1) == 1
    assert lf.century_label(-221) == "公元前3世纪"
    assert lf.century_label(1674) == "17世纪"


def test_every_template_formats():
    slots = {"subject": "「甲」", "when": "1674年", "ago": "约 352 年前", "century": "17世纪"}
    for pools in lf.TEMPLATES.values():
        assert pools["general"]
        assert any(not lf.YEAR_SLOTS.search(t) for t in pools["general"])  # 没有年份时也有可用模板
        for templates in pools.values():
            for t in templates:
                t.format(**slots)


# ---------------------------------------------------------------- 网页和命令行

@pytest.fixture
def client(db_path):
    web.app.config.update(TESTING=True, DB_PATH=db_path)
    return web.app.test_client()


def test_api_local(client):
    resp = client.post("/api/facts", json={"keyword": "咖啡", "count": 2})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["engine"] == "local"
    assert len(data["facts"]) == 2
    assert data["total_matches"] == 3


def test_api_local_no_match(client):
    resp = client.post("/api/facts", json={"keyword": "不存在的关键词"})
    assert resp.status_code == 404


def test_api_local_missing_db(client, tmp_path):
    web.app.config["DB_PATH"] = tmp_path / "nope.db"
    assert client.post("/api/facts", json={"keyword": "猫"}).status_code == 503
    assert "build_db.py" in client.get("/").get_data(as_text=True)


def test_index_shows_stats(client):
    page = client.get("/").get_data(as_text=True)
    assert "7 条记录" in page


def test_cli_local(db_path, capsys):
    assert cli.main(["咖啡", "--db", str(db_path), "--seed", "1"]) == 0
    out = capsys.readouterr().out
    assert "本地数据库中共有 3 条相关记录" in out
    assert "🔗 来源：维基百科" in out


def test_cli_local_missing_db(tmp_path, capsys):
    assert cli.main(["咖啡", "--db", str(tmp_path / "nope.db")]) == 1
    assert "build_db.py" in capsys.readouterr().err

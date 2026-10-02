from types import SimpleNamespace

import pytest

import app as web
import cli
import history_facts as hf


def sample_result() -> hf.FactsResult:
    return hf.FactsResult(keyword="咖啡", facts=[hf.HistoryFact(
        title="从咖啡馆诞生的保险巨头", era="约 1688 年", place="英国伦敦",
        fact="劳合社起源于爱德华·劳埃德的咖啡馆。", why_interesting="金融机构起源于咖啡馆。",
        reliability="well_documented", reliability_note="有充分记载。",
        critical_responses=[
            hf.CriticalResponse(angle="cause_effect", response="信息是关键。"),
            hf.CriticalResponse(angle="hidden_assumption", response="机构不一定是设计出来的。"),
            hf.CriticalResponse(angle="multiple_perspectives", response="对不同的人意义不同。"),
        ],
        discussion_question="今天的“咖啡馆”是什么？", how_to_verify="查阅劳合社的历史介绍。",
    )])


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, stop_reason="end_turn", parsed_output=None):
        self.messages = FakeMessages(SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed_output))
        self.beta = SimpleNamespace(messages=self.messages)


def test_generate_facts_sends_expected_request():
    client = FakeClient(parsed_output=sample_result())
    result = hf.generate_facts("  咖啡 ", 4, "en", client=client)

    assert result == sample_result()
    call = client.messages.calls[0]
    assert call["model"] == hf.MODEL
    assert call["output_format"] is hf.FactsResult
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["system"] == hf.SYSTEM_PROMPT
    content = call["messages"][0]["content"]
    assert "<keyword>咖啡</keyword>" in content
    assert "4 条" in content
    assert "English" in content


@pytest.mark.parametrize("keyword", ["", "   ", "字" * (hf.MAX_KEYWORD_LENGTH + 1)])
def test_invalid_keyword(keyword):
    with pytest.raises(hf.InputError):
        hf.generate_facts(keyword, client=FakeClient())


@pytest.mark.parametrize("count", [0, hf.MAX_FACTS + 1, "abc", None])
def test_invalid_count(count):
    with pytest.raises(hf.InputError):
        hf.generate_facts("猫", count, client=FakeClient())


def test_invalid_language():
    with pytest.raises(hf.InputError):
        hf.generate_facts("猫", 3, "fr", client=FakeClient())


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_bad_stop_reason_raises(stop_reason):
    client = FakeClient(stop_reason=stop_reason, parsed_output=sample_result())
    with pytest.raises(hf.HistoryFactsError):
        hf.generate_facts("猫", client=client)


def test_unparsed_output_raises():
    with pytest.raises(hf.HistoryFactsError):
        hf.generate_facts("猫", client=FakeClient(parsed_output=None))


def test_every_label_is_defined():
    for lang in hf.LANGUAGE_NAMES:
        assert set(hf.ANGLE_LABELS[lang]) == set(hf.Angle.__args__)
        assert set(hf.RELIABILITY_LABELS[lang]) == set(hf.Reliability.__args__)


@pytest.fixture
def client(monkeypatch):
    web.app.config.update(TESTING=True)
    return web.app.test_client()


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "批判性思考" in resp.get_data(as_text=True)


def test_api_returns_facts(client, monkeypatch):
    seen = {}

    def fake_generate(keyword, count, language, client=None):
        seen.update(keyword=keyword, count=count, language=language)
        return sample_result()

    monkeypatch.setattr(hf, "generate_facts", fake_generate)
    monkeypatch.setattr(web, "get_client", lambda: None)
    resp = client.post("/api/facts", json={"keyword": "猫", "count": 2, "language": "en", "engine": "ai"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["engine"] == "ai"
    assert len(data["facts"]) == 1
    assert seen == {"keyword": "猫", "count": 2, "language": "en"}


def test_api_input_error(client):
    resp = client.post("/api/facts", json={"keyword": "", "engine": "ai"})
    assert resp.status_code == 400
    assert "关键词" in resp.get_json()["error"]


def test_api_upstream_error(client, monkeypatch):
    def failing(*args, **kwargs):
        raise hf.HistoryFactsError("boom")

    monkeypatch.setattr(hf, "generate_facts", failing)
    monkeypatch.setattr(web, "get_client", lambda: None)
    resp = client.post("/api/facts", json={"keyword": "猫", "engine": "ai"})
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "boom"


def test_api_unknown_engine(client):
    resp = client.post("/api/facts", json={"keyword": "猫", "engine": "magic"})
    assert resp.status_code == 400


def test_cli_ai_reports_errors(monkeypatch, capsys):
    def failing(*args, **kwargs):
        raise hf.HistoryFactsError("没有找到 API Key")

    monkeypatch.setattr(hf, "generate_facts", failing)
    assert cli.main(["猫", "--ai"]) == 1
    assert "没有找到 API Key" in capsys.readouterr().err


def test_cli_ai_formats_output(monkeypatch, capsys):
    monkeypatch.setattr(hf, "generate_facts", lambda *a, **k: sample_result())
    assert cli.main(["咖啡", "--ai"]) == 0
    out = capsys.readouterr().out
    assert "从咖啡馆诞生的保险巨头" in out
    assert "【因果分析】" in out

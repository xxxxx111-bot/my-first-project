from types import SimpleNamespace

import pytest

import app as web
import cli
import history_facts as hf


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
    client = FakeClient(parsed_output=hf.demo_result())
    result = hf.generate_facts("  咖啡 ", 4, "en", client=client)

    assert result == hf.demo_result()
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
    client = FakeClient(stop_reason=stop_reason, parsed_output=hf.demo_result())
    with pytest.raises(hf.HistoryFactsError):
        hf.generate_facts("猫", client=client)


def test_unparsed_output_raises():
    with pytest.raises(hf.HistoryFactsError):
        hf.generate_facts("猫", client=FakeClient(parsed_output=None))


def test_demo_result_is_complete():
    result = hf.demo_result()
    assert len(result.facts) == 3
    for fact in result.facts:
        assert len(fact.critical_responses) == 3
        assert len({r.angle for r in fact.critical_responses}) == 3


def test_every_label_is_defined():
    for lang in hf.LANGUAGE_NAMES:
        assert set(hf.ANGLE_LABELS[lang]) == set(hf.Angle.__args__)
        assert set(hf.RELIABILITY_LABELS[lang]) == set(hf.Reliability.__args__)


@pytest.fixture
def client(monkeypatch):
    web.app.config.update(TESTING=True, DEMO=False)
    return web.app.test_client()


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "批判性思考" in resp.get_data(as_text=True)


def test_api_returns_facts(client, monkeypatch):
    seen = {}

    def fake_generate(keyword, count, language, client=None):
        seen.update(keyword=keyword, count=count, language=language)
        return hf.demo_result()

    monkeypatch.setattr(hf, "generate_facts", fake_generate)
    monkeypatch.setattr(web, "get_client", lambda: None)
    resp = client.post("/api/facts", json={"keyword": "猫", "count": 2, "language": "en"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["demo"] is False
    assert len(data["facts"]) == 3
    assert seen == {"keyword": "猫", "count": 2, "language": "en"}


def test_api_input_error(client):
    resp = client.post("/api/facts", json={"keyword": ""})
    assert resp.status_code == 400
    assert "关键词" in resp.get_json()["error"]


def test_api_upstream_error(client, monkeypatch):
    def failing(*args, **kwargs):
        raise hf.HistoryFactsError("boom")

    monkeypatch.setattr(hf, "generate_facts", failing)
    monkeypatch.setattr(web, "get_client", lambda: None)
    resp = client.post("/api/facts", json={"keyword": "猫"})
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "boom"


def test_api_demo_mode(client):
    web.app.config["DEMO"] = True
    resp = client.post("/api/facts", json={"keyword": "随便"})
    assert resp.status_code == 200
    assert resp.get_json()["demo"] is True
    assert resp.get_json()["keyword"] == "咖啡"


def test_cli_demo(capsys):
    assert cli.main(["随便", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "伦敦的“妇女反咖啡请愿书”" in out
    assert "【史料质疑】" in out


def test_cli_reports_errors(capsys):
    assert cli.main(["", "--demo"]) == 1
    assert "错误" in capsys.readouterr().err

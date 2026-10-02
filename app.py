"""网页版：运行 `python app.py`，然后在浏览器打开 http://127.0.0.1:5000

两种生成方式：
- 本地模式（默认）：从维基百科构建的本地数据库里检索，规则生成批判性思考回应，免费、离线
- AI 模式：调用 Claude 生成，需要 ANTHROPIC_API_KEY
"""

from __future__ import annotations

import argparse

import anthropic
from flask import Flask, jsonify, render_template, request

import history_facts as hf
import local_facts as lf

app = Flask(__name__)
app.config["DB_PATH"] = lf.DB_PATH
app.json.ensure_ascii = False

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def get_local() -> lf.LocalHistory:
    return lf.LocalHistory(app.config["DB_PATH"])


@app.get("/")
def index():
    try:
        local_stats = get_local().stats()
    except lf.DatabaseMissingError:
        local_stats = None
    return render_template(
        "index.html",
        local_stats=local_stats,
        angle_labels=hf.ANGLE_LABELS,
        reliability_labels=hf.RELIABILITY_LABELS,
        min_facts=hf.MIN_FACTS,
        max_facts=hf.MAX_FACTS,
        default_facts=hf.DEFAULT_FACTS,
        max_keyword_length=hf.MAX_KEYWORD_LENGTH,
    )


@app.post("/api/facts")
def api_facts():
    data = request.get_json(silent=True) or {}
    keyword = data.get("keyword", "")
    count = data.get("count", hf.DEFAULT_FACTS)
    engine = data.get("engine", "local")
    try:
        if engine == "local":
            result = get_local().generate(keyword, count)
        elif engine == "ai":
            result = hf.generate_facts(keyword, count, data.get("language", "zh"), client=get_client())
        else:
            raise hf.InputError("engine 只能是 local 或 ai。")
    except hf.InputError as e:
        return jsonify(error=str(e)), 400
    except lf.NoMatchError as e:
        return jsonify(error=str(e)), 404
    except lf.DatabaseMissingError as e:
        return jsonify(error=str(e)), 503
    except hf.HistoryFactsError as e:
        return jsonify(error=str(e)), 502
    return jsonify(result.model_dump() | {"engine": engine})


def main() -> None:
    parser = argparse.ArgumentParser(description="历史事实 + 批判性思考 生成器（网页版）")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--db", help="本地数据库路径（默认 data/history.db）")
    args = parser.parse_args()
    if args.db:
        app.config["DB_PATH"] = args.db
    app.run(host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()

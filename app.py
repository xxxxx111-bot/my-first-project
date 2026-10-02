"""网页版：运行 `python app.py`，然后在浏览器打开 http://127.0.0.1:5000"""

from __future__ import annotations

import argparse
import os

import anthropic
from flask import Flask, jsonify, render_template, request

import history_facts as hf

app = Flask(__name__)
app.config["DEMO"] = os.environ.get("HISTORY_FACTS_DEMO") == "1"
app.json.ensure_ascii = False

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


@app.get("/")
def index():
    return render_template(
        "index.html",
        demo=app.config["DEMO"],
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
    language = data.get("language", "zh")
    try:
        if app.config["DEMO"]:
            hf.validate_keyword(keyword)
            result = hf.demo_result()
        else:
            result = hf.generate_facts(keyword, count, language, client=get_client())
    except hf.InputError as e:
        return jsonify(error=str(e)), 400
    except hf.HistoryFactsError as e:
        return jsonify(error=str(e)), 502
    return jsonify(result.model_dump() | {"demo": app.config["DEMO"]})


def main() -> None:
    parser = argparse.ArgumentParser(description="历史事实 + 批判性思考 生成器（网页版）")
    parser.add_argument("--demo", action="store_true", help="演示模式：不调用 API，显示固定示例")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    if args.demo:
        app.config["DEMO"] = True
    app.run(host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()

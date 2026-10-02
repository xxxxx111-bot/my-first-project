"""命令行版：python cli.py 咖啡 -n 3"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap

import history_facts as hf


def format_result(result: hf.FactsResult, language: str = "zh") -> str:
    angles = hf.ANGLE_LABELS[language]
    reliability = hf.RELIABILITY_LABELS[language]
    zh = language == "zh"
    lines = [f"关键词：{result.keyword}" if zh else f"Keyword: {result.keyword}", ""]
    for i, fact in enumerate(result.facts, 1):
        lines.append(f"{'=' * 60}")
        lines.append(f"{i}. {fact.title}")
        lines.append(f"   {fact.era} · {fact.place} · [{reliability[fact.reliability]}]")
        lines.append("")
        lines.append(textwrap.indent(fact.fact, "   "))
        lines.append("")
        lines.append(f"   {'💡 有趣在哪' if zh else '💡 Why it matters'}：{fact.why_interesting}")
        lines.append(f"   {'🔎 可信度' if zh else '🔎 Reliability'}：{fact.reliability_note}")
        lines.append("")
        lines.append(f"   {'🧠 批判性思考' if zh else '🧠 Critical thinking'}")
        for r in fact.critical_responses:
            lines.append(f"   - 【{angles[r.angle]}】{r.response}")
        lines.append("")
        lines.append(f"   {'❓ 留给你的问题' if zh else '❓ Your turn'}：{fact.discussion_question}")
        lines.append(f"   {'📚 如何核实' if zh else '📚 How to verify'}：{fact.how_to_verify}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="根据关键词生成有趣的历史事实和批判性思考回应")
    parser.add_argument("keyword", help="关键词，例如：咖啡、丝绸之路、猫")
    parser.add_argument("-n", "--count", type=int, default=hf.DEFAULT_FACTS,
                        help=f"生成几条（{hf.MIN_FACTS}-{hf.MAX_FACTS}，默认 {hf.DEFAULT_FACTS}）")
    parser.add_argument("--lang", choices=sorted(hf.LANGUAGE_NAMES), default="zh", help="输出语言")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument("--demo", action="store_true", help="演示模式：不调用 API，显示固定示例")
    args = parser.parse_args(argv)

    try:
        if args.demo:
            hf.validate_keyword(args.keyword)
            result, language = hf.demo_result(), "zh"
        else:
            print("正在翻阅史书……" if args.lang == "zh" else "Digging through the archives...", file=sys.stderr)
            result = hf.generate_facts(args.keyword, args.count, args.lang)
            language = args.lang
    except (hf.InputError, hf.HistoryFactsError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(format_result(result, language))
    return 0


if __name__ == "__main__":
    sys.exit(main())

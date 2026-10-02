"""命令行版：
    python cli.py 咖啡             # 本地模式（默认，免费、离线）
    python cli.py 咖啡 --ai -n 3   # 用 Claude 生成（需要 ANTHROPIC_API_KEY）
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap

import history_facts as hf
import local_facts as lf


def format_result(result, language: str = "zh") -> str:
    angles = hf.ANGLE_LABELS[language]
    zh = language == "zh"
    lines = [f"关键词：{result.keyword}" if zh else f"Keyword: {result.keyword}"]
    if getattr(result, "total_matches", None):
        lines.append(f"本地数据库中共有 {result.total_matches} 条相关记录，随机挑选了 {len(result.facts)} 条。")
    lines.append("")
    for i, fact in enumerate(result.facts, 1):
        label = getattr(fact, "reliability_label", None) or hf.RELIABILITY_LABELS[language][fact.reliability]
        meta = " · ".join(x for x in (fact.era, fact.place, f"[{label}]") if x)
        lines.append("=" * 60)
        lines.append(f"{i}. {fact.title}")
        lines.append(f"   {meta}")
        lines.append("")
        lines.append(textwrap.indent(fact.fact, "   "))
        if getattr(fact, "answer", None):
            lines.append(f"   （答案：{fact.answer}）")
        lines.append("")
        if fact.why_interesting:
            lines.append(f"   {'💡 有趣在哪' if zh else '💡 Why it matters'}：{fact.why_interesting}")
        lines.append(f"   {'🔎 可信度' if zh else '🔎 Reliability'}：{fact.reliability_note}")
        lines.append("")
        lines.append(f"   {'🧠 批判性思考' if zh else '🧠 Critical thinking'}")
        for r in fact.critical_responses:
            lines.append(f"   - 【{angles[r.angle]}】{r.response}")
        lines.append("")
        lines.append(f"   {'❓ 留给你的问题' if zh else '❓ Your turn'}：{fact.discussion_question}")
        lines.append(f"   {'📚 如何核实' if zh else '📚 How to verify'}：{fact.how_to_verify}")
        if getattr(fact, "source_url", None):
            lines.append(f"   🔗 来源：维基百科《{fact.source_title}》 {fact.source_url}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="根据关键词生成有趣的历史事实和批判性思考回应")
    parser.add_argument("keyword", help="关键词，例如：咖啡、丝绸之路、郑和；多个词用空格隔开表示同时包含")
    parser.add_argument("-n", "--count", type=int, default=hf.DEFAULT_FACTS,
                        help=f"生成几条（{hf.MIN_FACTS}-{hf.MAX_FACTS}，默认 {hf.DEFAULT_FACTS}）")
    parser.add_argument("--ai", action="store_true", help="用 Claude 生成（需要 ANTHROPIC_API_KEY），默认使用本地数据库")
    parser.add_argument("--lang", choices=sorted(hf.LANGUAGE_NAMES), default="zh", help="输出语言（仅 AI 模式）")
    parser.add_argument("--db", help="本地数据库路径（默认 data/history.db）")
    parser.add_argument("--seed", type=int, help="随机种子（本地模式），固定后每次结果相同")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args(argv)

    language = args.lang if args.ai else "zh"
    try:
        if args.ai:
            print("正在翻阅史书……" if language == "zh" else "Digging through the archives...", file=sys.stderr)
            result = hf.generate_facts(args.keyword, args.count, language)
        else:
            result = lf.LocalHistory(args.db or lf.DB_PATH).generate(args.keyword, args.count, seed=args.seed)
    except (hf.InputError, hf.HistoryFactsError, lf.NoMatchError, lf.DatabaseMissingError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(format_result(result, language))
    return 0


if __name__ == "__main__":
    sys.exit(main())

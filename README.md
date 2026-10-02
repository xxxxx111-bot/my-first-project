# 📜 历史冷知识 · 批判性思考生成器

输入一个关键词（比如“咖啡”“丝绸之路”“猫”），程序会调用 Claude 生成几条**有趣且真实的历史事实**，并为每条事实给出 3 条从不同角度出发的 **critical thinking 回应**。

每条事实包含：

| 内容 | 说明 |
| --- | --- |
| 标题、时间、地点 | 一眼看懂发生在哪里、什么时候 |
| 事实正文 + “有趣在哪” | 讲清楚发生了什么、为什么值得一看 |
| 可信度标签 | 史料确凿 / 存在争议 / 传说轶事，并说明判断依据 |
| 3 条批判性思考回应 | 从史料质疑、因果分析、多元视角、反事实推演、古今联系、隐含假设中选 3 个角度 |
| 留给你的问题 | 一个没有标准答案的开放式问题 |
| 如何核实 | 去哪类资料验证这条事实 |

网页上的批判性思考回应默认是折叠的——先自己想一想，再展开对照。

## 快速开始

需要 Python 3.10 或更高版本。

```bash
# 1. 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. 设置 API Key（在 https://console.anthropic.com 获取）
export ANTHROPIC_API_KEY=sk-ant-...        # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."

# 3. 启动网页版，然后在浏览器打开 http://127.0.0.1:5000
python app.py
```

还没有 API Key？可以先用**演示模式**看看效果（不调用 AI，固定显示“咖啡”的示例）：

```bash
python app.py --demo
```

## 命令行版

```bash
python cli.py 丝绸之路              # 默认 3 条，中文
python cli.py Rome -n 5 --lang en   # 5 条，英文输出
python cli.py 猫 --json             # 输出原始 JSON
python cli.py 咖啡 --demo           # 演示模式
```

## 文件说明

```
history_facts.py   核心逻辑：提示词、输出结构、调用 Claude API
app.py             网页版（Flask）
templates/index.html  网页界面
cli.py             命令行版
tests/             单元测试（不需要 API Key）
```

想调整生成风格？直接修改 `history_facts.py` 里的 `SYSTEM_PROMPT`。

## 运行测试

```bash
pip install pytest
python -m pytest
```

## 技术细节

- 模型：`claude-opus-5-5`，使用结构化输出（Pydantic）保证返回格式稳定。
- 开启了服务端 fallback（`fallbacks: "default"`）：如果安全分类器误拦了某个正常关键词，API 会自动换模型重试，而不是直接报错。
- 每次生成大约需要几十秒。按 Opus 5.5 的价格（每百万 token 输入 $4 / 输出 $20）估算，生成 3 条大约 0.1–0.2 美元，条数越多越贵。

> ⚠️ 内容由 AI 生成，可能有误。“可信度”和“如何核实”是思考的起点，而不是终点——这本身也是一种批判性思考。

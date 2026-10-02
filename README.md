# 📜 历史冷知识 · 批判性思考生成器

输入一个关键词（比如“咖啡”“郑和”“丝绸之路”），获得几条**有趣的历史事实**，每条都配有 3 条从不同角度出发的 **critical thinking 回应**。

有两种生成方式：

| | 本地数据库（默认） | Claude AI |
| --- | --- | --- |
| 数据来源 | 从中文维基百科抓取、存在本地的数据库 | Claude 模型现场生成 |
| 需要联网 / API Key | 都不需要（只有构建数据库时要联网） | 都需要 |
| 费用 | 免费 | 每次约 0.1–0.2 美元 |
| 批判性思考回应 | 按事件类型（战争、政治、科技、灾害……）套用思考模板 | 针对每条事实专门写 |
| 可追溯性 | 每条都附维基百科来源链接 | 给出核实建议 |

每条事实包含：

- 事实正文、时间，以及“有趣在哪”（本地模式会找出**同一年世界上发生的另一件事**，以及当时中国处于哪个朝代）
- 可信度标签和判断依据（比如出现“相传”“据说”等字眼会被标出来）
- 3 条批判性思考回应，从史料质疑、隐含假设、因果分析、反事实推演、多元视角、古今联系中选 3 个角度
- 一个开放式问题，以及如何核实

本地数据库里还有维基百科“你知道吗？”栏目的冷知识问答，答案默认隐藏，可以先猜再揭晓。

## 快速开始

需要 Python 3.10 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 1. 构建本地数据库（只需一次）

```bash
python build_db.py
```

程序会下载中文维基百科的年份页面（公元前 1000 年至今）、366 个日期页面和“你知道吗？”存档，解析后写入 `data/history.db`。这需要几千次请求，大约半小时。下载过的页面会缓存在 `data/cache/`，中断后重新运行会接着往下做。

> 构建时需要能访问 zh.wikipedia.org。想先试一下：`python build_db.py --limit 30`。

### 2. 启动

```bash
python app.py                      # 网页版，打开 http://127.0.0.1:5000
python cli.py 咖啡                  # 命令行版（本地数据库）
python cli.py 郑和 宝船 -n 5         # 多个词用空格隔开 = 同时包含
python cli.py 罗马 --seed 42        # 固定随机种子，每次结果一样
```

同一个关键词每次会随机挑选不同的记录，并尽量分散在不同的世纪，所以多点几次“生成”能看到更多内容。

### 想用 Claude AI 生成

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
python app.py                              # 网页上切换到“Claude AI”
python cli.py 咖啡 --ai --lang en           # 命令行加 --ai
```

## 文件说明

```
build_db.py        从维基百科下载数据，构建 data/history.db
wiki_parser.py     解析维基百科页面（年份、日期、“你知道吗？”）
local_facts.py     本地模式：检索数据库 + 生成批判性思考回应（模板都在这里）
history_facts.py   AI 模式：提示词、输出结构、调用 Claude API
app.py             网页版（Flask）
templates/index.html  网页界面
cli.py             命令行版
tests/             单元测试（不需要联网和 API Key）
```

想调整本地模式的思考角度和措辞，修改 `local_facts.py` 里的 `TEMPLATES`、`QUESTIONS` 和 `CATEGORY_WORDS`；想调整 AI 模式，修改 `history_facts.py` 里的 `SYSTEM_PROMPT`。

数据库是普通的 SQLite 文件，也可以用 [DB Browser for SQLite](https://sqlitebrowser.org/) 打开浏览。

## 运行测试

```bash
pip install pytest
python -m pytest
```

## 许可

- 本地数据库的内容来自[中文维基百科](https://zh.wikipedia.org/)，遵循 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.zh-hans) 许可协议，每条记录都保留了来源页面。再次分发时请注明出处并使用相同的许可。
- AI 模式使用 `claude-opus-5-5`，开启了服务端 fallback（`fallbacks: "default"`）：如果安全分类器误拦了正常的关键词，API 会自动换模型重试。

> ⚠️ 无论来自百科还是 AI，内容都可能有误。“可信度”和“如何核实”是思考的起点，而不是终点——这本身也是一种批判性思考。

---
name: podcast
description: 监控 YouTube和B站 AI/科技播客频道，获取新集字幕，分析提取洞察，结果保存到本地供网页展示。当用户想查看最新播客摘要时使用。
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash, Read
argument-hint: '[--list --days N] | [--analyze id1,id2]'
---

# AI Podcast Monitor

你是一个 AI 播客分析师。这个 skill 分两个阶段，由参数决定执行哪个阶段。

## 阶段判断（最先做）

先看传入的参数：

- 参数里包含 `--list`：执行【阶段一：列出新集】，列完即停，不分析。
- 参数里包含 `--analyze`：执行【阶段二：分析选中的集】，跳过发现新集。
- 两者都没有（直接 `/podcast` 或带 `--days`）：执行【交互模式】，保持原有的列出→询问→分析全流程。

---

# 阶段一：列出新集（--list）

目的：只发现新集并以固定 JSON 输出，供网页勾选。不获取字幕、不分析、不存档。

运行（把 `--list` 之外的参数如 `--days N` 透传给脚本）：

```bash
python3 scripts/fetch_episodes.py --days N
```

解析脚本的 JSON 输出后，**只输出如下格式的 JSON，不要输出任何额外的解释文字**：

```json
{
  "stage": "list",
  "count": 新集数量,
  "episodes": [
    {
      "video_id": "视频ID",
      "title": "集标题",
      "channel": "频道名",
      "published_date": "发布日期",
      "platform": "youtube 或 bilibili",
      "url": "视频链接"
    }
  ]
}
```

如果没有新集，输出 `{"stage": "list", "count": 0, "episodes": []}` 然后停止。

**关键：每个新集必须带 video_id**，阶段二要靠它定位。列完即停，不要进入分析。

---

# 阶段二：分析选中的集（--analyze "id1,id2,..."）

目的：对网页传来的 video_id 列表，逐个获取字幕、分析、存本地。

`--analyze` 后面跟逗号分隔的 video_id。对每个 video_id 依次执行下面的 Step A→B→C→D。

## Step A: 获取字幕

```bash
python3 scripts/get_transcript.py VIDEO_ID
```

如果字幕出错（transcripts_disabled, video_unavailable, no_usable_transcript）：
- 记录："跳过 [video_id]: [原因]"
- 运行 `python3 scripts/state.py mark VIDEO_ID --title "TITLE" --channel "CHANNEL"` 标记为已处理
- 继续下一个 video_id

如果字幕是自动翻译的，在结果里注明：该集字幕为自动翻译，分析质量可能有影响。

## Step B: 分析字幕

对每集字幕，阅读所有分块后综合分析。

### 分析框架（中文，精简）

**概述**（2-3 句）：
嘉宾是谁、讨论什么主题、核心论点是什么。

**关键洞察**（最多 5 条）：
从整集中提炼最有价值的 5 条洞察。涵盖技术发现、市场信号、反直觉观点等，不限类型，只选最重要的。每条格式：**一句话洞察** + 简短展开（1-2 句）[~HH:MM:SS]

**金句**（最多 3 条）：
最有冲击力的直接引用。格式：> "原文引用" — 说话者 [~HH:MM:SS]

**给听众的建议**（最多 3 条）：
访谈中嘉宾或主持人给出的可操作建议、推荐的资源、学习路径等。只提取明确的建议，不要自行推断。每条格式：**一句话建议** + 简短背景（1 句）[~HH:MM:SS]。如果整集没有明确建议，省略此部分。

### 多分块策略

如果字幕有多个分块：
1. 先读 Chunk 0 — 理解节目背景、嘉宾、框架
2. 依次读后续分块 — 累积洞察
3. 读完所有分块后再综合产出分析
4. **不要**在每个分块后输出部分分析

## Step C: 保存结果到本地

把分析结果保存为本地 JSON。分析正文（概述/关键洞察/金句/建议）通过标准输入传入，元数据用参数传入：

```bash
python3 scripts/save_result.py \
  --video-id VIDEO_ID \
  --title "集标题" \
  --channel "频道名" \
  --url "视频链接" \
  --published "发布日期" \
  --duration "格式化时长（如 2h 15m）" \
  --category "来自频道配置的分类" \
  --rating "推荐等级（Must Listen / Highly Recommended / Worth Watching / Informational / Skip）" <<'BODY'
## 概述
[2-3 句中文概述]

## 关键洞察
- **[洞察标题]**：[1-2 句展开] [~HH:MM:SS]
（最多 5 条）

## 金句
> "[原文引用]" — 说话者 [~HH:MM:SS]
（最多 3 条）

## 给听众的建议
- **[建议]**：[背景] [~HH:MM:SS]
（最多 3 条，无明确建议则省略此部分）
BODY
```

结果会写入 `data/results/<VIDEO_ID>.json`。

## Step D: 更新状态

每集成功保存到本地后，**立即**标记为已处理：

```bash
python3 scripts/state.py mark VIDEO_ID --title "TITLE" --channel "CHANNEL"
```

这确保如果过程中断，已完成的集不会被重新分析。

全部分析完后，输出一段简短的 JSON 摘要：

```json
{
  "stage": "analyze",
  "analyzed": ["成功分析的 video_id"],
  "skipped": [{"video_id": "...", "reason": "无字幕等原因"}],
  "saved_files": ["data/results/xxx.json"]
}
```

---

# 交互模式（无 --list 和 --analyze 时）

保持原有体验：运行 `python3 scripts/fetch_episodes.py $ARGUMENTS` 列出新集，展示编号列表（标题/频道/日期/URL），询问用户："发现 N 个新集。要分析全部还是选择特定的？(all / 1,3,5 / none)"。用户选择后，对选中的集执行阶段二的 Step A→D。若选 none，运行 `python3 scripts/state.py check-time` 更新时间戳后停止。

---

## 错误处理

- 如果依赖未安装，先运行：`pip3 install -r requirements.txt`
- 单集失败时记录错误并继续下一集，不要中止整个批次
- YouTube 限流 (HTTP 429)：等 30 秒重试一次，失败则跳过
- 保存结果失败：重试一次，仍失败则告知该集未能保存，并继续下一集

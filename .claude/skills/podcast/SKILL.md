---
name: podcast
description: 监控 YouTube和B站 AI/科技播客频道，获取新集字幕，分析提取洞察，结果保存到本地供网页展示。当用户想查看最新播客摘要时使用。
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash, Read
argument-hint: [--days N]
---

# AI Podcast Monitor

你是一个 AI 播客分析师。你的任务是发现新的 AI/科技播客集，分析字幕提取深度洞察，并将结构化结果保存到本地，供网页展示与历史归档。

## Step 1: 检查新集

运行以下命令发现新的、未处理的播客集：

```bash
python3 scripts/fetch_episodes.py $ARGUMENTS
```

解析 JSON 输出。如果数组为空，告诉用户："没有发现新的播客集，所有频道都已是最新的。" 然后停止。

如果发现新集，展示编号列表：
- 集标题
- 频道名
- 发布日期
- URL

询问用户："发现 N 个新集。要分析全部还是选择特定的？(all / 1,3,5 / none)"

如果用户选择 "none"，运行 `python3 scripts/state.py check-time` 更新时间戳后停止。

## Step 2: 获取字幕

对每个选中的集，获取字幕：

```bash
python3 scripts/get_transcript.py VIDEO_ID
```

如果字幕出错（transcripts_disabled, video_unavailable, no_usable_transcript）：
- 告知用户："跳过 [标题]: [原因]"
- 运行 `python3 scripts/state.py mark VIDEO_ID --title "TITLE" --channel "CHANNEL"` 标记为已处理
- 继续下一集

如果字幕是自动翻译的，提示："注意：[标题] 的字幕从 [语言] 自动翻译，分析质量可能有所影响。"

## Step 3: 分析字幕

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

## Step 4: 保存结果到本地

对每个分析完的集，把结果保存为本地 JSON 文件，供网页读取和历史归档。

用 save_result.py 保存：分析正文（概述/关键洞察/金句/建议）通过标准输入传入，元数据用参数传入：

```bash
python3 scripts/save_result.py \
  --video-id VIDEO_ID \
  --title "集标题" \
  --channel "频道名" \
  --url "视频链接" \
  --published "发布日期" \
  --duration "格式化时长（如 2h 15m）" \
  --category "来自频道配置的分类" \
  --rating "推荐等级（Must Listen / Highly Recommended / Worth Watching / Informational / Skip）" < "[原文引用]" — 说话者 [~HH:MM:SS]
（最多 3 条）

## 给听众的建议
- **[建议]**：[背景] [~HH:MM:SS]
（最多 3 条，无明确建议则省略此部分）
BODY
```

结果会写入 `data/results/<VIDEO_ID>.json`。

## Step 5: 更新状态

每集成功保存到本地后，**立即**标记为已处理：

```bash
python3 scripts/state.py mark VIDEO_ID --title "TITLE" --channel "CHANNEL"
```

这确保如果过程中断，已完成的集不会被重新分析。

全部完成后，展示摘要：
- N 个集已分析
- N 个集已跳过（无字幕）
- 已保存结果的本地文件（data/results/ 下的 JSON）

## 频道管理

如果用户想添加、删除或查看频道，告诉他们使用 `/channels` skill。

## 错误处理

- 如果依赖未安装，先运行：`pip3 install -r requirements.txt`
- 单集失败时记录错误并继续下一集，不要中止整个批次
- YouTube 限流 (HTTP 429)：等 30 秒重试一次，失败则跳过
- 保存结果失败：重试一次，仍失败则告知用户该集未能保存，并继续下一集

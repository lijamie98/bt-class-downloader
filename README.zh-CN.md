# bt-class-downloader

**Languages / 語言 / 语言:** [English](README.md) · [繁體中文](README.zh-TW.md) · **简体中文**

---

从 [BiblicalTraining.org](https://www.biblicaltraining.org/) 下载**任意课程**的**课堂逐字稿**文本；可提供**课程总览 URL**，或使用本地课程索引中可唯一解析的 **slug 前缀**（见下方 **`download`**）。

## 前提条件

- Python 3.11+

## 安装

```bash
cd /path/to/class-downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

使用 **`python -m bt`** 运行（包的 `__main__`）。安装后 **`bt`** 也会在 `PATH` 中（与 **`biblicaltraining-transcripts`** 相同）。

## 快速开始

在项目目录中：

```bash
# 若缺少课程索引，首次运行 CLI 时会拉取；再用 slug 前缀下载（须唯一对应一门课）
python -m bt download nt201
# 或：bt download nt201
```

会写入 **`courses/nt201-biblical-greek/nt201-biblical-greek.md`**（逐字稿）与 **`courses/nt201-biblical-greek/nt201-biblical-greek.outline.md`**（大纲；实际路径取决于解析出的 slug）。

**可选 — Gemini 分段**（设置 **`GEMINI_API_KEY`**，或在工作目录的 **`.env`** 中配置；详见下方 **`paragraph`** 与 **`paragraph-outline`**）：

```bash
# 仅逐字稿（不用大纲文件）
python -m bt paragraph nt201 --lesson 1

# 逐字稿 + 磁盘上的大纲
python -m bt paragraph-outline nt201 --lesson 1
```

**一次处理多门课：**

```bash
python -m bt download nt201 nt203
python -m bt paragraph nt201 nt203
```

## 应使用哪种课程标识？

**`download`** 需要**课程总览**页面：URL 路径须在**课程 slug** 处结束（例如 `…/learn/<segment>/<course-slug>`），HTML 中才会列出该课程下的各课链接。本工具不按特定标题或标签查找页面。

**不要**将**单课** URL 当作课程 URL（路径在课程 slug 之后还有一段）。这些页面不会用于枚举全部课时。

**总览 URL 示例：**

- `https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek`
- `https://www.biblicaltraining.org/learn/institute/nt605-textual-criticism`
- `https://www.biblicaltraining.org/learn/foundations/nt101-essentials-of-the-new-testament`

**或**传入 **slug 前缀**（例如 `nt201`），只要在索引中**恰好对应一门课**即可—规则与下方 **`download`** 与**课程索引**相同。

## 命令

### `download` — 获取逐字稿

**必填：** `download` 子命令，以及一个或多个课程标识（各为 URL 或索引中的 slug 前缀）。

```bash
python -m bt download \
  "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"

# 或使用本地课程索引的 slug 前缀：
python -m bt download nt201

# 多门课（各写入 courses/<slug>/<slug>.md；勿使用 --out）：
python -m bt download nt201 nt203
```

默认输出：`courses/<course-slug>/<course-slug>.md`（例如 `courses/nt201-biblical-greek/nt201-biblical-greek.md`）。

工具始终将课程大纲写入 **`courses/<course-slug>/<course-slug>.outline.md`**（与逐字稿同目录）。文件以课程标题 `# …` 开头，随后每课为 `## Lesson {n}: {课名}` 与 Markdown 项目式大纲（已去除 HTML）。若存在内嵌 `__NEXT_DATA__` 则优先使用；否则大纲来自 JSON:API（`include=field_lessons`）。若无法获取大纲，**`download` 以退出码 4 结束**，且不再抓取课时页面。

自定义逐字稿路径（仅单门课；下载多门课时不可用）：

```bash
python -m bt download \
  "https://www.biblicaltraining.org/learn/institute/nt605-textual-criticism" \
  --out courses/nt605-textual-criticism/nt605-textual-criticism.md
```

安装后也可使用控制台脚本：

```bash
biblicaltraining-transcripts download "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"
```

#### 课程索引（slug 前缀查询）

CLI 会维护本地**课程索引**，从 `https://www.biblicaltraining.org/classes` 拉取，缓存在**用户缓存目录**：

- macOS：`~/Library/Caches/bt-class-downloader/course_index.json`
- 其他：`~/.cache/bt-class-downloader/course_index.json`

启动时若索引文件不存在会自动拉取。若要强制刷新：

```bash
python -m bt refresh-index
```

可查看已缓存的索引：

```bash
python -m bt list-index --limit 25
python -m bt search-index nt201
```

Slug 前缀查询（如 `nt201`）必须**恰好**对应一个课程 slug；0 个或多个则命令失败。

#### Cloudflare / 登录

若页面返回 Cloudflare 验证或需登录，请使用 cookies（Playwright 导出格式）与 `auto` 抓取器：

```bash
python -m bt download "COURSE_URL" --cookies-json /path/to/cookies.json --fetcher auto
```

#### `download` 选项

- `--fail-fast` — 第一个无法提取逐字稿的课时即停止
- `--fetcher playwright` — 始终使用真实浏览器（较慢，部分站点更稳）
- `--headless` — Playwright 无头运行（默认有界面）

### `paragraph` — Gemini 分段（仅逐字稿）

使用 **`GEMINI_API_KEY`**。若环境变量未设置，CLI 会从**当前工作目录**的 **`.env`** 加载（`python-dotenv`）；行为与下方 **`paragraph-outline`** 一致。请在项目目录（或 `courses/` 与 `.env` 所在处）执行：

```bash
# 单课（默认：courses/<slug>/paragraph/<model>/<slug>.lessonNN.paragraph.md）
python -m bt paragraph nt203-greek-tools-for-bible-study --lesson 3

python -m bt paragraph nt203 --lesson 3

# 全部课时（每课一次 Gemini 请求；一个合并文件：courses/<slug>/paragraph/<model>/<slug>.paragraph.md）
python -m bt paragraph nt203-greek-tools-for-bible-study

# 多门课（每门课默认路径；勿使用 --transcript 或 --out）
python -m bt paragraph nt203 nt201
```

读取 **`courses/<course-slug>/<course-slug>.md`**，提取课文（仅 **`--lesson`** 指定一课，或省略时处理每个 `# Lesson N:` 区块），并**不**使用课程大纲调用 Gemini（每课一次请求）。系统提示要求模型为逐字稿分段且不改动措辞、不为段落加标题；工具再将每课标题以 **`##`** 置于开头（来自逐字稿的 `# Lesson N:`），并以课程 **`#`** 标题与**目录**包装，目录会链接文件中**每一个** `##`–`######` 标题（按层级缩进），外层版式与 `paragraph-outline` 相同。

### `paragraph-outline` — Gemini 大纲分段

旧别名 **`paragraph-lesson`** 与此命令相同。

使用 **`GEMINI_API_KEY`**。若环境变量未设置，CLI 会从**当前工作目录**的 **`.env`** 加载。请将密钥放在 `.env`（已由 git 忽略）：

```bash
# .env（一行，除非值需要引号否则不要加引号）
GEMINI_API_KEY=your_key_here
```

**Shell 替代方式**（若不想用 `.env`）：

- **一次性：** `export GEMINI_API_KEY=your_key_here` 后在同一终端会话中运行。
- **在 shell 中加载 `.env`**（zsh/bash）：`set -a && source .env && set +a`（`.env` 须为 `KEY=value` 格式）。

请在项目目录（或 `courses/` 与 `.env` 所在处）执行。**`paragraph-outline`** 需要逐字稿与大纲文件同在 **`courses/<slug>/`** 下：

```bash
# 单课（默认：courses/<slug>/paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md）
python -m bt paragraph-outline nt203-greek-tools-for-bible-study --lesson 3

# 全部课时（每课一次 Gemini；单文件：courses/<slug>/paragraph-outlined/<model>/<slug>.paragraph-outlined.md）
python -m bt paragraph-outline nt203-greek-tools-for-bible-study

# slug 前缀亦可（须唯一）：
python -m bt paragraph-outline nt203 --lesson 3

# 多门课（勿使用 --transcript、--outline 或 --out）
python -m bt paragraph-outline nt203 nt201
```

读取 **`courses/<course-slug>/<course-slug>.md`** 与 **`courses/<course-slug>/<course-slug>.outline.md`**，提取每课的**逐字稿正文**与**大纲区块**（或仅 `--lesson` 指定的一课），再调用 Gemini。系统说明（见 `src/bt/lesson_paragraph.py`）要求模型分段、保留措辞、将大纲内嵌为标题、不重复课名、大纲最浅层使用 **`###`**，且模型输出中不使用 **`#`** / **`##`**。用户消息包含逐字稿与大纲文本。

输出文件中的课名为**二级标题**（`##`）；工具会规范化标题层级，使模型正文最浅为 **`###`**。

**输出：** **Markdown**（`.md`）。文件以**课程标题**为**一级标题**（`#`，取自逐字稿第一个非课名的 `# …` 行，若无则由 slug 推导），接着 **`## Table of contents`**，以缩进列表链接合并后文件内**每一个** `##`–`######` 标题（不限课名），水平线后为正文。链接锚点采用 GitHub 风格；相同标题文字重复时会加数字后缀。

默认路径：有 **`--lesson`** 时为 **`courses/<slug>/paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md`**；无则为 **`courses/<slug>/paragraph-outlined/<model>/<slug>.paragraph-outlined.md`**。此处 ``<model>`` 为经文件名安全处理后的 Gemini 模型 id。每课一次 Gemini 请求。每课区块对应逐字稿的 `## Lesson N: …`（由 `# Lesson N: …` 提升），接大纲分段正文。

**单门**课可用 **`--out 路径`** 覆盖输出文件（**无**扩展名时会自动加 **`.md`**）。**多门**课时请省略 **`--out`**（并省略 **`--transcript`** / **`--outline`**）。可用 **`--transcript`** / **`--outline`** 覆盖输入，**`--model`** 指定模型（默认 **`gemini-3.1-flash-lite-preview`**）。若有课失败（缺逐字稿或大纲、或 Gemini 错误），命令在非零退出码下仍会尽量处理其余内容；合并文件会跳过失败的课。

**`study-note-zh`**（繁体中文）与 **`study-note-cn`**（简体中文）使用与 **`paragraph-outline`** 相同的逐字稿 + 大纲输入与 **`GEMINI_API_KEY`**，但生成学习指南式说明 Markdown，位于 **`courses/<slug>/study-note-zh/…`** 或 **`courses/<slug>/study-note-cn/…`**（见**输出布局**）。模型会输出简短大纲对照引言块，以及 HTML 注释（`study-note-zh-h2` / `study-note-cn-h2`；旧版 `explain-zh-h2` / `explain-cn-h2` 仍兼容）供工具生成双语 **`##`** 课名；提示词要求圣经用语优先采用**改革宗／归正神学**惯用中文。示例：`python -m bt study-note-cn nt203 --lesson 1`。命令 **`explain-zh`** / **`explain-cn`** 为弃用别名。

## 工作原理

1. **`download`：** 抓取**课程**页面并收集课时链接。从内嵌 JSON 或 JSON:API 解析课程大纲；若失败，命令在尚未下载课时逐字稿前即停止（退出码 **4**）。
2. 抓取每个课时页面，将 **Transcription** 区块提取为纯文本。
3. 将逐字稿与大纲写入 **`courses/<course-slug>/`**（平铺：`<slug>.md` 与 `<slug>.outline.md`），含**课程标题**（来自课程页）、**目录**，以及每课 `# Lesson {n}: {title}`。

## 输出布局

路径均在 **`courses/<course-slug>/`** 下。Gemini 输出含经文件名安全处理的 **`/<model>/`** 目录段。

| 类型 | 默认路径 |
|------|----------------|
| 课程逐字稿 | `courses/<course-slug>/<course-slug>.md` |
| 课程大纲 | `courses/<course-slug>/<course-slug>.outline.md` |
| 分段单课（Gemini，仅逐字稿，`--lesson`） | `courses/<course-slug>/paragraph/<model>/<course-slug>.lessonNN.paragraph.md` |
| 分段整课（Gemini，仅逐字稿，全部课） | `courses/<course-slug>/paragraph/<model>/<course-slug>.paragraph.md` |
| 大纲分段单课（Gemini，`--lesson`） | `courses/<course-slug>/paragraph-outlined/<model>/<course-slug>.lessonNN.paragraph-outlined.md` |
| 大纲分段整课（Gemini，全部课） | `courses/<course-slug>/paragraph-outlined/<model>/<course-slug>.paragraph-outlined.md` |
| 中文学习笔记单课，繁体（`study-note-zh`，`--lesson`） | `courses/<course-slug>/study-note-zh/<model>/<course-slug>.lessonNN.zh.md` |
| 中文学习笔记整课，繁体（`study-note-zh`，全部课） | `courses/<course-slug>/study-note-zh/<model>/<course-slug>.zh.md` |
| 中文学习笔记单课，简体（`study-note-cn`，`--lesson`） | `courses/<course-slug>/study-note-cn/<model>/<course-slug>.lessonNN.cn.md` |
| 中文学习笔记整课，简体（`study-note-cn`，全部课） | `courses/<course-slug>/study-note-cn/<model>/<course-slug>.cn.md` |
| 中文翻译单课，繁体（`translate-zh`，`--lesson`） | `courses/<course-slug>/translate-zh/<model>/<course-slug>.lessonNN.zh.md` |
| 中文翻译整课，繁体（`translate-zh`，全部课） | `courses/<course-slug>/translate-zh/<model>/<course-slug>.zh.md` |
| 中文翻译单课，简体（`translate-cn`，`--lesson`） | `courses/<course-slug>/translate-cn/<model>/<course-slug>.lessonNN.cn.md` |
| 中文翻译整课，简体（`translate-cn`，全部课） | `courses/<course-slug>/translate-cn/<model>/<course-slug>.cn.md` |

### 从 `data/` 迁移

若您仍有旧版 **`data/transcripts/`**、**`data/outlines/`** 与 **`data/<command>/<model>/…`** 目录，可按上文迁移，例如：

- `data/transcripts/<slug>.md` → `courses/<slug>/<slug>.md`
- `data/outlines/<slug>.outline.md` → `courses/<slug>/<slug>.outline.md`
- `data/paragraph/<model>/…` → `courses/<slug>/paragraph/<model>/…`（文件名不变）；`paragraph-outlined`、`study-note-zh`、`study-note-cn`、`translate-zh`、`translate-cn` 同理（旧目录 `explain-zh` / `explain-cn` 请改名为 `study-note-zh` / `study-note-cn`）。

## 说明

- 请遵守 BiblicalTraining 使用条款；本工具适用于个人学习／无障碍用途之公开逐字稿副本。
- 部分课时版面不同；若提取失败，可尝试 `--fetcher playwright` 或提供 cookies。
- 可安装的 Python 发行版在 PyPI 上名为 **`biblicaltraining-class-transcripts`**；仓库目录常为 **`bt-class-downloader`**。CLI 模块为 **`bt`**（`python -m bt`，控制台脚本 **`bt`** 与 **`biblicaltraining-transcripts`**）。

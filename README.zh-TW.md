# bt-class-downloader

**Languages / 語言 / 语言:** [English](README.md) · **繁體中文** · [简体中文](README.zh-CN.md)

---

從 [BiblicalTraining.org](https://www.biblicaltraining.org/) 下載**任何課程**的**課堂逐字稿**文字；可輸入**課程總覽網址**，或使用本機課程索引中可唯一對應的 **slug 前綴**（見下方 **`download`**）。

## 必要條件

- Python 3.11+

## 安裝

```bash
cd /path/to/class-downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

使用 **`python -m bt`** 執行（套件 `__main__`）。安裝後 **`bt`** 也會在 `PATH` 上（與 **`biblicaltraining-transcripts`** 相同）。

## 快速開始

在專案目錄中：

```bash
# 若缺少課程索引，第一次執行 CLI 時會抓取；再以 slug 前綴下載（須唯一對應一門課）
python -m bt download nt201
# 或：bt download nt201
```

會寫入 **`courses/nt201-biblical-greek/nt201-biblical-greek.md`**（逐字稿）與 **`courses/nt201-biblical-greek/nt201-biblical-greek.outline.md`**（大綱；實際路徑依解析出的 slug 而定）。

**選用 — Gemini 分段**（設定 **`GEMINI_API_KEY`**，或在工作目錄的 **`.env`** 中設定；詳見下方 **`paragraph`** 與 **`paragraph-outline`**）：

```bash
# 僅逐字稿（不使用大綱檔）
python -m bt paragraph nt201 --lesson 1

# 逐字稿 + 磁碟上的大綱
python -m bt paragraph-outline nt201 --lesson 1
```

**一次處理多門課：**

```bash
python -m bt download nt201 nt203
python -m bt paragraph nt201 nt203
```

## 應使用哪種課程識別？

**`download`** 需要**課程總覽**頁面：網址路徑須在**課程 slug** 結束（例如 `…/learn/<segment>/<course-slug>`），HTML 中才會列出該課程底下的各課連結。本工具不會依特定標題或標籤尋找頁面。

**不要**把**單一課堂**網址當成課程網址（路徑在課程 slug 之後還多一段）。這類頁面不會用來列舉全部課堂。

**總覽網址範例：**

- `https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek`
- `https://www.biblicaltraining.org/learn/institute/nt605-textual-criticism`
- `https://www.biblicaltraining.org/learn/foundations/nt101-essentials-of-the-new-testament`

**或**改傳 **slug 前綴**（例如 `nt201`），只要在索引中**恰好對應一門課**即可—規則與下方 **`download`** 與**課程索引**相同。

## 指令

### `download` — 取得逐字稿

**必填：** `download` 子指令，以及一個或多個課程識別（各為網址或索引中的 slug 前綴）。

```bash
python -m bt download \
  "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"

# 或使用本機課程索引的 slug 前綴：
python -m bt download nt201

# 多門課（各寫入 courses/<slug>/<slug>.md；勿使用 --out）：
python -m bt download nt201 nt203
```

預設輸出：`courses/<course-slug>/<course-slug>.md`（例如 `courses/nt201-biblical-greek/nt201-biblical-greek.md`）。

工具一律將課程大綱寫入 **`courses/<course-slug>/<course-slug>.outline.md`**（與逐字稿同目錄）。檔案開頭為課程標題 `# …`，接著每課為 `## Lesson {n}: {課名}` 與 Markdown 項目式大綱（已去除 HTML）。若存在內嵌 `__NEXT_DATA__` 則優先使用；否則課程大綱來自 JSON:API（`include=field_lessons`）。若無法取得大綱，**`download` 會以結束代碼 4 離開**，且不會再抓取課堂頁面。

自訂逐字稿路徑（僅單一課程；下載多門課時不可用）：

```bash
python -m bt download \
  "https://www.biblicaltraining.org/learn/institute/nt605-textual-criticism" \
  --out courses/nt605-textual-criticism/nt605-textual-criticism.md
```

安裝後也可使用主控台指令：

```bash
biblicaltraining-transcripts download "https://www.biblicaltraining.org/learn/institute/nt201-biblical-greek"
```

#### 課程索引（slug 前綴查詢用）

CLI 會維護本機**課程索引**，從 `https://www.biblicaltraining.org/classes` 抓取，快取於**使用者快取目錄**：

- macOS：`~/Library/Caches/bt-class-downloader/course_index.json`
- 其他：`~/.cache/bt-class-downloader/course_index.json`

啟動時若索引檔不存在會自動抓取。若要強制重新抓取：

```bash
python -m bt refresh-index
```

可檢視已快取的索引：

```bash
python -m bt list-index --limit 25
python -m bt search-index nt201
```

Slug 前綴查詢（如 `nt201`）必須**恰好**對應一個課程 slug；0 個或多個則指令失敗。

#### Cloudflare / 登入

若頁面回傳 Cloudflare 驗證或需登入，請使用 cookies（Playwright 匯出格式）與 `auto` 抓取器：

```bash
python -m bt download "COURSE_URL" --cookies-json /path/to/cookies.json --fetcher auto
```

#### `download` 選項

- `--fail-fast` — 第一個無法擷取逐字稿的課堂即停止
- `--fetcher playwright` — 一律使用真實瀏覽器（較慢，部分網站較穩）
- `--headless` — Playwright 以無頭模式執行（預設為有介面）

### `paragraph` — Gemini 分段（僅逐字稿）

使用 **`GEMINI_API_KEY`**。若環境變數未設定，CLI 會從**目前工作目錄**的 **`.env`** 載入（`python-dotenv`）；行為與下方 **`paragraph-outline`** 一致。請在專案目錄（或 `courses/` 與 `.env` 所在處）執行：

```bash
# 單一課（預設：courses/<slug>/paragraph/<model>/<slug>.lessonNN.paragraph.md）
python -m bt paragraph nt203-greek-tools-for-bible-study --lesson 3

python -m bt paragraph nt203 --lesson 3

# 全部課程（每課一次 Gemini 請求；一個合併檔：courses/<slug>/paragraph/<model>/<slug>.paragraph.md）
python -m bt paragraph nt203-greek-tools-for-bible-study

# 多門課（每門課預設路徑；勿使用 --transcript 或 --out）
python -m bt paragraph nt203 nt201
```

讀取 **`courses/<course-slug>/<course-slug>.md`**，擷取課程內文（僅 **`--lesson`** 指定一課，或省略時處理每個 `# Lesson N:` 區段），並**不**使用課程大綱呼叫 Gemini（每課一次請求）。系統提示要求模型為逐字稿分段且不更動用字、不為段落加標題；工具再將每課標題以 **`##`** 置於開頭（來自逐字稿的 `# Lesson N:`），並以課程 **`#`** 標題與**目錄**包裝，目錄會連結文件中**每一個** `##`–`######` 標題（依層級縮排），外層版面與 `paragraph-outline` 相同。

### `paragraph-outline` — Gemini 大綱分段

舊別名 **`paragraph-lesson`** 與此指令相同。

使用 **`GEMINI_API_KEY`**。若環境變數未設定，CLI 會從**目前工作目錄**的 **`.env`** 載入。請將金鑰放在 `.env`（已由 git 忽略）：

```bash
# .env（一行，除非值需要引號否則不要加引號）
GEMINI_API_KEY=your_key_here
```

**Shell 替代方式**（若不想用 `.env`）：

- **單次：** `export GEMINI_API_KEY=your_key_here` 後於同一終端機工作階段執行。
- **在 shell 載入 `.env`**（zsh/bash）：`set -a && source .env && set +a`（`.env` 須為 `KEY=value` 格式）。

請在專案目錄（或 `courses/` 與 `.env` 所在處）執行。**`paragraph-outline`** 需要逐字稿與大綱檔同在 **`courses/<slug>/`** 下：

```bash
# 單一課（預設：courses/<slug>/paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md）
python -m bt paragraph-outline nt203-greek-tools-for-bible-study --lesson 3

# 全部課程（每課一次 Gemini；一檔：courses/<slug>/paragraph-outlined/<model>/<slug>.paragraph-outlined.md）
python -m bt paragraph-outline nt203-greek-tools-for-bible-study

# slug 前綴亦可（須唯一）：
python -m bt paragraph-outline nt203 --lesson 3

# 多門課（勿使用 --transcript、--outline 或 --out）
python -m bt paragraph-outline nt203 nt201
```

讀取 **`courses/<course-slug>/<course-slug>.md`** 與 **`courses/<course-slug>/<course-slug>.outline.md`**，擷取每課的**逐字稿內文**與**大綱區段**（或僅 `--lesson` 指定的一課），再呼叫 Gemini。系統指示（見 `src/bt/lesson_paragraph.py`）要求模型分段、保留用字、將大綱內嵌為標題、不重複課名、大綱最淺層使用 **`###`**，且模型輸出中不使用 **`#`** / **`##`**。使用者訊息包含逐字稿與大綱文字。

輸出檔中的課名為**二級標題**（`##`）；工具會正規化標題層級，使模型內文最淺為 **`###`**。

**輸出：** **Markdown**（`.md`）。檔案以**課程標題**為**一級標題**（`#`，取自逐字稿第一個非課程的 `# …` 行，若無則由 slug 推導），接著 **`## Table of contents`**，以縮排清單連結合併後文件內**每一個** `##`–`######` 標題（不限課名），水平線後為內文。連結錨點採 GitHub 風格；相同標題文字重複時會加上數字後綴。

預設路徑：有 **`--lesson`** 時為 **`courses/<slug>/paragraph-outlined/<model>/<slug>.lessonNN.paragraph-outlined.md`**；無則為 **`courses/<slug>/paragraph-outlined/<model>/<slug>.paragraph-outlined.md`**。此處 ``<model>`` 為經檔名安全處理後的 Gemini 模型 id。每課一次 Gemini 請求。每課區塊對應逐字稿的 `## Lesson N: …`（由 `# Lesson N: …` 提升），接著為大綱分段內文。

**單一**課程可用 **`--out 路徑`** 覆寫輸出檔（**無**副檔名時會自動加上 **`.md`**）。**多門**課時請省略 **`--out`**（並省略 **`--transcript`** / **`--outline`**）。可用 **`--transcript`** / **`--outline`** 覆寫輸入，**`--model`** 指定模型（預設 **`gemini-3.1-flash-lite-preview`**）。若有課程失敗（缺逐字稿或大綱、或 Gemini 錯誤），指令會在非零結束碼下仍盡可能處理其餘內容；合併檔會略過失敗的課。

**`study-note-zh`**（繁體中文）與 **`study-note-cn`**（簡體中文）使用與 **`paragraph-outline`** 相同的逐字稿 + 大綱輸入與 **`GEMINI_API_KEY`**，但產出學習指南式說明 Markdown，位於 **`courses/<slug>/study-note-zh/…`** 或 **`courses/<slug>/study-note-cn/…`**（見**輸出配置**）。模型會輸出簡短大綱對照引言區塊，以及 HTML 註解（`study-note-zh-h2` / `study-note-cn-h2`；舊版 `explain-zh-h2` / `explain-cn-h2` 仍相容）供工具產生雙語 **`##`** 課名；提示詞要求聖經用語優先採**改革宗／歸正神學**慣用中文。範例：`python -m bt study-note-cn nt203 --lesson 1`。命令 **`explain-zh`** / **`explain-cn`** 為棄用別名。

## 運作方式

1. **`download`：** 抓取**課程**頁面並收集課堂連結。從內嵌 JSON 或 JSON:API 解析課程大綱；若失敗，指令在尚未下載課堂逐字稿前即停止（結束代碼 **4**）。
2. 抓取每個課堂頁面，將 **Transcription** 區段擷取為純文字。
3. 將逐字稿與大綱寫入 **`courses/<course-slug>/`**（平鋪：`<slug>.md` 與 `<slug>.outline.md`），含**課程標題**（來自課程頁）、**目錄**，以及每課 `# Lesson {n}: {title}`。

## 輸出配置

路徑均在 **`courses/<course-slug>/`** 下。Gemini 輸出含經檔名安全處理的 **`/<model>/`** 目錄段。

| 類型 | 預設路徑 |
|------|----------------|
| 課程逐字稿 | `courses/<course-slug>/<course-slug>.md` |
| 課程大綱 | `courses/<course-slug>/<course-slug>.outline.md` |
| 分段單課（Gemini，僅逐字稿，`--lesson`） | `courses/<course-slug>/paragraph/<model>/<course-slug>.lessonNN.paragraph.md` |
| 分段整課（Gemini，僅逐字稿，全部課） | `courses/<course-slug>/paragraph/<model>/<course-slug>.paragraph.md` |
| 大綱分段單課（Gemini，`--lesson`） | `courses/<course-slug>/paragraph-outlined/<model>/<course-slug>.lessonNN.paragraph-outlined.md` |
| 大綱分段整課（Gemini，全部課） | `courses/<course-slug>/paragraph-outlined/<model>/<course-slug>.paragraph-outlined.md` |
| 中文學習筆記單課，繁體（`study-note-zh`，`--lesson`） | `courses/<course-slug>/study-note-zh/<model>/<course-slug>.lessonNN.zh.md` |
| 中文學習筆記整課，繁體（`study-note-zh`，全部課） | `courses/<course-slug>/study-note-zh/<model>/<course-slug>.zh.md` |
| 中文學習筆記單課，簡體（`study-note-cn`，`--lesson`） | `courses/<course-slug>/study-note-cn/<model>/<course-slug>.lessonNN.cn.md` |
| 中文學習筆記整課，簡體（`study-note-cn`，全部課） | `courses/<course-slug>/study-note-cn/<model>/<course-slug>.cn.md` |
| 中文翻譯單課，繁體（`translate-zh`，`--lesson`） | `courses/<course-slug>/translate-zh/<model>/<course-slug>.lessonNN.zh.md` |
| 中文翻譯整課，繁體（`translate-zh`，全部課） | `courses/<course-slug>/translate-zh/<model>/<course-slug>.zh.md` |
| 中文翻譯單課，簡體（`translate-cn`，`--lesson`） | `courses/<course-slug>/translate-cn/<model>/<course-slug>.lessonNN.cn.md` |
| 中文翻譯整課，簡體（`translate-cn`，全部課） | `courses/<course-slug>/translate-cn/<model>/<course-slug>.cn.md` |

### 從 `data/` 遷移

若您仍有舊版 **`data/transcripts/`**、**`data/outlines/`** 與 **`data/<command>/<model>/…`** 目錄，可按上文遷移，例如：

- `data/transcripts/<slug>.md` → `courses/<slug>/<slug>.md`
- `data/outlines/<slug>.outline.md` → `courses/<slug>/<slug>.outline.md`
- `data/paragraph/<model>/…` → `courses/<slug>/paragraph/<model>/…`（檔名不變）；`paragraph-outlined`、`study-note-zh`、`study-note-cn`、`translate-zh`、`translate-cn` 同理（舊目錄 `explain-zh` / `explain-cn` 請改名為 `study-note-zh` / `study-note-cn`）。

## 備註

- 請遵守 BiblicalTraining 使用條款；本工具適用於個人研讀／無障礙用途之公開逐字稿副本。
- 部分課堂版面不同；若擷取失敗，可嘗試 `--fetcher playwright` 或提供 cookies。
- 可安裝的 Python 套件在 PyPI 上名為 **`biblicaltraining-class-transcripts`**；儲存庫目錄常為 **`bt-class-downloader`**。CLI 模組為 **`bt`**（`python -m bt`，主控台指令 **`bt`** 與 **`biblicaltraining-transcripts`**）。

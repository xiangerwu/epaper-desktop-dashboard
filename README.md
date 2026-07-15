# epaper-desktop-dashboard

把電腦上的即時資料整理成一頁高對比電子紙看板。FastAPI 定時收集資料、SQLite 保留最後一次成功值、Jinja2 即時輸出 HTML；電子閱讀器只要用 kiosk 瀏覽器開啟網頁。

實機環境：**HyRead Gaze Note Plus**、1404×1872、Android 11、Fully Kiosk。

樹莓派佈署（含複製金鑰、Claude/Codex 登入、Tailscale 連閱讀器）見 [PI_DEPLOY.md](PI_DEPLOY.md)。

![看板預覽](docs/preview.png)

## 功能

- 天氣與空氣品質：中央氣象署 CWA、環境部 MOENV。
- AI 額度：Claude Code、Codex CLI 的本機登入資訊。
- Steam 狀態：等級、成就、徽章、近期遊玩時數。
- 作息區：時段提示、50 分鐘番茄鐘、依狀態切換的桌寵與對話氣泡。
- 斷線降級：單一來源失敗時保留舊快取，不清空整個畫面。
- 裝置控制：ADB 喚醒、開啟看板、刷新與真機截圖。
- Windows 桌面模式：系統匣常駐服務與預覽視窗。

## 快速開始（Windows PowerShell）

需要 Python 3.11 以上。

```powershell
cd D:\Project\for_pi
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.main
```

開啟：

- 看板：<http://localhost:8000/>
- 健康狀態：<http://localhost:8000/health>

主埠被占用時會改用 `.env` 的 `FALLBACK_PORTS`。裝置網址與 ADB reverse 必須跟著改成實際埠號。

### 最少設定

編輯 `.env`。沒有金鑰的來源可以暫時留空，服務仍會啟動，對應卡片顯示無資料或最後一次成功值。

| 功能 | 設定 |
|------|------|
| 天氣 | `CWA_API_KEY`、`CWA_LOCATION` |
| AQI | `MOENV_API_KEY`、`AQI_SITE`、`AQI_COUNTY` |
| Steam | `STEAM_API_KEY`、`STEAM_ID` |
| Claude | 自動讀取 `~/.claude/.credentials.json` |
| Codex | 自動讀取 `~/.codex/auth.json` |

完整設定與註解見 [.env.example](.env.example)。

### Windows 系統匣模式

雙擊 `run_app.bat`，或執行：

```powershell
.\.venv\Scripts\python.exe -m app.desktop
```

## 顯示到電子閱讀器

### USB：最短路徑

1. 開啟電子閱讀器的 USB 偵錯並接上電腦。
2. Fully Kiosk 的 Start URL 設成 `http://localhost:8000/`。
3. `.env` 設定：

```ini
DASHBOARD_URL=http://localhost:8000/
DEVICE_BROWSER_COMPONENT=de.ozerov.fully/.MainActivity
```

4. 建立反向連接並刷新：

```powershell
.\adb\adb.exe devices -l
.\adb\adb.exe reverse tcp:8000 tcp:8000
.\.venv\Scripts\python.exe -m app.device.adb refresh
.\.venv\Scripts\python.exe -m app.device.adb screencap data\device_screen.png
```

最後一行取得的 **1872×1404 橫向真機截圖**才是版面驗證依據；不要只看 PC 瀏覽器。

### Wi-Fi 與開機自啟

要脫離 USB，將 Fully Start URL 與 `DASHBOARD_URL` 改成主機區網 IP。systemd、Wi-Fi ADB、Fully Kiosk 設定見 [DEPLOY.md](DEPLOY.md)。

## 常用操作

| 目的 | 指令 |
|------|------|
| 啟動服務 | `.\.venv\Scripts\python.exe -m app.main` |
| 啟動桌面模式 | `.\.venv\Scripts\python.exe -m app.desktop` |
| 確認 ADB | `.\.venv\Scripts\python.exe -m app.device.adb devices` |
| 刷新裝置 | `.\.venv\Scripts\python.exe -m app.device.adb refresh` |
| 真機截圖 | `.\.venv\Scripts\python.exe -m app.device.adb screencap data\device_screen.png` |
| Gate tests | `.\.venv\Scripts\python.exe -m unittest tests.test_gate` |
| Dashboard eval | `.\.venv\Scripts\python.exe -m evals.pet_dashboard` |
| 真機 eval | `.\.venv\Scripts\python.exe -m evals.device_screen` |

## 資料更新節奏

| 來源 | 更新時間 |
|------|----------|
| 天氣、AQI | 每小時整點 |
| Steam | 每小時 `:00`、`:30` |
| Claude、Codex、作息提示 | 每 10 分鐘 |

服務啟動時會並行收集一次。`GET /` 只渲染現有快取；`/refresh` 才會重新執行 collectors。

## 架構

```text
app/collectors/* ──fetch──> SQLite cache ──> view-model ──> Jinja2 live HTML
                                                              │
FastAPI  /  /health  /refresh              ADB <──────────────┘
```

| 路徑 | 職責 |
|------|------|
| `app/collectors/` | 各資料來源與更新週期 |
| `app/cache.py` | SQLite 最後成功值 |
| `app/render/` | view-model、模板與 HTML |
| `app/net.py` | 共用 httpx 與 CWA 憑證相容設定 |
| `app/scheduler.py` | cron、interval 與選用 ADB 刷新工作 |
| `app/device/adb.py` | 裝置連線、喚醒、重載與截圖 |
| `app/main.py` | FastAPI app、啟動收集與備用埠 |

## 操作注意

- 不會自動刷新 Claude / Codex OAuth token，避免輪換失敗破壞 CLI 登入。
- `.env`、`data/`、`adb/` 不進版控。
- 電子閱讀器若使用備用埠，Fully URL、`DASHBOARD_URL`、ADB reverse 三處都要一致。
- e-ink 版面使用純黑白、高對比、粗框與相對尺寸；修改後應重新抓真機截圖。

## 延伸文件

- [GUIDE.md](GUIDE.md)：完整操作手冊與資料來源說明。
- [DEPLOY.md](DEPLOY.md)：常駐主機、systemd、Wi-Fi ADB、Fully Kiosk。
- [AGENTS.md](AGENTS.md)：架構慣例、擴充方式與已知地雷。

## 規劃中：番茄鐘音效（隨機播放，未實作）

目標：番茄鐘「開始」與進入「喝水休息（end）」時，各自從一個資料夾裡**隨機**挑一個音效播放。丟檔進資料夾即可新增，不用改程式。以下為設計規劃，尚未實作。

> **自備素材（版權）**：音效檔有版權，本專案**不附**，也不進版控——請自行放入下列資料夾。同理，桌寵圖片（`pet/*.webp`）也為使用者自備，需自行提供。

### 資料夾

```text
pet/sound/start/     # 番茄鐘開始音效（可放多個，檔名不限）
pet/sound/end/       # 喝水休息音效（可放多個，檔名不限）
```

資料夾結構進版控（含 `.gitkeep`），但底下的音檔（`*.wav` / `*.mp3` / `*.ogg`）已加入 `.gitignore`，不會被提交。

### 後端

- 掛靜態：讓 `pet/sound/` 可經 HTTP 取用（`/pet/sound/...`）。
- 清單路由：`GET /pet/sound/{kind}/list` 掃該資料夾回檔案 URL 陣列，例 `["/pet/sound/start/a.wav", ...]`。
  - `kind` 只允許 `start` / `end`（白名單，擋路徑穿越）。
  - 只列 `.wav` / `.mp3` / `.ogg`；空資料夾回 `[]`。

### 前端（番茄鐘 JS）

- 頁面載入時對兩個 `kind` 各抓一次清單，建 `<audio preload="auto">` **全部預載**（音效小，觸發即時）。
- 觸發：按「開始」→ 從 start 清單隨機挑一個播；tick 跨進第 5 段（喝水休息）→ 從 end 清單隨機挑一個播。
- 隨機：`arr[Math.floor(Math.random() * arr.length)]`；清單空則靜默略過。

### 跨整頁重載一致（關鍵）

看板每 600 秒整頁 `meta refresh`，段長也是 600 秒。用 `localStorage` 存 `pomo_last_seg`：每次 tick 由 `pomo_start` 算出目前第幾段，只要「目前段 > 已播段」且該段有音效就播並更新。比對段編號而非精確瞬間，重載後不漏播、也不重播，保證每個段界只響一次。

### 需要的設定

- Fully → Web Content Settings → **Autoplay Audio 開**（休息音非使用者手勢觸發，否則被瀏覽器擋）。開始音是按鈕手勢觸發，不受影響。
- 裝置媒體音量 > 0。

### 限制

- 音效控制在 < 200 KB（`wav` 為無壓縮，宜短、低取樣率；或改用 `ogg` / 低位元率 `mp3`），預載全部也無感。
- WiFi 斷線時退化為「沒聲音」，不影響看板顯示。

## 現況

已完成 live HTML、CWA、AQI、Claude、Codex、Steam、番茄鐘、桌寵、Fully Kiosk 與 ADB 真機流程。

待辦：脫離 USB、Fully 鎖定與開機自啟、e-ink full-refresh 廣播、跨機憑證同步、番茄鐘隨機音效（見上方規劃），以及預留的 Notion / 一般 DB connector。

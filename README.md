# epaper-desktop-dashboard

把電腦上的即時資料整理成一頁高對比電子紙看板。FastAPI 定時收集資料、SQLite 保留最後一次成功值、Jinja2 即時輸出 HTML；電子閱讀器只要用 kiosk 瀏覽器開啟網頁。

實機環境：**HyRead Gaze Note Plus**、1404×1872、Android 11、Fully Kiosk。

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

## 現況

已完成 live HTML、CWA、AQI、Claude、Codex、Steam、番茄鐘、桌寵、Fully Kiosk 與 ADB 真機流程。

待辦：脫離 USB、Fully 鎖定與開機自啟、e-ink full-refresh 廣播、跨機憑證同步，以及預留的 Notion / 一般 DB connector。

# AGENTS.md — 給 AI 協作者的說明書

此檔給 Claude Code / Codex 等 AI 代理閱讀,說明本專案的架構、慣例、擴充方式與地雷。
人用的操作手冊在 [GUIDE.md](GUIDE.md)。CLAUDE.md 指向本檔。

## 這是什麼

樹莓派桌面電子紙看板。FastAPI 定時抓資料 → 存 SQLite 快取 → 用 Jinja2 吐 **live HTML** →
**HyRead Gaze Note Plus**(1404×1872 e-ink,Android 11)的 **Fully Kiosk** 全螢幕顯示。
Pi/PC 用 **ADB** 控制裝置(喚醒 / 重載 / 截圖)。**刻意不產圖**(無 Playwright/Chromium)。

## 架構與資料流

```
app/collectors/*  ──fetch()──►  app/cache.py (SQLite)  ──►  app/render/view.py  ──►  html.py (Jinja2)
      (每 600s,APScheduler)          最後一次成功值            組 view-model         live HTML 字串
                                                                                          │
app/main.py (FastAPI):  GET /  即時渲染   ·   GET /health   ·   app/device/adb.py 控制裝置 ◄┘
```

三層解耦是核心設計:**收集**、**渲染**、**顯示**互不阻塞。單一來源失敗不可清空畫面。

## 模組地圖

| 檔案 | 職責 |
|------|------|
| `app/config.py` | 從 `.env` 讀設定(`load_dotenv` 在 import 時執行);常數與 `Settings` |
| `app/net.py` | 共用 httpx client。**放寬 Py3.14 的 `VERIFY_X509_STRICT`**,否則 CWA 憑證會被擋 |
| `app/cache.py` | SQLite 存 `{source: (json_payload, updated_at)}`;`put/get`,`get` 附 `age_seconds` |
| `app/collectors/base.py` | `Collector` ABC:`source`、`interval_seconds`、`fetch()`;`run()` 吞例外保留舊快取 |
| `app/collectors/*.py` | 各來源:weather / anthropic_usage / codex_usage / openrouter |
| `app/collectors/__init__.py` | `COLLECTORS` 清單;OpenRouter 只在有金鑰時註冊 |
| `app/render/view.py` | 讀快取組 view-model(天氣 + `ai_columns`) |
| `app/render/html.py` | view-model → Jinja2 → HTML 字串 |
| `app/render/templates/dashboard.html.j2` | e-ink 版面(vw 相對單位;兩格 AI) |
| `app/scheduler.py` | APScheduler:各 collector 依自己節奏 +(選)ADB 刷新 job |
| `app/device/adb.py` | ADB 封裝:connect/open/refresh/wake/screencap;CLI 入口 |
| `app/main.py` | FastAPI app + lifespan(啟動先抓一輪)+ 備用埠選擇 |

## 慣例

- **新增資料來源**:在 `app/collectors/` 建一個 `Collector` 子類,實作 `async fetch() -> dict`
  回傳可 JSON 序列化的 dict,設 `source`(cache key / job id)與 `interval_seconds`。
  在 `collectors/__init__.py` 的 `COLLECTORS` 註冊。**失敗就 raise**,`base.run()` 會處理降級。
- **AI 額度格式**:collector 回 `{"lines": [{"label","pct","detail"}, ...]}`;`view.build` 攤平進 `ai_columns`。
- **對外 HTTP**:一律用 `app.net.client()`(帶放寬後的 SSL context),不要自己 `httpx.get`。
- **時間**:一律轉本地時區顯示(`.astimezone()`)。注意各家 reset 格式不同(見地雷)。
- **e-ink 版面**:純黑白高對比、粗線、大字、無漸層;尺寸用 `vw`(裝置 2x → CSS 寬約 702px)。
- **秘密**:只進 `.env`(已 gitignore);`./adb/`(Windows 二進位)與 `data/` 也已忽略。

## 地雷(踩過的真 bug)

1. **Jinja 屬性撞內建方法**:`weather.today.pop` 會取到 dict 的 `pop()` 方法印空白。
   凡 key 名與 dict 方法同名(pop/items/keys...)用中括號:`weather['pop']`。
2. **Py3.14 SSL 太嚴**:預設 `VERIFY_X509_STRICT` 擋掉缺 SKI 的 CWA 憑證。
   `app/net.py` 已清該 flag(仍驗 CA 信任鏈)。別繞回去用裸 httpx。
3. **reset 時間格式不一**:Claude `resets_at` 是 ISO 字串;Codex `reset_at` 是 **Unix epoch 秒**。
   各自的 collector 有對應解析,別混用。
4. **CLI 不載 .env**:`python -m app.device.adb` 需 `from ..config import ROOT` 觸發 `load_dotenv`,
   否則讀不到 `ADB_BINARY` 等。
5. **Android 11 file:// 限制**:曾想推圖用 `file://` intent,被 FileUriExposure 擋 → 已改 live HTML 網頁路線。
6. **Fully 埠綁定**:裝置端 URL 是寫死的埠;若伺服器用了備用埠,Fully Start URL 要一起改。

## 不要做

- **不要自動 refresh Claude/Codex 的 OAuth token**。refresh 會輪換 token,寫回失誤會弄壞使用者
  正在用的 Claude Code / Codex CLI 登入。過期就顯示舊值,由使用者在該機重新登入。
- **不要 commit** 二進位(`./adb/`)、`data/`、`.env`、model 權重。
- **不要重新引入 Playwright/Pillow**(已刻意移除以省 Pi 資源);顯示走網頁,不產圖。
- **不要批次刪檔**(見使用者全域規則);一次刪一個明確路徑。

## 常用指令

```bash
# 開發機(Windows)用 venv 內的 python
.venv/Scripts/python -m app.main                    # 起服務(自動選可用埠)
.venv/Scripts/python -m app.device.adb screencap data/device_screen.png   # 驗證裝置畫面
# 單獨測某來源解析:
.venv/Scripts/python -c "import asyncio;from app.collectors.weather import WeatherCollector;print(asyncio.run(WeatherCollector().fetch()))"
curl -s http://localhost:8000/health                 # 各來源快取是否有值
```

驗證裝置顯示的正解:`app/device/adb.py screencap` 抓回真機畫面看,別只信本機瀏覽器預覽。

## 目標裝置

HyRead Gaze Note Plus:`model K08P`、`rk3566_eink`、Android 11 / SDK 30、
1404×1872 @ density 320(DPR 2.0)、RAM 2.8G。細節見 `device_info.json`。

## 現況與待辦

已完成:天氣(CWA)、Claude 額度、Codex 額度、live HTML、Fully Kiosk 滿版(實機驗證)、
ADB 控制、備用埠、全站 10 分更新。
未完成:脫離 USB(改區網 IP / Pi 部署)、Fully 鎖定與開機自啟、e-ink full-refresh 廣播、
Pi 端 token 同步、OpenRouter(待金鑰)、預留的 Notion / 一般 DB connector。

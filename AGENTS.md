# AGENTS.md — 給 AI 協作者的說明書

此檔給 Claude Code / Codex 等 AI 代理閱讀,說明本專案的架構、慣例、擴充方式與地雷。
人用的操作手冊在 [GUIDE.md](GUIDE.md)。CLAUDE.md 指向本檔。

## 這是什麼

一個後端程式。FastAPI 定時抓資料 → 存 SQLite 快取 → 用 Jinja2 吐 **live HTML**,
電子閱讀器上的 app 開網頁即可顯示(實機 **HyRead Gaze Note Plus**,1404×1872 e-ink,Android 11,
用 **Fully Kiosk** 全螢幕)。主機用 **ADB** 控制電子閱讀器(喚醒 / 重載 / 截圖)。
顯示走網頁,無 Playwright/Chromium。

## 架構與資料流

```
app/collectors/*  ──fetch()──►  app/cache.py (SQLite)  ──►  app/render/view.py  ──►  html.py (Jinja2)
 (整點 cron / 每 600s)               最後一次成功值            組 view-model         live HTML 字串
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
| `app/collectors/*.py` | 各來源:weather / air / anthropic_usage / codex_usage / routine / steam / stocks;openrouter 保留 |
| `app/holdings.py` | 持股設定 `data/holdings.json` 存讀(原子寫入)、驗證、盤中判斷、卡片總覽計算 |
| `app/funds.py` | 基金設定 `data/funds.json` 存讀、驗證、卡片總覽計算(淨值 × 單位數 × 臺銀即期買入) |
| `app/collectors/__init__.py` | `COLLECTORS` 清單;OpenRouter 目前不註冊 |
| `app/render/view.py` | 讀快取組 view-model(天氣、AQI、AI 額度、Steam、左下作息卡) |
| `app/render/html.py` | view-model → Jinja2 → HTML 字串 |
| `app/render/templates/dashboard.html.j2` | e-ink 版面(vmin 相對單位;左欄 天氣＋作息卡、右欄 AI 額度＋Steam) |
| `app/scheduler.py` | APScheduler:天氣/AQI 整點 cron;Claude/Codex/作息 600s interval +(選)ADB 刷新 job |
| `app/device/adb.py` | ADB 封裝:connect/open/refresh/wake/screencap;CLI 入口 |
| `app/main.py` | FastAPI app + lifespan(啟動先抓一輪)+ 備用埠選擇;`/settings`、`/api/holdings`、`/api/snapshot`、`/settings/funds`、`/api/funds*`(僅內網/Tailscale) |

## 慣例

- **新增資料來源**:在 `app/collectors/` 建一個 `Collector` 子類,實作 `async fetch() -> dict`
  回傳可 JSON 序列化的 dict,設 `source`(cache key / job id)與 `interval_seconds`。
  在 `collectors/__init__.py` 的 `COLLECTORS` 註冊。**失敗就 raise**,`base.run()` 會處理降級。
- **AI 額度格式**:collector 回 `{"lines": [{"label","pct","detail"}, ...]}`;`view.build` 攤平進 `ai_columns`。
- **對外 HTTP**:一律用 `app.net.client()`(帶放寬後的 SSL context),不要自己 `httpx.get`。
- **時間**:一律轉本地時區顯示(`.astimezone()`)。注意各家 reset 格式不同(見地雷)。
- **排程**:天氣與 AQI 的 `cron_minute=0`;Claude、Codex、作息的 `interval_seconds=600`。
  interval job 不可設 `next_run_time=None`,那代表永久暫停,不是「首抓已完成」。
- **作息循環**:09–12、13–18、19–22 是三個獨立工作段;每段/換日重置。
  第 1–3 次更新顯示專注倒數,第 4 次提醒喝水伸展 5 分鐘,下一次回第 1 次。
  `/refresh` 會跑 collectors,所以手動刷新也會推進;單純 GET `/` 或 ADB 重載不會。
- **e-ink 版面**:純黑白高對比、粗線、大字、無漸層;尺寸用 `vw`(裝置 2x → CSS 寬約 702px)。
- **持股卡片**:卡片數字 = 目前 `holdings.json` 股數 × 快取最新報價,於渲染時算(`holdings.summarize`);
  collector 只負責報價。右下格位 Steam ↔ 持股輪播是頁面 JS,間隔取 `display.rotate_seconds`。
  卡片沿用 Steam 卡片的 class(`.card.steam`、`.steam-cols`、`.steam-stat`),別另寫一套框線/虛線。
- **基金卡片**:同上模式,輪播順序 Steam → 股票 → 基金(不存在的卡片跳過)。排程 `cron_hour="8,21"`、
  `cron_minute=30`(base 支援 `cron_hour`)。設定頁用 FundClear 搜尋加入,存 `fundclear_code`+`site`+`isin`。
- **農民曆宜忌**:`collectors/almanac.py` 爬好日網(goodaytw.com)**首頁**的今日宜忌,顯示在股票卡左欄。
  robots.txt 禁止日期頁 `/20*-*-*`,只能抓首頁;一天 00:05/06:05/12:05(後兩次是重試)。頁面日期 ≠ 今天
  就不採用,看板也只顯示 date == 今天的資料。解析前先移除 `<style>`(MUI SSR 會把 style 插在標籤與內容之間),
  只取日期標頭後第一組(頁面後段有各時辰宜忌)。
- **今日電網**:`collectors/power.py` 每 10 分鐘抓台電開放資料(data.gov.tw/dataset/8931)各類型「小計」列,
  基金卡左欄每次渲染隨機顯示一種(佔全台 %、MW、資料時間)。開放資料實測會停更數小時,所以一定要顯示時間。
  不要算「發電量/裝置容量」:小計列兩者統計範圍不同(燃氣 106%、汽電共生 294%)。台電官網 genary.json 會擋爬蟲。
- **輪播隱藏按鈕**:點右下卡片標題左側 LOGO(`h2 .ttl .ic`)立即切到下一張並重新計時,外觀刻意不變。
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
7. **APScheduler 暫停語意**:`add_job(..., next_run_time=None)` 會建立暫停 job,之後永遠不跑。
   啟動首抓由 lifespan 負責;interval job 省略該參數,讓 APScheduler 排定下一次執行。
8. **`<meta http-equiv="refresh">` 會盲目導覽**:到點若網路/伺服器剛好斷線,WebView 會停在
   系統錯誤頁,該頁沒有 meta refresh,之後永遠不再自動刷新——裝置端症狀是「放久了不再跟著
   循環更新、e-ink 殘影疊出破版」。已改成 `dashboard.html.j2` 內的 JS:到點先
   `fetch("/health")` 探活,成功才 `location.reload()`,失敗每 30 秒重試並留在目前完整頁面上。
   別再改回單純 meta refresh。

9. **TWSE MIS 的 `z`(成交價)常是 `"-"`**:13:25–13:30 集合競價、或最近一筆沒成交時。
   `collectors/stocks.py` 依序退回 `pz` → `trade.z` → 買賣一檔中價。代號前綴不知道上市或上櫃,
   每檔同時送 `tse_` 與 `otc_`,無效的會回 `c` 為空字串的空殼,要略過。
   TWSE OpenAPI `STOCK_DAY_ALL` 實測落後數個交易日,不適合當「收盤校正」。
10. **FundClear 不接受 ISIN 查詢**:淨值 API(`/api/{onshore|offshore}/nav-profit/query-five-dates`)
    只認它自己的基金代碼(境內如 `18480065`、境外如 `BLKTEAMA`)當 `searchName`。`oneDate` 是最新
    (= `dateList[-1]`),值可能帶千分位逗號或是 `-`。ISIN 只能從 `query-details` 反查。
    這是無公開文件的前端 API,改版時先看 `collectors/funds.py` 的註解重新驗證。
11. **臺銀匯率 CSV 會擋預設 UA**:不帶瀏覽器 User-Agent + `Accept-Language` 時回機器人驗證頁
    (HTTP 200、HTML)。collector 以 content-type 判斷,非 CSV 就當失敗、沿用上次匯率。
12. **設定頁打字時別重建輸入框**:`settings.html.j2` / `funds.html.j2` 的 `render()` 只在列數改變時
    重建 DOM,打字走 `refresh()` 就地更新錯誤訊息。`type=number` 讀不到也設不回游標位置,
    整列 innerHTML 重建會讓游標跳回開頭、焦點被搶回(使用者回報過)。
13. **dashboard 模板改 CSS 時小心 `</style>`**:少了結尾標籤,整個 body 會被當成樣式文字,
    畫面全白但 HTML 看起來正常。改完用 headless 截圖確認。

## 不要做

- **Claude token refresh 預設關,靠旗標開**。`CLAUDE_TOKEN_REFRESH=true` 時,Claude collector
  才會用 refreshToken 換新並「防禦性寫回」`.credentials.json`(重讀最新檔、只換 accessToken/
  refreshToken/expiresAt、原子替換)。只在派這種「唯一持有憑證、沒跑互動 CLI」的機器開;
  dev PC 別開(refresh 會作廢舊 refreshToken,和互動 CLI 的輪換打架)。旗標關就維持舊行為:
  過期即 raise、顯示舊值,由使用者重新登入。**Codex token 目前仍不 refresh**。
- **不要 commit** 二進位(`./adb/`)、`data/`、`.env`、model 權重。
- **不要重新引入 Playwright/Pillow**(已刻意移除以維持輕量);顯示走網頁。
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

已完成:天氣(CWA)、AQI(MOENV)、Claude 額度、Codex 額度、本機作息提醒、台股持股卡片、基金卡片(與 Steam 輪播)、live HTML、
Fully Kiosk 滿版(實機驗證)、ADB 控制、備用埠、分來源排程。
未完成:脫離 USB(改用主機區網 IP)、Fully 鎖定與開機自啟、e-ink full-refresh 廣播、
跨機 token 同步、OpenRouter(待金鑰)、預留的 Notion / 一般 DB connector。

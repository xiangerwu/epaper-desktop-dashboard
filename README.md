# pi-eink-dashboard

樹莓派上跑的桌面資訊看板。把天氣 / AQI / AI 額度 / 作息提醒定時更新,
以 **live HTML** 供 **HyRead Gaze Note Plus**(7.8" e-ink,1404×1872,Android 11)
瀏覽器顯示。Pi 透過 **ADB** 控制裝置刷新(喚醒 + 重載 + e-ink full refresh)。

不產圖:FastAPI 直接吐 HTML,省磁碟與記憶體(無需 Chromium)。

## 架構

```
資料源(API/爬蟲) → 收集層(定時) → SQLite 快取 → live HTML(/) → 裝置瀏覽器顯示
                                                            ↑
                                              Pi 用 ADB 定時叫裝置刷新
```

三層獨立:任一資料源失敗,渲染讀舊快取續畫,只標精簡資料年齡,畫面不空白。
啟動時各來源並行抓取,不讓單一逾時串行拖慢整體啟動。天氣與 AQI 每小時整點抓取;
Claude、Codex 與本機作息提醒每 10 分鐘更新。

- `app/collectors/` 各來源收集器(各依自己節奏抓,寫入快取)
- `app/render/` view-model(`view.py`)→ Jinja2 模板 → HTML 字串(`html.py`)
- `app/net.py` 共用 httpx(放寬 Py3.14 過嚴的 X509 strict,CWA 憑證才過)
- `app/scheduler.py` APScheduler:整點 cron 與 10 分鐘 interval job(+ 選用 ADB 刷新 job)
- `app/device/adb.py` ADB 控制:connect / open / refresh / wake / screencap
- `app/main.py` FastAPI:`/`(看板)、`/health`

## 開發(先在 PC 上測)

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# bash:               source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # 填 CWA_API_KEY、CWA_LOCATION
python -m app.main
```

開 http://localhost:8000/ 看看板。`/health` 保留頂層 `ok`,各啟用來源另回報
`available`、`age_seconds`、`stale`;超過兩倍收集週期才算 stale。

Windows 要背景常駐 + 系統匣預覽視窗:雙擊 `run_app.bat`(或 `python -m app.desktop`),
見 [GUIDE.md](GUIDE.md) §6.5。

## 驗證

```powershell
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python -m evals.device_screen  # 需連上真機;驗證 PNG 與 1404×1872
```

## 部署到 Pi 5 + 裝置設定

見 [DEPLOY.md](DEPLOY.md):systemd 開機自啟、ADB 安裝與裝置配對、kiosk 瀏覽器、
以及「Pi 定時用 ADB 叫裝置刷新」的開啟方式。

## 建置進度

- [x] Phase 1:骨架 + 假資料,打通「Pi 出頁 → 裝置顯示」
- [x] Phase 2:天氣接真來源(CWA F-C0032-001),實測 200 + 真資料上頁
- [x] 架構轉為 live HTML(移除產圖 / Playwright / Pillow)
- [x] ADB 控制層(connect/open/refresh/wake/screencap);**已在實機 K08P 驗證**
- [x] Claude / Codex 額度皆實測真資料;參考 openusage。OpenRouter 程式保留但不啟用
- [x] 右側本機作息提醒卡:日常時段 + 4 次更新/40 分鐘工作循環
- [x] 天氣 / AQI 每小時整點更新;Claude / Codex / 作息每 10 分鐘更新
- [x] 裝置全螢幕:Fully Kiosk 已裝並設定,實機驗證滿版(無系統列/工具列/網址列)
- [ ] 脫離 USB:改用 Pi 或 PC 區網 IP,裝置走 WiFi(目前 localhost + adb reverse 是 USB 綁定)
- [ ] Phase 4:Fully 鎖定/開機自啟 + e-ink full refresh 廣播 + Pi 端憑證方案
- [ ] 預留:Notion / 一般 DB connector(目前不啟用)

作息提醒只讀本機時間與 SQLite 快取狀態,不串接 Apple 行事曆、健康資料或 iCloud。

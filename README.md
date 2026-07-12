# pi-eink-dashboard

樹莓派上跑的桌面資訊看板。把 AI 額度 / 天氣 / 日曆等資料定時更新,
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
啟動時各來源並行抓取,不讓單一逾時串行拖慢整體啟動。

- `app/collectors/` 各來源收集器(各依自己節奏抓,寫入快取)
- `app/render/` view-model(`view.py`)→ Jinja2 模板 → HTML 字串(`html.py`)
- `app/net.py` 共用 httpx(放寬 Py3.14 過嚴的 X509 strict,CWA 憑證才過)
- `app/scheduler.py` APScheduler:收集 job(+ 選用 ADB 刷新 job)
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
- [x] AI 額度兩格(左 Claude / 右 Codex),皆實測真資料;參考 openusage。OpenRouter 程式保留但不啟用
- [x] UI 縮小、移除今日行程、全站 10 分鐘更新
- [x] 裝置全螢幕:Fully Kiosk 已裝並設定,實機驗證滿版(無系統列/工具列/網址列)
- [ ] 脫離 USB:改用 Pi 或 PC 區網 IP,裝置走 WiFi(目前 localhost + adb reverse 是 USB 綁定)
- [ ] Phase 4:Fully 鎖定/開機自啟 + e-ink full refresh 廣播 + Pi 端憑證方案
- [ ] 預留:Notion / 一般 DB connector(目前不啟用)

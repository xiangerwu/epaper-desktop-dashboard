# 完全使用指南 — epaper-desktop-dashboard

一個後端程式。定時抓天氣 / AQI / AI 額度並產生本機作息提醒,輸出一頁 live HTML 看板。
電子閱讀器上的 app 開這個網頁即可顯示(實機 **HyRead Gaze Note Plus**,7.8" e-ink,1404×1872,
Android 11,用 **Fully Kiosk** 全螢幕),主機另可用 **ADB** 控制刷新。

本檔是給「人」看的完整操作手冊。給 AI 協作看的技術說明在 [AGENTS.md](AGENTS.md)。
樹莓派 + Tailscale 的一步步佈署見 [PI_DEPLOY.md](PI_DEPLOY.md)。

---

## 目錄
1. [它在做什麼](#1-它在做什麼)
2. [五分鐘跑起來(開發機)](#2-五分鐘跑起來開發機)
3. [資料來源與憑證](#3-資料來源與憑證)
4. [裝置端:Fully Kiosk 滿版](#4-裝置端fully-kiosk-滿版)
5. [ADB 控制指令](#5-adb-控制指令)
6. [三種部署形態](#6-三種部署形態)
7. [設定總表(.env)](#7-設定總表env)
8. [備用端口與失效設計](#8-備用端口與失效設計)
9. [疑難排解](#9-疑難排解)

---

## 1. 它在做什麼

```
資料源(API/本機時間)  →  收集層(依來源節奏)  →  SQLite 快取  →  live HTML(/)  →  電子閱讀器 Fully Kiosk 滿版
                                                              ↑
                                          後端可用 ADB 喚醒、重載、截圖驗證
```

- **輕量**:直接吐 HTML,省磁碟與記憶體,無需 Chromium。
- **三層解耦**:任一 API 失敗,渲染讀「最後一次成功」的舊快取續畫,只標精簡資料年齡,畫面不空白。
- **並行首抓**:啟動時同時抓各啟用來源,單一逾時不會讓其他來源排隊。
- **目前顯示**:頁首日期／星期／更新時間，左欄 天氣＋作息提醒卡(番茄鐘＋桌寵)、右欄 Claude／Codex 額度＋Steam 狀態。

---

## 2. 五分鐘跑起來(開發機)

Windows PowerShell:
```powershell
cd D:\Project\for_pi
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env      # 填 CWA_API_KEY(見下節)
.\.venv\Scripts\python -m app.main
```

瀏覽器開 <http://localhost:8000/> 看看板;<http://localhost:8000/health> 看各來源狀態。

> 相依很輕(fastapi / uvicorn / apscheduler / jinja2 / httpx / python-dotenv),
> 沒有 Playwright/Chromium。Python 3.11+ 皆可。

---

## 3. 資料來源與憑證

| 來源 | 端點 | 憑證來源 | 需手動設定? |
|------|------|----------|--------------|
| 天氣 | CWA `F-C0032-001` 縣市預報 | `CWA_API_KEY` | 要,見下 |
| AQI | 環境部 `aqx_p_432` | `MOENV_API_KEY` | 要;測站/縣市可設定 |
| Claude 額度 | `api.anthropic.com/api/oauth/usage` | `~/.claude/.credentials.json`(Claude Code 登入即有) | 不用 |
| Codex 額度 | `chatgpt.com/backend-api/wham/usage` | `~/.codex/auth.json`(Codex CLI 登入即有) | 不用 |
| 作息提醒 | 本機時間 + SQLite 上次循環狀態 | 無 | 不用 |
| OpenRouter(預留) | `openrouter.ai/api/v1/credits` | `OPENROUTER_API_KEY` | 程式保留,目前不啟用 |

**天氣金鑰**:到 <https://opendata.cwa.gov.tw/> 免費申請授權碼(`CWA-xxxx`),
填進 `.env` 的 `CWA_API_KEY`。地區用縣市名 `CWA_LOCATION`(例 `雲林縣`;此資料集只到縣市級)。

**Claude / Codex**:只要你在這台機器上用 Claude Code / Codex CLI 登入過就自動讀得到,
無需填 key。token 會過期,但你平常在用時系統會自動保鮮。
- 若要在「另一台」主機跑,設環境變數 `CLAUDE_CODE_OAUTH_TOKEN` / `CODEX_ACCESS_TOKEN`,
  或複製整個 `.credentials.json` / `auth.json` 過去(token 過期需重新登入處保鮮)。
- 程式**不會**自動 refresh 這些 token(避免輪換時寫壞你正在用的登入)。過期就顯示舊值。

### 更新節奏

- 天氣、AQI:每小時 `:00` 整點 cron 抓取。
- Claude、Codex、作息提醒:每 600 秒更新。
- 啟動時所有啟用來源先並行抓一次。

### 作息提醒

| 本地時間 | 提醒/模式 |
|----------|-----------|
| 00:00–02:00 | 夜深了，該休息了 |
| 02:00–07:00 | 凌晨了，請立即休息 |
| 07:00–09:00 | 早餐提醒 |
| 09:00–12:00 | 工作循環 |
| 12:00–13:00 | 午餐提醒 |
| 13:00–18:00 | 工作循環,重新從第 1 步開始 |
| 18:00–19:00 | 晚餐提醒 |
| 19:00–22:00 | 工作循環,重新從第 1 步開始 |
| 22:00–24:00 | 夜深了，該休息了 |

工作循環每 10 分鐘推進一步:第 1–3 步顯示專注與倒數,第 4 步提醒喝水、伸展 5 分鐘,
下一次回到第 1 步。自動排程下完整循環約 40 分鐘;跨工作時段或換日會重置。
點頁首「立即刷新」會呼叫 `/refresh`,當場抓取所有來源,因此也會提前推進作息一步。
單純重新載入 `/` 或用 ADB 重載頁面不會推進。

作息功能只讀本機時間與 SQLite 上次循環狀態,不需要任何外部帳號與憑證。

---

## 4. 裝置端:Fully Kiosk 滿版

裝置是開放 Android 11,內建瀏覽器有網址列去不掉,故用 Fully Kiosk 全螢幕。

**首次設定(已完成範例)**
1. 裝置開 Play 商店裝 **Fully Kiosk Browser**(或 `adb install <apk>`)。
2. Quick Start Settings:
   - **Start URL** = 看板網址(USB 測試 `http://localhost:8000/`;WiFi 用 `http://<主機IP>:8000/`)。
   - **Fullscreen Mode** ON、**Show Action Bar** OFF、**Show Address Bar** OFF。
3. 按 **START USING FULLY**。
4. 自動刷新由**頁面自己**做(HTML 內建 `meta refresh`,預設 600 秒),不必設 Fully 的 reload。

**無人值守強化(選用,在 Fully 設定裡,從左緣滑出選單)**
- 開 **Kiosk Mode** 鎖定,避免誤觸離開。
- 設為 **開機自啟 / Launcher**。
- 關螢幕保護、保持螢幕開啟。

---

## 5. ADB 控制指令

開發機用專案內附 `./adb/adb.exe`(`.env` 的 `ADB_BINARY` 已指它);Linux 主機用系統 `adb`。

```bash
python -m app.device.adb devices     # 列出裝置
python -m app.device.adb connect     # WiFi target 才需要(先 adb tcpip 5555)
python -m app.device.adb open        # 在裝置開看板 URL(丟給 Fully)
python -m app.device.adb refresh     # 喚醒 + 重載 +(選)e-ink full refresh
python -m app.device.adb wake        # 只喚醒螢幕
python -m app.device.adb screencap out.png   # 抓裝置畫面回來驗證
```

**USB 測試不必同網段**:用埠轉發讓裝置的 localhost 直通主機伺服器:
```bash
./adb/adb.exe reverse tcp:8000 tcp:8000
# 此時 Fully Start URL / DASHBOARD_URL 用 http://localhost:8000/
```

**排程自動推**:`.env` 設 `REFRESH_VIA_ADB=true` + `ADB_TARGET`,每 `ADB_REFRESH_SECONDS`
秒自動喚醒重載(與頁面自刷並存;ADB 斷線只記警告不中斷)。

---

## 6. 三種部署形態

| 形態 | 伺服器在哪 | 電子閱讀器連線 | 適合 |
|------|-----------|----------------|------|
| **USB 開發** | 這台 PC | USB + `adb reverse` | 現在的開發/示範 |
| **PC 常駐(WiFi)** | 這台 PC | WiFi 到 PC 區網 IP | 想先脫離 USB 試 |
| **常駐主機(WiFi)** | 任一常駐 Linux/PC 主機 | WiFi 到主機區網 IP | 桌面長期無人值守 |

切換只改兩處:**伺服器主機的區網 IP**,填進 (a) Fully 的 Start URL、(b) `.env` 的 `DASHBOARD_URL`。
常駐主機完整步驟(systemd 開機自啟、`apt install adb`、WiFi ADB)見 [DEPLOY.md](DEPLOY.md)。

查主機區網 IP:Windows `ipconfig`;Linux `hostname -I`。桌面背景 App(下節)會自動
偵測並顯示區網 IP,免手動查。

---

## 6.5 桌面背景 App(Windows 系統匣)

不想開著終端機、又要隨手看預覽與區網 IP 時用這個。服務跑在背景,縮到系統匣;需要時叫出
一個內嵌即時看板的視窗,頂列直接顯示可分享給裝置的看板網址。

```powershell
.\.venv\Scripts\python -m pip install -r requirements.txt   # 首次:裝 pywebview/pystray/pythonnet
```

啟動:**雙擊專案根目錄的 `run_app.bat`**(用 `pythonw` 無主控台),或手動
`.\.venv\Scripts\python -m app.desktop`(會保留 log,除錯用)。

- **系統匣圖示**右鍵選單:顯示預覽 / 用瀏覽器開啟看板 / 一列顯示 `區網IP:埠` / 結束。
  左鍵(或雙擊)圖示 = 顯示預覽。
- **關閉視窗只是隱藏**,服務續跑;要真的結束請用選單「結束」(會收掉服務、釋放埠)。
- 埠沿用 `_choose_port()`:主埠被占就自動換備用埠,視窗與網址會跟著顯示實際埠。
- 僅 Windows;常駐主機端仍用 `python -m app.main` / systemd(見 [DEPLOY.md](DEPLOY.md)),不受影響。

---

## 7. 設定總表(.env)

| 變數 | 預設 | 說明 |
|------|------|------|
| `HOST` | `0.0.0.0` | 綁定介面,`0.0.0.0` = 對區網開放 |
| `PORT` | `8000` | 主要服務埠 |
| `FALLBACK_PORTS` | `8080,8888` | 主埠被占時依序嘗試 |
| `HTML_AUTO_REFRESH_SECONDS` | `600` | 頁面自刷秒數;`0` = 關(交給 ADB) |
| `CWA_API_KEY` | — | 中央氣象署授權碼 |
| `CWA_LOCATION` | `臺中市` | 縣市名,例 `雲林縣` |
| `MOENV_API_KEY` | — | 環境部資料開放平臺 API key |
| `AQI_SITE` | `斗六` | 優先選用的 AQI 測站 |
| `AQI_COUNTY` | `雲林縣` | 找不到指定測站時使用的縣市 |
| `OPENROUTER_API_KEY` | — | 預留;目前不註冊 OpenRouter 收集器 |
| `CLAUDE_CODE_OAUTH_TOKEN` | — | 覆寫 Claude token(跨機用) |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Claude 憑證目錄 |
| `CODEX_ACCESS_TOKEN` | — | 覆寫 Codex token(跨機用) |
| `CODEX_HOME` | `~/.codex` | Codex 憑證目錄 |
| `REFRESH_VIA_ADB` | `false` | 每次排程後用 ADB 推裝置 |
| `ADB_REFRESH_SECONDS` | `600` | ADB 刷新間隔 |
| `ADB_BINARY` | `adb` | adb 執行檔;開發機指 `./adb/adb.exe` |
| `ADB_TARGET` | — | WiFi `ip:5555` 或 USB serial;空=第一台 |
| `DASHBOARD_URL` | `http://localhost:8000/` | 裝置要開的看板網址 |
| `DEVICE_BROWSER_COMPONENT` | — | `de.ozerov.fully/.MainActivity`(Fully) |
| `DEVICE_REFRESH_BROADCAST` | — | e-ink full refresh 廣播(裝置特有,選填) |

---

## 8. 備用端口與失效設計

**備用端口**:啟動時自動檢查 `PORT` 是否可用;被占用就依 `FALLBACK_PORTS` 順序找下一個可用埠,
並在 log 明確警告。開發機常有其他服務占 8000,這樣不會啟動失敗。
> 注意:若真的用了備用埠,**裝置端 Fully 的 Start URL 與 `.env` 的 `DASHBOARD_URL` 埠號要一起改**,
> 否則裝置連不到。log 會提醒你改成哪個埠。

**失效設計(各層獨立降級)**
- **某個 API 掛掉**:該來源 `fetch` 例外被吞,保留上次成功的快取,畫面照畫舊值 + 時間戳。
- **健康狀態**:`/health` 頂層 `ok` 表示服務存活;各來源回 `available`、`age_seconds`、`stale`。
  無資料或資料年齡超過兩倍收集週期才是 stale,剛好兩倍仍視為新鮮。
- **憑證過期**(Claude/Codex):同上,顯示舊值不清空;重新登入該機後自動恢復。
- **伺服器重啟**:啟動時先同步抓一輪再開埠,首個請求就有資料。
- **網路 / 裝置離線**:Fully 停在最後一次載入的畫面;恢復後下次 `meta refresh` 自動更新。
- **ADB 斷線**:排程推送只記警告,不影響伺服器與頁面自刷。

---

## 9. 疑難排解

| 症狀 | 處理 |
|------|------|
| 裝置打不開頁面 | `DASHBOARD_URL` 用**區網 IP**不要 localhost(除非 USB + `adb reverse`);主機防火牆放行該埠 |
| CWA 憑證錯 `Missing Subject Key Identifier` | 已在 `app/net.py` 放寬 Py3.14 X509 strict;主機上仍失敗就 `pip install -U certifi` |
| Claude/Codex 格空白或「待憑證」 | 在該機用 Claude Code / Codex CLI 登入;跨機則設對應 token 環境變數 |
| `adb devices` 看不到裝置 | 裝置開發者選項開 USB 偵錯並在裝置上「允許」;WiFi 先 `adb tcpip 5555` 再 `adb connect ip:5555` |
| 啟動說埠被占用 | 交給備用埠自動處理;或改 `PORT`,記得同步改裝置 URL |
| e-ink 殘影明顯 | 靠 `meta refresh` 整頁重載通常會全刷;仍明顯再查 `DEVICE_REFRESH_BROADCAST`(見 DEPLOY C-3) |

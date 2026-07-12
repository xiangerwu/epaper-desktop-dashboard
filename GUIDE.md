# 完全使用指南 — pi-eink-dashboard

樹莓派桌面電子紙看板。定時抓天氣 / AI 額度,以 live HTML 供 **HyRead Gaze Note Plus**
(7.8" e-ink,1404×1872,Android 11)透過 **Fully Kiosk** 全螢幕顯示,Pi/PC 用 **ADB** 控制。

本檔是給「人」看的完整操作手冊。給 AI 協作看的技術說明在 [AGENTS.md](AGENTS.md)。

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
資料源(API)  →  收集層(每 10 分)  →  SQLite 快取  →  live HTML(/)  →  裝置 Fully Kiosk 滿版
                                                              ↑
                                          Pi/PC 可用 ADB 喚醒、重載、截圖驗證
```

- **不產圖**:直接吐 HTML,省磁碟與記憶體(Pi 不需 Chromium)。
- **三層解耦**:任一 API 失敗,渲染讀「最後一次成功」的舊快取續畫,只標精簡資料年齡,畫面不空白。
- **並行首抓**:啟動時同時抓各啟用來源,單一逾時不會讓其他來源排隊。
- **目前顯示的四塊**:日期 / 天氣(CWA)/ Claude 額度 / Codex 額度。

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
| Claude 額度 | `api.anthropic.com/api/oauth/usage` | `~/.claude/.credentials.json`(Claude Code 登入即有) | 不用 |
| Codex 額度 | `chatgpt.com/backend-api/wham/usage` | `~/.codex/auth.json`(Codex CLI 登入即有) | 不用 |
| OpenRouter(預留) | `openrouter.ai/api/v1/credits` | `OPENROUTER_API_KEY` | 程式保留,目前不啟用 |

**天氣金鑰**:到 <https://opendata.cwa.gov.tw/> 免費申請授權碼(`CWA-xxxx`),
填進 `.env` 的 `CWA_API_KEY`。地區用縣市名 `CWA_LOCATION`(例 `雲林縣`;此資料集只到縣市級)。

**Claude / Codex**:只要你在這台機器上用 Claude Code / Codex CLI 登入過就自動讀得到,
無需填 key。token 會過期,但你平常在用時系統會自動保鮮。
- 若要在「另一台」(如 Pi)跑,設環境變數 `CLAUDE_CODE_OAUTH_TOKEN` / `CODEX_ACCESS_TOKEN`,
  或複製整個 `.credentials.json` / `auth.json` 過去(token 過期需重新登入處保鮮)。
- 程式**不會**自動 refresh 這些 token(避免輪換時寫壞你正在用的登入)。過期就顯示舊值。

---

## 4. 裝置端:Fully Kiosk 滿版

裝置是開放 Android 11,內建瀏覽器有網址列去不掉,故用 Fully Kiosk 全螢幕。

**首次設定(已完成範例)**
1. 裝置開 Play 商店裝 **Fully Kiosk Browser**(或 `adb install <apk>`)。
2. Quick Start Settings:
   - **Start URL** = 看板網址(USB 測試 `http://localhost:8000/`;WiFi/Pi 用 `http://<主機IP>:8000/`)。
   - **Fullscreen Mode** ON、**Show Action Bar** OFF、**Show Address Bar** OFF。
3. 按 **START USING FULLY**。
4. 自動刷新由**頁面自己**做(HTML 內建 `meta refresh`,預設 600 秒),不必設 Fully 的 reload。

**無人值守強化(選用,在 Fully 設定裡,從左緣滑出選單)**
- 開 **Kiosk Mode** 鎖定,避免誤觸離開。
- 設為 **開機自啟 / Launcher**。
- 關螢幕保護、保持螢幕開啟。

---

## 5. ADB 控制指令

開發機用專案內附 `./adb/adb.exe`(`.env` 的 `ADB_BINARY` 已指它);Pi 用系統 `adb`。

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

| 形態 | 伺服器在哪 | 裝置連線 | 適合 |
|------|-----------|----------|------|
| **USB 開發** | 這台 PC | USB + `adb reverse` | 現在的開發/示範 |
| **PC 常駐(WiFi)** | 這台 PC | WiFi 到 PC 區網 IP | 想先脫離 USB 試 |
| **Pi 5 常駐(目標)** | 樹莓派 | WiFi 到 Pi 區網 IP | 桌面長期無人值守 |

切換只改兩處:**伺服器主機的區網 IP**,填進 (a) Fully 的 Start URL、(b) `.env` 的 `DASHBOARD_URL`。
Pi 完整步驟(systemd 開機自啟、`apt install adb`、WiFi ADB)見 [DEPLOY.md](DEPLOY.md)。

查主機區網 IP:Windows `ipconfig`;Pi/Linux `hostname -I`。

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
| CWA 憑證錯 `Missing Subject Key Identifier` | 已在 `app/net.py` 放寬 Py3.14 X509 strict;Pi 上仍失敗就 `pip install -U certifi` |
| Claude/Codex 格空白或「待憑證」 | 在該機用 Claude Code / Codex CLI 登入;跨機則設對應 token 環境變數 |
| `adb devices` 看不到裝置 | 裝置開發者選項開 USB 偵錯並在裝置上「允許」;WiFi 先 `adb tcpip 5555` 再 `adb connect ip:5555` |
| 啟動說埠被占用 | 交給備用埠自動處理;或改 `PORT`,記得同步改裝置 URL |
| e-ink 殘影明顯 | 靠 `meta refresh` 整頁重載通常會全刷;仍明顯再查 `DEVICE_REFRESH_BROADCAST`(見 DEPLOY C-3) |

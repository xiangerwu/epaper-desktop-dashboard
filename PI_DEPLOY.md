# 樹莓派佈署(含 Tailscale)

從一台乾淨的樹莓派,到「開機自動跑看板、電子閱讀器透過 Tailscale 連上看、
主機再用 ADB 定時刷新閱讀器」的一步步照抄版。

這份是**樹莓派專用、可獨立照抄**的版本。通用 Linux 佈署見 [DEPLOY.md](DEPLOY.md)、
人用手冊見 [GUIDE.md](GUIDE.md)、架構見 [AGENTS.md](AGENTS.md)。

---

## 名詞

- **派(Pi)** = 常駐後端主機,跑 FastAPI 服務,輸出看板 HTML。
- **電子閱讀器** = HyRead Gaze Note Plus(e-ink 顯示端),用 Fully Kiosk 開網頁滿版顯示。

顯示走網頁,派上**不需要** Chromium/Playwright/Pillow,`pip install` 很輕。

## 需要準備

- 一台樹莓派,建議 **Raspberry Pi OS Bookworm**(內建 Python 3.11,不會踩到 Py3.14 的
  X509 strict 問題)。能 SSH 進去。
- **你的開發機**:已經填好 `.env`、已用 Claude Code / Codex CLI 登入過(要把這些搬到派)。
- 電子閱讀器(HyRead Gaze Note Plus 或同型 e-ink Android 機)。
- 一個 **Tailscale** 帳號(Google/GitHub/Microsoft 皆可登入)。

外部要申請的 API key 只有兩個,都在開發機的 `.env` 裡了,等下整包搬過去:

- `CWA_API_KEY` — 天氣,中央氣象署 <https://opendata.cwa.gov.tw/>(授權碼 `CWA-xxxx`)。
- `MOENV_API_KEY` — 空氣品質,環境部 <https://data.moenv.gov.tw/>(資料集 `aqx_p_432`)。

留空服務仍會啟動,只是該卡沒資料。Steam 選填。Claude/Codex 額度**不吃 API key**,走登入憑證(見步驟三)。

---

## 步驟一:派上裝系統套件與程式碼

```bash
sudo apt update
sudo apt install -y python3-venv git adb
git clone <你的repo> ~/epaper-desktop-dashboard    # 或用 scp/rsync 把整個資料夾複製過去
cd ~/epaper-desktop-dashboard
```

## 步驟二:虛擬環境 + 只裝服務依賴

`requirements.txt` 的後 4 個套件(`pywebview` / `pystray` / `pythonnet` / `Pillow`)是
Windows 桌面系統匣模式專用,樹莓派純服務**不需要**,而且 `pythonnet` 在 Linux 難裝。
只裝前 6 個:

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install \
  fastapi==0.139.0 \
  "uvicorn[standard]==0.51.0" \
  apscheduler==3.11.3 \
  jinja2==3.1.6 \
  httpx==0.28.1 \
  python-dotenv==1.2.2
```

> 或直接過濾掉註解區塊後安裝:
> `.venv/bin/pip install $(grep -vE '^\s*#|^\s*$' requirements.txt | head -6)`
> (`requirements.txt` 前 6 行剛好是服務所需,第 7 行起是桌面模式套件。)

---

## 步驟三:從開發機複製 API key 與 Claude/Codex 登入

這是這份文檔的重點。三個檔案要從開發機搬到派。把 `<派IP>` 換成派的區網 IP(派上 `hostname -I` 查),
`pi` 換成你的使用者名。

### 3a. `.env`(所有 API key)

`.env` 含 CWA / MOENV / Steam 的真實金鑰,而且**不進版控**(在 `.gitignore` 內),
所以用 `scp` 直接搬,不要貼進任何公開檔案:

```bash
# 在開發機執行
scp .env pi@<派IP>:~/epaper-desktop-dashboard/.env
```

Windows 開發機的 `.env` 在專案根目錄,一樣可用 PowerShell 的 `scp`,或用 WinSCP 拖過去。

### 3b. Claude 登入憑證

服務讀 `~/.claude/.credentials.json` 的 `claudeAiOauth.accessToken`(不是 API key,是 Claude Code 登入的 OAuth token):

```bash
# 先在派上建目錄
ssh pi@<派IP> 'mkdir -p ~/.claude && chmod 700 ~/.claude'
# 開發機把憑證搬過去
scp ~/.claude/.credentials.json pi@<派IP>:~/.claude/.credentials.json
```

Windows 開發機的路徑是 `%USERPROFILE%\.claude\.credentials.json`。

> `claude setup-token` 產生的 token 缺 `user:profile` scope,讀不到訂閱額度。
> 要複製的是**實際登入**後產生的 `.credentials.json`。

### 3c. Codex 登入憑證

服務讀 `~/.codex/auth.json` 的 `tokens.access_token`:

```bash
ssh pi@<派IP> 'mkdir -p ~/.codex && chmod 700 ~/.codex'
scp ~/.codex/auth.json pi@<派IP>:~/.codex/auth.json
```

Windows 開發機的路徑是 `%USERPROFILE%\.codex\auth.json`。

### 3d. 收尾

在派上鎖權限:

```bash
chmod 600 ~/.claude/.credentials.json ~/.codex/auth.json
```

**替代方案**:不想搬憑證,就直接在派上用 CLI 各登入一次(`claude` 走登入流程、`codex` 登入),
效果一樣。

> **重要:token 不會自動保鮮。** 服務**刻意不自動 refresh** 這兩個 token(refresh 會輪換
> token,寫回失誤會弄壞你正在用的 CLI 登入)。token 一旦過期,Claude/Codex 卡會停在舊值。
> 要恢復,就回到「有在用 Claude Code / Codex 的那台機器」重新登入,再重複 3b / 3c 複製過來;
> 或直接在派上重登一次。若派是無人值守的純顯示機,這兩張卡會隨 token 到期而失去更新。

### 3e. 改派上 `.env` 兩處

```bash
nano ~/epaper-desktop-dashboard/.env
```

- `ADB_BINARY=adb` — 用 `apt` 裝的系統版,不是開發機的 `./adb/adb.exe`。
- `DASHBOARD_URL` — 先留著,步驟六拿到 Tailscale IP 再回填。

---

## 步驟四:測跑與驗證

```bash
cd ~/epaper-desktop-dashboard
.venv/bin/python -m app.main
```

另開一個 SSH 視窗:

```bash
curl -s http://localhost:8000/health
# {"ok":true,"sources":{"weather":{"available":true,...},"aqi":{...},"claude":{...},"codex":{...}}}
```

- `weather` / `aqi` 是否 `available:true` → 確認 `.env` 的 API key 有搬到。
- `claude` / `codex` 若 `available:false` → 多半是憑證沒複製對、路徑不對、或 token 過期(回步驟三)。

服務啟動時會並行首抓一輪;之後天氣/AQI 每小時 `:00` 抓,Claude/Codex/作息每 600 秒更新。
確認沒問題後 `Ctrl-C` 停掉,進步驟五掛成服務。

> 預設埠 8000。若被占用,服務會依 `FALLBACK_PORTS`(預設 `8080,8888`)自動換,並在 log 警告 —
> 換了埠記得同步改後面 `DASHBOARD_URL` 與 Fully 的 Start URL 的埠號。

---

## 步驟五:開機自啟(systemd)

```bash
sudo nano /etc/systemd/system/epaper-dashboard.service
```

```ini
[Unit]
Description=epaper-desktop-dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=<你的使用者>
WorkingDirectory=/home/<你的使用者>/epaper-desktop-dashboard
ExecStart=/home/<你的使用者>/epaper-desktop-dashboard/.venv/bin/python -m app.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now epaper-dashboard
systemctl status epaper-dashboard --no-pager
journalctl -u epaper-dashboard -f       # 看即時 log
```

---

## 步驟六:Tailscale — 讓閱讀器連上派

同區網時閱讀器可以直接用派的區網 IP;但用 **Tailscale** 有兩個好處:派與閱讀器**不必在同一個
區網**,而且拿到的 tailnet IP(`100.x.y.z`)固定,不怕路由器換 DHCP 位址。

### 6a. 派上裝 Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

`tailscale up` 會印一個授權 URL。在瀏覽器打開、登入你的 Tailscale 帳號,把派加進 tailnet。
取得派的 tailnet IP:

```bash
tailscale ip -4       # 例如 100.101.102.103
```

> 若在 Tailscale 後台開了 MagicDNS,也可用主機名(如 `http://raspberrypi:8000/`)取代 IP。

### 6b. 回填派 `.env` 並重啟

```bash
nano ~/epaper-desktop-dashboard/.env
# DASHBOARD_URL=http://100.101.102.103:8000/
sudo systemctl restart epaper-dashboard
```

### 6c. 電子閱讀器裝 Tailscale + Fully Kiosk

1. 閱讀器上開 **Play 商店** → 裝 **Tailscale** → 登入**同一個 Tailscale 帳號** → 連上 tailnet。
2. 裝 **Fully Kiosk Browser & App Lockdown**(免費版夠用)。
3. Fully 設定:
   - **Start URL** = 派的 tailnet 位址,和派 `.env` 的 `DASHBOARD_URL` 一致(`http://100.101.102.103:8000/`)。
   - 開 **Kiosk Mode**,隱藏 status/navigation bar(全螢幕沉浸)。
   - 設為開機啟動 / 預設 App。
   - 頁面自刷靠看板 HTML 內建的 meta refresh(`HTML_AUTO_REFRESH_SECONDS`,預設 600 秒),
     Fully 不必另設 reload。(細節見 [DEPLOY.md](DEPLOY.md) B 段。)

> **安全提醒**:Tailscale 授權是把裝置加進你的私有 tailnet,登入走瀏覽器 OAuth。
> 請自己在派與閱讀器上完成登入,不要把帳密交給別人代填。

此時閱讀器已能透過 Tailscale 看到看板。若你只要「閱讀器開網頁看」,到這裡就完成了。
想讓派反過來主動刷新閱讀器(e-ink 控時機),繼續步驟七。

---

## 步驟七:ADB over Tailscale — 派反向刷新閱讀器

讓派透過 tailnet 用 ADB 喚醒閱讀器並重載頁面,由後端統一控制刷新時機。

### 7a. 閱讀器開發者選項 + 無線 debug

閱讀器:設定 → 關於 → 連點「版本號」數次開開發者選項 → 進開發者選項 → 開「USB 偵錯」。
先用 USB 或同區網把無線 debug 開起來一次:

```bash
# 派用 USB 線接閱讀器,或先同區網,執行:
adb tcpip 5555
```

### 7b. 派用閱讀器的 tailnet IP 連上

閱讀器裝了 Tailscale 後也有自己的 tailnet IP(在閱讀器的 Tailscale App 裡看,或派上
`tailscale status` 查)。派用這個 IP 連:

```bash
adb connect <閱讀器tailnetIP>:5555
```

寫進派 `.env`:

```ini
ADB_TARGET=<閱讀器tailnetIP>:5555
```

### 7c. 手動驗證

```bash
cd ~/epaper-desktop-dashboard
.venv/bin/python -m app.device.adb devices
.venv/bin/python -m app.device.adb open        # 閱讀器應打開看板 URL
.venv/bin/python -m app.device.adb refresh     # 喚醒 + 重載
.venv/bin/python -m app.device.adb screencap /tmp/s.png   # 抓畫面回來看
```

搭配 Fully 用時,把 `.env` 的 `DEVICE_BROWSER_COMPONENT=de.ozerov.fully/.MainActivity`,
`adb refresh` 會精準把看板丟給 Fully 而非系統選擇器。

### 7d. 開自動刷新

```ini
# .env
REFRESH_VIA_ADB=true
ADB_REFRESH_SECONDS=300
HTML_AUTO_REFRESH_SECONDS=0     # 交給 ADB 控時機,關掉頁面自刷避免雙重刷新
ADB_BINARY=adb
```

```bash
sudo systemctl restart epaper-dashboard
```

> **註記**:Android 無線 debug 在裝置重開機/深睡後可能斷線或換埠,tailnet IP 則相對穩定。
> `adb refresh` 連不上只記 warning,不影響閱讀器繼續看網頁。
> 頁面重載或 ADB refresh **不會**推進看板的作息循環;只有排程收集或點頁首「立即刷新」
> (`/refresh`)才會更新作息。

---

## 疑難排解

- **頁面打不開**:派防火牆放行 8000(`sudo ufw allow 8000` 若有開 ufw);`DASHBOARD_URL`
  用 tailnet 或區網 IP,別用 `localhost`(那是閱讀器自己的 localhost)。
- **Claude/Codex 卡沒資料**:憑證沒複製對、路徑不對、或 token 過期。`curl .../health` 看
  `claude`/`codex` 的 `available`;回步驟三重新複製或在派上重登。
- **Tailscale 連不上**:確認派與閱讀器**登入同一個帳號**;派上 `tailscale status` 看兩端是否都在線。
- **adb 一直 offline**:閱讀器上重按一次「允許 USB 偵錯」;tailnet 模式先
  `adb disconnect` 再 `adb connect <閱讀器tailnetIP>:5555`。
- **CWA 憑證錯誤**:Bookworm 的 Python 3.11 通常沒這問題(X509 strict 是 3.14 才預設開,
  已在 `app/net.py` 放寬);若仍失敗 `.venv/bin/pip install -U certifi`。

# 部署步驟(Raspberry Pi 5 + HyRead Gaze Note Plus)

從零到「Pi 開機自動跑看板、裝置定時被 ADB 刷新」。
你目前 PC 與 Pi 都沒裝 adb — 下面含安裝。

---

## A. Pi 上跑起服務

### 1. 系統與程式碼
```bash
sudo apt update
sudo apt install -y python3-venv git adb
# 把專案放到 Pi,例如:
git clone <你的repo> ~/pi-eink-dashboard    # 或用 scp/rsync 複製整個資料夾
cd ~/pi-eink-dashboard
```
> 不需要 Playwright/Chromium(已改 live HTML)。`pip install -r requirements.txt` 很輕。

### 2. 虛擬環境 + 相依
```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
```

### 3. 設定 .env
```bash
cp .env.example .env
nano .env
```
至少填:
```
CWA_API_KEY=CWA-你的授權碼
CWA_LOCATION=臺中市
DASHBOARD_URL=http://<PiのIP>:8000/     # 用 hostname -I 查 Pi 的區網 IP
```
ADB 相關先留預設(`REFRESH_VIA_ADB=false`),等 C 段驗證通再開。

### 4. 測跑
```bash
.venv/bin/python -m app.main
# 另一台機器瀏覽器開 http://<PiのIP>:8000/ 應看到看板
curl -s http://localhost:8000/health
# {"ok":true,"sources":{"weather":{"available":true,"age_seconds":12,"stale":false},...}}
```

### 5. 開機自啟(systemd)
`sudo nano /etc/systemd/system/eink-dashboard.service`:
```ini
[Unit]
Description=pi-eink-dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/pi-eink-dashboard
ExecStart=/home/pi/pi-eink-dashboard/.venv/bin/python -m app.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now eink-dashboard
systemctl status eink-dashboard --no-pager
journalctl -u eink-dashboard -f       # 看即時 log
```

---

## B. 裝置端:開發者選項 + 顯示看板

### 1. 開 USB 偵錯
Gaze Note Plus:設定 → 關於 → 連點「版本號」數次開開發者選項 → 進開發者選項 → 開「USB 偵錯」。

### 2. 讓裝置全螢幕開看板(kiosk App)
內建瀏覽器 `com.android.browser` 有網址列/工具列去不掉。裝置已內建 Play 商店,
直接裝 kiosk 瀏覽器最乾淨:

1. 裝置上開 **Play 商店** → 裝「**Fully Kiosk Browser & App Lockdown**」(免費版夠用)。
2. Fully 設定:
   - **Start URL** = 看板網址(Pi 部署用 `http://<PiのIP>:8000/`;USB 測試用 `http://localhost:8000/` + adb reverse)。
   - 開 **Kiosk Mode**,隱藏 status/navigation bar(全螢幕沉浸)。
   - 自動刷新:看板 HTML 內建 `meta refresh`(`HTML_AUTO_REFRESH_SECONDS`,預設 600),
     Fully 會每 10 分自己重載,**不必**另設 Fully 的 reload。要改頻率調該環境變數即可。
3. 設為開機啟動 / 預設 App。
4. 回到專案 `.env` 填:
   ```
   DEVICE_BROWSER_COMPONENT=de.ozerov.fully/.MainActivity
   ```
   之後 `adb refresh` 會精準把看板丟給 Fully(而非系統選擇器)。

> e-ink 整頁刷新:Fully 每次重載頁面時,HyRead 系統通常自帶一次全刷清殘影。
> 若殘影明顯,再研究 `DEVICE_REFRESH_BROADCAST`(見 C-3)。

---

## C. ADB 控制刷新

> 已在實機驗證:HyRead Gaze Note Plus 回報 `model:K08P product:rk3566_eink`。
> 內建瀏覽器 `com.android.browser` 可開看板,但有工具列/網址列非全螢幕 —
> 正式用建議 kiosk App(見 B-2),把 component 填 `DEVICE_BROWSER_COMPONENT`。

### 0. Windows 開發機測試(USB,免區網)
本機開發時 adb 二進位放 `./adb/adb.exe`(`.env` 的 `ADB_BINARY` 已指它)。
USB 接裝置後,用 `adb reverse` 讓裝置的 localhost 直通 PC 伺服器:
```bash
./adb/adb.exe reverse tcp:8000 tcp:8000
# .env: DASHBOARD_URL=http://localhost:8000/
.venv/Scripts/python -m app.device.adb refresh
.venv/Scripts/python -m app.device.adb screencap data/device_screen.png
```
> Pi 正式部署改回區網:`DASHBOARD_URL=http://<PiのIP>:8000/`,裝置走 WiFi。

### 1. 從 Pi 連上裝置
**USB**(先驗證最簡單):Pi 用 USB 線接裝置 →
```bash
adb devices           # 裝置上會跳「允許 USB 偵錯」,勾記住 → 允許
```
**WiFi**(桌面擺放實用,免線):USB 接一次開 tcpip,之後走網路:
```bash
adb tcpip 5555
adb connect <裝置IP>:5555      # 裝置 IP 在 設定→WiFi→該網路 查
```
把 target 寫進 `.env`:
```
ADB_TARGET=<裝置IP>:5555        # USB 模式則留空
```
> WiFi ADB 裝置重開機後要重連。可在 systemd 或 cron 加一條開機 `adb connect`。

### 2. 手動驗證
```bash
.venv/bin/python -m app.device.adb devices
.venv/bin/python -m app.device.adb open        # 裝置應打開看板 URL
.venv/bin/python -m app.device.adb refresh     # 喚醒 + 重載
.venv/bin/python -m app.device.adb screencap /tmp/s.png   # 抓畫面回來看
```

### 3. e-ink full refresh(裝置特有,需現場確認)
`refresh` 目前做「喚醒 + 重載」。要清殘影的整頁刷新,得知道 HyRead 的廣播 action。
接上裝置後用下列找線索,再把 action 填進 `.env` 的 `DEVICE_REFRESH_BROADCAST`:
```bash
adb shell dumpsys package | grep -i refresh      # 找含 refresh 的 receiver/action
adb logcat | grep -i -E "eink|refresh|epd"       # 操作裝置刷新時看它印什麼
```
找不到就先靠「整頁重載」，多數 e-ink 瀏覽器重載時會自帶一次全刷。

### 4. 開自動刷新
`.env`:
```
REFRESH_VIA_ADB=true
ADB_REFRESH_SECONDS=300
HTML_AUTO_REFRESH_SECONDS=0     # 交給 ADB 控時機,關掉頁面自刷避免雙重刷新
```
```bash
sudo systemctl restart eink-dashboard
```

---

## 疑難

- **頁面打不開**:Pi 防火牆放行 8000;`DASHBOARD_URL` 用區網 IP 不要用 localhost。
- **CWA 憑證錯誤**:已在 `app/net.py` 放寬 X509 strict;若 Pi 上仍失敗,`pip install -U certifi`。
- **adb 一直 offline**:裝置重按一次「允許 USB 偵錯」;WiFi 模式先 `adb disconnect` 再 `adb connect`。
- **裝置睡眠後 adb 斷**:開發者選項開「USB 偵錯(安全設定)」與充電時不休眠;WiFi 模式加開機重連。

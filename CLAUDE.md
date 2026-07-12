# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

完整的 AI 協作說明(架構、慣例、地雷、擴充方式、指令)在 **[AGENTS.md](AGENTS.md)** — 請先讀它。
人用的操作手冊在 [GUIDE.md](GUIDE.md),部署在 [DEPLOY.md](DEPLOY.md)。

## 一句話

一個後端程式:FastAPI 定時抓天氣/AI 額度 → SQLite 快取 → 輸出 live HTML;電子閱讀器上的
app 開網頁即可顯示(實機 HyRead Gaze Note Plus + Fully Kiosk 滿版),主機用 ADB 控制刷新。

## 最常忘的幾點(細節見 AGENTS.md)

- 對外 HTTP 一律走 `app.net.client()`(放寬了 Py3.14 的 X509 strict,否則 CWA 憑證被擋)。
- 新來源 = `app/collectors/` 加一個 `Collector` 子類 + 在 `__init__.py` 註冊;`fetch` 失敗就 raise。
- **別自動 refresh Claude/Codex 的 OAuth token**(會弄壞使用者的 CLI 登入)。
- 別重新引入 Playwright/Pillow;顯示走網頁。
- 驗證裝置顯示用 `python -m app.device.adb screencap`,別只信本機預覽。

## 常用指令

```bash
.venv/Scripts/python -m app.main       # 起服務(自動選可用埠)
curl -s http://localhost:8000/health   # 各來源快取狀態
.venv/Scripts/python -m app.device.adb screencap data/device_screen.png
```

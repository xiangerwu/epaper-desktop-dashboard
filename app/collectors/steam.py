"""Steam 狀態 collector: 帳號摘要 + 最近玩最多那款遊戲(時數 + 成就進度 + 最新成就)。

用 Steam Web API(需自建金鑰 https://steamcommunity.com/dev/apikey):
  IPlayerService/GetRecentlyPlayedGames        近兩週玩過的遊戲 + 時數(分鐘)
  IPlayerService/GetBadges                      等級 + 徽章數
  IPlayerService/GetOwnedGames                 擁有款數 + 各款總時數
  ISteamUserStats/GetPlayerAchievements        逐款成就(top 遊戲進度;帳號總成就掃全部玩過的)
  ISteamUserStats/GetGlobalAchievementPercentagesForApp  該成就全球取得率

需要玩家個資設為公開(遊戲細節 + 成就),否則對應 API 回無資料;各項 enrichment 各自
try/except,單項失敗只少該欄。金鑰/SteamID 缺一就 raise,由 base 保留舊快取。
"""
from __future__ import annotations

import asyncio

from ..config import settings
from ..net import client
from .base import Collector

BASE = "https://api.steampowered.com/"
RECENT_URL = BASE + "IPlayerService/GetRecentlyPlayedGames/v1/"
BADGES_URL = BASE + "IPlayerService/GetBadges/v1/"
OWNED_URL = BASE + "IPlayerService/GetOwnedGames/v1/"
ACH_URL = BASE + "ISteamUserStats/GetPlayerAchievements/v1/"
GLOBAL_ACH_URL = BASE + "ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/"


class SteamCollector(Collector):
    source = "steam"
    interval_seconds = 1800  # 供 /health 判 stale(2× = 1 小時)
    cron_minute = "0,30"  # 每小時 :00、:30 更新(對齊時鐘的半小時)

    async def fetch(self) -> dict:
        if not settings.steam_api_key or not settings.steam_id:
            raise RuntimeError("STEAM_API_KEY / STEAM_ID 未設定")

        async with client() as c:
            # 不帶 count:回全部近期遊戲;[0] 為近兩週玩最多那款
            r = await c.get(RECENT_URL, params=self._key())
            r.raise_for_status()
            games = (r.json().get("response") or {}).get("games") or []

            summary = await self._summary(c, games)
            top = await self._top(c, games[0]) if games else None

        return {"summary": summary, "top": top}

    def _key(self) -> dict:
        return {"key": settings.steam_api_key, "steamid": settings.steam_id}

    async def _summary(self, c, games: list) -> dict | None:
        """等級 + 徽章數 + 帳號總成就數 + 過去兩週遊玩總時數。任一子項失敗給 None。"""
        level = badge_count = total_achievements = None
        owned: list = []
        try:
            # GetBadges 一次拿等級與徽章數
            r = await c.get(BADGES_URL, params=self._key())
            r.raise_for_status()
            resp = r.json().get("response") or {}
            level = resp.get("player_level")
            badge_count = len(resp.get("badges") or [])
        except Exception:  # noqa: BLE001
            pass
        try:
            r = await c.get(OWNED_URL, params={**self._key(), "include_played_free_games": 1})
            r.raise_for_status()
            owned = (r.json().get("response") or {}).get("games") or []
        except Exception:  # noqa: BLE001
            pass
        total_achievements = await self._total_achievements(c, owned)
        hours_2weeks_total = round(
            sum(g.get("playtime_2weeks", 0) for g in games) / 60, 1
        ) if games else None
        if all(v is None for v in (level, badge_count, total_achievements, hours_2weeks_total)):
            return None
        return {
            "level": level,
            "badge_count": badge_count,
            "total_achievements": total_achievements,
            "hours_2weeks_total": hours_2weeks_total,
        }

    async def _total_achievements(self, c, owned: list) -> int | None:
        """帳號總解鎖成就:掃所有玩過(playtime>0)的遊戲並加總。併發限流避免爆量。"""
        appids = [g["appid"] for g in owned
                  if g.get("playtime_forever", 0) > 0 and g.get("appid")]
        if not appids:
            return None
        sem = asyncio.Semaphore(12)

        async def one(appid: int) -> int:
            async with sem:
                try:
                    r = await c.get(ACH_URL, params={**self._key(), "appid": appid})
                    if r.status_code != 200:
                        return 0
                    stats = r.json().get("playerstats") or {}
                    if not stats.get("success"):
                        return 0
                    return sum(1 for a in stats.get("achievements") or [] if a.get("achieved"))
                except Exception:  # noqa: BLE001 - 單款失敗當 0
                    return 0

        return sum(await asyncio.gather(*(one(a) for a in appids)))

    async def _top(self, c, g: dict) -> dict:
        """最近玩最多那款:基本時數 + 該遊戲成就進度 + 最新解鎖成就。"""
        appid = g.get("appid")
        top = {
            "name": g.get("name", ""),
            "appid": appid,
            "hours_total": round(g.get("playtime_forever", 0) / 60, 1),
            "hours_2weeks": round(g.get("playtime_2weeks", 0) / 60, 1),
            "ach": None,
            "latest": None,
        }
        if not appid:
            return top

        try:
            r = await c.get(ACH_URL, params={**self._key(), "appid": appid, "l": "tchinese"})
            r.raise_for_status()
            stats = r.json().get("playerstats") or {}
        except Exception:  # noqa: BLE001 - 該遊戲無成就/私密即略過進度
            return top
        if not stats.get("success"):
            return top

        achs = stats.get("achievements") or []
        total = len(achs)
        unlocked = sum(1 for a in achs if a.get("achieved"))
        if total:
            top["ach"] = {"unlocked": unlocked, "total": total,
                          "pct": round(unlocked / total * 100)}

        latest = max(
            (a for a in achs if a.get("achieved") and a.get("unlocktime")),
            key=lambda a: a["unlocktime"], default=None,
        )
        if latest:
            top["latest"] = {
                "name": latest.get("name") or latest.get("apiname", ""),
                "unlock_epoch": latest["unlocktime"],
                "rarity_pct": await self._rarity(c, appid, latest.get("apiname", "")),
            }
        return top

    async def _rarity(self, c, appid: int, apiname: str) -> float | None:
        """該成就的全球取得率(百分比,一位小數)。查不到回 None。"""
        if not apiname:
            return None
        try:
            r = await c.get(GLOBAL_ACH_URL, params={"gameid": appid})
            r.raise_for_status()
            items = (r.json().get("achievementpercentages") or {}).get("achievements") or []
        except Exception:  # noqa: BLE001
            return None
        for it in items:
            if it.get("name") == apiname:
                try:
                    return round(float(it["percent"]), 1)
                except (KeyError, TypeError, ValueError):
                    return None
        return None

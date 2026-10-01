"""資料收集層。每個 collector 抓一個來源,寫進 cache。

失敗不拖垮其他源:base.Collector.run 會吞例外並保留舊快取。
"""
from .air import AirQualityCollector
from .anthropic_usage import AnthropicUsageCollector
from .codex_usage import CodexUsageCollector
from .funds import FundsCollector
from .fx import FxCollector
from .routine import RoutineCollector
from .steam import SteamCollector
from .stocks import StocksCollector
from .weather import WeatherCollector

COLLECTORS = [
    WeatherCollector(),
    AirQualityCollector(),
    AnthropicUsageCollector(),
    CodexUsageCollector(),
    RoutineCollector(),
    SteamCollector(),
    StocksCollector(),
    FundsCollector(),
    FxCollector(),
]

# OpenRouter 程式與設定保留,等看板需要顯示時再註冊。

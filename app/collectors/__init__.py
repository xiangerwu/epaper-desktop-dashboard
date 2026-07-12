"""資料收集層。每個 collector 抓一個來源,寫進 cache。

失敗不拖垮其他源:base.Collector.run 會吞例外並保留舊快取。
"""
from .air import AirQualityCollector
from .anthropic_usage import AnthropicUsageCollector
from .codex_usage import CodexUsageCollector
from .routine import RoutineCollector
from .weather import WeatherCollector

COLLECTORS = [
    WeatherCollector(),
    AirQualityCollector(),
    AnthropicUsageCollector(),
    CodexUsageCollector(),
    RoutineCollector(),
]

# OpenRouter 程式與設定保留,等看板需要顯示時再註冊。

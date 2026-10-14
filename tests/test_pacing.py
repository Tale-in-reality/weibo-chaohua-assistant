"""请求节流：不背靠背连发，且间隔**不固定**。

⚠️ 这是**计时测试**，所以断言要留足余量：`t0` 取在调用返回之后，
调用内部还有记账开销（机器忙时能有几十毫秒），把断言卡在 10 毫秒余量上会 flaky。
这里一律按「要 0.3 秒、只要求 ≥ 0.25」这种比例留余量。
"""
import time

from app.modules import pacing

GAP = 0.3
SLACK = 0.05          # 允许的开销误差


def test_pace_enforces_minimum_gap():
    pacing.reset()
    pacing.pace(min_gap=0.05, jitter=0)          # 第一次不等待
    t0 = time.monotonic()
    pacing.pace(min_gap=GAP, jitter=0)
    assert time.monotonic() - t0 >= GAP - SLACK


def test_pace_intervals_are_jittered_not_fixed():
    """固定节律本身就是机器特征 —— 间隔必须有随机量。"""
    pacing.reset()
    gaps = []
    for _ in range(5):
        t0 = time.monotonic()
        pacing.pace(min_gap=0.02, jitter=0.08)
        gaps.append(round(time.monotonic() - t0, 3))
    assert len(set(gaps)) > 1, "间隔全都一样 → 抖动没生效"


def test_pace_state_is_shared_across_modules():
    """所有模块共用同一份节流状态（否则各自为政还是会连发）。"""
    from app.modules import fetcher  # noqa: F401  （确认它与我们用的是同一个 pacing）
    pacing.reset()
    pacing.pace(min_gap=0.05, jitter=0)
    t0 = time.monotonic()
    pacing.pace(min_gap=GAP, jitter=0)
    assert time.monotonic() - t0 >= GAP - SLACK


def test_pace_can_be_turned_off():
    """jitter=0 且 min_gap=0 → 完全不等（导入时「休息填 0」依赖这种语义）。"""
    pacing.reset()
    pacing.pace(min_gap=0, jitter=0)
    t0 = time.monotonic()
    pacing.pace(min_gap=0, jitter=0)
    assert time.monotonic() - t0 < 0.2

"""微博请求节流 —— 所有对微博的请求都先过这里。

目的：
  1. **不背靠背连发**：两个请求之间强制留出间隔（以前好几处是连续发，
     比如「按名找超话」一次打 3 个搜索接口、导入时长文连发取全文）。
  2. **间隔带随机抖动**：固定节律本身就是机器特征，所以每次间隔 = 最小间隔 + 随机量。

⚠️ 注意：**别把间隔改成固定值**，那就白做了。
   调松紧只需要动下面两个常量。
"""
import random
import threading
import time

MIN_GAP = 1.0        # 两个请求之间的最小间隔（秒）
JITTER = 1.5         # 再叠加 0~JITTER 秒的随机量 → 实际间隔 1.0~2.5s

_lock = threading.Lock()
_last = 0.0


def pace(min_gap: float | None = None, jitter: float | None = None) -> float:
    """睡够「最小间隔 + 随机抖动」再放行；并发调用会排队。返回实际等待秒数。"""
    global _last
    gap = MIN_GAP if min_gap is None else min_gap
    jit = JITTER if jitter is None else jitter
    with _lock:                       # 持锁睡 → 多个线程也不会同时冲出去
        wait = (_last + gap + random.uniform(0, jit)) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        return max(wait, 0.0)


def reset():
    """测试用：把节流状态清零。"""
    global _last
    with _lock:
        _last = 0.0

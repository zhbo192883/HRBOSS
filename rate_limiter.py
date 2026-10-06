# -*- coding: utf-8 -*-
"""
统一风控节流器。

设计原则（稳妥优先）：
1. 每日上限：超过当日设置的条数，直接停止该模块，第二天自动重置。
2. 最小/最大间隔：每次动作之间强制随机等待，杜绝"秒回"这种最容易被识别的模式。
3. 工作时间窗口：默认只在设定的时间段内运行，夜间不操作，规避"永不下线"这种非人类特征。
4. 各模块（回复 / 复聊）分别计数、互不影响，但共享同一套判断逻辑，方便统一调参。
"""
import datetime
import random
import time


def _today_str():
    return datetime.date.today().isoformat()


class ActionLimiter:
    """
    单个动作类型（比如"AI自动回复"或"复聊唤醒"）的节流器。
    cfg: dict，需要包含 daily_max / count_key / date_key 三个字段名对应的值。
    save_cb: 每次计数变化后回调，用于把计数写回配置文件持久化。
    """

    def __init__(self, cfg: dict, daily_max_key: str, count_key: str, date_key: str, save_cb=None):
        self.cfg = cfg
        self.daily_max_key = daily_max_key
        self.count_key = count_key
        self.date_key = date_key
        self.save_cb = save_cb
        self._ensure_today()

    def _ensure_today(self):
        today = _today_str()
        if self.cfg.get(self.date_key) != today:
            self.cfg[self.date_key] = today
            self.cfg[self.count_key] = '0'
            self._persist()

    def _persist(self):
        if self.save_cb:
            try:
                self.save_cb(self.cfg)
            except Exception:
                pass

    def daily_max(self) -> int:
        try:
            return int(self.cfg.get(self.daily_max_key, 0) or 0)
        except Exception:
            return 0

    def today_count(self) -> int:
        self._ensure_today()
        try:
            return int(self.cfg.get(self.count_key, 0) or 0)
        except Exception:
            return 0

    def remaining_today(self) -> int:
        return max(0, self.daily_max() - self.today_count())

    def limit_reached(self) -> bool:
        return self.remaining_today() <= 0

    def record_action(self):
        self._ensure_today()
        n = self.today_count() + 1
        self.cfg[self.count_key] = str(n)
        self._persist()
        return n


def within_work_window(start_enabled, start_hm, end_enabled, end_hm) -> bool:
    """判断当前时间是否在允许工作的时间窗口内。任一端未启用则该端不限制。"""
    now = datetime.datetime.now().time()

    def _parse(hm):
        h, m = hm.split(':')
        return datetime.time(int(h), int(m))

    ok = True
    try:
        if str(start_enabled) == '1':
            ok = ok and now >= _parse(start_hm)
        if str(end_enabled) == '1':
            ok = ok and now <= _parse(end_hm)
    except Exception:
        pass
    return ok


def human_delay(min_s: float, max_s: float, sleep_check=None, step: float = 0.2) -> bool:
    """
    随机等待 min_s~max_s 秒，可被外部中断标志打断。
    sleep_check: 传入一个返回 True 表示"应继续睡"的回调（例如 lambda: not stop_flag）；
                 不传则直接 time.sleep。
    返回 False 表示被中断，调用方应立刻退出当前循环。
    """
    wait = random.uniform(min_s, max_s)
    if sleep_check is None:
        time.sleep(wait)
        return True
    elapsed = 0.0
    while elapsed < wait:
        if not sleep_check():
            return False
        time.sleep(min(step, wait - elapsed))
        elapsed += step
    return True


def typing_delay_for_text(text: str, per_char: float, min_s: float, max_s: float) -> float:
    """按文本长度模拟打字耗时，避免"秒回"这种最典型的机器人特征。"""
    raw = len(text or '') * per_char
    jitter = random.uniform(0.85, 1.25)
    return max(min_s, min(max_s, raw * jitter))

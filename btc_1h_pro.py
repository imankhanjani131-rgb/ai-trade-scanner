import json
import math
import os
import time
from datetime import datetime, timezone

import requests


# =========================================================
# BTC 1H PRO - CONFIG
# =========================================================

BASE_URL = "https://api.toobit.com"
SYMBOL = "BTC-SWAP-USDT"

INTERVAL = "15m"
CANDLE_MS = 15 * 60 * 1000

STATE_FILE = "btc_1h_pro_state.json"
STATE_CHANGED_FILE = "btc_1h_pro_state_changed.txt"
STATE_VERSION = 1

REQUEST_TIMEOUT = 25
SIGNAL_COOLDOWN_HOURS = 3

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    "",
).strip()

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "ai-trade-scanner-btc-1h-pro/1.0"
})


# =========================================================
# BASIC HELPERS
# =========================================================

def utc_now_ms():
    return int(
        datetime.now(timezone.utc).timestamp()
        * 1000
    )


def fmt_ms(ms):
    return datetime.fromtimestamp(
        ms / 1000,
        tz=timezone.utc,
    ).strftime("%Y-%m-%d %H:%M UTC")


def floor_ms(value, size):
    return value - (value % size)


def average(values):
    values = list(values)

    if not values:
        return 0.0

    return sum(values) / len(values)


def pct_change(current, previous):
    if not previous:
        return 0.0

    return (
        (current / previous) - 1.0
    ) * 100.0


def clamp(value, low, high):
    return max(
        low,
        min(high, value),
    )


# =========================================================
# TELEGRAM
# =========================================================

def telegram_available():
    return bool(
        TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
    )


def send_telegram(text):
    if not telegram_available():
        print("TELEGRAM: disabled")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )

        if response.ok:
            print("TELEGRAM: sent ✅")
            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:300],
        )

    except Exception as exc:
        print(
            "TELEGRAM ERROR:",
            repr(exc),
        )

    return False


# =========================================================
# HTTP / TOOBIT
# =========================================================

def request_json(
    url,
    params=None,
    retries=4,
):
    last_error = None

    for attempt in range(
        1,
        retries + 1,
    ):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            return response.json()

        except Exception as exc:
            last_error = exc

            print(
                f"REQUEST ERROR "
                f"{attempt}/{retries}: "
                f"{exc!r}"
            )

            if attempt < retries:
                time.sleep(attempt)

    raise RuntimeError(
        f"Request failed: "
        f"{last_error!r}"
    )


def get_server_time_ms():
    try:
        payload = request_json(
            f"{BASE_URL}/api/v1/time"
        )

        if (
            isinstance(payload, dict)
            and payload.get("serverTime")
            is not None
        ):
            return int(
                payload["serverTime"]
            )

    except Exception as exc:
        print(
            "SERVER TIME FALLBACK:",
            repr(exc),
        )

    return utc_now_ms()


# =========================================================
# MARKET DATA
# =========================================================

def extract_rows(payload):
    if isinstance(payload, list):
        raw = payload

    elif isinstance(payload, dict):
        raw = payload.get(
            "data",
            [],
        )

        if isinstance(raw, dict):
            raw = (
                raw.get("list")
                or raw.get("rows")
                or raw.get("klines")
                or []
            )

    else:
        raw = []

    result = {}

    for item in raw:
        if not isinstance(item, list):
            continue

        if len(item) < 6:
            continue

        try:
            candle = {
                "t": int(item[0]),
                "o": float(item[1]),
                "h": float(item[2]),
                "l": float(item[3]),
                "c": float(item[4]),
                "v": float(item[5]),
            }

        except (
            TypeError,
            ValueError,
        ):
            continue

        if min(
            candle["o"],
            candle["h"],
            candle["l"],
            candle["c"],
        ) <= 0:
            continue

        result[
            candle["t"]
        ] = candle

    return sorted(
        result.values(),
        key=lambda x: x["t"],
    )


def fetch_15m_candles(now_ms):
    end_ms = floor_ms(
        now_ms,
        CANDLE_MS,
    )

    # 1000 candles ≈ 10 days.
    start_ms = (
        end_ms
        - (1000 * CANDLE_MS)
    )

    payload = request_json(
        f"{BASE_URL}/quote/v1/klines",
        params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "startTime": start_ms,
            "endTime": end_ms - 1,
            "limit": 1000,
        },
    )

    rows = extract_rows(payload)

    rows = [
        row
        for row in rows
        if (
            start_ms
            <= row["t"]
            < end_ms
        )
    ]

    return rows


# =========================================================
# AGGREGATION
# =========================================================

def aggregate_candles(
    rows,
    bucket_ms,
):
    groups = {}

    for row in rows:
        bucket = floor_ms(
            row["t"],
            bucket_ms,
        )

        groups.setdefault(
            bucket,
            [],
        ).append(row)

    expected_count = (
        bucket_ms // CANDLE_MS
    )

    output = []

    for bucket in sorted(
        groups.keys()
    ):
        group = sorted(
            groups[bucket],
            key=lambda x: x["t"],
        )

        if len(group) != expected_count:
            continue

        expected_times = [
            bucket
            + i * CANDLE_MS
            for i in range(
                expected_count
            )
        ]

        actual_times = [
            x["t"]
            for x in group
        ]

        if (
            actual_times
            != expected_times
        ):
            continue

        candle = {
            "t": bucket,
            "o": group[0]["o"],
            "h": max(
                x["h"]
                for x in group
            ),
            "l": min(
                x["l"]
                for x in group
            ),
            "c": group[-1]["c"],
            "v": sum(
                x["v"]
                for x in group
            ),
        }

        output.append(candle)

    return output


# =========================================================
# INDICATORS
# =========================================================

def ema(values, period):
    values = list(values)

    if len(values) < period:
        return None

    alpha = 2.0 / (
        period + 1.0
    )

    result = average(
        values[:period]
    )

    for value in values[
        period:
    ]:
        result = (
            alpha * value
            + (1 - alpha) * result
        )

    return result


def rsi(values, period=14):
    values = list(values)

    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(
        1,
        len(values),
    ):
        change = (
            values[i]
            - values[i - 1]
        )

        gains.append(
            max(change, 0)
        )

        losses.append(
            max(-change, 0)
        )

    recent_gains = gains[
        -period:
    ]

    recent_losses = losses[
        -period:
    ]

    avg_gain = average(
        recent_gains
    )

    avg_loss = average(
        recent_losses
    )

    if avg_loss == 0:
        return 100.0

    rs = (
        avg_gain
        / avg_loss
    )

    return 100.0 - (
        100.0
        / (1.0 + rs)
    )


def atr(rows, period=14):
    if len(rows) <= period:
        return None

    ranges = []

    for i in range(
        1,
        len(rows),
    ):
        current = rows[i]
        previous = rows[
            i - 1
        ]

        tr = max(
            current["h"]
            - current["l"],

            abs(
                current["h"]
                - previous["c"]
            ),

            abs(
                current["l"]
                - previous["c"]
            ),
        )

        ranges.append(tr)

    return average(
        ranges[-period:]
    )


def close_strength(candle):
    candle_range = (
        candle["h"]
        - candle["l"]
    )

    if candle_range <= 0:
        return 0.5

    return (
        candle["c"]
        - candle["l"]
    ) / candle_range


def volume_ratio(
    rows,
    period=20,
):
    if len(rows) < (
        period + 1
    ):
        return 1.0

    previous = [
        x["v"]
        for x in rows[
            -(period + 1):-1
        ]
    ]

    baseline = average(
        previous
    )

    if baseline <= 0:
        return 1.0

    return (
        rows[-1]["v"]
        / baseline
    )


# =========================================================
# STRUCTURE
# =========================================================

def structure_counts(
    rows,
    lookback=5,
):
    sample = rows[
        -lookback:
    ]

    higher_highs = 0
    higher_lows = 0
    lower_highs = 0
    lower_lows = 0

    for a, b in zip(
        sample,
        sample[1:],
    ):
        if b["h"] > a["h"]:
            higher_highs += 1

        if b["l"] > a["l"]:
            higher_lows += 1

        if b["h"] < a["h"]:
            lower_highs += 1

        if b["l"] < a["l"]:
            lower_lows += 1

    return {
        "HH": higher_highs,
        "HL": higher_lows,
        "LH": lower_highs,
        "LL": lower_lows,
    }


# =========================================================
# 4H TREND ENGINE
# =========================================================

def analyze_4h(rows):
    closes = [
        x["c"]
        for x in rows
    ]

    latest = rows[-1]

    ema20 = ema(
        closes,
        20,
    )

    ema50 = ema(
        closes,
        50,
    )

    current_rsi = rsi(
        closes,
        14,
    )

    structure = (
        structure_counts(
            rows,
            5,
        )
    )

    long_score = 0
    short_score = 0

    reasons_long = []
    reasons_short = []

    if latest["c"] > ema20:
        long_score += 2
        reasons_long.append(
            "Price > EMA20"
        )

    else:
        short_score += 2
        reasons_short.append(
            "Price < EMA20"
        )

    if ema20 > ema50:
        long_score += 2
        reasons_long.append(
            "EMA20 > EMA50"
        )

    else:
        short_score += 2
        reasons_short.append(
            "EMA20 < EMA50"
        )

    if current_rsi >= 52:
        long_score += 1

    if current_rsi <= 48:
        short_score += 1

    if (
        structure["HH"] >= 2
        and structure["HL"] >= 2
    ):
        long_score += 1
        reasons_long.append(
            "Bullish structure"
        )

    if (
        structure["LH"] >= 2
        and structure["LL"] >= 2
    ):
        short_score += 1
        reasons_short.append(
            "Bearish structure"
        )

    difference = (
        long_score
        - short_score
    )

    if (
        long_score >= 4
        and difference >= 2
    ):
        bias = "LONG"

    elif (
        short_score >= 4
        and difference <= -2
    ):
        bias = "SHORT"

    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "long_score": long_score,
        "short_score": short_score,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": current_rsi,
        "structure": structure,
        "reasons_long": reasons_long,
        "reasons_short": reasons_short,
    }


# =========================================================
# 1H SETUP ENGINE
# =========================================================

def analyze_1h(
    rows,
    trend_4h,
):
    closes = [
        x["c"]
        for x in rows
    ]

    latest = rows[-1]

    ema20 = ema(
        closes,
        20,
    )

    ema50 = ema(
        closes,
        50,
    )

    ema200 = ema(
        closes,
        200,
    )

    current_rsi = rsi(
        closes,
        14,
    )

    current_atr = atr(
        rows,
        14,
    )

    vol_ratio = volume_ratio(
        rows,
        20,
    )

    strength = close_strength(
        latest
    )

    structure = (
        structure_counts(
            rows,
            5,
        )
    )

    previous_20 = rows[
        -21:-1
    ]

    previous_high = max(
        x["h"]
        for x in previous_20
    )

    previous_low = min(
        x["l"]
        for x in previous_20
    )

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    # -----------------------------------------------------
    # 4H FILTER
    # -----------------------------------------------------

    if trend_4h[
        "bias"
    ] == "LONG":

        long_score += 3

        short_score -= 2

        long_reasons.append(
            "4H bullish"
        )

    elif trend_4h[
        "bias"
    ] == "SHORT":

        short_score += 3

        long_score -= 2

        short_reasons.append(
            "4H bearish"
        )

    # -----------------------------------------------------
    # EMA STRUCTURE
    # -----------------------------------------------------

    if latest["c"] > ema20:
        long_score += 1

    else:
        short_score += 1

    if ema20 > ema50:
        long_score += 1
        long_reasons.append(
            "EMA20 > EMA50"
        )

    else:
        short_score += 1
        short_reasons.append(
            "EMA20 < EMA50"
        )

    if ema200 is not None:

        if latest["c"] > ema200:
            long_score += 1

        else:
            short_score += 1

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    if 54 <= current_rsi <= 68:
        long_score += 1
        long_reasons.append(
            "Healthy bullish RSI"
        )

    elif current_rsi > 75:
        long_score -= 2
        long_reasons.append(
            "RSI overextended"
        )

    if 32 <= current_rsi <= 46:
        short_score += 1
        short_reasons.append(
            "Healthy bearish RSI"
        )

    elif current_rsi < 25:
        short_score -= 2
        short_reasons.append(
            "RSI oversold"
        )

    # -----------------------------------------------------
    # STRUCTURE
    # -----------------------------------------------------

    if (
        structure["HH"] >= 2
        and structure["HL"] >= 2
    ):
        long_score += 2

        long_reasons.append(
            "HH + HL structure"
        )

    elif structure[
        "HL"
    ] >= 2:

        long_score += 1

    if (
        structure["LH"] >= 2
        and structure["LL"] >= 2
    ):
        short_score += 2

        short_reasons.append(
            "LH + LL structure"
        )

    elif structure[
        "LH"
    ] >= 2:

        short_score += 1

    # -----------------------------------------------------
    # BREAKOUT / BREAKDOWN
    # -----------------------------------------------------

    breakout = (
        latest["c"]
        > previous_high
    )

    breakdown = (
        latest["c"]
        < previous_low
    )

    if breakout:
        long_score += 2

        long_reasons.append(
            "1H breakout"
        )

    if breakdown:
        short_score += 2

        short_reasons.append(
            "1H breakdown"
        )

    # -----------------------------------------------------
    # CANDLE QUALITY
    # -----------------------------------------------------

    if strength >= 0.72:
        long_score += 1

        long_reasons.append(
            "Strong close"
        )

    if strength <= 0.28:
        short_score += 1

        short_reasons.append(
            "Weak close"
        )

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    if vol_ratio >= 1.30:

        if latest["c"] > latest["o"]:
            long_score += 1

            long_reasons.append(
                "Volume expansion"
            )

        elif latest["c"] < latest["o"]:
            short_score += 1

            short_reasons.append(
                "Volume expansion"
            )

    # -----------------------------------------------------
    # EMA20 PULLBACK
    # -----------------------------------------------------

    ema_touch_zone = (
        0.003
    )

    if (
        latest["l"]
        <= ema20
        * (
            1 + ema_touch_zone
        )
        and latest["c"] > ema20
        and latest["c"] > latest["o"]
    ):
        long_score += 1

        long_reasons.append(
            "Bullish EMA20 pullback"
        )

    if (
        latest["h"]
        >= ema20
        * (
            1 - ema_touch_zone
        )
        and latest["c"] < ema20
        and latest["c"] < latest["o"]
    ):
        short_score += 1

        short_reasons.append(
            "Bearish EMA20 pullback"
        )

    # -----------------------------------------------------
    # ANTI-CHASE
    # -----------------------------------------------------

    distance_from_ema20 = abs(
        latest["c"]
        - ema20
    )

    atr_distance = (
        distance_from_ema20
        / current_atr
        if current_atr
        else 0
    )

    candle_range = (
        latest["h"]
        - latest["l"]
    )

    range_atr = (
        candle_range
        / current_atr
        if current_atr
        else 0
    )

    chase_risk = False

    if atr_distance >= 1.80:
        chase_risk = True

        if latest["c"] > ema20:
            long_score -= 2

        else:
            short_score -= 2

    if range_atr >= 2.30:
        chase_risk = True

        if latest["c"] > latest["o"]:
            long_score -= 1

        else:
            short_score -= 1

    return {
        "long_score": long_score,
        "short_score": short_score,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "rsi": current_rsi,
        "atr": current_atr,
        "vol_ratio": vol_ratio,
        "close_strength": strength,
        "structure": structure,
        "breakout": breakout,
        "breakdown": breakdown,
        "chase_risk": chase_risk,
        "atr_distance": atr_distance,
        "range_atr": range_atr,
        "reasons_long": long_reasons,
        "reasons_short": short_reasons,
        "candle_time_ms": latest["t"],
        "price": latest["c"],
    }


# =========================================================
# 15M ENTRY CONFIRMATION
# =========================================================

def analyze_15m(rows):
    closes = [
        x["c"]
        for x in rows
    ]

    latest = rows[-1]

    ema20 = ema(
        closes,
        20,
    )

    current_rsi = rsi(
        closes,
        14,
    )

    vol_ratio = volume_ratio(
        rows,
        20,
    )

    strength = close_strength(
        latest
    )

    recent = rows[
        -4:
    ]

    long_score = 0
    short_score = 0

    long_reasons = []
    short_reasons = []

    if latest["c"] > ema20:
        long_score += 1

    else:
        short_score += 1

    if (
        latest["c"] > latest["o"]
        and strength >= 0.65
    ):
        long_score += 1

        long_reasons.append(
            "Strong bullish 15m close"
        )

    if (
        latest["c"] < latest["o"]
        and strength <= 0.35
    ):
        short_score += 1

        short_reasons.append(
            "Strong bearish 15m close"
        )

    higher_lows = sum(
        b["l"] > a["l"]
        for a, b in zip(
            recent,
            recent[1:],
        )
    )

    lower_highs = sum(
        b["h"] < a["h"]
        for a, b in zip(
            recent,
            recent[1:],
        )
    )

    if higher_lows >= 2:
        long_score += 1

        long_reasons.append(
            "15m higher lows"
        )

    if lower_highs >= 2:
        short_score += 1

        short_reasons.append(
            "15m lower highs"
        )

    if vol_ratio >= 1.20:

        if latest["c"] > latest["o"]:
            long_score += 1

        elif latest["c"] < latest["o"]:
            short_score += 1

    previous_8 = rows[
        -9:-1
    ]

    previous_high = max(
        x["h"]
        for x in previous_8
    )

    previous_low = min(
        x["l"]
        for x in previous_8
    )

    if latest["c"] > previous_high:
        long_score += 1

        long_reasons.append(
            "15m breakout"
        )

    if latest["c"] < previous_low:
        short_score += 1

        short_reasons.append(
            "15m breakdown"
        )

    if (
        52 <= current_rsi <= 72
    ):
        long_score += 1

    if (
        28 <= current_rsi <= 48
    ):
        short_score += 1

    return {
        "long_score": long_score,
        "short_score": short_score,
        "ema20": ema20,
        "rsi": current_rsi,
        "vol_ratio": vol_ratio,
        "close_strength": strength,
        "price": latest["c"],
        "time_ms": latest["t"],
        "reasons_long": long_reasons,
        "reasons_short": short_reasons,
    }


# =========================================================
# TRADE PLAN
# =========================================================

def build_trade_plan(
    side,
    rows_15m,
    setup_1h,
):
    entry = rows_15m[-1][
        "c"
    ]

    current_atr = setup_1h[
        "atr"
    ]

    recent = rows_15m[
        -8:
    ]

    if side == "LONG":

        local_low = min(
            x["l"]
            for x in recent
        )

        structure_sl = (
            local_low * 0.998
        )

        atr_sl = (
            entry
            - current_atr * 1.15
        )

        # Use the closer protective stop.
        sl = max(
            structure_sl,
            atr_sl,
        )

        risk = entry - sl

    else:

        local_high = max(
            x["h"]
            for x in recent
        )

        structure_sl = (
            local_high * 1.002
        )

        atr_sl = (
            entry
            + current_atr * 1.15
        )

        sl = min(
            structure_sl,
            atr_sl,
        )

        risk = sl - entry

    if risk <= 0:
        return None

    risk_pct = (
        risk / entry
    ) * 100

    # Avoid absurdly tight or overly wide stops.
    if (
        risk_pct < 0.25
        or risk_pct > 2.50
    ):
        return None

    if side == "LONG":

        tp1 = entry + risk * 1.0
        tp2 = entry + risk * 1.8
        tp3 = entry + risk * 2.8

    else:

        tp1 = entry - risk * 1.0
        tp2 = entry - risk * 1.8
        tp3 = entry - risk * 2.8

    return {
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk_pct": risk_pct,
    }


# =========================================================
# FINAL DECISION
# =========================================================

def make_decision(
    trend_4h,
    setup_1h,
    entry_15m,
    rows_15m,
):
    long_score = setup_1h[
        "long_score"
    ]

    short_score = setup_1h[
        "short_score"
    ]

    long_confirm = entry_15m[
        "long_score"
    ]

    short_confirm = entry_15m[
        "short_score"
    ]

    long_edge = (
        long_score
        - short_score
    )

    short_edge = (
        short_score
        - long_score
    )

    side = "NO TRADE"

    if (
        long_score >= 7
        and long_edge >= 3
        and long_confirm >= 3
        and trend_4h["bias"]
        != "SHORT"
    ):
        side = "LONG"

    elif (
        short_score >= 7
        and short_edge >= 3
        and short_confirm >= 3
        and trend_4h["bias"]
        != "LONG"
    ):
        side = "SHORT"

    if side == "NO TRADE":

        return {
            "signal": "NO TRADE",
            "reason":
                "Conditions are not strong enough.",
            "plan": None,
            "strength": 0,
        }

    if (
        setup_1h[
            "chase_risk"
        ]
    ):
        return {
            "signal": "NO TRADE",
            "reason":
                "Anti-Chase blocked the setup.",
            "plan": None,
            "strength": 0,
        }

    plan = build_trade_plan(
        side,
        rows_15m,
        setup_1h,
    )

    if plan is None:
        return {
            "signal": "NO TRADE",
            "reason":
                "Stop-loss structure is not acceptable.",
            "plan": None,
            "strength": 0,
        }

    if side == "LONG":

        directional_score = (
            long_score
        )

        confirm_score = (
            long_confirm
        )

        edge = long_edge

    else:

        directional_score = (
            short_score
        )

        confirm_score = (
            short_confirm
        )

        edge = short_edge

    # This is a setup-strength score,
    # NOT a calibrated probability.
    strength = (
        55
        + max(
            0,
            directional_score - 7
        ) * 5
        + max(
            0,
            confirm_score - 3
        ) * 4
        + max(
            0,
            edge - 3
        ) * 3
    )

    strength = int(
        clamp(
            strength,
            55,
            90,
        )
    )

    return {
        "signal": side,
        "reason":
            "Multi-timeframe confirmation",
        "plan": plan,
        "strength": strength,
    }


# =========================================================
# STATE
# =========================================================

def default_state():
    return {
        "state_version":
            STATE_VERSION,

        "telegram_setup_notified":
            False,

        "last_signal_side":
            None,

        "last_signal_ms":
            0,

        "last_signal_key":
            None,
    }


def load_state():
    if not os.path.exists(
        STATE_FILE
    ):
        return default_state()

    with open(
        STATE_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        state = json.load(f)

    if (
        state.get(
            "state_version"
        )
        != STATE_VERSION
    ):
        return default_state()

    return state


def save_state(state):
    temp = (
        STATE_FILE + ".tmp"
    )

    with open(
        temp,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    os.replace(
        temp,
        STATE_FILE,
    )


def state_signature(state):
    return json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def write_state_changed(
    changed,
):
    with open(
        STATE_CHANGED_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        f.write(
            "YES"
            if changed
            else "NO"
        )


# =========================================================
# TELEGRAM MESSAGES
# =========================================================

def setup_message():
    return (
        "₿ BTC 1H PRO CONNECTED ✅\n\n"
        "BTC-only signal engine is active.\n\n"
        "4H Trend Filter\n"
        "↓\n"
        "1H Setup Engine\n"
        "↓\n"
        "15m Entry Confirmation\n\n"
        "Output:\n"
        "LONG / SHORT / NO TRADE\n\n"
        "⚠️ SHADOW MODE\n"
        "No real orders are placed."
    )


def signal_message(
    decision,
    trend_4h,
    setup_1h,
    entry_15m,
    now_ms,
):
    signal = decision[
        "signal"
    ]

    plan = decision[
        "plan"
    ]

    icon = (
        "🟢"
        if signal == "LONG"
        else "🔴"
    )

    if signal == "LONG":

        reasons = setup_1h[
            "reasons_long"
        ]

        confirm = entry_15m[
            "long_score"
        ]

        one_hour_score = (
            setup_1h[
                "long_score"
            ]
        )

    else:

        reasons = setup_1h[
            "reasons_short"
        ]

        confirm = entry_15m[
            "short_score"
        ]

        one_hour_score = (
            setup_1h[
                "short_score"
            ]
        )

    reason_text = ", ".join(
        reasons[:5]
    )

    return (
        f"{icon} BTC 1H PRO — {signal}\n\n"
        f"BTC/USDT\n"
        f"4H Bias: "
        f"{trend_4h['bias']}\n\n"

        f"1H Score: "
        f"{one_hour_score}\n"

        f"15m Confirm: "
        f"{confirm}\n"

        f"RSI 1H: "
        f"{setup_1h['rsi']:.1f}\n"

        f"Volume: "
        f"{setup_1h['vol_ratio']:.2f}x\n\n"

        f"Entry: "
        f"{plan['entry']:.2f}\n"

        f"SL: "
        f"{plan['sl']:.2f}\n"

        f"TP1: "
        f"{plan['tp1']:.2f}\n"

        f"TP2: "
        f"{plan['tp2']:.2f}\n"

        f"TP3: "
        f"{plan['tp3']:.2f}\n\n"

        f"Risk distance: "
        f"{plan['risk_pct']:.2f}%\n"

        f"Setup Strength: "
        f"{decision['strength']}/100\n\n"

        f"Logic: {reason_text}\n\n"

        f"Time: {fmt_ms(now_ms)}\n\n"

        "⚠️ SHADOW MODE\n"
        "No real trade was opened."
    )


# =========================================================
# NOTIFICATION CONTROL
# =========================================================

def should_notify(
    state,
    decision,
    setup_1h,
    now_ms,
):
    signal = decision[
        "signal"
    ]

    if signal not in (
        "LONG",
        "SHORT",
    ):
        return False

    signal_key = (
        f"{signal}:"
        f"{setup_1h['candle_time_ms']}"
    )

    if (
        state.get(
            "last_signal_key"
        )
        == signal_key
    ):
        return False

    last_signal_ms = int(
        state.get(
            "last_signal_ms",
            0,
        )
        or 0
    )

    last_side = state.get(
        "last_signal_side"
    )

    cooldown_ms = (
        SIGNAL_COOLDOWN_HOURS
        * 60
        * 60
        * 1000
    )

    if (
        last_side == signal
        and last_signal_ms > 0
        and (
            now_ms - last_signal_ms
        ) < cooldown_ms
    ):
        return False

    state[
        "last_signal_key"
    ] = signal_key

    state[
        "last_signal_side"
    ] = signal

    state[
        "last_signal_ms"
    ] = now_ms

    return True


# =========================================================
# PRINT SUMMARY
# =========================================================

def print_summary(
    trend_4h,
    setup_1h,
    entry_15m,
    decision,
):
    print()
    print(
        "#" * 80
    )

    print(
        "BTC 1H PRO SUMMARY"
    )

    print(
        "#" * 80
    )

    print(
        "4H Bias:",
        trend_4h["bias"],
    )

    print(
        "4H LONG:",
        trend_4h[
            "long_score"
        ],
        "| SHORT:",
        trend_4h[
            "short_score"
        ],
    )

    print()

    print(
        "1H LONG score:",
        setup_1h[
            "long_score"
        ],
    )

    print(
        "1H SHORT score:",
        setup_1h[
            "short_score"
        ],
    )

    print(
        "1H RSI:",
        f"{setup_1h['rsi']:.2f}",
    )

    print(
        "1H Volume ratio:",
        f"{setup_1h['vol_ratio']:.2f}x",
    )

    print(
        "1H ATR:",
        f"{setup_1h['atr']:.2f}",
    )

    print(
        "Anti-Chase:",
        setup_1h[
            "chase_risk"
        ],
    )

    print()

    print(
        "15m LONG confirm:",
        entry_15m[
            "long_score"
        ],
    )

    print(
        "15m SHORT confirm:",
        entry_15m[
            "short_score"
        ],
    )

    print()

    print(
        "FINAL DECISION:",
        decision[
            "signal"
        ],
    )

    print(
        "Reason:",
        decision[
            "reason"
        ],
    )

    if decision[
        "plan"
    ]:

        plan = decision[
            "plan"
        ]

        print()
        print(
            "Entry:",
            f"{plan['entry']:.2f}",
        )

        print(
            "SL:",
            f"{plan['sl']:.2f}",
        )

        print(
            "TP1:",
            f"{plan['tp1']:.2f}",
        )

        print(
            "TP2:",
            f"{plan['tp2']:.2f}",
        )

        print(
            "TP3:",
            f"{plan['tp3']:.2f}",
        )

        print(
            "Strength:",
            f"{decision['strength']}/100",
        )


# =========================================================
# MAIN
# =========================================================

def main():
    print(
        "BTC 1H PRO V1"
    )

    print(
        "BTC-only signal engine"
    )

    print(
        "4H Trend → "
        "1H Setup → "
        "15m Entry"
    )

    print(
        "LONG / SHORT / NO TRADE"
    )

    print(
        "SHADOW MODE ONLY"
    )

    print()

    now_ms = (
        get_server_time_ms()
    )

    print(
        "Toobit/server time:",
        fmt_ms(now_ms),
    )

    print(
        "Telegram available:",
        telegram_available(),
    )

    state = load_state()

    before = state_signature(
        state
    )

    # -----------------------------------------------------
    # First Telegram confirmation
    # -----------------------------------------------------

    if not state.get(
        "telegram_setup_notified",
        False,
    ):

        if send_telegram(
            setup_message()
        ):
            state[
                "telegram_setup_notified"
            ] = True

    print()
    print(
        "Downloading BTC candles..."
    )

    rows_15m = fetch_15m_candles(
        now_ms
    )

    print(
        "15m candles:",
        len(rows_15m),
    )

    if len(rows_15m) < 850:
        raise RuntimeError(
            "Not enough 15m BTC data."
        )

    rows_1h = aggregate_candles(
        rows_15m,
        60 * 60 * 1000,
    )

    rows_4h = aggregate_candles(
        rows_15m,
        4 * 60 * 60 * 1000,
    )

    print(
        "1H candles:",
        len(rows_1h),
    )

    print(
        "4H candles:",
        len(rows_4h),
    )

    if len(rows_1h) < 200:
        raise RuntimeError(
            "Not enough complete 1H candles."
        )

    if len(rows_4h) < 50:
        raise RuntimeError(
            "Not enough complete 4H candles."
        )

    # -----------------------------------------------------
    # ANALYSIS
    # -----------------------------------------------------

    trend_4h = analyze_4h(
        rows_4h
    )

    setup_1h = analyze_1h(
        rows_1h,
        trend_4h,
    )

    entry_15m = analyze_15m(
        rows_15m
    )

    decision = make_decision(
        trend_4h,
        setup_1h,
        entry_15m,
        rows_15m,
    )

    print_summary(
        trend_4h,
        setup_1h,
        entry_15m,
        decision,
    )

    # -----------------------------------------------------
    # TELEGRAM SIGNAL
    # -----------------------------------------------------

    if should_notify(
        state,
        decision,
        setup_1h,
        now_ms,
    ):

        send_telegram(
            signal_message(
                decision,
                trend_4h,
                setup_1h,
                entry_15m,
                now_ms,
            )
        )

    else:

        print()
        print(
            "No new Telegram signal."
        )

    # -----------------------------------------------------
    # SAVE STATE
    # -----------------------------------------------------

    after = state_signature(
        state
    )

    changed = (
        before != after
    )

    if changed:
        save_state(
            state
        )

    write_state_changed(
        changed
    )

    print()
    print(
        "STATE_CHANGED:",
        (
            "YES"
            if changed
            else "NO"
        ),
    )

    print(
        "Telegram:",
        (
            "ENABLED"
            if telegram_available()
            else "DISABLED"
        ),
    )

    print(
        "No real orders are placed."
    )


if __name__ == "__main__":
    main()

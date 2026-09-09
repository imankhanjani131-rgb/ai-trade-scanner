import time
from datetime import datetime, timedelta, timezone

import requests


BASE = "https://api.toobit.com"
TIMEOUT = 25

TESTS = {
    "PONS": {
        "symbol": "PONS-SWAP-USDT",
        "listing_date": "2026-09-07",
    },
    "CAPAPP": {
        "symbol": "CAPAPP-SWAP-USDT",
        "listing_date": "2026-06-29",
    },
    "GRAM": {
        "symbol": "GRAM-SWAP-USDT",
        "listing_date": "2026-07-02",
    },
    "DATAIP": {
        "symbol": "DATAIP-SWAP-USDT",
        "listing_date": "2026-07-03",
    },
    "ZEST": {
        "symbol": "ZEST-SWAP-USDT",
        "listing_date": "2026-06-05",
    },
    "BTW": {
        "symbol": "BTW-SWAP-USDT",
        "listing_date": "2026-06-05",
    },
}


def to_ms(dt):
    return int(dt.timestamp() * 1000)


def avg(values):
    return sum(values) / len(values) if values else 0.0


def pct(a, b):
    if not b:
        return 0.0
    return ((a / b) - 1.0) * 100.0


def fmt_time(ms_value):
    return datetime.fromtimestamp(
        ms_value / 1000,
        tz=timezone.utc,
    ).strftime("%Y-%m-%d %H:%M UTC")


def request_json(url, params=None, retries=4):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            r = requests.get(
                url,
                params=params,
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            return r.json()

        except Exception as exc:
            last_error = exc

            print(
                f"REQUEST ERROR "
                f"{attempt}/{retries}: "
                f"{repr(exc)}"
            )

            if attempt < retries:
                time.sleep(attempt)

    raise RuntimeError(
        f"Request failed: {last_error!r}"
    )


def extract_rows(payload):
    if isinstance(payload, list):
        raw = payload

    elif isinstance(payload, dict):
        raw = payload.get("data", [])

        if isinstance(raw, dict):
            raw = (
                raw.get("list")
                or raw.get("rows")
                or raw.get("klines")
                or []
            )

    else:
        raw = []

    rows = []

    for item in raw:
        if not isinstance(item, list):
            continue

        if len(item) < 6:
            continue

        try:
            row = {
                "t": int(item[0]),
                "o": float(item[1]),
                "h": float(item[2]),
                "l": float(item[3]),
                "c": float(item[4]),
                "v": float(item[5]),
            }

        except (TypeError, ValueError):
            continue

        if min(
            row["o"],
            row["h"],
            row["l"],
            row["c"],
        ) <= 0:
            continue

        rows.append(row)

    rows.sort(
        key=lambda x: x["t"]
    )

    return rows


def fetch_symbol(symbol, listing_date):
    start = datetime.fromisoformat(
        listing_date
    ).replace(
        tzinfo=timezone.utc
    )

    end = min(
        start + timedelta(days=7),
        datetime.now(timezone.utc),
    )

    payload = request_json(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": "15m",
            "startTime": to_ms(start),
            "endTime": to_ms(end),
            "limit": 1000,
        },
    )

    return extract_rows(payload)


def first_trade_index(rows):
    for i, row in enumerate(rows):
        if row["v"] > 0:
            return i

    return None


def base_features(sample):
    first_price = sample[0]["o"]
    price = sample[-1]["c"]

    high = max(
        x["h"] for x in sample
    )

    low = min(
        x["l"] for x in sample
    )

    recent = sample[-4:]

    prior = (
        sample[-8:-4]
        if len(sample) >= 8
        else []
    )

    recent_vol = avg(
        [x["v"] for x in recent]
    )

    prior_vol = (
        avg([x["v"] for x in prior])
        if prior
        else recent_vol
    )

    vol_ratio = (
        recent_vol / prior_vol
        if prior_vol > 0
        else 1.0
    )

    higher_lows = sum(
        b["l"] > a["l"]
        for a, b in zip(
            recent,
            recent[1:],
        )
    )

    higher_highs = sum(
        b["h"] > a["h"]
        for a, b in zip(
            recent,
            recent[1:],
        )
    )

    sma4 = avg(
        [x["c"] for x in recent]
    )

    gain = pct(
        price,
        first_price,
    )

    pullback = pct(
        price,
        high,
    )

    range_pos = (
        (price - low)
        / (high - low)
        if high > low
        else 0.5
    )

    score = 0

    if price > sma4:
        score += 1

    if higher_lows >= 2:
        score += 2

    if higher_highs >= 2:
        score += 1

    if vol_ratio >= 1.50:
        score += 2

    elif vol_ratio >= 1.15:
        score += 1

    if 3 <= gain <= 45:
        score += 1

    if range_pos >= 0.65:
        score += 1

    if pullback <= -15:
        score -= 3

    if gain >= 80:
        score -= 2

    if gain <= -12:
        score -= 3

    return {
        "score": score,
        "price": price,
        "gain": gain,
        "vol_ratio": vol_ratio,
    }


def momentum_features(sample):
    if len(sample) < 4:
        return None

    c = sample[:4]

    first_half = c[:2]
    second_half = c[2:]

    vol1 = avg(
        [x["v"] for x in first_half]
    )

    vol2 = avg(
        [x["v"] for x in second_half]
    )

    vol_accel = (
        vol2 / vol1
        if vol1 > 0
        else 1.0
    )

    high = max(
        x["h"] for x in c
    )

    low = min(
        x["l"] for x in c
    )

    close = c[-1]["c"]

    close_strength = (
        (close - low)
        / (high - low)
        if high > low
        else 0.5
    )

    first_half_high = max(
        x["h"]
        for x in first_half
    )

    first_half_close = max(
        x["c"]
        for x in first_half
    )

    breakout = (
        c[-1]["h"] > first_half_high
        or c[-1]["c"] > first_half_close
    )

    second_half_green = sum(
        x["c"] > x["o"]
        for x in second_half
    )

    higher_low = (
        second_half[-1]["l"]
        >= second_half[0]["l"]
    )

    gain = pct(
        c[-1]["c"],
        c[0]["o"],
    )

    points = 0

    if vol_accel >= 1.10:
        points += 2

    elif vol_accel >= 0.95:
        points += 1

    if close_strength >= 0.72:
        points += 2

    elif close_strength >= 0.58:
        points += 1

    if breakout:
        points += 2

    if second_half_green >= 1:
        points += 1

    if higher_low:
        points += 1

    if 0.3 <= gain <= 25:
        points += 1

    if gain >= 35:
        points -= 2

    return {
        "vol_accel": vol_accel,
        "close_strength": close_strength,
        "breakout": breakout,
        "points": points,
        "gain": gain,
    }


def classify_v12(base, momentum, hour):
    score = base["score"]

    if score >= 6:
        return (
            "READY LONG",
            "BASE_SCORE",
        )

    rescue_ready = (
        hour == 1
        and momentum is not None
        and momentum["points"] >= 6
        and momentum["breakout"]
        and momentum["vol_accel"] >= 1.10
        and momentum["close_strength"] >= 0.58
        and 0 < momentum["gain"] <= 1.50
        and score <= 4
    )

    if rescue_ready:
        return (
            "READY LONG",
            "MOMENTUM_RESCUE",
        )

    if score >= 4:
        return (
            "EARLY SETUP",
            "BASE",
        )

    if hour >= 4:
        return (
            "REJECT",
            "BASE",
        )

    return (
        "WAIT",
        "BASE",
    )


def future_stats(
    candles,
    entry_index,
    entry,
    hours=72,
):
    max_bars = hours * 4

    future = candles[
        entry_index + 1:
        entry_index + 1 + max_bars
    ]

    if not future:
        return {
            "max_up": 0.0,
            "max_down": 0.0,
        }

    high = max(
        x["h"] for x in future
    )

    low = min(
        x["l"] for x in future
    )

    return {
        "max_up": pct(
            high,
            entry,
        ),
        "max_down": pct(
            low,
            entry,
        ),
    }


def target_before_stop(
    candles,
    entry_index,
    entry,
    hours=72,
):
    stop_price = (
        entry * 0.92
    )

    tp1 = (
        entry * 1.10
    )

    tp2 = (
        entry * 1.20
    )

    tp3 = (
        entry * 1.30
    )

    future = candles[
        entry_index + 1:
        entry_index + 1 + hours * 4
    ]

    best_target = 0

    for candle in future:

        # اگر در یک کندل هم SL و هم TP لمس شوند،
        # محافظه‌کارانه SL را اول حساب می‌کنیم.
        if candle["l"] <= stop_price:

            if best_target == 0:
                return "STOP_BEFORE_TP"

            return (
                f"TP{best_target}_THEN_STOP"
            )

        if (
            best_target < 3
            and candle["h"] >= tp3
        ):
            best_target = 3

        elif (
            best_target < 2
            and candle["h"] >= tp2
        ):
            best_target = 2

        elif (
            best_target < 1
            and candle["h"] >= tp1
        ):
            best_target = 1

    if best_target == 3:
        return "TP3"

    if best_target == 2:
        return "TP2"

    if best_target == 1:
        return "TP1"

    return "NO_TP_NO_STOP"


def evaluate_symbol(candles):
    checkpoints = []

    for hour in (1, 2, 4):

        needed = hour * 4

        if len(candles) < needed:
            continue

        sample = candles[:needed]

        base = base_features(
            sample
        )

        momentum = (
            momentum_features(sample)
            if hour == 1
            else None
        )

        label, route = classify_v12(
            base,
            momentum,
            hour,
        )

        stats = future_stats(
            candles,
            needed - 1,
            base["price"],
        )

        checkpoints.append({
            "hour": hour,
            "label": label,
            "route": route,
            "score": base["score"],
            "entry": base["price"],
            "gain": base["gain"],
            "max_up": stats["max_up"],
            "max_down": stats["max_down"],
            "momentum": momentum,
            "entry_index": needed - 1,
        })

    return checkpoints


def first_ready(checkpoints):
    for item in checkpoints:
        if item["label"] == "READY LONG":
            return item

    return None


def classify_signal_quality(result):
    up = result["max_up"]
    down = result["max_down"]

    if up >= 20:
        return "STRONG"

    if up >= 10:
        return "GOOD"

    if up >= 5:
        return "WEAK"

    if down <= -8:
        return "BAD"

    return "FLAT"


def main():
    print(
        "NEW LISTING HUNTER V1.2 "
        "- UNSEEN VALIDATION"
    )

    print(
        "No tuning symbols are included "
        "in this batch."
    )

    print(
        "READY signal evaluation window: "
        "72 hours"
    )

    print(
        "Diagnostic SL: -8%"
    )

    print(
        "Diagnostic targets: "
        "+10% / +20% / +30%"
    )

    print()

    ready_count = 0
    strong_good = 0
    bad_count = 0
    missed_pumps = 0
    usable_symbols = 0

    results = {}

    for token, meta in TESTS.items():

        print("=" * 88)
        print(token)
        print("=" * 88)

        try:
            rows = fetch_symbol(
                meta["symbol"],
                meta["listing_date"],
            )

        except Exception as exc:
            print(
                "DATA ERROR:",
                repr(exc),
            )
            print()
            continue

        first_i = first_trade_index(
            rows
        )

        if first_i is None:
            print("NO DATA")
            print()
            continue

        candles = rows[first_i:]

        usable_symbols += 1

        print(
            "First traded candle:",
            fmt_time(
                candles[0]["t"]
            ),
        )

        print(
            "First price:",
            candles[0]["o"],
        )

        print(
            "15m candles:",
            len(candles),
        )

        checkpoints = evaluate_symbol(
            candles
        )

        results[token] = checkpoints

        for item in checkpoints:

            line = (
                f"{item['hour']}H"
                f" | {item['label']}"
                f" | Route {item['route']}"
                f" | Score {item['score']}"
                f" | Entry {item['entry']:.8g}"
                f" | From launch {item['gain']:+.2f}%"
                f" | 72H max {item['max_up']:+.2f}%"
                f" | 72H DD {item['max_down']:+.2f}%"
            )

            if (
                item["hour"] == 1
                and item["momentum"]
                is not None
            ):

                m = item["momentum"]

                line += (
                    f" | VolAccel "
                    f"{m['vol_accel']:.2f}x"
                    f" | CloseStrength "
                    f"{m['close_strength']:.2f}"
                    f" | MomPts "
                    f"{m['points']}"
                    f" | Breakout "
                    f"{m['breakout']}"
                )

            print(line)

        ready = first_ready(
            checkpoints
        )

        if ready is not None:

            ready_count += 1

            quality = (
                classify_signal_quality(
                    ready
                )
            )

            path = target_before_stop(
                candles,
                ready["entry_index"],
                ready["entry"],
            )

            if quality in (
                "STRONG",
                "GOOD",
            ):
                strong_good += 1

            if quality == "BAD":
                bad_count += 1

            print(
                "DECISION: READY at "
                f"{ready['hour']}H"
                f" via {ready['route']}"
            )

            print(
                "QUALITY:",
                quality,
            )

            print(
                "TARGET/STOP PATH:",
                path,
            )

        else:
            print(
                "DECISION: NO READY LONG"
            )

            if checkpoints:
                ref = checkpoints[-1]

                if ref["max_up"] >= 15:
                    missed_pumps += 1

                    print(
                        "MISSED PUMP: YES "
                        f"({ref['max_up']:+.2f}% "
                        "after last checkpoint)"
                    )

                else:
                    print(
                        "MISSED PUMP: NO"
                    )

        print()
        time.sleep(0.4)

    print()
    print("#" * 88)
    print("UNSEEN SUMMARY")
    print("#" * 88)

    print(
        "Usable symbols:",
        usable_symbols,
    )

    print(
        "READY signals:",
        ready_count,
    )

    print(
        "GOOD or STRONG READY:",
        strong_good,
    )

    print(
        "BAD READY:",
        bad_count,
    )

    print(
        "Missed pumps >=15%:",
        missed_pumps,
    )

    if ready_count > 0:

        precision = (
            strong_good
            / ready_count
            * 100
        )

        print(
            "READY quality rate:",
            f"{precision:.1f}%",
        )

    else:
        print(
            "READY quality rate: N/A"
        )

    print()

    print(
        "PASS GUIDE:"
    )

    print(
        "- Prefer READY quality rate >= 60%"
    )

    print(
        "- Prefer BAD READY <= 1"
    )

    print(
        "- Prefer missed pumps reasonably low"
    )

    print()

    print(
        "IMPORTANT: "
        "This is diagnostic validation only. "
        "The -8% SL and +10/+20/+30% targets "
        "are comparison rules, not live trade advice."
    )


if __name__ == "__main__":
    main()

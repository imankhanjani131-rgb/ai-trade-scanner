import time
from datetime import datetime, timezone, timedelta

import requests

BASE = "https://api.toobit.com"
TIMEOUT = 25

TESTS = {
    "RE-SWAP-USDT": "2026-06-18",
    "GRVT-SWAP-USDT": "2026-08-03",
    "DOS-SWAP-USDT": "2026-08-12",
    "MARSCOIN-SWAP-USDT": "2026-09-01",
    "CASHCAT-SWAP-USDT": "2026-09-04",
}


def to_ms(dt):
    return int(dt.timestamp() * 1000)


def fetch_window(symbol, date_text, days=7):
    start = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=days)

    response = requests.get(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": "15m",
            "startTime": to_ms(start),
            "endTime": to_ms(end),
            "limit": 1000,
        },
        timeout=TIMEOUT,
    )

    response.raise_for_status()
    raw = response.json()

    rows = []

    for x in raw:
        if not isinstance(x, list) or len(x) < 7:
            continue

        try:
            row = {
                "t": int(x[0]),
                "o": float(x[1]),
                "h": float(x[2]),
                "l": float(x[3]),
                "c": float(x[4]),
                "v": float(x[5]),
                "ct": int(x[6]),
            }
        except (TypeError, ValueError):
            continue

        if (
            row["o"] <= 0
            or row["h"] <= 0
            or row["l"] <= 0
            or row["c"] <= 0
        ):
            continue

        rows.append(row)

    rows.sort(
        key=lambda r: r["t"]
    )

    return rows


def find_launch_index(rows):
    for i, row in enumerate(rows):
        if row["v"] > 0:
            return i

    return None


def score_checkpoint(candles, hour):
    needed = hour * 4
    sample = candles[:needed]

    if len(sample) < needed:
        return None

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

    gain = (
        (price / first_price) - 1
    ) * 100

    pullback = (
        (price / high) - 1
    ) * 100 if high > 0 else 0

    recent_volume = (
        sum(x["v"] for x in recent)
        / len(recent)
    )

    prior_volume = (
        sum(x["v"] for x in prior)
        / len(prior)
        if prior
        else recent_volume
    )

    volume_ratio = (
        recent_volume / prior_volume
        if prior_volume > 0
        else 1.0
    )

    higher_lows = sum(
        b["l"] > a["l"]
        for a, b in zip(
            recent,
            recent[1:]
        )
    )

    higher_highs = sum(
        b["h"] > a["h"]
        for a, b in zip(
            recent,
            recent[1:]
        )
    )

    sma4 = (
        sum(x["c"] for x in recent)
        / len(recent)
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

    if volume_ratio >= 1.50:
        score += 2
    elif volume_ratio >= 1.15:
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

    if score >= 6:
        label = "READY LONG"
    elif score >= 4:
        label = "EARLY SETUP"
    elif hour >= 4:
        label = "REJECT"
    else:
        label = "WAIT"

    return {
        "hour": hour,
        "score": score,
        "label": label,
        "entry": price,
        "gain_from_launch": gain,
        "pullback": pullback,
        "volume_ratio": volume_ratio,
        "entry_index": needed - 1,
    }


def future_stats(candles, checkpoint):
    start_index = (
        checkpoint["entry_index"]
        + 1
    )

    future = candles[
        start_index:
    ]

    if not future:
        return {
            "max_up": 0.0,
            "max_down": 0.0,
            "max_high": checkpoint["entry"],
            "min_low": checkpoint["entry"],
        }

    entry = checkpoint["entry"]

    max_high = max(
        x["h"] for x in future
    )

    min_low = min(
        x["l"] for x in future
    )

    return {
        "max_up": (
            (max_high / entry) - 1
        ) * 100,

        "max_down": (
            (min_low / entry) - 1
        ) * 100,

        "max_high": max_high,
        "min_low": min_low,
    }


def fmt_time(ms):
    return datetime.fromtimestamp(
        ms / 1000,
        tz=timezone.utc,
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def run_symbol(symbol, date_text):
    print()
    print("=" * 72)
    print(symbol)
    print("=" * 72)

    try:
        rows = fetch_window(
            symbol,
            date_text,
            days=7
        )

    except Exception as exc:
        print(
            "DATA ERROR:",
            repr(exc)
        )
        return []

    if not rows:
        print("NO DATA")
        return []

    launch_i = find_launch_index(
        rows
    )

    if launch_i is None:
        print(
            "NO TRADED CANDLES"
        )
        return []

    candles = rows[
        launch_i:
    ]

    print(
        "First traded candle:",
        fmt_time(
            candles[0]["t"]
        )
    )

    print(
        "First price:",
        candles[0]["o"]
    )

    print(
        "15m candles available:",
        len(candles)
    )

    results = []

    for hour in (1, 2, 4):

        checkpoint = score_checkpoint(
            candles,
            hour
        )

        if checkpoint is None:
            print(
                f"{hour}H | "
                "NOT ENOUGH DATA"
            )
            continue

        future = future_stats(
            candles,
            checkpoint
        )

        checkpoint.update(
            future
        )

        results.append(
            checkpoint
        )

        print(
            f"{hour}H | "
            f"{checkpoint['label']} | "
            f"Score {checkpoint['score']} | "
            f"Entry {checkpoint['entry']:.8g} | "
            f"From launch "
            f"{checkpoint['gain_from_launch']:+.2f}% | "
            f"Vol "
            f"{checkpoint['volume_ratio']:.2f}x | "
            f"Future max "
            f"{checkpoint['max_up']:+.2f}% | "
            f"Future drawdown "
            f"{checkpoint['max_down']:+.2f}%"
        )

    ready = [
        x for x in results
        if x["score"] >= 6
    ]

    if ready:
        first_ready = ready[0]

        print(
            "DECISION: FIRST READY = "
            f"{first_ready['hour']}H | "
            "Potential after entry: "
            f"{first_ready['max_up']:+.2f}%"
        )

    else:
        early = [
            x for x in results
            if x["score"] >= 4
        ]

        if early:
            first_early = early[0]

            print(
                "DECISION: NO READY LONG; "
                "first EARLY = "
                f"{first_early['hour']}H"
            )

        else:
            print(
                "DECISION: "
                "REJECT / NO LONG SIGNAL"
            )

    return results


def main():
    print(
        "NEW LISTING HUNTER V1 - REPLAY"
    )

    print(
        "Window: first 7 days "
        "after listing date"
    )

    print(
        "Logic: same 1H / 2H / 4H "
        "score used by Hunter"
    )

    all_results = {}

    for symbol, date_text in TESTS.items():

        all_results[
            symbol
        ] = run_symbol(
            symbol,
            date_text
        )

        time.sleep(0.4)

    print()
    print("#" * 72)
    print("SUMMARY")
    print("#" * 72)

    total_best = 0.0
    ready_count = 0

    for symbol, results in all_results.items():

        ready = [
            x for x in results
            if x["score"] >= 6
        ]

        if ready:
            first_ready = ready[0]

            ready_count += 1

            total_best += max(
                0.0,
                first_ready["max_up"]
            )

            print(
                f"{symbol}: "
                f"READY at "
                f"{first_ready['hour']}H | "
                f"future max "
                f"{first_ready['max_up']:+.2f}%"
            )

        else:
            print(
                f"{symbol}: "
                "NO READY LONG"
            )

    print("-" * 72)

    print(
        f"READY symbols: "
        f"{ready_count}/{len(TESTS)}"
    )

    print(
        "Sum of post-signal maximum moves "
        f"(not account return): "
        f"{total_best:.2f}%"
    )

    print(
        "NOTE: This is a replay diagnostic, "
        "not proof that the exact high could "
        "have been captured in live trading."
    )


if __name__ == "__main__":
    main()

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


def ms(dt):
    return int(dt.timestamp() * 1000)


def avg(values):
    return sum(values) / len(values) if values else 0.0


def pct(a, b):
    return ((a / b) - 1) * 100 if b else 0.0


def fetch(symbol, date_text):
    start = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=7)

    r = requests.get(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": "15m",
            "startTime": ms(start),
            "endTime": ms(end),
            "limit": 1000,
        },
        timeout=TIMEOUT,
    )

    r.raise_for_status()
    rows = []

    for x in r.json():
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
            }
        except (TypeError, ValueError):
            continue

        if min(row["o"], row["h"], row["l"], row["c"]) <= 0:
            continue

        rows.append(row)

    rows.sort(key=lambda z: z["t"])
    return rows


def first_trade(rows):
    for i, row in enumerate(rows):
        if row["v"] > 0:
            return i
    return None


def base_features(sample):
    first = sample[0]["o"]
    price = sample[-1]["c"]
    high = max(x["h"] for x in sample)
    low = min(x["l"] for x in sample)

    recent = sample[-4:]
    prior = sample[-8:-4] if len(sample) >= 8 else []

    recent_vol = avg([x["v"] for x in recent])
    prior_vol = avg([x["v"] for x in prior]) if prior else recent_vol

    vol_ratio = recent_vol / prior_vol if prior_vol > 0 else 1.0

    higher_lows = sum(
        b["l"] > a["l"]
        for a, b in zip(recent, recent[1:])
    )

    higher_highs = sum(
        b["h"] > a["h"]
        for a, b in zip(recent, recent[1:])
    )

    sma4 = avg([x["c"] for x in recent])
    gain = pct(price, first)
    pullback = pct(price, high)

    range_pos = (
        (price - low) / (high - low)
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


def one_hour_momentum(sample, base_score):
    c = sample[:4]

    first_half = c[:2]
    second_half = c[2:]

    vol1 = avg([x["v"] for x in first_half])
    vol2 = avg([x["v"] for x in second_half])

    vol_accel = vol2 / vol1 if vol1 > 0 else 1.0

    high = max(x["h"] for x in c)
    low = min(x["l"] for x in c)
    close = c[-1]["c"]

    close_strength = (
        (close - low) / (high - low)
        if high > low
        else 0.5
    )

    first_half_high = max(x["h"] for x in first_half)
    first_half_close = max(x["c"] for x in first_half)

    breakout = (
        c[-1]["h"] > first_half_high
        or c[-1]["c"] > first_half_close
    )

    second_half_green = sum(
        x["c"] > x["o"]
        for x in second_half
    )

    higher_low = second_half[-1]["l"] >= second_half[0]["l"]
    gain = pct(c[-1]["c"], c[0]["o"])

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

    rescue_ready = (
        points >= 6
        and breakout
        and vol_accel >= 1.10
        and close_strength >= 0.58
        and 0 < gain <= 1.50
        and base_score <= 4
    )

    return {
        "points": points,
        "vol_accel": vol_accel,
        "close_strength": close_strength,
        "breakout": breakout,
        "gain": gain,
        "ready": rescue_ready,
    }


def checkpoint(candles, hour):
    needed = hour * 4

    if len(candles) < needed:
        return None

    sample = candles[:needed]
    f = base_features(sample)

    route = "BASE"
    mom = None

    if hour == 1:
        mom = one_hour_momentum(sample, f["score"])

    if f["score"] >= 6:
        label = "READY LONG"
        route = "BASE_SCORE"

    elif hour == 1 and mom and mom["ready"]:
        label = "READY LONG"
        route = "MOMENTUM_RESCUE"

    elif f["score"] >= 4:
        label = "EARLY SETUP"

    elif hour >= 4:
        label = "REJECT"

    else:
        label = "WAIT"

    return {
        "hour": hour,
        "label": label,
        "route": route,
        "v1": f["score"],
        "v12": f["score"],
        "entry": f["price"],
        "gain": f["gain"],
        "mom": mom,
        "entry_index": needed - 1,
    }


def future_stats(candles, cp):
    future = candles[cp["entry_index"] + 1:]

    if not future:
        return 0.0, 0.0

    high = max(x["h"] for x in future)
    low = min(x["l"] for x in future)

    return pct(high, cp["entry"]), pct(low, cp["entry"])


def run_symbol(symbol, date_text):
    print()
    print("=" * 86)
    print(symbol)
    print("=" * 86)

    try:
        rows = fetch(symbol, date_text)
    except Exception as e:
        print("DATA ERROR:", repr(e))
        return []

    if not rows:
        print("NO DATA")
        return []

    idx = first_trade(rows)

    if idx is None:
        print("NO TRADED CANDLES")
        return []

    candles = rows[idx:]

    launch_time = datetime.fromtimestamp(
        candles[0]["t"] / 1000,
        tz=timezone.utc,
    ).strftime("%Y-%m-%d %H:%M UTC")

    print("First traded candle:", launch_time)
    print("First price:", candles[0]["o"])
    print("15m candles available:", len(candles))

    results = []

    for hour in (1, 2, 4):
        cp = checkpoint(candles, hour)

        if cp is None:
            print(f"{hour}H | NOT ENOUGH DATA")
            continue

        up, dd = future_stats(candles, cp)

        cp["max_up"] = up
        cp["max_down"] = dd

        extra = ""

        if hour == 1 and cp["mom"]:
            m = cp["mom"]

            extra = (
                f" | VolAccel {m['vol_accel']:.2f}x"
                f" | CloseStrength {m['close_strength']:.2f}"
                f" | MomPts {m['points']}"
                f" | Breakout {m['breakout']}"
                f" | RescueGain {m['gain']:+.2f}%"
            )

        print(
            f"{hour}H | {cp['label']}"
            f" | Route {cp['route']}"
            f" | V1 {cp['v1']}"
            f" | V1.2 {cp['v12']}"
            f" | Entry {cp['entry']:.8g}"
            f" | From launch {cp['gain']:+.2f}%"
            f" | Future max {up:+.2f}%"
            f" | Future DD {dd:+.2f}%"
            f"{extra}"
        )

        results.append(cp)

    ready = [
        x for x in results
        if x["label"] == "READY LONG"
    ]

    if ready:
        first = ready[0]

        print(
            "DECISION: READY at "
            f"{first['hour']}H via {first['route']}"
        )
    else:
        print("DECISION: NO READY LONG")

    return results


def main():
    print("NEW LISTING HUNTER V1.2 - REPLAY")
    print("Base score cannot be boosted from 5 to 6.")
    print("Momentum route is a strict 1H rescue only.")
    print("Live Hunter is NOT changed.")

    all_results = {}

    for symbol, date_text in TESTS.items():
        all_results[symbol] = run_symbol(symbol, date_text)
        time.sleep(0.4)

    print()
    print("#" * 86)
    print("SUMMARY")
    print("#" * 86)

    for symbol, results in all_results.items():
        ready = [
            x for x in results
            if x["label"] == "READY LONG"
        ]

        if ready:
            first = ready[0]

            print(
                f"{symbol}: READY at {first['hour']}H"
                f" via {first['route']}"
                f" | future max {first['max_up']:+.2f}%"
            )
        else:
            print(f"{symbol}: NO READY LONG")

    print()
    print("#" * 86)
    print("TARGET CHECK")
    print("#" * 86)

    targets = {
        "MARSCOIN-SWAP-USDT": True,
        "GRVT-SWAP-USDT": True,
        "DOS-SWAP-USDT": False,
        "CASHCAT-SWAP-USDT": False,
    }

    passed = 0

    for symbol, expected in targets.items():
        results = all_results.get(symbol, [])

        actual = any(
            x["label"] == "READY LONG"
            for x in results
        )

        ok = actual == expected

        if ok:
            passed += 1

        print(
            f"{symbol}: "
            f"expected={'READY' if expected else 'NO READY'}"
            f" | actual={'READY' if actual else 'NO READY'}"
            f" | {'PASS' if ok else 'FAIL'}"
        )

    print("-" * 86)
    print(f"TARGET SCORE: {passed}/4")

    if passed == 4:
        print(
            "RESULT: PASS on this small diagnostic set. "
            "Do NOT move it live yet. "
            "Next step: test a larger unseen listing sample."
        )
    else:
        print(
            "RESULT: NOT READY for live use. "
            "Keep the live Hunter unchanged."
        )

    print(
        "NOTE: Future max is diagnostic only, "
        "not realized trading profit."
    )


if __name__ == "__main__":
    main()

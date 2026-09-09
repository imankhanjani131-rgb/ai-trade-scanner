import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import requests


BASE = "https://api.toobit.com"
TIMEOUT = 25

TESTS = {
    "RE": {
        "symbol": "RE-SWAP-USDT",
        "listing_date": "2026-06-18",
    },
    "GRVT": {
        "symbol": "GRVT-SWAP-USDT",
        "listing_date": "2026-08-03",
    },
    "DOS": {
        "symbol": "DOS-SWAP-USDT",
        "listing_date": "2026-08-12",
    },
    "MARSCOIN": {
        "symbol": "MARSCOIN-SWAP-USDT",
        "listing_date": "2026-09-01",
    },
    "CASHCAT": {
        "symbol": "CASHCAT-SWAP-USDT",
        "listing_date": "2026-09-04",
    },
}

TARGETS = {
    "GRVT": True,
    "DOS": False,
    "MARSCOIN": True,
    "CASHCAT": False,
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
            response = requests.get(
                url,
                params=params,
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            return response.json()

        except Exception as exc:
            last_error = exc
            print(
                f"REQUEST ERROR {attempt}/{retries}: {repr(exc)}"
            )

            if attempt < retries:
                time.sleep(attempt)

    raise RuntimeError(
        f"Request failed after {retries} attempts: {last_error!r}"
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

    rows.sort(key=lambda x: x["t"])
    return rows


def fetch_symbol_once(symbol, listing_date):
    start = datetime.fromisoformat(
        listing_date
    ).replace(tzinfo=timezone.utc)

    end = start + timedelta(days=7)

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


def data_hash(rows):
    compact = [
        [
            x["t"],
            x["o"],
            x["h"],
            x["l"],
            x["c"],
            x["v"],
        ]
        for x in rows
    ]

    raw = json.dumps(
        compact,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(raw).hexdigest()


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

    if len(sample) >= 8:
        prior = sample[-8:-4]
    else:
        prior = []

    recent_vol = avg(
        [x["v"] for x in recent]
    )

    if prior:
        prior_vol = avg(
            [x["v"] for x in prior]
        )
    else:
        prior_vol = recent_vol

    if prior_vol > 0:
        vol_ratio = recent_vol / prior_vol
    else:
        vol_ratio = 1.0

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

    if high > low:
        range_pos = (
            (price - low)
            / (high - low)
        )
    else:
        range_pos = 0.5

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

    candles = sample[:4]

    first_half = candles[:2]
    second_half = candles[2:]

    vol1 = avg(
        [x["v"] for x in first_half]
    )

    vol2 = avg(
        [x["v"] for x in second_half]
    )

    if vol1 > 0:
        vol_accel = vol2 / vol1
    else:
        vol_accel = 1.0

    high = max(
        x["h"] for x in candles
    )

    low = min(
        x["l"] for x in candles
    )

    close = candles[-1]["c"]

    if high > low:
        close_strength = (
            (close - low)
            / (high - low)
        )
    else:
        close_strength = 0.5

    first_half_high = max(
        x["h"] for x in first_half
    )

    first_half_close = max(
        x["c"] for x in first_half
    )

    breakout = (
        candles[-1]["h"] > first_half_high
        or candles[-1]["c"] > first_half_close
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
        candles[-1]["c"],
        candles[0]["o"],
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


def classify_v1(base, hour):
    score = base["score"]

    if score >= 6:
        return (
            "READY LONG",
            "BASE_SCORE",
            score,
        )

    if score >= 4:
        return (
            "EARLY SETUP",
            "BASE",
            score,
        )

    if hour >= 4:
        return (
            "REJECT",
            "BASE",
            score,
        )

    return (
        "WAIT",
        "BASE",
        score,
    )


def classify_v11(base, momentum, hour):
    score = base["score"]

    if (
        hour == 1
        and momentum is not None
        and momentum["vol_accel"] >= 1.25
    ):
        score += 1

    if score >= 6:
        return (
            "READY LONG",
            "BASE_SCORE",
            score,
        )

    momentum_ready = (
        hour == 1
        and momentum is not None
        and momentum["points"] >= 6
        and momentum["breakout"]
        and momentum["close_strength"] >= 0.58
        and momentum["gain"] > 0
    )

    if momentum_ready:
        return (
            "READY LONG",
            "MOMENTUM_BREAKOUT",
            score,
        )

    if score >= 4:
        return (
            "EARLY SETUP",
            "BASE",
            score,
        )

    if hour >= 4:
        return (
            "REJECT",
            "BASE",
            score,
        )

    return (
        "WAIT",
        "BASE",
        score,
    )


def classify_v12(base, momentum, hour):
    score = base["score"]

    if score >= 6:
        return (
            "READY LONG",
            "BASE_SCORE",
            score,
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
            score,
        )

    if score >= 4:
        return (
            "EARLY SETUP",
            "BASE",
            score,
        )

    if hour >= 4:
        return (
            "REJECT",
            "BASE",
            score,
        )

    return (
        "WAIT",
        "BASE",
        score,
    )


def future_stats(candles, entry_index, entry):
    future = candles[
        entry_index + 1:
    ]

    if not future:
        return 0.0, 0.0

    high = max(
        x["h"] for x in future
    )

    low = min(
        x["l"] for x in future
    )

    return (
        pct(high, entry),
        pct(low, entry),
    )


def evaluate(candles):
    results = {
        "V1": [],
        "V1.1": [],
        "V1.2": [],
    }

    for hour in (1, 2, 4):
        needed = hour * 4

        if len(candles) < needed:
            continue

        sample = candles[:needed]

        base = base_features(
            sample
        )

        if hour == 1:
            momentum = momentum_features(
                sample
            )
        else:
            momentum = None

        future_max, future_dd = future_stats(
            candles,
            needed - 1,
            base["price"],
        )

        v1_label, v1_route, v1_score = classify_v1(
            base,
            hour,
        )

        v11_label, v11_route, v11_score = classify_v11(
            base,
            momentum,
            hour,
        )

        v12_label, v12_route, v12_score = classify_v12(
            base,
            momentum,
            hour,
        )

        common = {
            "hour": hour,
            "entry": base["price"],
            "gain": base["gain"],
            "future_max": future_max,
            "future_dd": future_dd,
        }

        results["V1"].append({
            **common,
            "label": v1_label,
            "route": v1_route,
            "score": v1_score,
        })

        results["V1.1"].append({
            **common,
            "label": v11_label,
            "route": v11_route,
            "score": v11_score,
            "momentum": momentum,
        })

        results["V1.2"].append({
            **common,
            "label": v12_label,
            "route": v12_route,
            "score": v12_score,
            "momentum": momentum,
        })

    return results


def first_ready(items):
    for item in items:
        if item["label"] == "READY LONG":
            return item

    return None


def print_version(version, items):
    print()
    print(f"[{version}]")

    for item in items:
        line = (
            f"{item['hour']}H"
            f" | {item['label']}"
            f" | Route {item['route']}"
            f" | Score {item['score']}"
            f" | Entry {item['entry']:.8g}"
            f" | From launch {item['gain']:+.2f}%"
            f" | Future max {item['future_max']:+.2f}%"
            f" | Future DD {item['future_dd']:+.2f}%"
        )

        momentum = item.get(
            "momentum"
        )

        if (
            item["hour"] == 1
            and momentum is not None
        ):
            line += (
                f" | VolAccel {momentum['vol_accel']:.2f}x"
                f" | CloseStrength {momentum['close_strength']:.2f}"
                f" | MomPts {momentum['points']}"
                f" | Breakout {momentum['breakout']}"
            )

        print(line)

    ready = first_ready(items)

    if ready is None:
        print(
            f"DECISION {version}: NO READY LONG"
        )
    else:
        print(
            f"DECISION {version}: "
            f"READY at {ready['hour']}H "
            f"via {ready['route']}"
        )


def main():
    print(
        "NEW LISTING HUNTER - SAME DATA COMPARISON"
    )
    print(
        "Each symbol is fetched ONCE."
    )
    print(
        "V1 / V1.1 / V1.2 use identical candles."
    )
    print(
        "Live Hunter is NOT changed."
    )
    print()

    all_results = {}

    for token, meta in TESTS.items():
        print("=" * 90)
        print(token)
        print("=" * 90)

        try:
            rows = fetch_symbol_once(
                meta["symbol"],
                meta["listing_date"],
            )

        except Exception as exc:
            print(
                "DATA ERROR:",
                repr(exc),
            )
            all_results[token] = None
            print()
            continue

        first_i = first_trade_index(
            rows
        )

        if first_i is None:
            print("NO DATA")
            all_results[token] = None
            print()
            continue

        candles = rows[first_i:]

        print(
            "Symbol:",
            meta["symbol"],
        )

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

        print(
            "DATA SHA256:",
            data_hash(candles),
        )

        versions = evaluate(
            candles
        )

        all_results[token] = versions

        print_version(
            "V1",
            versions["V1"],
        )

        print_version(
            "V1.1",
            versions["V1.1"],
        )

        print_version(
            "V1.2",
            versions["V1.2"],
        )

        print()
        time.sleep(0.4)

    print()
    print("#" * 90)
    print("TARGET SCORE BY VERSION")
    print("#" * 90)

    for version in (
        "V1",
        "V1.1",
        "V1.2",
    ):
        print()
        print(version)

        passed = 0
        total = 0

        for token, expected in TARGETS.items():
            versions = all_results.get(
                token
            )

            if versions is None:
                print(
                    f"{token}: NO DATA | EXCLUDED"
                )
                continue

            actual = (
                first_ready(
                    versions[version]
                )
                is not None
            )

            ok = (
                actual == expected
            )

            total += 1

            if ok:
                passed += 1

            print(
                f"{token}: "
                f"expected="
                f"{'READY' if expected else 'NO READY'}"
                f" | actual="
                f"{'READY' if actual else 'NO READY'}"
                f" | {'PASS' if ok else 'FAIL'}"
            )

        print(
            f"{version} TARGET SCORE: "
            f"{passed}/{total}"
        )

    print()
    print("#" * 90)
    print("IMPORTANT")
    print("#" * 90)

    print(
        "All versions were compared on identical "
        "candles inside the same run."
    )

    print(
        "Future max is diagnostic only, "
        "not realized trading profit."
    )


if __name__ == "__main__":
    main()

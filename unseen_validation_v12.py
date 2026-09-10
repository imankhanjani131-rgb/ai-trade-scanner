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

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ai-trade-scanner-v12-unseen-validation/2.0"
})


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
            response = SESSION.get(
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
                time.sleep(1.2 * attempt)

    raise RuntimeError(
        f"Request failed after {retries} attempts: {last_error!r}"
    )


def extract_contract_items(payload):
    if not isinstance(payload, dict):
        return []

    for key in ("contracts", "symbols"):
        items = payload.get(key)
        if isinstance(items, list):
            return items

    data = payload.get("data")

    if isinstance(data, dict):
        for key in ("contracts", "symbols"):
            items = data.get(key)
            if isinstance(items, list):
                return items

    return []


def fetch_contracts():
    payload = request_json(
        f"{BASE}/api/v1/exchangeInfo"
    )
    return extract_contract_items(payload)


def resolve_symbol(wanted_symbol, token, contracts):
    wanted = wanted_symbol.upper()
    token = token.upper()

    symbols = []

    for item in contracts:
        if not isinstance(item, dict):
            continue

        if item.get("isRwa") is True:
            continue

        symbol = str(
            item.get("symbol", "")
        ).upper()

        if symbol:
            symbols.append(symbol)

    if wanted in symbols:
        return wanted, []

    candidates = [
        symbol
        for symbol in symbols
        if token in symbol
        and symbol.endswith("-SWAP-USDT")
    ]

    if len(candidates) == 1:
        return candidates[0], candidates

    return wanted, candidates


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

    return rows


def fetch_chunk(symbol, start_dt, end_dt):
    payload = request_json(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": "15m",
            "startTime": to_ms(start_dt),
            "endTime": to_ms(end_dt),
            "limit": 1000,
        },
    )

    return extract_rows(payload)


def fetch_symbol(symbol, listing_date):
    start = datetime.fromisoformat(
        listing_date
    ).replace(
        tzinfo=timezone.utc
    )

    now = datetime.now(
        timezone.utc
    )

    end = min(
        start + timedelta(days=7),
        now,
    )

    if end <= start:
        return []

    chunk_size = timedelta(
        hours=12
    )

    cursor = start
    by_time = {}

    while cursor < end:
        chunk_end = min(
            cursor + chunk_size,
            end,
        )

        try:
            rows = fetch_chunk(
                symbol,
                cursor,
                chunk_end,
            )

        except Exception as exc:
            print(
                "CHUNK ERROR:",
                cursor.isoformat(),
                "->",
                chunk_end.isoformat(),
                repr(exc),
            )
            rows = []

        for row in rows:
            if (
                to_ms(start)
                <= row["t"]
                <= to_ms(end)
            ):
                by_time[row["t"]] = row

        cursor = chunk_end
        time.sleep(0.08)

    return sorted(
        by_time.values(),
        key=lambda x: x["t"],
    )


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

    candles = sample[:4]

    first_half = candles[:2]
    second_half = candles[2:]

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
        x["h"] for x in candles
    )

    low = min(
        x["l"] for x in candles
    )

    close = candles[-1]["c"]

    close_strength = (
        (close - low)
        / (high - low)
        if high > low
        else 0.5
    )

    first_half_high = max(
        x["h"] for x in first_half
    )

    first_half_close = max(
        x["c"] for x in first_half
    )

    breakout = (
        candles[-1]["h"] > first_half_high
        or
        candles[-1]["c"] > first_half_close
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
    future = candles[
        entry_index + 1:
        entry_index + 1 + hours * 4
    ]

    if not future:
        return {
            "max_up": 0.0,
            "max_down": 0.0,
        }

    highest = max(
        x["h"] for x in future
    )

    lowest = min(
        x["l"] for x in future
    )

    return {
        "max_up": pct(
            highest,
            entry,
        ),
        "max_down": pct(
            lowest,
            entry,
        ),
    }


def target_stop_path(
    candles,
    entry_index,
    entry,
    hours=72,
):
    stop_price = entry * 0.92

    target_prices = {
        10: entry * 1.10,
        15: entry * 1.15,
        20: entry * 1.20,
        30: entry * 1.30,
    }

    future = candles[
        entry_index + 1:
        entry_index + 1 + hours * 4
    ]

    best_target = 0

    for candle in future:

        if candle["l"] <= stop_price:

            if best_target == 0:
                return {
                    "best_target": 0,
                    "stopped": True,
                    "label": "STOP -8% BEFORE +10%",
                }

            return {
                "best_target": best_target,
                "stopped": True,
                "label": (
                    f"+{best_target}% THEN STOP -8%"
                ),
            }

        for target in (
            10,
            15,
            20,
            30,
        ):
            if (
                candle["h"]
                >= target_prices[target]
            ):
                best_target = max(
                    best_target,
                    target,
                )

    if best_target > 0:
        return {
            "best_target": best_target,
            "stopped": False,
            "label": (
                f"+{best_target}% NO -8% STOP"
            ),
        }

    return {
        "best_target": 0,
        "stopped": False,
        "label": "NO +10% / NO -8%",
    }


def ready_quality(path):
    best = path["best_target"]

    if best >= 20:
        return "STRONG"

    if best >= 10:
        return "GOOD"

    if path["stopped"]:
        return "BAD"

    return "FLAT"


def evaluate_symbol(candles):
    checkpoints = []

    for hour in (
        1,
        2,
        4,
    ):
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

        path = target_stop_path(
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
            "path": path,
        })

    return checkpoints


def first_ready(checkpoints):
    for item in checkpoints:
        if item["label"] == "READY LONG":
            return item

    return None


def best_missed_opportunity(
    checkpoints,
):
    best_item = None
    best_target = 0

    for item in checkpoints:

        path = item["path"]

        target = path[
            "best_target"
        ]

        if target > best_target:
            best_target = target
            best_item = item

    if (
        best_item is not None
        and best_target >= 15
    ):
        return best_item

    return None


def main():
    print(
        "NEW LISTING HUNTER V1.2 "
        "- UNSEEN VALIDATION V2"
    )

    print(
        "V1.2 logic is NOT changed."
    )

    print(
        "NO-READY opportunities are now "
        "checked on 1H / 2H / 4H."
    )

    print(
        "Path rule: target must happen "
        "BEFORE diagnostic -8% stop."
    )

    print(
        "Evaluation window: 72 hours."
    )

    print()

    try:
        contracts = fetch_contracts()

        print(
            "Contracts discovered:",
            len(contracts),
        )

    except Exception as exc:
        print(
            "EXCHANGE INFO ERROR:",
            repr(exc),
        )
        contracts = []

    print()

    usable_symbols = 0
    ready_count = 0
    good_or_strong = 0
    bad_ready = 0
    missed_pumps = 0
    no_data_count = 0

    for token, meta in TESTS.items():

        print("=" * 92)
        print(token)
        print("=" * 92)

        resolved, candidates = (
            resolve_symbol(
                meta["symbol"],
                token,
                contracts,
            )
        )

        print(
            "Requested symbol:",
            meta["symbol"],
        )

        print(
            "Resolved symbol:",
            resolved,
        )

        if candidates:
            print(
                "Matching candidates:",
                ", ".join(candidates),
            )

        try:
            rows = fetch_symbol(
                resolved,
                meta["listing_date"],
            )

        except Exception as exc:
            print(
                "DATA ERROR:",
                repr(exc),
            )

            no_data_count += 1

            print()
            continue

        first_i = first_trade_index(
            rows
        )

        if first_i is None:
            print("NO DATA")

            no_data_count += 1

            print()
            continue

        candles = rows[
            first_i:
        ]

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

        for item in checkpoints:

            line = (
                f"{item['hour']}H"
                f" | {item['label']}"
                f" | Route {item['route']}"
                f" | Score {item['score']}"
                f" | Entry {item['entry']:.8g}"
                f" | Launch {item['gain']:+.2f}%"
                f" | 72H max {item['max_up']:+.2f}%"
                f" | 72H DD {item['max_down']:+.2f}%"
                f" | Path {item['path']['label']}"
            )

            momentum = item[
                "momentum"
            ]

            if (
                item["hour"] == 1
                and momentum is not None
            ):
                line += (
                    f" | VolAccel "
                    f"{momentum['vol_accel']:.2f}x"
                    f" | CloseStrength "
                    f"{momentum['close_strength']:.2f}"
                    f" | MomPts "
                    f"{momentum['points']}"
                    f" | Breakout "
                    f"{momentum['breakout']}"
                )

            print(line)

        ready = first_ready(
            checkpoints
        )

        if ready is not None:

            ready_count += 1

            quality = ready_quality(
                ready["path"]
            )

            if quality in (
                "GOOD",
                "STRONG",
            ):
                good_or_strong += 1

            if quality == "BAD":
                bad_ready += 1

            print(
                "DECISION: READY at "
                f"{ready['hour']}H "
                f"via {ready['route']}"
            )

            print(
                "READY PATH:",
                ready["path"]["label"],
            )

            print(
                "READY QUALITY:",
                quality,
            )

        else:
            print(
                "DECISION: NO READY LONG"
            )

            missed = (
                best_missed_opportunity(
                    checkpoints
                )
            )

            if missed is not None:

                missed_pumps += 1

                print(
                    "MISSED OPPORTUNITY: YES"
                )

                print(
                    "BEST MISSED CHECKPOINT:",
                    f"{missed['hour']}H",
                )

                print(
                    "MISSED PATH:",
                    missed["path"]["label"],
                )

            else:
                print(
                    "MISSED OPPORTUNITY: NO"
                )

        print()

        time.sleep(0.25)

    print()
    print("#" * 92)
    print("UNSEEN SUMMARY V2")
    print("#" * 92)

    print(
        "Requested symbols:",
        len(TESTS),
    )

    print(
        "Usable symbols:",
        usable_symbols,
    )

    print(
        "NO DATA symbols:",
        no_data_count,
    )

    print(
        "READY signals:",
        ready_count,
    )

    print(
        "GOOD or STRONG READY:",
        good_or_strong,
    )

    print(
        "BAD READY:",
        bad_ready,
    )

    print(
        "Missed opportunities "
        ">=15% before -8%:",
        missed_pumps,
    )

    if ready_count > 0:

        quality_rate = (
            good_or_strong
            / ready_count
            * 100
        )

        print(
            "READY quality rate:",
            f"{quality_rate:.1f}%",
        )

    else:
        print(
            "READY quality rate: N/A"
        )

    print()

    if usable_symbols < 5:

        print(
            "VALIDATION STATUS: "
            "INSUFFICIENT SAMPLE"
        )

        print(
            "Need at least 5 usable "
            "unseen symbols before judging V1.2."
        )

    else:

        if (
            ready_count > 0
            and (
                good_or_strong
                / ready_count
                >= 0.60
            )
            and bad_ready <= 1
        ):
            print(
                "VALIDATION STATUS: "
                "PROMISING"
            )

        else:
            print(
                "VALIDATION STATUS: "
                "NOT PASSED"
            )

    print()

    print(
        "IMPORTANT:"
    )

    print(
        "The -8% stop and "
        "+10/+15/+20/+30% levels "
        "are diagnostic comparison rules."
    )

    print(
        "They are not live trading advice."
    )


if __name__ == "__main__":
    main()

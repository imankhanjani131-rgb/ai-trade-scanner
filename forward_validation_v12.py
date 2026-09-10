import json
import os
import time
from datetime import datetime, timezone

import requests


BASE = "https://api.toobit.com"
TIMEOUT = 25

STATE_FILE = "forward_validation_state.json"
STATE_CHANGED_FILE = "forward_state_changed.txt"
STATE_VERSION = 1

INTERVAL = "15m"
CANDLE_MS = 15 * 60 * 1000

CHECKPOINT_HOURS = (1, 2, 4)
FINALIZE_AFTER_HOURS = 76

DIAGNOSTIC_STOP_PCT = -8
TARGETS = (10, 15, 20, 30)
MISSED_THRESHOLD = 15

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    "",
).strip()


EXCLUDED_TOKENS = {
    "RE",
    "GRVT",
    "DOS",
    "MARSCOIN",
    "CASHCAT",
    "PONS",
    "CAPAPP",
    "GRAM",
    "DATAIP",
    "ZEST",
    "BTW",
}


SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent":
        "ai-trade-scanner-forward-validation-v12-telegram/2.0"
})


def from_ms(value):
    return datetime.fromtimestamp(
        value / 1000,
        tz=timezone.utc,
    )


def fmt_ms(value):
    return from_ms(value).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def floor_15m(value):
    return value - (value % CANDLE_MS)


def avg(values):
    if not values:
        return 0.0
    return sum(values) / len(values)


def pct(a, b):
    if not b:
        return 0.0
    return ((a / b) - 1.0) * 100.0


def telegram_available():
    return bool(
        TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
    )


def send_telegram(text):
    if not telegram_available():
        print(
            "TELEGRAM: disabled "
            "(secrets not available)"
        )
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
        )
        return False

    except Exception as exc:
        print(
            "TELEGRAM ERROR:",
            repr(exc),
        )
        return False


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
                timeout=TIMEOUT,
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
                time.sleep(
                    1.0 * attempt
                )

    raise RuntimeError(
        f"Request failed after "
        f"{retries} attempts: "
        f"{last_error!r}"
    )


def get_server_time_ms():
    try:
        payload = request_json(
            f"{BASE}/api/v1/time"
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

    return int(
        datetime.now(
            timezone.utc
        ).timestamp()
        * 1000
    )


def get_contracts():
    payload = request_json(
        f"{BASE}/api/v1/exchangeInfo"
    )

    if not isinstance(
        payload,
        dict,
    ):
        return []

    contracts = payload.get(
        "contracts"
    )

    if isinstance(
        contracts,
        list,
    ):
        return contracts

    data = payload.get("data")

    if (
        isinstance(data, dict)
        and isinstance(
            data.get("contracts"),
            list,
        )
    ):
        return data["contracts"]

    return []


def normalize_categories(item):
    raw = item.get(
        "categories",
        [],
    )

    if not isinstance(
        raw,
        list,
    ):
        return []

    return [
        str(x).strip()
        for x in raw
        if str(x).strip()
    ]


def token_from_symbol(symbol):
    suffix = "-SWAP-USDT"

    if symbol.endswith(suffix):
        return symbol[
            :-len(suffix)
        ]

    return symbol


def is_crypto_usdt_contract(item):
    if not isinstance(
        item,
        dict,
    ):
        return False

    symbol = str(
        item.get("symbol", "")
    ).upper()

    status = str(
        item.get("status", "")
    ).upper()

    quote = str(
        item.get("quoteAsset", "")
    ).upper()

    categories = " ".join(
        x.upper()
        for x in normalize_categories(
            item
        )
    )

    if not symbol.endswith(
        "-SWAP-USDT"
    ):
        return False

    if status != "TRADING":
        return False

    if (
        quote
        and quote != "USDT"
    ):
        return False

    if item.get("inverse") is True:
        return False

    if item.get("isRwa") is True:
        return False

    if str(
        item.get(
            "rwaType",
            "",
        )
    ).strip():
        return False

    blocked = (
        "TRADFI",
        "STOCK",
        "FOREX",
        "COMMODITY",
        "RWA",
    )

    if any(
        word in categories
        for word in blocked
    ):
        return False

    return True


def contract_map(contracts):
    result = {}

    for item in contracts:
        if not is_crypto_usdt_contract(
            item
        ):
            continue

        symbol = str(
            item.get("symbol", "")
        ).upper()

        token = token_from_symbol(
            symbol
        )

        if token in EXCLUDED_TOKENS:
            continue

        result[symbol] = {
            "symbol": symbol,
            "token": token,
            "categories":
                normalize_categories(
                    item
                ),
        }

    return result


def extract_rows(payload):
    if isinstance(
        payload,
        list,
    ):
        raw = payload

    elif isinstance(
        payload,
        dict,
    ):
        raw = payload.get(
            "data",
            [],
        )

        if isinstance(
            raw,
            dict,
        ):
            raw = (
                raw.get("list")
                or raw.get("rows")
                or raw.get("klines")
                or []
            )

    else:
        raw = []

    by_time = {}

    for item in raw:
        if not isinstance(
            item,
            list,
        ):
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

        except (
            TypeError,
            ValueError,
        ):
            continue

        if min(
            row["o"],
            row["h"],
            row["l"],
            row["c"],
        ) <= 0:
            continue

        by_time[
            row["t"]
        ] = row

    return sorted(
        by_time.values(),
        key=lambda x: x["t"],
    )


def fetch_klines(
    symbol,
    start_ms,
    end_ms,
):
    if end_ms <= start_ms:
        return []

    payload = request_json(
        f"{BASE}/quote/v1/klines",
        params={
            "symbol": symbol,
            "interval": INTERVAL,
            "startTime":
                int(start_ms),
            "endTime":
                int(end_ms - 1),
            "limit": 1000,
        },
    )

    rows = extract_rows(
        payload
    )

    return [
        row
        for row in rows
        if (
            start_ms
            <= row["t"]
            < end_ms
        )
    ]


def base_features(sample):
    first_price = sample[0]["o"]
    price = sample[-1]["c"]

    high = max(
        x["h"]
        for x in sample
    )

    low = min(
        x["l"]
        for x in sample
    )

    recent = sample[-4:]

    prior = (
        sample[-8:-4]
        if len(sample) >= 8
        else []
    )

    recent_vol = avg(
        [
            x["v"]
            for x in recent
        ]
    )

    prior_vol = (
        avg(
            [
                x["v"]
                for x in prior
            ]
        )
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
        [
            x["c"]
            for x in recent
        ]
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
        "vol_ratio":
            vol_ratio,
    }


def momentum_features(sample):
    if len(sample) < 4:
        return None

    candles = sample[:4]

    first_half = candles[:2]
    second_half = candles[2:]

    vol1 = avg(
        [
            x["v"]
            for x in first_half
        ]
    )

    vol2 = avg(
        [
            x["v"]
            for x in second_half
        ]
    )

    vol_accel = (
        vol2 / vol1
        if vol1 > 0
        else 1.0
    )

    high = max(
        x["h"]
        for x in candles
    )

    low = min(
        x["l"]
        for x in candles
    )

    close = candles[-1]["c"]

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
        candles[-1]["h"]
        > first_half_high
        or
        candles[-1]["c"]
        > first_half_close
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
        "vol_accel":
            vol_accel,
        "close_strength":
            close_strength,
        "breakout":
            breakout,
        "points":
            points,
        "gain":
            gain,
    }


def classify_v12(
    base,
    momentum,
    hour,
):
    score = base["score"]

    if score >= 6:
        return (
            "READY LONG",
            "BASE_SCORE",
        )

    rescue_ready = (
        hour == 1
        and momentum is not None
        and momentum[
            "points"
        ] >= 6
        and momentum[
            "breakout"
        ]
        and momentum[
            "vol_accel"
        ] >= 1.10
        and momentum[
            "close_strength"
        ] >= 0.58
        and 0
        < momentum["gain"]
        <= 1.50
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


def evaluate_checkpoint(
    rows,
    hour,
):
    needed = hour * 4

    if len(rows) < needed:
        return None

    sample = rows[:needed]

    base = base_features(
        sample
    )

    momentum = (
        momentum_features(
            sample
        )
        if hour == 1
        else None
    )

    label, route = (
        classify_v12(
            base,
            momentum,
            hour,
        )
    )

    result = {
        "hour": hour,
        "label": label,
        "route": route,
        "score": base["score"],
        "entry": base["price"],
        "launch_gain":
            base["gain"],
        "vol_ratio":
            base["vol_ratio"],
        "entry_time_ms":
            sample[-1]["t"],
        "entry_time_utc":
            fmt_ms(
                sample[-1]["t"]
            ),
    }

    if momentum is not None:
        result[
            "momentum"
        ] = momentum

    return result


def future_rows(
    rows,
    entry_time_ms,
    hours=72,
):
    end_ms = (
        entry_time_ms
        + hours
        * 60
        * 60
        * 1000
    )

    return [
        row
        for row in rows
        if (
            entry_time_ms
            < row["t"]
            < end_ms
        )
    ]


def future_stats(
    rows,
    entry_time_ms,
    entry,
    hours=72,
):
    future = future_rows(
        rows,
        entry_time_ms,
        hours,
    )

    if not future:
        return {
            "max_up": 0.0,
            "max_down": 0.0,
        }

    highest = max(
        x["h"]
        for x in future
    )

    lowest = min(
        x["l"]
        for x in future
    )

    return {
        "max_up":
            pct(
                highest,
                entry,
            ),
        "max_down":
            pct(
                lowest,
                entry,
            ),
    }


def target_stop_path(
    rows,
    entry_time_ms,
    entry,
    hours=72,
):
    stop_price = (
        entry
        * (
            1
            + DIAGNOSTIC_STOP_PCT
            / 100
        )
    )

    target_prices = {
        target:
            entry
            * (
                1
                + target / 100
            )
        for target in TARGETS
    }

    future = future_rows(
        rows,
        entry_time_ms,
        hours,
    )

    best_target = 0

    for candle in future:

        if (
            candle["l"]
            <= stop_price
        ):
            if best_target == 0:
                return {
                    "best_target": 0,
                    "stopped": True,
                    "label":
                        "STOP -8% BEFORE +10%",
                }

            return {
                "best_target":
                    best_target,
                "stopped": True,
                "label":
                    (
                        f"+{best_target}% "
                        "THEN STOP -8%"
                    ),
            }

        for target in TARGETS:
            if (
                candle["h"]
                >= target_prices[
                    target
                ]
            ):
                best_target = max(
                    best_target,
                    target,
                )

    if best_target > 0:
        return {
            "best_target":
                best_target,
            "stopped": False,
            "label":
                (
                    f"+{best_target}% "
                    "NO -8% STOP"
                ),
        }

    return {
        "best_target": 0,
        "stopped": False,
        "label":
            "NO +10% / NO -8%",
    }


def ready_quality(path):
    best = path[
        "best_target"
    ]

    if best >= 20:
        return "STRONG"

    if best >= 10:
        return "GOOD"

    if path["stopped"]:
        return "BAD"

    return "FLAT"


def load_state():
    if not os.path.exists(
        STATE_FILE
    ):
        return None

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
        raise RuntimeError(
            "Unsupported state version."
        )

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


def write_changed(value):
    with open(
        STATE_CHANGED_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        f.write(
            "YES"
            if value
            else "NO"
        )


def initialize_state(
    current_symbols,
    now_ms,
):
    return {
        "state_version":
            STATE_VERSION,
        "strategy":
            "NEW_LISTING_HUNTER_V1.2",
        "mode":
            "FORWARD_SHADOW",
        "initialized_at_ms":
            now_ms,
        "initialized_at_utc":
            fmt_ms(now_ms),
        "known_symbols":
            sorted(
                current_symbols
            ),
        "candidates": {},
        "telegram_setup_notified":
            False,
    }


def send_setup_notification(
    state,
):
    if state.get(
        "telegram_setup_notified",
        False,
    ):
        return False

    message = (
        "✅ شکارچی لیست‌های توبیت\n\n"
        "Forward Validation V1.2 به تلگرام متصل شد.\n"
        "حالت: Shadow Mode\n"
        "معامله واقعی: خاموش\n\n"
        "از این به بعد فقط هنگام رخداد مهم پیام می‌فرستم:\n"
        "• لیست جدید\n"
        "• نتیجه 1H / 2H / 4H\n"
        "• نتیجه نهایی 72H"
    )

    if send_telegram(
        message
    ):
        state[
            "telegram_setup_notified"
        ] = True
        return True

    return False


def add_candidate(
    state,
    info,
    now_ms,
):
    symbol = info["symbol"]

    anchor_ms = floor_15m(
        now_ms
    )

    state[
        "candidates"
    ][symbol] = {
        "symbol":
            symbol,
        "token":
            info["token"],
        "detected_at_ms":
            now_ms,
        "detected_at_utc":
            fmt_ms(now_ms),
        "anchor_ms":
            anchor_ms,
        "anchor_utc":
            fmt_ms(anchor_ms),
        "categories":
            info["categories"],
        "status":
            "TRACKING",
        "checkpoints":
            {},
        "final_result":
            None,
    }


def candidate_age_hours(
    candidate,
    now_ms,
):
    return (
        now_ms
        - candidate["anchor_ms"]
    ) / (
        60 * 60 * 1000
    )


def fetch_candidate_rows(
    candidate,
    now_ms,
):
    anchor_ms = candidate[
        "anchor_ms"
    ]

    max_end = (
        anchor_ms
        + (
            FINALIZE_AFTER_HOURS
            * 60
            * 60
            * 1000
        )
        + CANDLE_MS
    )

    return fetch_klines(
        candidate["symbol"],
        anchor_ms,
        min(
            now_ms,
            max_end,
        ),
    )


def checkpoint_message(
    candidate,
    checkpoint,
):
    hour = checkpoint["hour"]

    text = (
        "📊 شکارچی لیست‌های توبیت\n\n"
        f"{candidate['symbol']}\n"
        f"بررسی {hour}H\n\n"
        f"وضعیت: {checkpoint['label']}\n"
        f"Route: {checkpoint['route']}\n"
        f"Score: {checkpoint['score']}\n"
        f"Entry: {checkpoint['entry']:.8g}\n"
        f"From detection: "
        f"{checkpoint['launch_gain']:+.2f}%\n"
        f"Time: "
        f"{checkpoint['entry_time_utc']}"
    )

    momentum = checkpoint.get(
        "momentum"
    )

    if momentum:
        text += (
            "\n\n"
            f"VolAccel: "
            f"{momentum['vol_accel']:.2f}x\n"
            f"CloseStrength: "
            f"{momentum['close_strength']:.2f}\n"
            f"Momentum Points: "
            f"{momentum['points']}\n"
            f"Breakout: "
            f"{momentum['breakout']}"
        )

    text += (
        "\n\n⚠️ Shadow Validation — "
        "معامله‌ای باز نشده."
    )

    return text


def process_checkpoints(
    candidate,
    rows,
    now_ms,
):
    changed = False

    age_hours = (
        candidate_age_hours(
            candidate,
            now_ms,
        )
    )

    for hour in CHECKPOINT_HOURS:
        key = str(hour)

        if (
            key
            in candidate[
                "checkpoints"
            ]
        ):
            continue

        if age_hours < hour:
            continue

        checkpoint = (
            evaluate_checkpoint(
                rows,
                hour,
            )
        )

        if checkpoint is None:
            print(
                f"  {hour}H due, "
                "but not enough candles."
            )
            continue

        candidate[
            "checkpoints"
        ][key] = checkpoint

        changed = True

        print(
            f"  NEW {hour}H CHECKPOINT"
            f" | {checkpoint['label']}"
            f" | Route {checkpoint['route']}"
            f" | Score {checkpoint['score']}"
        )

        send_telegram(
            checkpoint_message(
                candidate,
                checkpoint,
            )
        )

    return changed


def first_ready_checkpoint(
    candidate,
):
    for hour in CHECKPOINT_HOURS:
        item = (
            candidate[
                "checkpoints"
            ].get(
                str(hour)
            )
        )

        if (
            item
            and item["label"]
            == "READY LONG"
        ):
            return item

    return None


def can_finalize(
    candidate,
    rows,
    now_ms,
):
    if (
        candidate["status"]
        == "FINALIZED"
    ):
        return False

    if any(
        str(hour)
        not in candidate[
            "checkpoints"
        ]
        for hour
        in CHECKPOINT_HOURS
    ):
        return False

    if (
        candidate_age_hours(
            candidate,
            now_ms,
        )
        < FINALIZE_AFTER_HOURS
    ):
        return False

    if not rows:
        return False

    cp4 = (
        candidate[
            "checkpoints"
        ]["4"]
    )

    required_last_ms = (
        cp4["entry_time_ms"]
        + (
            72
            * 60
            * 60
            * 1000
        )
        - CANDLE_MS
    )

    return (
        rows[-1]["t"]
        >= required_last_ms
    )


def finalize_candidate(
    candidate,
    rows,
    now_ms,
):
    checkpoint_paths = {}

    for hour in CHECKPOINT_HOURS:
        checkpoint = (
            candidate[
                "checkpoints"
            ][str(hour)]
        )

        stats = future_stats(
            rows,
            checkpoint[
                "entry_time_ms"
            ],
            checkpoint["entry"],
            72,
        )

        path = target_stop_path(
            rows,
            checkpoint[
                "entry_time_ms"
            ],
            checkpoint["entry"],
            72,
        )

        checkpoint_paths[
            str(hour)
        ] = {
            "max_up":
                stats["max_up"],
            "max_down":
                stats["max_down"],
            "path":
                path,
        }

    ready = (
        first_ready_checkpoint(
            candidate
        )
    )

    if ready is not None:
        key = str(
            ready["hour"]
        )

        ready_path = (
            checkpoint_paths[
                key
            ]["path"]
        )

        result = {
            "decision":
                "READY",
            "ready_hour":
                ready["hour"],
            "ready_route":
                ready["route"],
            "quality":
                ready_quality(
                    ready_path
                ),
            "ready_path":
                ready_path,
            "ready_max_up":
                checkpoint_paths[
                    key
                ]["max_up"],
            "ready_max_down":
                checkpoint_paths[
                    key
                ]["max_down"],
            "missed_opportunity":
                False,
            "checkpoint_paths":
                checkpoint_paths,
        }

    else:
        best_hour = None
        best_target = 0

        for hour in CHECKPOINT_HOURS:
            target = (
                checkpoint_paths[
                    str(hour)
                ]["path"][
                    "best_target"
                ]
            )

            if target > best_target:
                best_target = target
                best_hour = hour

        missed = (
            best_target
            >= MISSED_THRESHOLD
        )

        result = {
            "decision":
                "NO_READY",
            "quality":
                "N/A",
            "missed_opportunity":
                missed,
            "best_missed_hour":
                (
                    best_hour
                    if missed
                    else None
                ),
            "best_missed_target":
                (
                    best_target
                    if missed
                    else 0
                ),
            "checkpoint_paths":
                checkpoint_paths,
        }

    result[
        "finalized_at_ms"
    ] = now_ms

    result[
        "finalized_at_utc"
    ] = fmt_ms(
        now_ms
    )

    candidate[
        "final_result"
    ] = result

    candidate["status"] = (
        "FINALIZED"
    )

    return result


def final_message(
    candidate,
    result,
):
    symbol = candidate["symbol"]

    if result["decision"] == "READY":
        return (
            "🏁 نتیجه نهایی Shadow Validation\n\n"
            f"{symbol}\n"
            f"Decision: READY LONG\n"
            f"Signal: "
            f"{result['ready_hour']}H\n"
            f"Route: "
            f"{result['ready_route']}\n"
            f"Quality: "
            f"{result['quality']}\n"
            f"Path: "
            f"{result['ready_path']['label']}\n"
            f"Max: "
            f"{result['ready_max_up']:+.2f}%\n"
            f"DD: "
            f"{result['ready_max_down']:+.2f}%\n\n"
            "⚠️ این فقط نتیجه آزمایشی است؛ "
            "معامله واقعی باز نشده."
        )

    if result[
        "missed_opportunity"
    ]:
        missed_text = (
            "YES\n"
            f"Best checkpoint: "
            f"{result['best_missed_hour']}H\n"
            f"Target before stop: "
            f"+{result['best_missed_target']}%"
        )

    else:
        missed_text = "NO"

    return (
        "🏁 نتیجه نهایی Shadow Validation\n\n"
        f"{symbol}\n"
        "Decision: NO READY LONG\n"
        f"Missed opportunity >=15% "
        f"before -8%: {missed_text}\n\n"
        "⚠️ این فقط نتیجه آزمایشی است؛ "
        "معامله واقعی باز نشده."
    )


def summary_counts(state):
    candidates = list(
        state[
            "candidates"
        ].values()
    )

    tracking = sum(
        x["status"]
        == "TRACKING"
        for x in candidates
    )

    finalized = [
        x
        for x in candidates
        if (
            x["status"]
            == "FINALIZED"
            and x.get(
                "final_result"
            )
        )
    ]

    ready = [
        x
        for x in finalized
        if (
            x[
                "final_result"
            ]["decision"]
            == "READY"
        )
    ]

    good = [
        x
        for x in ready
        if (
            x[
                "final_result"
            ]["quality"]
            in (
                "GOOD",
                "STRONG",
            )
        )
    ]

    bad = [
        x
        for x in ready
        if (
            x[
                "final_result"
            ]["quality"]
            == "BAD"
        )
    ]

    missed = [
        x
        for x in finalized
        if x[
            "final_result"
        ].get(
            "missed_opportunity"
        )
    ]

    return {
        "tracking": tracking,
        "finalized":
            len(finalized),
        "ready":
            len(ready),
        "good_or_strong":
            len(good),
        "bad":
            len(bad),
        "missed":
            len(missed),
    }


def main():
    print(
        "NEW LISTING HUNTER V1.2 "
        "- FORWARD SHADOW VALIDATION "
        "+ TELEGRAM"
    )

    print(
        "NO real orders are placed."
    )

    print(
        "Telegram alerts only on "
        "meaningful new events."
    )

    print()

    now_ms = (
        get_server_time_ms()
    )

    print(
        "Toobit/server time:",
        fmt_ms(now_ms),
    )

    contracts = get_contracts()

    current = contract_map(
        contracts
    )

    current_symbols = set(
        current.keys()
    )

    print(
        "Active crypto USDT contracts:",
        len(current_symbols),
    )

    print(
        "Telegram available:",
        telegram_available(),
    )

    print()

    state = load_state()

    if state is None:
        state = initialize_state(
            current_symbols,
            now_ms,
        )

        send_setup_notification(
            state
        )

        save_state(state)
        write_changed(True)

        print(
            "BASELINE CREATED ✅"
        )

        print(
            "STATE_CHANGED: YES"
        )
        return

    before = state_signature(
        state
    )

    # برای State قدیمی که قبل از
    # اضافه‌شدن تلگرام ساخته شده.
    if (
        "telegram_setup_notified"
        not in state
    ):
        state[
            "telegram_setup_notified"
        ] = False

    send_setup_notification(
        state
    )

    known_symbols = set(
        state.get(
            "known_symbols",
            [],
        )
    )

    new_symbols = sorted(
        current_symbols
        - known_symbols
    )

    print(
        "New contracts since "
        "saved state:",
        len(new_symbols),
    )

    if new_symbols:
        for symbol in new_symbols:
            print(
                "  🆕 DETECTED:",
                symbol,
            )

            add_candidate(
                state,
                current[symbol],
                now_ms,
            )

            send_telegram(
                "🆕 شکارچی لیست‌های توبیت\n\n"
                f"قرارداد جدید پیدا شد:\n"
                f"{symbol}\n\n"
                f"Detected: "
                f"{fmt_ms(now_ms)}\n"
                "وضعیت: Forward Shadow Tracking\n\n"
                "بررسی‌های 1H / 2H / 4H "
                "به‌صورت خودکار انجام می‌شود.\n"
                "⚠️ معامله واقعی باز نشده."
            )

    else:
        print(
            "  No new crypto contract "
            "detected on this run."
        )

    state[
        "known_symbols"
    ] = sorted(
        known_symbols
        | current_symbols
    )

    print()

    candidates = state[
        "candidates"
    ]

    if not candidates:
        print(
            "No forward candidates "
            "are being tracked yet."
        )

    for symbol in sorted(
        candidates.keys()
    ):
        candidate = candidates[
            symbol
        ]

        age_hours = (
            candidate_age_hours(
                candidate,
                now_ms,
            )
        )

        print(
            "=" * 88
        )

        print(
            candidate["symbol"],
            "|",
            candidate["status"],
            "| age",
            f"{age_hours:.1f}h",
        )

        if (
            candidate["status"]
            == "FINALIZED"
        ):
            continue

        checkpoint_due = any(
            (
                age_hours >= hour
                and str(hour)
                not in candidate[
                    "checkpoints"
                ]
            )
            for hour
            in CHECKPOINT_HOURS
        )

        final_due = (
            age_hours
            >= FINALIZE_AFTER_HOURS
        )

        if not (
            checkpoint_due
            or final_due
        ):
            continue

        try:
            rows = fetch_candidate_rows(
                candidate,
                now_ms,
            )

        except Exception as exc:
            print(
                "  DATA ERROR:",
                repr(exc),
            )
            continue

        print(
            "  Forward 15m rows:",
            len(rows),
        )

        process_checkpoints(
            candidate,
            rows,
            now_ms,
        )

        if can_finalize(
            candidate,
            rows,
            now_ms,
        ):
            result = (
                finalize_candidate(
                    candidate,
                    rows,
                    now_ms,
                )
            )

            print(
                "  ✅ FINALIZED"
            )

            send_telegram(
                final_message(
                    candidate,
                    result,
                )
            )

    counts = summary_counts(
        state
    )

    print()
    print("#" * 88)
    print(
        "FORWARD VALIDATION SUMMARY"
    )
    print("#" * 88)

    print(
        "Baseline initialized:",
        state[
            "initialized_at_utc"
        ],
    )

    print(
        "Known symbols:",
        len(
            state[
                "known_symbols"
            ]
        ),
    )

    print(
        "Total forward candidates:",
        len(
            state[
                "candidates"
            ]
        ),
    )

    print(
        "Currently tracking:",
        counts["tracking"],
    )

    print(
        "Finalized cases:",
        counts["finalized"],
    )

    print(
        "READY signals:",
        counts["ready"],
    )

    print(
        "GOOD or STRONG READY:",
        counts[
            "good_or_strong"
        ],
    )

    print(
        "BAD READY:",
        counts["bad"],
    )

    print(
        "Missed opportunities "
        ">=15% before -8%:",
        counts["missed"],
    )

    if counts["ready"] > 0:
        quality_rate = (
            counts[
                "good_or_strong"
            ]
            / counts["ready"]
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

    if counts["finalized"] < 5:
        print(
            "VALIDATION STATUS: "
            "COLLECTING SAMPLE"
        )

        print(
            "Need at least 5 finalized "
            "forward cases before "
            "judging V1.2."
        )

    else:
        print(
            "VALIDATION STATUS: "
            "SAMPLE AVAILABLE"
        )

    changed = (
        state_signature(state)
        != before
    )

    if changed:
        save_state(state)

    write_changed(
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
        "State file:",
        STATE_FILE,
    )

    print(
        "Telegram alerts:",
        (
            "ENABLED"
            if telegram_available()
            else "DISABLED"
        ),
    )

    print(
        "Shadow mode only. "
        "No exchange orders are created."
    )


if __name__ == "__main__":
    main()

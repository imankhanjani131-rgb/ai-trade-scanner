import json
import os
import time
from datetime import datetime, timezone

import requests


# =========================================================
# CONFIG
# =========================================================

BASE = "https://api.toobit.com"
TIMEOUT = 25

STATE_FILE = "early_hunter_state.json"
STATE_CHANGED_FILE = "early_state_changed.txt"
STATE_VERSION = 1

INTERVAL = "5m"
CANDLE_MS = 5 * 60 * 1000

CHECKPOINT_MINUTES = (
    5,
    15,
    30,
    60,
)

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
    "User-Agent":
        "ai-trade-scanner-new-listing-early-hunter/1.0"
})


# =========================================================
# BASIC HELPERS
# =========================================================

def from_ms(value):
    return datetime.fromtimestamp(
        value / 1000,
        tz=timezone.utc,
    )


def fmt_ms(value):
    return from_ms(value).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def floor_5m(value):
    return (
        value
        - (value % CANDLE_MS)
    )


def avg(values):
    if not values:
        return 0.0

    return (
        sum(values)
        / len(values)
    )


def pct(a, b):
    if not b:
        return 0.0

    return (
        (a / b) - 1.0
    ) * 100.0


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
        print(
            "TELEGRAM: disabled"
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
                "chat_id":
                    TELEGRAM_CHAT_ID,
                "text":
                    text,
                "disable_web_page_preview":
                    True,
            },
            timeout=20,
        )

        if response.ok:
            print(
                "TELEGRAM: sent ✅"
            )
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


# =========================================================
# TOOBIT API
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
                    attempt
                )

    raise RuntimeError(
        f"Request failed: "
        f"{last_error!r}"
    )


def get_server_time_ms():
    try:
        payload = request_json(
            f"{BASE}/api/v1/time"
        )

        if (
            isinstance(
                payload,
                dict,
            )
            and payload.get(
                "serverTime"
            )
            is not None
        ):
            return int(
                payload[
                    "serverTime"
                ]
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

    data = payload.get(
        "data"
    )

    if (
        isinstance(
            data,
            dict,
        )
        and isinstance(
            data.get(
                "contracts"
            ),
            list,
        )
    ):
        return data[
            "contracts"
        ]

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

    if symbol.endswith(
        suffix
    ):
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
        item.get(
            "symbol",
            "",
        )
    ).upper()

    status = str(
        item.get(
            "status",
            "",
        )
    ).upper()

    quote = str(
        item.get(
            "quoteAsset",
            "",
        )
    ).upper()

    categories = " ".join(
        x.upper()
        for x in
        normalize_categories(
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

    if item.get(
        "inverse"
    ) is True:
        return False

    if item.get(
        "isRwa"
    ) is True:
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
            item.get(
                "symbol",
                "",
            )
        ).upper()

        result[
            symbol
        ] = {
            "symbol":
                symbol,
            "token":
                token_from_symbol(
                    symbol
                ),
            "categories":
                normalize_categories(
                    item
                ),
        }

    return result


# =========================================================
# KLINES
# =========================================================

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
                "t":
                    int(item[0]),
                "o":
                    float(item[1]),
                "h":
                    float(item[2]),
                "l":
                    float(item[3]),
                "c":
                    float(item[4]),
                "v":
                    float(item[5]),
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
        key=lambda x:
            x["t"],
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
            "symbol":
                symbol,
            "interval":
                INTERVAL,
            "startTime":
                int(start_ms),
            "endTime":
                int(end_ms - 1),
            "limit":
                1000,
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


# =========================================================
# EARLY ANALYSIS
# =========================================================

def analyze_sample(
    rows,
    minutes,
):
    needed = max(
        1,
        minutes // 5,
    )

    if len(rows) < needed:
        return None

    sample = rows[
        :needed
    ]

    first_open = (
        sample[0]["o"]
    )

    close = (
        sample[-1]["c"]
    )

    highest = max(
        x["h"]
        for x in sample
    )

    lowest = min(
        x["l"]
        for x in sample
    )

    launch_gain = pct(
        close,
        first_open,
    )

    pullback = pct(
        close,
        highest,
    )

    close_strength = (
        (close - lowest)
        / (highest - lowest)
        if highest > lowest
        else 0.5
    )

    green_count = sum(
        x["c"] > x["o"]
        for x in sample
    )

    green_ratio = (
        green_count
        / len(sample)
    )

    # Volume acceleration
    if len(sample) >= 2:
        midpoint = max(
            1,
            len(sample) // 2,
        )

        first_vol = avg(
            [
                x["v"]
                for x in sample[
                    :midpoint
                ]
            ]
        )

        second_vol = avg(
            [
                x["v"]
                for x in sample[
                    midpoint:
                ]
            ]
        )

        vol_accel = (
            second_vol
            / first_vol
            if first_vol > 0
            else 1.0
        )

    else:
        vol_accel = 1.0

    if len(sample) >= 2:
        previous_high = max(
            x["h"]
            for x in sample[:-1]
        )

        breakout = (
            sample[-1]["c"]
            > previous_high
        )

    else:
        breakout = False

    higher_lows = 0

    if len(sample) >= 2:
        higher_lows = sum(
            b["l"] > a["l"]
            for a, b in zip(
                sample,
                sample[1:],
            )
        )

    score = 0

    # Close quality
    if close_strength >= 0.75:
        score += 2

    elif close_strength >= 0.58:
        score += 1

    # Volume
    if vol_accel >= 1.50:
        score += 2

    elif vol_accel >= 1.10:
        score += 1

    # Breakout
    if breakout:
        score += 2

    # Candle structure
    if green_ratio >= 0.66:
        score += 1

    if higher_lows >= 2:
        score += 1

    elif (
        minutes <= 15
        and higher_lows >= 1
    ):
        score += 1

    # Healthy positive move
    if (
        0.5
        <= launch_gain
        <= 15
    ):
        score += 1

    # Weakness penalties
    if launch_gain <= -5:
        score -= 3

    elif launch_gain < 0:
        score -= 1

    if pullback <= -10:
        score -= 3

    elif pullback <= -6:
        score -= 1

    # Anti-Chase thresholds
    chase_limits = {
        5: 12,
        15: 20,
        30: 30,
        60: 45,
    }

    chase_limit = (
        chase_limits[
            minutes
        ]
    )

    chase = (
        launch_gain
        >= chase_limit
    )

    dump_risk = (
        pullback <= -10
    )

    weak_close = (
        close_strength
        < 0.30
    )

    # =====================================================
    # SIGNAL CLASSIFICATION
    # =====================================================

    if chase:
        label = (
            "CHASE BLOCK"
        )

        reason = (
            "PRICE TOO EXTENDED"
        )

    elif dump_risk:
        label = (
            "REJECT"
        )

        reason = (
            "HEAVY PULLBACK"
        )

    elif weak_close:
        label = (
            "WAIT"
        )

        reason = (
            "WEAK CLOSE"
        )

    elif minutes == 5:
        if (
            score >= 3
            and launch_gain > 0
        ):
            label = (
                "FAST WATCH"
            )

            reason = (
                "EARLY MOMENTUM"
            )

        else:
            label = (
                "WAIT"
            )

            reason = (
                "NOT ENOUGH CONFIRMATION"
            )

    elif minutes == 15:
        if (
            score >= 5
            and launch_gain > 0
        ):
            label = (
                "EARLY READY"
            )

            reason = (
                "15M MOMENTUM CONFIRMED"
            )

        elif score >= 3:
            label = (
                "EARLY WATCH"
            )

            reason = (
                "PARTIAL CONFIRMATION"
            )

        else:
            label = (
                "WAIT"
            )

            reason = (
                "LOW SCORE"
            )

    elif minutes == 30:
        if (
            score >= 5
            and launch_gain > 0
        ):
            label = (
                "EARLY READY"
            )

            reason = (
                "30M STRUCTURE CONFIRMED"
            )

        elif score >= 3:
            label = (
                "WATCH"
            )

            reason = (
                "SETUP DEVELOPING"
            )

        else:
            label = (
                "REJECT"
            )

            reason = (
                "STRUCTURE NOT STRONG"
            )

    else:
        if (
            score >= 5
            and launch_gain > 0
        ):
            label = (
                "READY CONFIRM"
            )

            reason = (
                "1H CONFIRMATION"
            )

        elif score >= 3:
            label = (
                "WATCH"
            )

            reason = (
                "MIXED 1H STRUCTURE"
            )

        else:
            label = (
                "REJECT"
            )

            reason = (
                "WEAK 1H STRUCTURE"
            )

    return {
        "minutes":
            minutes,
        "label":
            label,
        "reason":
            reason,
        "score":
            score,
        "price":
            close,
        "launch_gain":
            launch_gain,
        "pullback":
            pullback,
        "close_strength":
            close_strength,
        "green_ratio":
            green_ratio,
        "vol_accel":
            vol_accel,
        "breakout":
            breakout,
        "higher_lows":
            higher_lows,
        "chase":
            chase,
        "time_ms":
            sample[-1]["t"],
        "time_utc":
            fmt_ms(
                sample[-1]["t"]
            ),
    }


# =========================================================
# STATE
# =========================================================

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
        state = json.load(
            f
        )

    if (
        state.get(
            "state_version"
        )
        != STATE_VERSION
    ):
        raise RuntimeError(
            "Unsupported state version"
        )

    return state


def save_state(state):
    temp = (
        STATE_FILE
        + ".tmp"
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
        separators=(
            ",",
            ":",
        ),
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
        "mode":
            "NEW_LISTING_EARLY_HUNTER",
        "initialized_at_ms":
            now_ms,
        "initialized_at_utc":
            fmt_ms(
                now_ms
            ),
        "known_symbols":
            sorted(
                current_symbols
            ),
        "candidates":
            {},
        "telegram_setup_notified":
            False,
    }


def candidate_age_minutes(
    candidate,
    now_ms,
):
    return (
        now_ms
        - candidate[
            "anchor_ms"
        ]
    ) / (
        60 * 1000
    )


def add_candidate(
    state,
    info,
    now_ms,
):
    symbol = info[
        "symbol"
    ]

    anchor_ms = floor_5m(
        now_ms
    )

    state[
        "candidates"
    ][symbol] = {
        "symbol":
            symbol,
        "token":
            info[
                "token"
            ],
        "detected_at_ms":
            now_ms,
        "detected_at_utc":
            fmt_ms(
                now_ms
            ),
        "anchor_ms":
            anchor_ms,
        "anchor_utc":
            fmt_ms(
                anchor_ms
            ),
        "categories":
            info[
                "categories"
            ],
        "status":
            "TRACKING",
        "checkpoints":
            {},
    }


# =========================================================
# MESSAGES
# =========================================================

def new_listing_message(
    candidate
):
    return (
        "🆕 NEW LISTING EARLY HUNTER\n\n"
        f"{candidate['symbol']}\n\n"
        "قرارداد جدید در Toobit پیدا شد.\n"
        f"Detected: "
        f"{candidate['detected_at_utc']}\n\n"
        "بررسی سریع شروع شد:\n"
        "5m → 15m → 30m → 1H\n\n"
        "⚠️ Shadow Mode\n"
        "هیچ معامله‌ای باز نشده."
    )


def checkpoint_message(
    candidate,
    result,
):
    minutes = result[
        "minutes"
    ]

    if minutes == 60:
        tf = "1H"
    else:
        tf = f"{minutes}m"

    if result[
        "label"
    ] in (
        "EARLY READY",
        "READY CONFIRM",
    ):
        icon = "🚀"

    elif result[
        "label"
    ] == "CHASE BLOCK":
        icon = "⛔"

    elif result[
        "label"
    ] in (
        "FAST WATCH",
        "EARLY WATCH",
        "WATCH",
    ):
        icon = "👀"

    else:
        icon = "⚪"

    return (
        f"{icon} NEW LISTING EARLY HUNTER\n\n"
        f"{candidate['symbol']}\n"
        f"Timeframe: {tf}\n\n"
        f"Signal: {result['label']}\n"
        f"Reason: {result['reason']}\n"
        f"Score: {result['score']}\n\n"
        f"Price: {result['price']:.8g}\n"
        f"From detection: "
        f"{result['launch_gain']:+.2f}%\n"
        f"Pullback from high: "
        f"{result['pullback']:+.2f}%\n\n"
        f"VolAccel: "
        f"{result['vol_accel']:.2f}x\n"
        f"CloseStrength: "
        f"{result['close_strength']:.2f}\n"
        f"Green ratio: "
        f"{result['green_ratio']:.2f}\n"
        f"Breakout: "
        f"{result['breakout']}\n\n"
        f"Time: {result['time_utc']}\n\n"
        "⚠️ Shadow Mode — "
        "این پیام سیگنال اجرای خودکار معامله نیست."
    )


# =========================================================
# PROCESS
# =========================================================

def process_candidate(
    candidate,
    now_ms,
):
    changed = False

    age_minutes = (
        candidate_age_minutes(
            candidate,
            now_ms,
        )
    )

    if age_minutes > 90:
        candidate[
            "status"
        ] = "COMPLETE"

        return True

    due = [
        minute
        for minute
        in CHECKPOINT_MINUTES
        if (
            age_minutes >= minute
            and str(minute)
            not in candidate[
                "checkpoints"
            ]
        )
    ]

    if not due:
        return False

    try:
        rows = fetch_klines(
            candidate[
                "symbol"
            ],
            candidate[
                "anchor_ms"
            ],
            now_ms,
        )

    except Exception as exc:
        print(
            "DATA ERROR:",
            candidate[
                "symbol"
            ],
            repr(exc),
        )

        return False

    print(
        "  5m candles:",
        len(rows),
    )

    for minute in due:
        result = analyze_sample(
            rows,
            minute,
        )

        if result is None:
            print(
                f"  {minute}m due "
                "but candles not ready."
            )

            continue

        candidate[
            "checkpoints"
        ][
            str(minute)
        ] = result

        changed = True

        print(
            f"  {minute}m"
            f" | {result['label']}"
            f" | Score {result['score']}"
            f" | Gain "
            f"{result['launch_gain']:+.2f}%"
            f" | Pullback "
            f"{result['pullback']:+.2f}%"
        )

        send_telegram(
            checkpoint_message(
                candidate,
                result,
            )
        )

    if all(
        str(minute)
        in candidate[
            "checkpoints"
        ]
        for minute
        in CHECKPOINT_MINUTES
    ):
        candidate[
            "status"
        ] = "COMPLETE"

        changed = True

    return changed


# =========================================================
# SUMMARY
# =========================================================

def summary_counts(state):
    candidates = list(
        state[
            "candidates"
        ].values()
    )

    tracking = sum(
        x[
            "status"
        ] == "TRACKING"
        for x in candidates
    )

    complete = sum(
        x[
            "status"
        ] == "COMPLETE"
        for x in candidates
    )

    early_ready = 0
    chase_blocks = 0

    for candidate in candidates:
        for result in candidate[
            "checkpoints"
        ].values():

            if result[
                "label"
            ] in (
                "EARLY READY",
                "READY CONFIRM",
            ):
                early_ready += 1

            if (
                result[
                    "label"
                ]
                == "CHASE BLOCK"
            ):
                chase_blocks += 1

    return {
        "tracking":
            tracking,
        "complete":
            complete,
        "early_ready":
            early_ready,
        "chase_blocks":
            chase_blocks,
    }


# =========================================================
# MAIN
# =========================================================

def main():
    print(
        "NEW LISTING EARLY HUNTER V1"
    )

    print(
        "Shadow Mode only."
    )

    print(
        "Detection → 5m → 15m → 30m → 1H"
    )

    print(
        "Anti-Chase protection enabled."
    )

    print()

    now_ms = (
        get_server_time_ms()
    )

    print(
        "Toobit/server time:",
        fmt_ms(
            now_ms
        ),
    )

    contracts = (
        get_contracts()
    )

    current = (
        contract_map(
            contracts
        )
    )

    current_symbols = set(
        current.keys()
    )

    print(
        "Active crypto USDT contracts:",
        len(
            current_symbols
        ),
    )

    print(
        "Telegram available:",
        telegram_available(),
    )

    print()

    state = load_state()

    # First run = baseline only
    if state is None:
        state = initialize_state(
            current_symbols,
            now_ms,
        )

        save_state(
            state
        )

        write_changed(
            True
        )

        print(
            "EARLY HUNTER BASELINE CREATED ✅"
        )

        print(
            "Existing contracts are "
            "saved as known."
        )

        print(
            "From the next run, "
            "new contracts can be detected."
        )

        return

    before = state_signature(
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
        "New contracts:",
        len(
            new_symbols
        ),
    )

    for symbol in new_symbols:
        print(
            "🆕 NEW:",
            symbol,
        )

        add_candidate(
            state,
            current[
                symbol
            ],
            now_ms,
        )

        candidate = (
            state[
                "candidates"
            ][symbol]
        )

        send_telegram(
            new_listing_message(
                candidate
            )
        )

    # Never forget already seen symbols
    state[
        "known_symbols"
    ] = sorted(
        known_symbols
        | current_symbols
    )

    print()

    candidates = (
        state[
            "candidates"
        ]
    )

    if not candidates:
        print(
            "No Early Hunter "
            "candidates yet."
        )

    for symbol in sorted(
        candidates.keys()
    ):
        candidate = (
            candidates[
                symbol
            ]
        )

        if (
            candidate[
                "status"
            ]
            == "COMPLETE"
        ):
            continue

        age_minutes = (
            candidate_age_minutes(
                candidate,
                now_ms,
            )
        )

        print(
            "=" * 80
        )

        print(
            symbol,
            "|",
            candidate[
                "status"
            ],
            "| age",
            f"{age_minutes:.1f}m",
        )

        process_candidate(
            candidate,
            now_ms,
        )

    counts = summary_counts(
        state
    )

    print()

    print(
        "#" * 80
    )

    print(
        "EARLY HUNTER SUMMARY"
    )

    print(
        "#" * 80
    )

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
        "Total candidates:",
        len(
            state[
                "candidates"
            ]
        ),
    )

    print(
        "Tracking:",
        counts[
            "tracking"
        ],
    )

    print(
        "Completed:",
        counts[
            "complete"
        ],
    )

    print(
        "EARLY READY / READY CONFIRM:",
        counts[
            "early_ready"
        ],
    )

    print(
        "CHASE BLOCKS:",
        counts[
            "chase_blocks"
        ],
    )

    changed = (
        state_signature(
            state
        )
        != before
    )

    if changed:
        save_state(
            state
        )

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

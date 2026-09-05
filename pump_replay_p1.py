import time
import requests
import pandas as pd

import backtest_v42_super_pump as core


# ============================================================
# PUMP REPLAY P1
# ============================================================

VERSION = "PUMP-REPLAY-P1-TOOBIT"

# ارزهایی که با عکس، پامپ واقعی آنها را ثبت کردیم
SYMBOLS = [
    "FLOCK/USDT",
    "DASH/USDT",
    "AKE/USDT",
    "TUT/USDT",
    "BULLA/USDT",
    "4/USDT",
    "B/USDT",
]

# فقط آخرین چند روز را برای پیدا کردن پامپ واقعی بررسی می‌کنیم
EVENT_LOOKBACK_DAYS = 7

# از یک نقطه تا 24 ساعت بعد، بیشترین حرکت را پیدا می‌کنیم
PUMP_WINDOW_HOURS = 24

# حداقل رشد برای اینکه یک حرکت را Pump حساب کنیم
MIN_PUMP_PCT = 12.0

# سیگنال‌های حداکثر 12 ساعت قبل از شروع پامپ هم بررسی شوند
PRE_PUMP_HOURS = 12


# ============================================================
# P1_4H_CONFIRM
# همان پروفایل برتر V4.3
# ============================================================

PROFILE_NAME = "P1_4H_CONFIRM"

core.VERSION = VERSION

core.PROFILES = {
    PROFILE_NAME: {
        "min_score": 12,
        "min_vol_accel": 1.20,
        "min_vol_ratio5": 1.00,
        "max_dist5": 1.15,
        "need_near_breakout": True,
        "need_4h_bull": True,
    }
}

core.SYMBOLS = SYMBOLS


# ============================================================
# TOOBIT DATA
# ============================================================

BASE_URL = "https://api.toobit.com"

session = requests.Session()

_contract_map = None


def get_json(path, params=None):

    last_error = None

    for attempt in range(3):

        try:

            response = session.get(
                BASE_URL + path,
                params=params,
                timeout=20,
            )

            response.raise_for_status()

            return response.json()

        except Exception as error:

            last_error = error

            print(
                f"Request retry "
                f"{attempt + 1}/3 | "
                f"{type(error).__name__}: "
                f"{error}"
            )

            time.sleep(
                1.0 + attempt
            )

    raise RuntimeError(
        f"Toobit request failed: "
        f"{last_error}"
    )


def build_contract_map():

    global _contract_map

    if _contract_map is not None:
        return _contract_map

    print(
        "Loading Toobit futures symbols..."
    )

    data = get_json(
        "/api/v1/exchangeInfo"
    )

    result = {}

    contracts = data.get(
        "contracts",
        []
    )

    for item in contracts:

        api_symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).strip()

        index_symbol = str(
            item.get(
                "index",
                ""
            )
        ).strip().upper()

        underlying = str(
            item.get(
                "underlying",
                ""
            )
        ).strip().upper()

        status = str(
            item.get(
                "status",
                ""
            )
        ).upper()

        if not api_symbol:
            continue

        if status and status != "TRADING":
            continue

        if index_symbol:

            result[
                index_symbol
            ] = api_symbol

        if underlying:

            result[
                underlying + "USDT"
            ] = api_symbol

    _contract_map = result

    print(
        f"Toobit futures loaded: "
        f"{len(result)} mappings"
    )

    return result


def extract_batch(data):

    if isinstance(
        data,
        list
    ):
        return data

    if isinstance(
        data,
        dict
    ):

        rows = data.get(
            "data"
        )

        if isinstance(
            rows,
            list
        ):
            return rows

    return []


def fetch_toobit_5m_history(
    symbol
):

    mapping = build_contract_map()

    pair = (
        symbol
        .replace(
            "/",
            ""
        )
        .upper()
    )

    api_symbol = mapping.get(
        pair
    )

    if not api_symbol:

        print(
            f"{symbol} | "
            f"NOT FOUND on Toobit futures"
        )

        return None

    print(
        f"{symbol} -> "
        f"{api_symbol}"
    )

    now = pd.Timestamp.now(
        tz="UTC"
    )

    start = (
        now
        - pd.Timedelta(
            days=core.FETCH_DAYS
        )
    )

    start_ms = int(
        start.timestamp()
        * 1000
    )

    end_ms = int(
        now.timestamp()
        * 1000
    )

    bar_ms = (
        5
        * 60
        * 1000
    )

    # حداکثر 1000 کندل در هر درخواست
    chunk_ms = (
        1000
        * bar_ms
    )

    cursor = start_ms

    rows = []

    request_number = 0

    while cursor < end_ms:

        request_number += 1

        chunk_end = min(
            cursor
            + chunk_ms
            - 1,
            end_ms
        )

        params = {
            "symbol":
                api_symbol,

            "interval":
                "5m",

            "startTime":
                cursor,

            "endTime":
                chunk_end,

            "limit":
                1000,
        }

        raw = get_json(
            "/quote/v1/klines",
            params=params,
        )

        batch = extract_batch(
            raw
        )

        timestamps = []

        for candle in batch:

            if (
                not isinstance(
                    candle,
                    (list, tuple)
                )
                or len(candle) < 6
            ):
                continue

            try:

                ts = int(
                    candle[0]
                )

                close_time = (
                    int(candle[6])
                    if len(candle) > 6
                    else (
                        ts
                        + bar_ms
                        - 1
                    )
                )

                # فقط کندل بسته‌شده
                if close_time > end_ms:
                    continue

                rows.append([
                    ts,
                    float(candle[1]),
                    float(candle[2]),
                    float(candle[3]),
                    float(candle[4]),
                    float(candle[5]),
                ])

                timestamps.append(
                    ts
                )

            except Exception:
                continue

        if (
            request_number == 1
            or request_number % 5 == 0
        ):

            print(
                f"  Toobit chunk "
                f"{request_number} | "
                f"bars={len(rows)}"
            )

        if timestamps:

            cursor = (
                max(timestamps)
                + bar_ms
            )

        else:

            cursor = (
                chunk_end
                + 1
            )

        time.sleep(
            0.05
        )

    if not rows:

        print(
            f"{symbol} | "
            f"NO 5m DATA"
        )

        return None

    df = pd.DataFrame(
        rows,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ],
    )

    df = (
        df
        .drop_duplicates(
            subset=[
                "timestamp"
            ]
        )
        .sort_values(
            "timestamp"
        )
        .reset_index(
            drop=True
        )
    )

    df[
        "datetime"
    ] = pd.to_datetime(
        df["timestamp"],
        unit="ms",
        utc=True,
    )

    coverage = (
        df.iloc[-1][
            "datetime"
        ]
        -
        df.iloc[0][
            "datetime"
        ]
    ).total_seconds() / 86400

    print(
        f"{symbol} | "
        f"Toobit 5m bars="
        f"{len(df)} | "
        f"coverage="
        f"{coverage:.1f} days"
    )

    return df


# موتور V4.2/V4.3 را مجبور می‌کنیم
# دیتای Toobit استفاده کند
core.fetch_5m_history = (
    fetch_toobit_5m_history
)


# ============================================================
# PUMP EVENT DETECTOR
# ============================================================

def detect_pump_event(
    h5
):

    end_time = h5[
        "signal_time"
    ].max()

    recent_start = (
        end_time
        - pd.Timedelta(
            days=
                EVENT_LOOKBACK_DAYS
        )
    )

    recent = h5[
        h5[
            "signal_time"
        ]
        >= recent_start
    ].copy()

    if len(recent) < 20:
        return None

    future_bars = (
        PUMP_WINDOW_HOURS
        * 12
    )

    future_high = (
        recent[
            "high"
        ]
        .iloc[::-1]
        .rolling(
            future_bars,
            min_periods=1
        )
        .max()
        .iloc[::-1]
    )

    gain_pct = (
        (
            future_high
            /
            recent[
                "close"
            ]
        )
        - 1.0
    ) * 100.0

    start_idx = (
        gain_pct.idxmax()
    )

    pump_pct = float(
        gain_pct.loc[
            start_idx
        ]
    )

    start_row = recent.loc[
        start_idx
    ]

    start_time = start_row[
        "signal_time"
    ]

    start_price = float(
        start_row[
            "close"
        ]
    )

    event_end = (
        start_time
        + pd.Timedelta(
            hours=
                PUMP_WINDOW_HOURS
        )
    )

    window = recent[
        (
            recent[
                "signal_time"
            ]
            >= start_time
        )
        &
        (
            recent[
                "signal_time"
            ]
            <= event_end
        )
    ].copy()

    if window.empty:
        return None

    peak_idx = window[
        "high"
    ].idxmax()

    peak_row = window.loc[
        peak_idx
    ]

    peak_time = peak_row[
        "signal_time"
    ]

    peak_price = float(
        peak_row[
            "high"
        ]
    )

    return {
        "start_time":
            start_time,

        "start_price":
            start_price,

        "peak_time":
            peak_time,

        "peak_price":
            peak_price,

        "pump_pct":
            (
                (
                    peak_price
                    / start_price
                )
                - 1.0
            )
            * 100.0,
    }


# ============================================================
# SIGNAL SCORING
# ============================================================

def score_signal(
    trade,
    event,
    h5
):

    if trade is None:

        return {
            "stage":
                "MISS",
            "remaining_pct":
                None,
            "progress_pct":
                None,
            "lead_minutes":
                None,
            "mfe_pct":
                None,
            "mae_pct":
                None,
        }

    signal_time = trade[
        "time"
    ]

    entry = float(
        trade[
            "entry"
        ]
    )

    start_price = event[
        "start_price"
    ]

    peak_price = event[
        "peak_price"
    ]

    total_move = (
        peak_price
        - start_price
    )

    if total_move > 0:

        progress = (
            (
                entry
                - start_price
            )
            /
            total_move
        ) * 100.0

    else:

        progress = 100.0

    progress = max(
        0.0,
        min(
            100.0,
            progress
        )
    )

    remaining_pct = (
        (
            peak_price
            / entry
        )
        - 1.0
    ) * 100.0

    lead_minutes = (
        event[
            "start_time"
        ]
        - signal_time
    ).total_seconds() / 60.0

    if signal_time < event[
        "start_time"
    ]:

        stage = "PRE-PUMP"

    elif progress <= 25:

        stage = "EARLY"

    elif progress <= 55:

        stage = "CONFIRM"

    else:

        stage = "LATE"

    path = h5[
        (
            h5[
                "signal_time"
            ]
            >= signal_time
        )
        &
        (
            h5[
                "signal_time"
            ]
            <= event[
                "peak_time"
            ]
        )
    ]

    if path.empty:

        mfe_pct = 0.0
        mae_pct = 0.0

    else:

        mfe_pct = (
            (
                float(
                    path[
                        "high"
                    ].max()
                )
                / entry
            )
            - 1.0
        ) * 100.0

        mae_pct = (
            (
                float(
                    path[
                        "low"
                    ].min()
                )
                / entry
            )
            - 1.0
        ) * 100.0

    return {
        "stage":
            stage,

        "remaining_pct":
            remaining_pct,

        "progress_pct":
            progress,

        "lead_minutes":
            lead_minutes,

        "mfe_pct":
            mfe_pct,

        "mae_pct":
            mae_pct,
    }


# ============================================================
# ONE SYMBOL REPLAY
# ============================================================

def replay_symbol(
    symbol
):

    print()
    print(
        "=" * 96
    )

    print(
        f"REPLAY | {symbol}"
    )

    print(
        "=" * 96
    )

    prepared = (
        core.prepare_symbol(
            symbol
        )
    )

    if prepared is None:

        print(
            "RESULT: NO DATA"
        )

        return {
            "symbol":
                symbol,
            "status":
                "NO_DATA",
        }

    (
        h5,
        h15,
        h1,
        h4
    ) = prepared

    event = detect_pump_event(
        h5
    )

    if event is None:

        print(
            "RESULT: NO EVENT"
        )

        return {
            "symbol":
                symbol,
            "status":
                "NO_EVENT",
        }

    print(
        f"Pump start: "
        f"{event['start_time']}"
    )

    print(
        f"Start price: "
        f"{event['start_price']:.8f}"
    )

    print(
        f"Peak time: "
        f"{event['peak_time']}"
    )

    print(
        f"Peak price: "
        f"{event['peak_price']:.8f}"
    )

    print(
        f"Detected pump: "
        f"{event['pump_pct']:.2f}%"
    )

    if (
        event[
            "pump_pct"
        ]
        <
        MIN_PUMP_PCT
    ):

        print(
            f"RESULT: MOVE BELOW "
            f"{MIN_PUMP_PCT:.1f}%"
        )

        return {
            "symbol":
                symbol,
            "status":
                "BELOW_THRESHOLD",
            "pump_pct":
                event[
                    "pump_pct"
                ],
        }

    trades = core.find_trades(
        symbol,
        h5,
        h15,
        h1,
        h4,
        PROFILE_NAME,
    )

    search_start = (
        event[
            "start_time"
        ]
        - pd.Timedelta(
            hours=
                PRE_PUMP_HOURS
        )
    )

    candidates = [
        trade
        for trade in trades
        if (
            trade[
                "time"
            ]
            >= search_start
            and
            trade[
                "time"
            ]
            <= event[
                "peak_time"
            ]
        )
    ]

    candidates.sort(
        key=lambda x:
            x[
                "time"
            ]
    )

    trade = (
        candidates[0]
        if candidates
        else None
    )

    score = score_signal(
        trade,
        event,
        h5,
    )

    if trade is None:

        print(
            "P1 SIGNAL: MISS"
        )

        return {
            "symbol":
                symbol,
            "status":
                "MISS",
            "pump_pct":
                event[
                    "pump_pct"
                ],
            "stage":
                "MISS",
        }

    print()
    print(
        f"P1 signal: "
        f"{trade['time']}"
    )

    print(
        f"Entry: "
        f"{trade['entry']:.8f}"
    )

    print(
        f"Stage: "
        f"{score['stage']}"
    )

    if (
        score[
            "lead_minutes"
        ]
        >= 0
    ):

        print(
            f"Lead before pump: "
            f"{score['lead_minutes']:.0f} min"
        )

    else:

        print(
            f"Signal after pump start: "
            f"{abs(score['lead_minutes']):.0f} min"
        )

    print(
        f"Pump already used: "
        f"{score['progress_pct']:.1f}%"
    )

    print(
        f"Upside remaining to peak: "
        f"{score['remaining_pct']:.2f}%"
    )

    print(
        f"MFE to peak: "
        f"{score['mfe_pct']:.2f}%"
    )

    print(
        f"MAE before peak: "
        f"{score['mae_pct']:.2f}%"
    )

    print(
        f"Backtest R: "
        f"{trade['r']:+.2f}R | "
        f"Exit={trade['exit']}"
    )

    good = (
        score[
            "remaining_pct"
        ]
        >= 5.0
        and
        score[
            "stage"
        ]
        in (
            "PRE-PUMP",
            "EARLY",
            "CONFIRM",
        )
    )

    print(
        "REPLAY VERDICT: "
        +
        (
            "GOOD"
            if good
            else "LATE/WEAK"
        )
    )

    return {
        "symbol":
            symbol,

        "status":
            (
                "GOOD"
                if good
                else "LATE_WEAK"
            ),

        "pump_pct":
            event[
                "pump_pct"
            ],

        "stage":
            score[
                "stage"
            ],

        "remaining_pct":
            score[
                "remaining_pct"
            ],

        "progress_pct":
            score[
                "progress_pct"
            ],

        "mfe_pct":
            score[
                "mfe_pct"
            ],

        "mae_pct":
            score[
                "mae_pct"
            ],

        "r":
            trade[
                "r"
            ],
    }


# ============================================================
# FINAL REPORT
# ============================================================

def main():

    print(
        "#" * 96
    )

    print(
        "PUMP REPLAY P1 - TOOBIT"
    )

    print(
        "#" * 96
    )

    print(
        f"Profile: "
        f"{PROFILE_NAME}"
    )

    print(
        "Goal: check whether P1 "
        "detected real pumps early "
        "enough to leave usable upside."
    )

    results = []

    for number, symbol in enumerate(
        SYMBOLS,
        1
    ):

        print()
        print(
            f"[{number}/"
            f"{len(SYMBOLS)}]"
        )

        try:

            result = replay_symbol(
                symbol
            )

        except Exception as error:

            print(
                f"ERROR {symbol}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

            result = {
                "symbol":
                    symbol,
                "status":
                    "ERROR",
            }

        results.append(
            result
        )

    print()
    print(
        "#" * 96
    )

    print(
        "PUMP REPLAY P1 - FINAL"
    )

    print(
        "#" * 96
    )

    for result in results:

        symbol = result[
            "symbol"
        ]

        status = result[
            "status"
        ]

        pump = result.get(
            "pump_pct"
        )

        stage = result.get(
            "stage",
            "-"
        )

        remaining = result.get(
            "remaining_pct"
        )

        pump_text = (
            f"{pump:.1f}%"
            if pump is not None
            else "-"
        )

        remaining_text = (
            f"{remaining:.1f}%"
            if remaining is not None
            else "-"
        )

        print(
            f"{symbol:12s} | "
            f"Pump:{pump_text:>7s} | "
            f"Stage:{stage:9s} | "
            f"Remaining:{remaining_text:>7s} | "
            f"{status}"
        )

    valid = [
        r
        for r in results
        if r[
            "status"
        ]
        in (
            "GOOD",
            "LATE_WEAK",
            "MISS",
        )
    ]

    good_count = sum(
        r[
            "status"
        ]
        == "GOOD"
        for r in valid
    )

    miss_count = sum(
        r[
            "status"
        ]
        == "MISS"
        for r in valid
    )

    print()
    print(
        f"Usable pump events: "
        f"{len(valid)}"
    )

    print(
        f"GOOD captures: "
        f"{good_count}"
    )

    print(
        f"MISSED: "
        f"{miss_count}"
    )

    if valid:

        capture_rate = (
            good_count
            /
            len(valid)
            * 100.0
        )

        print(
            f"GOOD capture rate: "
            f"{capture_rate:.1f}%"
        )

    remaining_values = [
        float(
            r[
                "remaining_pct"
            ]
        )
        for r in valid
        if r.get(
            "remaining_pct"
        )
        is not None
    ]

    if remaining_values:

        print(
            f"Median upside remaining: "
            f"{pd.Series(remaining_values).median():.2f}%"
        )

    print()
    print(
        "IMPORTANT: This is a selected "
        "winner replay test, not proof "
        "of live profitability."
    )


if __name__ == "__main__":
    main()

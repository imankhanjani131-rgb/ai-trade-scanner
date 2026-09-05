import time
import requests
import pandas as pd

import backtest_v42_super_pump as core


VERSION = "PUMP-REPLAY-P1-TOOBIT-V2"

SYMBOLS = [
    "FLOCK/USDT",
    "DASH/USDT",
    "AKE/USDT",
    "TUT/USDT",
    "BULLA/USDT",
    "4/USDT",
    "B/USDT",
]

PROFILE_NAME = "P1_4H_CONFIRM"

EVENT_LOOKBACK_DAYS = 7
PUMP_WINDOW_HOURS = 24
MIN_PUMP_PCT = 12.0
PRE_PUMP_HOURS = 12

BASE_URL = "https://api.toobit.com"

INTERVAL_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
}

LOOKBACK_DAYS = {
    "5m": 14,
    "15m": 10,
    "1h": 20,
    "4h": 60,
}

session = requests.Session()
_contract_map = None


# ============================================================
# KEEP P1 EXACTLY THE SAME
# ============================================================

core.VERSION = VERSION
core.TEST_DAYS = 14

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


# ============================================================
# TOOBIT REQUESTS
# ============================================================

def get_json(path, params=None):

    last_error = None

    for attempt in range(4):

        try:

            r = session.get(
                BASE_URL + path,
                params=params,
                timeout=25,
            )

            r.raise_for_status()

            return r.json()

        except Exception as exc:

            last_error = exc

            print(
                f"Request retry {attempt + 1}/4 | "
                f"{type(exc).__name__}: {exc}"
            )

            time.sleep(
                1.0 + attempt
            )

    raise RuntimeError(
        f"Toobit request failed: {last_error}"
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

    for item in data.get(
        "contracts",
        []
    ):

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

        if (
            status
            and status != "TRADING"
        ):
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


def resolve_symbol(symbol):

    pair = (
        symbol
        .replace(
            "/",
            ""
        )
        .upper()
    )

    return build_contract_map().get(
        pair
    )


def extract_batch(payload):

    if isinstance(
        payload,
        list
    ):
        return payload

    if (
        isinstance(
            payload,
            dict
        )
        and
        isinstance(
            payload.get("data"),
            list
        )
    ):
        return payload["data"]

    return []


# ============================================================
# DIRECT MULTI-TIMEFRAME DATA
# ============================================================

def fetch_interval_history(
    symbol,
    interval,
    lookback_days,
):

    api_symbol = resolve_symbol(
        symbol
    )

    if not api_symbol:

        print(
            f"{symbol} | "
            "NOT FOUND on Toobit futures"
        )

        return None

    bar_ms = INTERVAL_MS[
        interval
    ]

    now = pd.Timestamp.now(
        tz="UTC"
    )

    end_ms = int(
        now.timestamp()
        * 1000
    )

    start_ms = int(
        (
            now
            - pd.Timedelta(
                days=lookback_days
            )
        ).timestamp()
        * 1000
    )

    # زیر سقف 1000 کندل در هر درخواست
    chunk_bars = 950

    chunk_ms = (
        chunk_bars
        * bar_ms
    )

    cursor = start_ms

    rows = []

    request_no = 0

    while cursor < end_ms:

        request_no += 1

        chunk_end = min(
            cursor
            + chunk_ms
            - 1,
            end_ms,
        )

        payload = get_json(
            "/quote/v1/klines",
            params={
                "symbol":
                    api_symbol,

                "interval":
                    interval,

                "startTime":
                    cursor,

                "endTime":
                    chunk_end,

                "limit":
                    1000,
            },
        )

        batch = extract_batch(
            payload
        )

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
                    else ts + bar_ms - 1
                )

                # کندل باز را استفاده نکن
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

            except Exception:
                continue

        if (
            request_no == 1
            or request_no % 5 == 0
        ):

            print(
                f"  {symbol} {interval} "
                f"request {request_no} | "
                f"batch={len(batch)} | "
                f"total={len(rows)}"
            )

        cursor = (
            chunk_end
            + 1
        )

        time.sleep(
            0.05
        )

    if not rows:
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
        df[
            "timestamp"
        ],
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
        f"{interval} raw bars="
        f"{len(df)} | "
        f"coverage="
        f"{coverage:.1f} days"
    )

    return df


def add_indicators_for_replay(
    df,
    label,
):

    if (
        df is None
        or df.empty
    ):
        return None

    before = len(
        df
    )

    out = core.add_indicators(
        df
    )

    after = len(
        out
    )

    print(
        f"  {label} indicators | "
        f"raw={before} | "
        f"usable={after}"
    )

    if (
        out is None
        or out.empty
    ):
        return None

    return out


def prepare_replay(
    symbol
):

    print(
        f"{symbol} -> "
        "direct multi-timeframe "
        "Toobit data"
    )

    h5_raw = fetch_interval_history(
        symbol,
        "5m",
        LOOKBACK_DAYS["5m"],
    )

    h15_raw = fetch_interval_history(
        symbol,
        "15m",
        LOOKBACK_DAYS["15m"],
    )

    h1_raw = fetch_interval_history(
        symbol,
        "1h",
        LOOKBACK_DAYS["1h"],
    )

    h4_raw = fetch_interval_history(
        symbol,
        "4h",
        LOOKBACK_DAYS["4h"],
    )

    if any(
        x is None or x.empty
        for x in [
            h5_raw,
            h15_raw,
            h1_raw,
            h4_raw,
        ]
    ):

        return (
            None,
            "MISSING_RAW_DATA",
        )

    # P1 از EMA200 تایم 4H استفاده می‌کند
    if len(
        h4_raw
    ) < 200:

        print(
            f"{symbol} | "
            "INSUFFICIENT 4H HISTORY: "
            f"{len(h4_raw)} bars; "
            "P1 needs EMA200."
        )

        return (
            None,
            "INSUFFICIENT_4H_HISTORY",
        )

    h5 = add_indicators_for_replay(
        h5_raw,
        "5m",
    )

    h15 = add_indicators_for_replay(
        h15_raw,
        "15m",
    )

    h1 = add_indicators_for_replay(
        h1_raw,
        "1h",
    )

    h4 = add_indicators_for_replay(
        h4_raw,
        "4h",
    )

    if any(
        x is None or x.empty
        for x in [
            h5,
            h15,
            h1,
            h4,
        ]
    ):

        return (
            None,
            "INDICATOR_WARMUP_FAILED",
        )

    h5[
        "signal_time"
    ] = (
        h5[
            "datetime"
        ]
        + pd.Timedelta(
            minutes=5
        )
    )

    h15[
        "available_time"
    ] = (
        h15[
            "datetime"
        ]
        + pd.Timedelta(
            minutes=15
        )
    )

    h1[
        "available_time"
    ] = (
        h1[
            "datetime"
        ]
        + pd.Timedelta(
            hours=1
        )
    )

    h4[
        "available_time"
    ] = (
        h4[
            "datetime"
        ]
        + pd.Timedelta(
            hours=4
        )
    )

    return (
        (
            h5,
            h15,
            h1,
            h4,
        ),
        None,
    )


# ============================================================
# FIND REAL PUMP
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

    if len(
        recent
    ) < 50:
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
            min_periods=1,
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
        gain_pct
        .idxmax()
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
# SCORE SIGNAL POSITION INSIDE PUMP
# ============================================================

def score_signal(
    trade,
    event,
    h5,
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
            progress,
        ),
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

    if (
        signal_time
        <
        event[
            "start_time"
        ]
    ):

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
# ONE SYMBOL
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

    (
        prepared,
        prep_error,
    ) = prepare_replay(
        symbol
    )

    if prepared is None:

        print(
            f"RESULT: "
            f"{prep_error}"
        )

        return {
            "symbol":
                symbol,

            "status":
                prep_error,
        }

    (
        h5,
        h15,
        h1,
        h4,
    ) = prepared

    event = detect_pump_event(
        h5
    )

    if event is None:

        print(
            "RESULT: NO_EVENT"
        )

        return {
            "symbol":
                symbol,

            "status":
                "NO_EVENT",
        }

    print(
        f"Detected pump | "
        f"start="
        f"{event['start_time']} | "
        f"peak="
        f"{event['peak_time']} | "
        f"move="
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
            "RESULT: BELOW_THRESHOLD "
            f"({event['pump_pct']:.2f}%)"
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
        t
        for t in trades
        if (
            search_start
            <= t["time"]
            <= event[
                "peak_time"
            ]
        )
    ]

    candidates.sort(
        key=lambda x:
            x["time"]
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

    print(
        "Pump already used: "
        f"{score['progress_pct']:.1f}%"
    )

    print(
        "Upside remaining to peak: "
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
        f"Exit="
        f"{trade['exit']}"
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

    status = (
        "GOOD"
        if good
        else "LATE_WEAK"
    )

    print(
        f"REPLAY VERDICT: "
        f"{status}"
    )

    return {
        "symbol":
            symbol,

        "status":
            status,

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
        "PUMP REPLAY P1 - TOOBIT V2"
    )

    print(
        "#" * 96
    )

    print(
        f"Profile: "
        f"{PROFILE_NAME}"
    )

    print(
        "Uses direct "
        "5m/15m/1h/4h Toobit history; "
        "P1 logic is unchanged."
    )

    results = []

    for (
        n,
        symbol,
    ) in enumerate(
        SYMBOLS,
        1,
    ):

        print()

        print(
            f"[{n}/"
            f"{len(SYMBOLS)}]"
        )

        try:

            result = replay_symbol(
                symbol
            )

        except Exception as exc:

            print(
                f"ERROR {symbol}: "
                f"{type(exc).__name__}: "
                f"{exc}"
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

    for r in results:

        pump = r.get(
            "pump_pct"
        )

        remaining = r.get(
            "remaining_pct"
        )

        stage = r.get(
            "stage",
            "-",
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
            f"{r['symbol']:12s} | "
            f"Pump:"
            f"{pump_text:>7s} | "
            f"Stage:"
            f"{stage:9s} | "
            f"Remaining:"
            f"{remaining_text:>7s} | "
            f"{r['status']}"
        )

    evaluable = [
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
        for r in evaluable
    )

    miss_count = sum(
        r[
            "status"
        ]
        == "MISS"
        for r in evaluable
    )

    print()

    print(
        "Evaluable pump events: "
        f"{len(evaluable)}"
    )

    print(
        f"GOOD captures: "
        f"{good_count}"
    )

    print(
        f"MISSED: "
        f"{miss_count}"
    )

    if evaluable:

        capture_rate = (
            good_count
            /
            len(evaluable)
            * 100.0
        )

        print(
            "GOOD capture rate: "
            f"{capture_rate:.1f}%"
        )

    remaining_values = [
        float(
            r[
                "remaining_pct"
            ]
        )
        for r in evaluable
        if r.get(
            "remaining_pct"
        )
        is not None
    ]

    if remaining_values:

        print(
            "Median upside remaining: "
            f"{pd.Series(remaining_values).median():.2f}%"
        )

    print()

    print(
        "IMPORTANT: "
        "selected-winner replay only; "
        "not proof of live profitability."
    )


if __name__ == "__main__":
    main()

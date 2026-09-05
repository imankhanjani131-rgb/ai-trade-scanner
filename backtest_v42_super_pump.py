import math
import time
import pandas as pd

import backtest as bt
import backtest_v4_15m as base


VERSION = "V4.2-SUPER-PUMP-MAX"

TEST_DAYS = 45
WARMUP_DAYS = 42
FETCH_DAYS = TEST_DAYS + WARMUP_DAYS

MAX_PAGES = 300
REQUEST_DELAY = 0.05

MAX_HOLD_BARS = 48 * 12
COOLDOWN = pd.Timedelta(hours=4)

RISK_PER_TRADE = 0.01

ROUND_TRIP_COST_PCT = (
    base.ROUND_TRIP_COST_PCT
)

SYMBOLS = base.SYMBOLS


PROFILES = {

    "S1_EARLY": {
        "min_score": 10,
        "min_vol_accel": 1.10,
        "min_vol_ratio5": 0.85,
        "max_dist5": 1.30,
        "need_near_breakout": False,
        "need_4h_bull": False,
    },

    "S2_CONFIRM": {
        "min_score": 12,
        "min_vol_accel": 1.20,
        "min_vol_ratio5": 1.00,
        "max_dist5": 1.15,
        "need_near_breakout": True,
        "need_4h_bull": False,
    },

    "S3_STRICT": {
        "min_score": 14,
        "min_vol_accel": 1.30,
        "min_vol_ratio5": 1.15,
        "max_dist5": 1.00,
        "need_near_breakout": True,
        "need_4h_bull": True,
    },
}


def safe_float(
    value,
    default=0.0,
):
    try:

        value = float(
            value
        )

        if (
            math.isnan(value)
            or math.isinf(value)
        ):
            return default

        return value

    except Exception:
        return default


# ============================================================
# DOWNLOAD TRUE 5M HISTORY
# ============================================================

def fetch_5m_history(
    symbol
):

    inst_id = symbol.replace(
        "/",
        "-"
    )

    now = pd.Timestamp.now(
        tz="UTC"
    )

    start = (
        now
        - pd.Timedelta(
            days=FETCH_DAYS
        )
    )

    start_ms = int(
        start.timestamp()
        * 1000
    )

    rows = []

    cursor = None
    previous_oldest = None

    print(
        f"Downloading "
        f"{symbol} 5m..."
    )

    for page in range(
        1,
        MAX_PAGES + 1
    ):

        params = {
            "instId": inst_id,
            "bar": "5m",
            "limit": "100",
        }

        if cursor is not None:

            params[
                "after"
            ] = str(
                cursor
            )

        batch = (
            bt.okx_request(
                params
            )
        )

        if not batch:
            break

        timestamps = []

        for candle in batch:

            if len(candle) < 6:
                continue

            try:

                ts = int(
                    candle[0]
                )

                confirm = (
                    candle[-1]
                    if len(candle) >= 7
                    else "1"
                )

                if str(
                    confirm
                ) != "1":
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

        if not timestamps:
            break

        oldest = min(
            timestamps
        )

        if (
            page == 1
            or page % 25 == 0
        ):

            print(
                f"  page {page} | "
                f"oldest="
                f"{pd.to_datetime(oldest, unit='ms', utc=True)}"
            )

        if oldest <= start_ms:
            break

        if (
            previous_oldest
            is not None
            and
            oldest
            >= previous_oldest
        ):
            break

        previous_oldest = (
            oldest
        )

        cursor = oldest

        time.sleep(
            REQUEST_DELAY
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

    df = df[
        df["timestamp"]
        >= start_ms
    ].copy()

    df[
        "datetime"
    ] = pd.to_datetime(
        df["timestamp"],
        unit="ms",
        utc=True
    )

    if df.empty:
        return None

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
        f"5m bars={len(df)} | "
        f"coverage="
        f"{coverage:.1f} days"
    )

    return df


# ============================================================
# MULTI TIME FRAME
# ============================================================

def resample_ohlcv(
    df,
    rule,
    count_needed
):

    x = (
        df
        .set_index(
            "datetime"
        )
        .copy()
    )

    out = x.resample(
        rule,
        label="left",
        closed="left",
        origin="epoch",
    ).agg({

        "open":
            "first",

        "high":
            "max",

        "low":
            "min",

        "close":
            "last",

        "volume":
            "sum",

        "timestamp":
            "count",
    })

    out = out.rename(
        columns={
            "timestamp":
                "bar_count"
        }
    )

    out = out[
        out["bar_count"]
        == count_needed
    ].copy()

    out = (
        out
        .drop(
            columns=[
                "bar_count"
            ]
        )
        .reset_index()
    )

    out[
        "timestamp"
    ] = (
        out["datetime"]
        .astype("int64")
        // 10**6
    )

    return out


def add_indicators(
    df
):

    out = (
        bt.add_indicators(
            df.copy()
        )
    )

    out[
        "range"
    ] = (
        out["high"]
        - out["low"]
    )

    out[
        "body"
    ] = (
        out["close"]
        - out["open"]
    ).abs()

    out[
        "body_ratio"
    ] = (
        out["body"]
        /
        out["range"].replace(
            0,
            float("nan")
        )
    )

    return (
        out
        .dropna()
        .reset_index(
            drop=True
        )
    )


def prepare_symbol(
    symbol
):

    h5 = fetch_5m_history(
        symbol
    )

    if (
        h5 is None
        or h5.empty
    ):
        return None

    h15 = resample_ohlcv(
        h5,
        "15min",
        3
    )

    h1 = resample_ohlcv(
        h5,
        "1h",
        12
    )

    h4 = resample_ohlcv(
        h5,
        "4h",
        48
    )

    h5 = add_indicators(
        h5
    )

    h15 = add_indicators(
        h15
    )

    h1 = add_indicators(
        h1
    )

    h4 = add_indicators(
        h4
    )

    if (
        h5.empty
        or h15.empty
        or h1.empty
        or h4.empty
    ):
        return None

    h5[
        "signal_time"
    ] = (
        h5["datetime"]
        + pd.Timedelta(
            minutes=5
        )
    )

    h15[
        "available_time"
    ] = (
        h15["datetime"]
        + pd.Timedelta(
            minutes=15
        )
    )

    h1[
        "available_time"
    ] = (
        h1["datetime"]
        + pd.Timedelta(
            hours=1
        )
    )

    h4[
        "available_time"
    ] = (
        h4["datetime"]
        + pd.Timedelta(
            hours=4
        )
    )

    return (
        h5,
        h15,
        h1,
        h4,
    )


def trend4(
    row
):
    return base.trend4(
        row
    )


# ============================================================
# SUPER PRE-PUMP ENGINE
# ============================================================

def pre_pump_features(
    h5,
    i,
    x15,
    p15,
    x1,
    p1,
    x4
):

    x = h5.iloc[i]

    p = h5.iloc[
        i - 1
    ]

    p2 = h5.iloc[
        i - 2
    ]

    p3 = h5.iloc[
        i - 3
    ]

    atr5 = max(
        safe_float(
            x["atr"]
        ),
        1e-12
    )

    atr15 = max(
        safe_float(
            x15["atr"]
        ),
        1e-12
    )

    close = safe_float(
        x["close"]
    )

    high = safe_float(
        x["high"]
    )

    low = safe_float(
        x["low"]
    )

    open_ = safe_float(
        x["open"]
    )


    # --------------------------------------------------------
    # VOLUME ACCELERATION
    # --------------------------------------------------------

    fast_vol = (
        h5.iloc[
            max(0, i - 2):
            i + 1
        ][
            "volume"
        ]
        .astype(float)
        .mean()
    )

    slow_vol = (
        h5.iloc[
            max(0, i - 20):
            max(0, i - 3)
        ][
            "volume"
        ]
        .astype(float)
        .mean()
    )

    vol_accel = (
        fast_vol
        /
        max(
            slow_vol,
            1e-12
        )
    )

    vol_ratio5 = (
        safe_float(
            x["vol_ratio"]
        )
    )


    # --------------------------------------------------------
    # COMPRESSION
    # --------------------------------------------------------

    recent_ranges = (
        h5.iloc[
            max(0, i - 5):
            i + 1
        ][
            "range"
        ]
        .astype(float)
    )

    prior_ranges = (
        h5.iloc[
            max(0, i - 24):
            max(0, i - 6)
        ][
            "range"
        ]
        .astype(float)
    )

    recent_range_avg = (
        safe_float(
            recent_ranges.mean(),
            999.0
        )
    )

    prior_range_avg = (
        safe_float(
            prior_ranges.mean(),
            recent_range_avg
        )
    )

    compression_ratio = (
        recent_range_avg
        /
        max(
            prior_range_avg,
            1e-12
        )
    )

    compressed = (
        compression_ratio
        <= 0.82
    )


    # --------------------------------------------------------
    # BREAKOUT PROXIMITY
    # --------------------------------------------------------

    prior24 = h5.iloc[
        max(0, i - 24):
        i
    ]

    recent_high = (
        safe_float(
            prior24[
                "high"
            ].max(),
            high
        )
    )

    dist_to_high_atr = (
        recent_high
        - close
    ) / atr5

    near_breakout = (
        -0.25
        <= dist_to_high_atr
        <= 0.90
    )

    breakout = (
        close
        > recent_high
    )


    # --------------------------------------------------------
    # HIGHER LOWS
    # --------------------------------------------------------

    lows_now = (
        h5.iloc[
            max(0, i - 2):
            i + 1
        ][
            "low"
        ]
        .astype(float)
        .mean()
    )

    lows_prev = (
        h5.iloc[
            max(0, i - 5):
            max(0, i - 2)
        ][
            "low"
        ]
        .astype(float)
        .mean()
    )

    higher_lows = (
        lows_now
        > lows_prev
    )


    # --------------------------------------------------------
    # LIQUIDITY SWEEP / RECLAIM PROXY
    # --------------------------------------------------------

    prev_swing_low = (
        safe_float(
            h5.iloc[
                max(0, i - 16):
                i
            ][
                "low"
            ].min(),
            low
        )
    )

    sweep_reclaim = (
        low
        < prev_swing_low

        and

        close
        > prev_swing_low

        and

        close
        > open_
    )


    # --------------------------------------------------------
    # MOMENTUM ACCELERATION
    # --------------------------------------------------------

    macd_accel = (

        safe_float(
            x["macd_hist"]
        )
        >
        safe_float(
            p["macd_hist"]
        )

        and

        safe_float(
            p["macd_hist"]
        )
        >=
        safe_float(
            p2["macd_hist"]
        )
    )

    macd_turn = (

        safe_float(
            x["macd_hist"]
        )
        >
        safe_float(
            p["macd_hist"]
        )

        and

        safe_float(
            p["macd_hist"]
        )
        >
        safe_float(
            p3["macd_hist"]
        )
    )


    # --------------------------------------------------------
    # CANDLE QUALITY
    # --------------------------------------------------------

    candle_range = max(
        high - low,
        1e-12
    )

    body_ratio = (
        abs(
            close - open_
        )
        /
        candle_range
    )

    close_pos = (
        close - low
    ) / candle_range

    bullish_close = (

        close
        > open_

        and

        body_ratio
        >= 0.45

        and

        close_pos
        >= 0.65
    )


    # --------------------------------------------------------
    # 5M ANTI CHASE
    # --------------------------------------------------------

    ema20_5 = safe_float(
        x["ema20"]
    )

    ema50_5 = safe_float(
        x["ema50"]
    )

    dist5 = (
        close
        - ema20_5
    ) / atr5

    impulse12 = (
        close
        -
        safe_float(
            h5.iloc[
                max(
                    0,
                    i - 12
                )
            ][
                "close"
            ],
            close
        )
    ) / atr5


    # --------------------------------------------------------
    # 15M CONFIRMATION
    # --------------------------------------------------------

    dist15 = (

        safe_float(
            x15["close"]
        )

        -

        safe_float(
            x15["ema20"]
        )

    ) / atr15

    momentum15 = (

        safe_float(
            x15[
                "macd_hist"
            ]
        )

        >

        safe_float(
            p15[
                "macd_hist"
            ]
        )
    )

    fifteen_ok = (

        safe_float(
            x15["close"]
        )
        >
        safe_float(
            x15["ema20"]
        )

        and

        46
        <=
        safe_float(
            x15["rsi"]
        )
        < 72

        and

        momentum15
    )


    # --------------------------------------------------------
    # 1H STRUCTURE
    # --------------------------------------------------------

    one_h_trend = (

        safe_float(
            x1["close"]
        )
        >
        safe_float(
            x1["ema20"]
        )

        and

        safe_float(
            x1["ema20"]
        )
        >=
        safe_float(
            x1["ema50"]
        )
        * 0.995

        and

        45
        <=
        safe_float(
            x1["rsi"]
        )
        < 70
    )

    adx_healthy = (

        safe_float(
            x1["adx"]
        )
        >= 18

        and

        safe_float(
            x1["adx"]
        )
        >=
        safe_float(
            p1["adx"]
        )
        - 2.0
    )


    # --------------------------------------------------------
    # 4H REGIME
    # --------------------------------------------------------

    t4 = trend4(
        x4
    )

    not_bearish_4h = (
        t4 != "BEARISH"
    )

    bullish_4h = (
        t4 == "BULLISH"
    )


    # --------------------------------------------------------
    # FINAL ANTI-CHASE
    # --------------------------------------------------------

    anti_chase = (

        dist5
        <= 1.30

        and

        impulse12
        <= 3.20

        and

        safe_float(
            x["rsi"]
        )
        < 74

        and

        dist15
        <= 1.45
    )


    # --------------------------------------------------------
    # SUPER SCORE
    # --------------------------------------------------------

    tests = [

        (
            not_bearish_4h,
            1
        ),

        (
            bullish_4h,
            1
        ),

        (
            one_h_trend,
            2
        ),

        (
            adx_healthy,
            1
        ),

        (
            fifteen_ok,
            2
        ),

        (
            compressed,
            2
        ),

        (
            vol_accel
            >= 1.10,
            1
        ),

        (
            vol_accel
            >= 1.30,
            1
        ),

        (
            vol_ratio5
            >= 1.00,
            1
        ),

        (
            higher_lows,
            1
        ),

        (
            near_breakout,
            1
        ),

        (
            breakout,
            1
        ),

        (
            macd_accel,
            1
        ),

        (
            macd_turn,
            1
        ),

        (
            bullish_close,
            1
        ),

        (
            sweep_reclaim,
            1
        ),

        (
            close
            > ema20_5,
            1
        ),

        (
            ema20_5
            >=
            ema50_5
            * 0.998,
            1
        ),
    ]

    score = sum(
        points
        for ok, points
        in tests
        if ok
    )

    return {

        "score":
            int(score),

        "trend4":
            t4,

        "one_h_trend":
            bool(
                one_h_trend
            ),

        "adx_healthy":
            bool(
                adx_healthy
            ),

        "fifteen_ok":
            bool(
                fifteen_ok
            ),

        "compressed":
            bool(
                compressed
            ),

        "compression_ratio":
            float(
                compression_ratio
            ),

        "vol_accel":
            float(
                vol_accel
            ),

        "vol_ratio5":
            float(
                vol_ratio5
            ),

        "higher_lows":
            bool(
                higher_lows
            ),

        "near_breakout":
            bool(
                near_breakout
            ),

        "breakout":
            bool(
                breakout
            ),

        "sweep_reclaim":
            bool(
                sweep_reclaim
            ),

        "macd_accel":
            bool(
                macd_accel
            ),

        "bullish_close":
            bool(
                bullish_close
            ),

        "anti_chase":
            bool(
                anti_chase
            ),

        "dist5":
            float(
                dist5
            ),

        "dist15":
            float(
                dist15
            ),

        "impulse12":
            float(
                impulse12
            ),

        "rsi5":
            safe_float(
                x["rsi"]
            ),

        "rsi15":
            safe_float(
                x15["rsi"]
            ),

        "rsi1":
            safe_float(
                x1["rsi"]
            ),

        "adx1":
            safe_float(
                x1["adx"]
            ),
    }


# ============================================================
# PROFILE FILTER
# ============================================================

def profile_ok(
    name,
    f
):

    p = PROFILES[
        name
    ]

    if not f[
        "anti_chase"
    ]:
        return False

    if not f[
        "one_h_trend"
    ]:
        return False

    if not f[
        "adx_healthy"
    ]:
        return False

    if not f[
        "fifteen_ok"
    ]:
        return False

    if (
        f["score"]
        <
        p["min_score"]
    ):
        return False

    if (
        f["vol_accel"]
        <
        p[
            "min_vol_accel"
        ]
    ):
        return False

    if (
        f["vol_ratio5"]
        <
        p[
            "min_vol_ratio5"
        ]
    ):
        return False

    if (
        f["dist5"]
        >
        p[
            "max_dist5"
        ]
    ):
        return False

    if (

        p[
            "need_near_breakout"
        ]

        and

        not (
            f["near_breakout"]
            or f["breakout"]
        )
    ):
        return False

    if (

        p[
            "need_4h_bull"
        ]

        and

        f["trend4"]
        != "BULLISH"
    ):
        return False

    if (

        not p[
            "need_4h_bull"
        ]

        and

        f["trend4"]
        == "BEARISH"
    ):
        return False

    accumulation_evidence = (

        f["compressed"]

        or

        f["higher_lows"]

        or

        f["sweep_reclaim"]
    )

    return accumulation_evidence


# ============================================================
# ENTRY / SL / TP
# ============================================================

def levels_super(
    h5,
    i,
    h1_closed,
    x15
):

    x = h5.iloc[i]

    entry = safe_float(
        x["close"]
    )

    atr15 = max(
        safe_float(
            x15["atr"]
        ),
        1e-12
    )

    recent = h5.iloc[
        max(
            0,
            i - 30
        ):
        i
    ]

    if len(
        recent
    ) < 18:

        raise ValueError(
            "Not enough 5m history"
        )

    swing_low = (
        safe_float(
            recent[
                "low"
            ].min()
        )
    )

    sl = min(

        swing_low
        - 0.10
        * atr15,

        entry
        - 0.70
        * atr15
    )

    risk = (
        entry
        - sl
    )

    if risk <= 0:

        raise ValueError(
            "Invalid risk"
        )

    if (
        risk
        >
        1.90
        * atr15
    ):

        raise ValueError(
            "Stop too wide"
        )

    resistance = (
        base.nearest_resistance(
            h1_closed,
            entry
        )
    )

    if (

        resistance
        is not None

        and

        resistance
        - entry
        <
        0.75
        * risk
    ):

        raise ValueError(
            "Resistance too close"
        )

    tp1 = (
        entry
        + 1.00
        * risk
    )

    tp2 = (
        entry
        + 1.80
        * risk
    )

    tp3 = (
        entry
        + 2.70
        * risk
    )

    be = (
        entry
        + 0.80
        * risk
    )

    return (
        entry,
        sl,
        tp1,
        tp2,
        tp3,
        be
    )


# ============================================================
# CONSERVATIVE 5M TRADE SIMULATOR
# ============================================================

def simulate_trade_5m(
    h5,
    i,
    entry,
    sl,
    tp1,
    tp2,
    tp3,
    be
):

    risk = (
        entry
        - sl
    )

    risk_pct = (
        risk
        / entry
        if entry > 0
        else 0.0
    )

    cost_r = (

        ROUND_TRIP_COST_PCT
        / risk_pct

        if risk_pct > 0

        else 0.0
    )

    tp1_hit = False
    tp2_hit = False
    tp3_hit = False

    be_armed = False

    end_i = min(
        len(h5) - 1,
        i + MAX_HOLD_BARS
    )

    for j in range(
        i + 1,
        end_i + 1
    ):

        bar = h5.iloc[j]

        low = safe_float(
            bar["low"]
        )

        high = safe_float(
            bar["high"]
        )

        active_stop = (

            entry

            if be_armed

            else sl
        )

        # Conservative:
        # adverse move counted first
        # if TP and stop occur
        # inside same 5m candle.

        if (
            low
            <= active_stop
        ):

            gross_r = (

                0.0

                if be_armed

                else -1.0
            )

            return {

                "r":
                    gross_r
                    - cost_r,

                "exit":
                    (
                        "BE"
                        if be_armed
                        else "SL"
                    ),

                "exit_i":
                    j,

                "tp1":
                    tp1_hit,

                "tp2":
                    tp2_hit,

                "tp3":
                    tp3_hit,
            }

        if (

            not be_armed

            and

            high >= be
        ):
            be_armed = True

        if (
            high >= tp1
        ):
            tp1_hit = True

        if (
            high >= tp2
        ):

            tp2_hit = True

            return {

                "r":
                    1.80
                    - cost_r,

                "exit":
                    "TP2",

                "exit_i":
                    j,

                "tp1":
                    tp1_hit,

                "tp2":
                    True,

                "tp3":
                    high >= tp3,
            }

        if (
            high >= tp3
        ):
            tp3_hit = True

    close = safe_float(
        h5.iloc[
            end_i
        ][
            "close"
        ]
    )

    gross_r = (
        close
        - entry
    ) / risk

    return {

        "r":
            gross_r
            - cost_r,

        "exit":
            "TIME",

        "exit_i":
            end_i,

        "tp1":
            tp1_hit,

        "tp2":
            tp2_hit,

        "tp3":
            tp3_hit,
    }


# ============================================================
# FIND PRE-PUMP TRADES
# ============================================================

def find_trades(
    symbol,
    h5,
    h15,
    h1,
    h4,
    profile_name
):

    trades = []

    last_signal_time = None

    test_end = (
        h5.iloc[-1][
            "signal_time"
        ]
    )

    test_start = (
        test_end
        -
        pd.Timedelta(
            days=TEST_DAYS
        )
    )

    for i in range(
        40,
        len(h5) - 1
    ):

        x5 = h5.iloc[i]

        signal_time = (
            x5[
                "signal_time"
            ]
        )

        if (
            signal_time
            < test_start
        ):
            continue

        if (

            last_signal_time
            is not None

            and

            signal_time
            - last_signal_time
            <
            COOLDOWN
        ):
            continue

        idx15 = (

            h15[
                "available_time"
            ]
            .searchsorted(
                signal_time,
                side="right"
            )

            - 1
        )

        idx1 = (

            h1[
                "available_time"
            ]
            .searchsorted(
                signal_time,
                side="right"
            )

            - 1
        )

        idx4 = (

            h4[
                "available_time"
            ]
            .searchsorted(
                signal_time,
                side="right"
            )

            - 1
        )

        if (

            idx15 < 1

            or idx1 < 1

            or idx4 < 0
        ):
            continue

        x15 = h15.iloc[
            idx15
        ]

        p15 = h15.iloc[
            idx15 - 1
        ]

        x1 = h1.iloc[
            idx1
        ]

        p1 = h1.iloc[
            idx1 - 1
        ]

        x4 = h4.iloc[
            idx4
        ]

        f = pre_pump_features(

            h5,
            i,
            x15,
            p15,
            x1,
            p1,
            x4
        )

        if not profile_ok(
            profile_name,
            f
        ):
            continue

        h1_closed = h1.iloc[
            :idx1 + 1
        ]

        try:

            (
                entry,
                sl,
                tp1,
                tp2,
                tp3,
                be
            ) = levels_super(

                h5,
                i,
                h1_closed,
                x15
            )

        except ValueError:
            continue

        outcome = (
            simulate_trade_5m(

                h5,
                i,
                entry,
                sl,
                tp1,
                tp2,
                tp3,
                be
            )
        )

        trades.append({

            "symbol":
                symbol,

            "time":
                signal_time,

            "profile":
                profile_name,

            "score":
                f["score"],

            "vol_accel":
                f[
                    "vol_accel"
                ],

            "vol_ratio5":
                f[
                    "vol_ratio5"
                ],

            "compression":
                f[
                    "compression_ratio"
                ],

            "trend4":
                f[
                    "trend4"
                ],

            "entry":
                entry,

            "sl":
                sl,

            "tp1_price":
                tp1,

            "tp2_price":
                tp2,

            "tp3_price":
                tp3,

            "r":
                float(
                    outcome[
                        "r"
                    ]
                ),

            "exit":
                outcome[
                    "exit"
                ],

            "tp1":
                bool(
                    outcome[
                        "tp1"
                    ]
                ),

            "tp2":
                bool(
                    outcome[
                        "tp2"
                    ]
                ),

            "tp3":
                bool(
                    outcome[
                        "tp3"
                    ]
                ),
        })

        last_signal_time = (
            signal_time
        )

    return trades


# ============================================================
# METRICS
# ============================================================

def metrics(
    trades
):

    if not trades:
        return None

    ordered = sorted(
        trades,
        key=lambda x:
            x["time"]
    )

    rs = [
        float(
            t["r"]
        )
        for t in ordered
    ]

    wins = sum(
        r > 0
        for r in rs
    )

    gross_profit = sum(
        r
        for r in rs
        if r > 0
    )

    gross_loss = abs(
        sum(
            r
            for r in rs
            if r < 0
        )
    )

    if gross_loss > 0:

        pf = (
            gross_profit
            / gross_loss
        )

    elif gross_profit > 0:

        pf = float(
            "inf"
        )

    else:
        pf = 0.0

    equity = 100.0
    peak = 100.0
    max_dd = 0.0

    for r in rs:

        equity *= (
            1
            +
            RISK_PER_TRADE
            * r
        )

        peak = max(
            peak,
            equity
        )

        if peak > 0:

            max_dd = max(

                max_dd,

                (
                    peak
                    - equity
                )
                / peak
                * 100
            )

    return {

        "trades":
            len(ordered),

        "wr":
            wins
            / len(ordered)
            * 100,

        "pf":
            pf,

        "net_r":
            sum(rs),

        "avg_r":
            sum(rs)
            / len(rs),

        "dd":
            max_dd,

        "equity":
            equity,

        "tp1":
            sum(
                t["tp1"]
                for t in ordered
            )
            / len(ordered)
            * 100,

        "tp2":
            sum(
                t["tp2"]
                for t in ordered
            )
            / len(ordered)
            * 100,
    }


def pf_text(
    value
):

    if math.isinf(
        value
    ):
        return "INF"

    return (
        f"{value:.2f}"
    )


# ============================================================
# ROBUSTNESS
# ============================================================

def robustness(
    trades
):

    if not trades:

        return {

            "recent":
                None,

            "positive_symbols":
                0,

            "top_share":
                0.0,
        }

    ordered = sorted(
        trades,
        key=lambda x:
            x["time"]
    )

    end_time = (
        ordered[-1][
            "time"
        ]
    )

    recent_start = (
        end_time
        -
        pd.Timedelta(
            days=15
        )
    )

    recent = [
        t
        for t in ordered
        if t["time"]
        >= recent_start
    ]

    symbol_counts = {}
    symbol_net = {}

    for t in ordered:

        symbol = t[
            "symbol"
        ]

        symbol_counts[
            symbol
        ] = (
            symbol_counts.get(
                symbol,
                0
            )
            + 1
        )

        symbol_net[
            symbol
        ] = (
            symbol_net.get(
                symbol,
                0.0
            )
            +
            float(
                t["r"]
            )
        )

    top_share = (

        max(
            symbol_counts.values()
        )
        /
        len(ordered)
        * 100

        if ordered

        else 0.0
    )

    positive_symbols = sum(
        value > 0
        for value
        in symbol_net.values()
    )

    return {

        "recent":
            metrics(
                recent
            ),

        "positive_symbols":
            positive_symbols,

        "top_share":
            top_share,
    }


# ============================================================
# RESULT PRINTING
# ============================================================

def print_profile(
    name,
    trades
):

    m = metrics(
        trades
    )

    r = robustness(
        trades
    )

    print()

    print(
        "=" * 96
    )

    print(
        f"{name} | "
        f"{PROFILES[name]}"
    )

    print(
        "=" * 96
    )

    if m is None:

        print(
            "NO TRADES"
        )

        return

    print(

        f"FULL | "
        f"Trades:{m['trades']} | "
        f"WR:{m['wr']:.2f}% | "
        f"PF:{pf_text(m['pf'])} | "
        f"NetR:{m['net_r']:.2f}R | "
        f"AvgR:{m['avg_r']:.3f}R | "
        f"DD:{m['dd']:.2f}% | "
        f"Equity:{m['equity']:.2f}"
    )

    print(

        f"TP1:{m['tp1']:.1f}% | "
        f"TP2:{m['tp2']:.1f}% | "
        f"PositiveSymbols:"
        f"{r['positive_symbols']} | "
        f"TopShare:"
        f"{r['top_share']:.1f}%"
    )

    if (
        r["recent"]
        is None
    ):

        print(
            "RECENT15 | "
            "no trades"
        )

    else:

        x = r[
            "recent"
        ]

        print(

            f"RECENT15 | "
            f"Trades:{x['trades']} | "
            f"WR:{x['wr']:.2f}% | "
            f"PF:{pf_text(x['pf'])} | "
            f"NetR:{x['net_r']:.2f}R | "
            f"AvgR:{x['avg_r']:.3f}R | "
            f"DD:{x['dd']:.2f}%"
        )


# ============================================================
# QUALITY GATE
# ============================================================

def quality_gate(
    trades
):

    m = metrics(
        trades
    )

    r = robustness(
        trades
    )

    if m is None:
        return False

    recent_ok = True

    if (

        r["recent"]
        is not None

        and

        r["recent"][
            "trades"
        ]
        >= 10
    ):

        recent_ok = (

            r["recent"][
                "pf"
            ]
            >= 1.00

            and

            r["recent"][
                "net_r"
            ]
            >= 0
        )

    return (

        m["trades"]
        >= 40

        and

        m["pf"]
        >= 1.20

        and

        m["net_r"]
        > 0

        and

        m["avg_r"]
        > 0.05

        and

        m["dd"]
        <= 20

        and

        r[
            "positive_symbols"
        ]
        >= 5

        and

        r[
            "top_share"
        ]
        <= 35

        and

        recent_ok
    )


def print_ranking(
    all_trades
):

    rows = []

    for name in PROFILES:

        m = metrics(
            all_trades[
                name
            ]
        )

        if m is not None:

            rows.append((

                name,

                m,

                quality_gate(
                    all_trades[
                        name
                    ]
                )
            ))

    print()

    print(
        "#" * 96
    )

    print(
        "V4.2 SUPER PUMP MAX "
        "- FINAL RANKING"
    )

    print(
        "#" * 96
    )

    rows.sort(

        key=lambda x: (

            x[2],

            x[1][
                "trades"
            ]
            >= 20,

            x[1][
                "net_r"
            ],

            x[1][
                "pf"
            ],

            -x[1][
                "dd"
            ],
        ),

        reverse=True
    )

    for rank, (
        name,
        m,
        passed
    ) in enumerate(
        rows,
        1
    ):

        print(

            f"{rank}. "
            f"{name:12s} | "

            f"Trades:"
            f"{m['trades']:3d} | "

            f"WR:"
            f"{m['wr']:6.2f}% | "

            f"PF:"
            f"{pf_text(m['pf']):>5s} | "

            f"NetR:"
            f"{m['net_r']:8.2f}R | "

            f"AvgR:"
            f"{m['avg_r']:7.3f}R | "

            f"DD:"
            f"{m['dd']:6.2f}% | "

            f"Gate:"
            f"{'PASS' if passed else 'FAIL'}"
        )

    if not rows:

        print(
            "NO RESULTS"
        )

        return

    best_name = (
        rows[0][0]
    )

    print()

    print(
        f"BEST PROFILE: "
        f"{best_name}"
    )

    print(

        "QUALITY GATE: "

        +

        (
            "PASS"

            if quality_gate(
                all_trades[
                    best_name
                ]
            )

            else "FAIL"
        )
    )

    print(

        "Gate = "
        "Trades>=40, "
        "PF>=1.20, "
        "NetR>0, "
        "AvgR>0.05, "
        "DD<=20%, "
        "PositiveSymbols>=5, "
        "TopShare<=35%, "
        "Recent15 not weak"
    )


def print_symbol_breakdown(
    all_trades
):

    print()

    print(
        "#" * 96
    )

    print(
        "PER-SYMBOL "
        "SUPER PUMP RESULTS"
    )

    print(
        "#" * 96
    )

    for symbol in SYMBOLS:

        parts = [
            symbol.ljust(
                12
            )
        ]

        any_trade = False

        for name in PROFILES:

            rows = [

                t

                for t
                in all_trades[
                    name
                ]

                if t[
                    "symbol"
                ]
                == symbol
            ]

            m = metrics(
                rows
            )

            if m is None:

                parts.append(
                    f"{name}: --"
                )

            else:

                any_trade = True

                parts.append(

                    f"{name}: "
                    f"N={m['trades']} "
                    f"PF="
                    f"{pf_text(m['pf'])} "
                    f"NetR="
                    f"{m['net_r']:+.2f}R"
                )

        if any_trade:

            print(
                " | ".join(
                    parts
                )
            )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 96
    )

    print(
        f"AI TRADE SCANNER "
        f"{VERSION} BACKTEST"
    )

    print(
        "=" * 96
    )

    print(
        f"Test period: "
        f"{TEST_DAYS} days"
    )

    print(
        f"Warmup: "
        f"{WARMUP_DAYS} days"
    )

    print(
        "True 5m trigger + "
        "closed 15m confirmation + "
        "1H setup + 4H regime"
    )

    print(
        "Features: volume acceleration, "
        "compression, higher lows, "
        "sweep/reclaim,"
    )

    print(
        "          breakout proximity, "
        "MACD acceleration, ADX, "
        "multi-TF anti-chase"
    )

    print(
        "Exit: TP2=1.8R, "
        "BE at +0.8R, "
        "conservative same-bar simulation"
    )

    print(
        "Costs: same fee+slippage "
        "assumption as V4 backtest"
    )

    print(
        "This is BACKTEST ONLY. "
        "main_v4.py is not modified."
    )

    all_trades = {

        name: []

        for name
        in PROFILES
    }

    usable_symbols = []

    for n, symbol in enumerate(
        SYMBOLS,
        1
    ):

        print()

        print(
            "-" * 96
        )

        print(
            f"[{n}/"
            f"{len(SYMBOLS)}] "
            f"{symbol}"
        )

        print(
            "-" * 96
        )

        try:

            prepared = (
                prepare_symbol(
                    symbol
                )
            )

            if prepared is None:

                print(
                    "SKIPPED - "
                    "no usable data"
                )

                continue

            (
                h5,
                h15,
                h1,
                h4
            ) = prepared

            usable_symbols.append(
                symbol
            )

            for name in PROFILES:

                rows = find_trades(

                    symbol,
                    h5,
                    h15,
                    h1,
                    h4,
                    name
                )

                all_trades[
                    name
                ].extend(
                    rows
                )

                m = metrics(
                    rows
                )

                if m is None:

                    print(
                        f"{name}: "
                        "0 trades"
                    )

                else:

                    print(

                        f"{name}: "
                        f"N="
                        f"{m['trades']} | "

                        f"WR="
                        f"{m['wr']:.1f}% | "

                        f"PF="
                        f"{pf_text(m['pf'])} | "

                        f"NetR="
                        f"{m['net_r']:+.2f}R"
                    )

        except Exception as error:

            print(

                f"ERROR "
                f"{symbol}: "
                f"{type(error).__name__}: "
                f"{error}"
            )

    print()

    print(

        f"Usable symbols: "
        f"{len(usable_symbols)}/"
        f"{len(SYMBOLS)}"
    )

    for name in PROFILES:

        all_trades[
            name
        ].sort(
            key=lambda x:
                x["time"]
        )

        print_profile(

            name,

            all_trades[
                name
            ]
        )

    print_ranking(
        all_trades
    )

    print_symbol_breakdown(
        all_trades
    )

    print()

    print(
        "V4.2 SUPER PUMP MAX "
        "BACKTEST COMPLETED"
    )


if __name__ == "__main__":
    main()

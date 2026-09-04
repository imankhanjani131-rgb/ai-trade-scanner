import math
import time
import pandas as pd

import backtest as bt


# ============================================================
# V4 15M BACKTEST - 90 DAYS
# 15m trigger + 1H setup + 4H trend + anti-chase
# Historical candles: OKX
# ============================================================

TEST_DAYS = 90
WARMUP_DAYS = 45
FETCH_DAYS = TEST_DAYS + WARMUP_DAYS

MAX_PAGES = 150
REQUEST_DELAY = 0.06

MAX_HOLD_BARS = 72 * 4
FINAL_MIN_SCORE = 8

FINAL_COOLDOWN = pd.Timedelta(
    hours=8
)

RISK_PER_TRADE = 0.01

FEE_PER_SIDE = 0.0006
SLIPPAGE_PER_SIDE = 0.0003

ROUND_TRIP_COST_PCT = 2 * (
    FEE_PER_SIDE
    + SLIPPAGE_PER_SIDE
)

SYMBOLS = bt.SYMBOLS


# ============================================================
# DOWNLOAD 15M HISTORY
# ============================================================

def fetch_15m_history(
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
        f"{symbol} 15m..."
    )

    for page in range(
        1,
        MAX_PAGES + 1
    ):
        params = {
            "instId": inst_id,
            "bar": "15m",
            "limit": "100",
        }

        if cursor is not None:
            params[
                "after"
            ] = str(
                cursor
            )

        batch = bt.okx_request(
            params
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
            or page % 20 == 0
        ):

            stamp = (
                pd.to_datetime(
                    oldest,
                    unit="ms",
                    utc=True
                )
            )

            print(
                f"  page {page} | "
                f"oldest={stamp}"
            )

        if oldest <= start_ms:
            break

        if (
            previous_oldest
            is not None
            and oldest
            >= previous_oldest
        ):
            break

        previous_oldest = oldest
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
        ]
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

    df["datetime"] = (
        pd.to_datetime(
            df["timestamp"],
            unit="ms",
            utc=True
        )
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
        f"bars={len(df)} | "
        f"coverage="
        f"{coverage:.1f} days"
    )

    return df


# ============================================================
# BUILD 1H / 4H FROM 15M
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
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "timestamp": "count",
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

    out["timestamp"] = (
        out["datetime"]
        .astype("int64")
        // 10**6
    )

    return out


def add_indicators(
    df
):
    out = bt.add_indicators(
        df.copy()
    )

    return (
        out
        .dropna()
        .reset_index(
            drop=True
        )
    )


# ============================================================
# 4H TREND
# ============================================================

def trend4(
    row
):
    if (
        row["close"]
        > row["ema200"]

        and row["ema20"]
        > row["ema50"]

        and row["ema50"]
        > row["ema200"]

        and row["rsi"]
        >= 50
    ):
        return "BULLISH"

    if (
        row["close"]
        < row["ema200"]

        and row["ema20"]
        < row["ema50"]

        and row["ema50"]
        < row["ema200"]

        and row["rsi"]
        <= 50
    ):
        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# V4 SCORE
# ============================================================

def score_v4(
    x15,
    p15,
    four_ago,
    x1,
    p1,
    x4
):
    atr15 = max(
        float(
            x15["atr"]
        ),
        1e-12
    )

    pullback = (
        float(
            x15["low"]
        )
        <=
        float(
            x15["ema20"]
        )
        + 0.25 * atr15

        and

        float(
            x15["close"]
        )
        >
        float(
            x15["ema20"]
        )
    )

    reclaim = (
        float(
            p15["close"]
        )
        <=
        float(
            p15["ema20"]
        )

        and

        float(
            x15["close"]
        )
        >
        float(
            x15["ema20"]
        )
    )

    momentum_rising = (
        float(
            x15["macd_hist"]
        )
        >
        float(
            p15["macd_hist"]
        )
    )

    adx_healthy = (
        float(
            x1["adx"]
        )
        >= 20

        and

        float(
            x1["adx"]
        )
        >=
        float(
            p1["adx"]
        )
        - 1.5
    )

    distance_atr = (
        float(
            x15["close"]
        )
        -
        float(
            x15["ema20"]
        )
    ) / atr15

    impulse_atr = max(
        0.0,
        (
            float(
                x15["close"]
            )
            -
            float(
                four_ago["close"]
            )
        )
        / atr15
    )

    overextended = (
        distance_atr
        > 1.25

        or

        impulse_atr
        > 2.50

        or

        float(
            x15["rsi"]
        )
        >= 69
    )

    trend = trend4(
        x4
    )

    tests = [

        (
            trend
            == "BULLISH",
            2
        ),

        (
            float(
                x1["close"]
            )
            >
            float(
                x1["ema50"]
            ),
            1
        ),

        (
            float(
                x1["ema20"]
            )
            >
            float(
                x1["ema50"]
            ),
            1
        ),

        (
            48
            <=
            float(
                x1["rsi"]
            )
            < 68,
            1
        ),

        (
            adx_healthy,
            1
        ),

        (
            float(
                x15["close"]
            )
            >
            float(
                x15["ema20"]
            ),
            1
        ),

        (
            pullback
            or reclaim,
            1
        ),

        (
            momentum_rising,
            1
        ),

        (
            float(
                x15["vol_ratio"]
            )
            >= 0.70,
            1
        ),
    ]

    score = sum(
        points
        for ok, points
        in tests
        if ok
    )

    mandatory = (
        trend
        == "BULLISH"

        and

        not overextended

        and

        48
        <= float(
            x1["rsi"]
        )
        < 68

        and

        float(
            x1["adx"]
        )
        >= 20
    )

    final_ok = (
        mandatory

        and

        score
        >= FINAL_MIN_SCORE

        and

        (
            pullback
            or reclaim
        )

        and

        momentum_rising
    )

    return {
        "score":
            int(score),

        "trend":
            trend,

        "pullback":
            pullback,

        "reclaim":
            reclaim,

        "momentum":
            momentum_rising,

        "overextended":
            overextended,

        "distance_atr":
            float(
                distance_atr
            ),

        "impulse_atr":
            float(
                impulse_atr
            ),

        "rsi1":
            float(
                x1["rsi"]
            ),

        "adx1":
            float(
                x1["adx"]
            ),

        "final_ok":
            final_ok,
    }


# ============================================================
# RESISTANCE
# ============================================================

def nearest_resistance(
    h1,
    entry
):
    highs = (
        h1["high"]
        .astype(float)
        .tolist()
    )

    if len(highs) < 5:
        return None

    pivots = []

    start = max(
        2,
        len(highs) - 45
    )

    end = (
        len(highs)
        - 2
    )

    for i in range(
        start,
        end
    ):

        high = highs[i]

        if (
            high
            > highs[i - 1]

            and

            high
            >= highs[i - 2]

            and

            high
            > highs[i + 1]

            and

            high
            >= highs[i + 2]

            and

            high
            > entry
        ):
            pivots.append(
                high
            )

    if pivots:
        return min(
            pivots
        )

    return None


# ============================================================
# V4 ENTRY / SL / TP
# ============================================================

def levels_v4(
    h15,
    i,
    h1_closed
):
    x = h15.iloc[i]

    entry = float(
        x["close"]
    )

    atr = float(
        x["atr"]
    )

    recent = h15.iloc[
        max(
            0,
            i - 16
        ):
        i
    ]

    if len(recent) < 10:
        raise ValueError(
            "Not enough history"
        )

    swing_low = float(
        recent["low"].min()
    )

    sl = min(
        swing_low
        - 0.10 * atr,

        entry
        - 0.80 * atr
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
        2.20 * atr
    ):
        raise ValueError(
            "Stop too wide"
        )

    resistance = (
        nearest_resistance(
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
        0.65 * risk
    ):
        raise ValueError(
            "Resistance too close"
        )

    tp1 = (
        entry
        + 1.00 * risk
    )

    if (
        resistance
        is not None

        and

        resistance
        < tp1
    ):
        tp1 = (
            resistance
            * 0.998
        )

    tp2 = (
        entry
        + 1.50 * risk
    )

    tp3 = (
        entry
        + 2.20 * risk
    )

    be = (
        entry
        + 0.70 * risk
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
# TRADE SIMULATION
# ============================================================

def simulate_trade(
    h15,
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
    )

    if risk_pct > 0:
        cost_r = (
            ROUND_TRIP_COST_PCT
            / risk_pct
        )
    else:
        cost_r = 0.0

    tp1_hit = False
    tp2_hit = False
    tp3_hit = False

    be_armed = False

    end_i = min(
        len(h15) - 1,
        i + MAX_HOLD_BARS
    )

    for j in range(
        i + 1,
        end_i + 1
    ):
        bar = h15.iloc[j]

        low = float(
            bar["low"]
        )

        high = float(
            bar["high"]
        )

        if be_armed:
            active_stop = entry
        else:
            active_stop = sl

        # Conservative:
        # if SL and TP happen in same candle,
        # adverse move is counted first.
        if low <= active_stop:

            if be_armed:
                gross_r = 0.0
                reason = "BE"

            else:
                gross_r = -1.0
                reason = "SL"

            return {
                "r":
                    gross_r
                    - cost_r,

                "exit":
                    reason,

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
            and high >= be
        ):
            be_armed = True

        if high >= tp1:
            tp1_hit = True

        if high >= tp2:

            tp2_hit = True

            return {
                "r":
                    1.50
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

        if high >= tp3:
            tp3_hit = True

    close = float(
        h15.iloc[
            end_i
        ]["close"]
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
# PREPARE DATA
# ============================================================

def prepare_symbol(
    symbol
):
    h15 = fetch_15m_history(
        symbol
    )

    if (
        h15 is None
        or h15.empty
    ):
        return None

    h1 = resample_ohlcv(
        h15,
        "1h",
        4
    )

    h4 = resample_ohlcv(
        h15,
        "4h",
        16
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
        h15.empty
        or h1.empty
        or h4.empty
    ):
        return None

    h15[
        "signal_time"
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
        h15,
        h1,
        h4
    )


# ============================================================
# FIND V4 FINAL TRADES
# ============================================================

def find_trades(
    symbol,
    h15,
    h1,
    h4
):
    trades = []

    test_end = (
        h15.iloc[-1][
            "signal_time"
        ]
    )

    test_start = (
        test_end
        - pd.Timedelta(
            days=TEST_DAYS
        )
    )

    last_signal_time = None

    for i in range(
        6,
        len(h15) - 1
    ):
        x15 = h15.iloc[i]

        signal_time = (
            x15[
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
            FINAL_COOLDOWN
        ):
            continue

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
            idx1 < 1
            or idx4 < 0
        ):
            continue

        x1 = h1.iloc[
            idx1
        ]

        p1 = h1.iloc[
            idx1 - 1
        ]

        x4 = h4.iloc[
            idx4
        ]

        p15 = h15.iloc[
            i - 1
        ]

        four_ago = h15.iloc[
            i - 4
        ]

        info = score_v4(
            x15,
            p15,
            four_ago,
            x1,
            p1,
            x4
        )

        if not info[
            "final_ok"
        ]:
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
            ) = levels_v4(
                h15,
                i,
                h1_closed
            )

        except ValueError:
            continue

        outcome = (
            simulate_trade(
                h15,
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

            "score":
                info[
                    "score"
                ],

            "rsi1":
                info[
                    "rsi1"
                ],

            "adx1":
                info[
                    "adx1"
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

def calc_metrics(
    trades
):
    if not trades:
        return None

    rs = [
        t["r"]
        for t in trades
    ]

    wins = sum(
        r > 0
        for r in rs
    )

    losses = sum(
        r < 0
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

    else:

        pf = float(
            "inf"
        )

    equity = 100.0
    peak = 100.0
    max_dd = 0.0

    for r in rs:

        equity *= (
            1
            + RISK_PER_TRADE
            * r
        )

        peak = max(
            peak,
            equity
        )

        if peak > 0:

            dd = (
                peak - equity
            ) / peak * 100

            max_dd = max(
                max_dd,
                dd
            )

    return {

        "trades":
            len(trades),

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            wins
            / len(trades)
            * 100,

        "pf":
            pf,

        "net_r":
            sum(rs),

        "avg_r":
            sum(rs)
            / len(rs),

        "max_dd":
            max_dd,

        "equity":
            equity,

        "tp1_rate":
            sum(
                t["tp1"]
                for t in trades
            )
            / len(trades)
            * 100,

        "tp2_rate":
            sum(
                t["tp2"]
                for t in trades
            )
            / len(trades)
            * 100,

        "tp3_rate":
            sum(
                t["tp3"]
                for t in trades
            )
            / len(trades)
            * 100,

        "sl":
            sum(
                t["exit"]
                == "SL"
                for t in trades
            ),

        "be":
            sum(
                t["exit"]
                == "BE"
                for t in trades
            ),

        "time":
            sum(
                t["exit"]
                == "TIME"
                for t in trades
            ),
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


def print_metrics(
    label,
    trades
):
    print()

    print(
        "=" * 78
    )

    print(
        label
    )

    print(
        "=" * 78
    )

    m = calc_metrics(
        trades
    )

    if m is None:

        print(
            "NO TRADES"
        )

        return

    print(
        f"Trades: "
        f"{m['trades']}"
    )

    print(
        f"Wins/Losses: "
        f"{m['wins']}/"
        f"{m['losses']}"
    )

    print(
        f"Win rate: "
        f"{m['win_rate']:.2f}%"
    )

    print(
        f"Profit factor: "
        f"{pf_text(m['pf'])}"
    )

    print(
        f"Net R: "
        f"{m['net_r']:.2f}R"
    )

    print(
        f"Avg R: "
        f"{m['avg_r']:.3f}R"
    )

    print(
        f"Max drawdown: "
        f"{m['max_dd']:.2f}%"
    )

    print(
        f"Ending equity "
        f"(1% risk): "
        f"{m['equity']:.2f}"
    )

    print(
        f"TP1 touched: "
        f"{m['tp1_rate']:.2f}%"
    )

    print(
        f"TP2 hit: "
        f"{m['tp2_rate']:.2f}%"
    )

    print(
        f"TP3 touched "
        f"before exit: "
        f"{m['tp3_rate']:.2f}%"
    )

    print(
        f"SL exits: "
        f"{m['sl']} | "
        f"BE exits: "
        f"{m['be']} | "
        f"TIME exits: "
        f"{m['time']}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 80
    )

    print(
        "AI TRADE SCANNER V4 "
        "- 15M BACKTEST"
    )

    print(
        "=" * 80
    )

    print(
        f"Test period: "
        f"{TEST_DAYS} days"
    )

    print(
        "Entry logic: "
        "V4 FINAL only"
    )

    print(
        "Trigger 15m | "
        "Setup 1H | "
        "Trend 4H"
    )

    print(
        "Anti-chase: ON"
    )

    print(
        "Primary target: "
        "TP2 = +1.5R"
    )

    print(
        "Profit protection: "
        "BE armed at +0.7R"
    )

    print(
        f"Max hold: "
        f"{MAX_HOLD_BARS / 4:.0f} "
        f"hours"
    )

    print(
        f"Round-trip cost "
        f"assumption: "
        f"{ROUND_TRIP_COST_PCT * 100:.3f}%"
    )

    print(
        f"Symbols requested: "
        f"{len(SYMBOLS)}"
    )

    all_trades = []
    usable = []

    for n, symbol in enumerate(
        SYMBOLS,
        start=1
    ):

        print()

        print(
            "#" * 80
        )

        print(
            f"[{n}/"
            f"{len(SYMBOLS)}] "
            f"{symbol}"
        )

        print(
            "#" * 80
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
                h15,
                h1,
                h4
            ) = prepared

            trades = find_trades(
                symbol,
                h15,
                h1,
                h4
            )

            all_trades.extend(
                trades
            )

            usable.append(
                symbol
            )

            print(
                f"V4 FINAL trades: "
                f"{len(trades)}"
            )

            print_metrics(
                f"{symbol} - "
                f"{TEST_DAYS} DAYS",
                trades
            )

        except Exception as error:

            print(
                f"ERROR "
                f"{symbol}: "
                f"{error}"
            )

    all_trades.sort(
        key=lambda x:
            x["time"]
    )

    print()

    print(
        "#" * 80
    )

    print(
        "OVERALL V4 "
        "15M RESULT"
    )

    print(
        "#" * 80
    )

    print(
        f"Usable symbols: "
        f"{len(usable)}/"
        f"{len(SYMBOLS)}"
    )

    print(
        usable
    )

    print_metrics(
        f"ALL SYMBOLS "
        f"- LAST "
        f"{TEST_DAYS} DAYS",
        all_trades
    )

    if all_trades:

        print()

        print(
            "PER-SYMBOL RANKING"
        )

        ranking = []

        for symbol in usable:

            rows = [
                t
                for t
                in all_trades
                if t["symbol"]
                == symbol
            ]

            m = calc_metrics(
                rows
            )

            if m is not None:

                ranking.append(
                    (
                        symbol,
                        m
                    )
                )

        ranking.sort(
            key=lambda x: (
                x[1]["net_r"],
                x[1]["pf"]
            ),
            reverse=True
        )

        for (
            pos,
            (
                symbol,
                m
            )
        ) in enumerate(
            ranking,
            start=1
        ):

            print(

                f"{pos:02d}. "
                f"{symbol:12s} | "

                f"Trades:"
                f"{m['trades']:3d} | "

                f"WR:"
                f"{m['win_rate']:6.2f}% | "

                f"PF:"
                f"{pf_text(m['pf']):>5s} | "

                f"NetR:"
                f"{m['net_r']:7.2f}R | "

                f"DD:"
                f"{m['max_dd']:5.2f}% | "

                f"TP1:"
                f"{m['tp1_rate']:5.1f}% | "

                f"TP2:"
                f"{m['tp2_rate']:5.1f}%"
            )

    print()

    print(
        "BACKTEST COMPLETED"
    )


if __name__ == "__main__":
    main()

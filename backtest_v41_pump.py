import math
import pandas as pd

import backtest_v4_15m as base


VERSION = "V4.1-PUMP-CORE"
PUMP_COOLDOWN = pd.Timedelta(hours=6)

PROFILES = {
    "P1_STRICT": {
        "min_score": 9,
        "min_vol": 1.50,
        "min_range_atr": 1.00,
        "require_breakout": True,
        "require_4h_bull": True,
    },
    "P2_BALANCED": {
        "min_score": 8,
        "min_vol": 1.20,
        "min_range_atr": 0.85,
        "require_breakout": True,
        "require_4h_bull": False,
    },
    "P3_EARLY": {
        "min_score": 7,
        "min_vol": 1.00,
        "min_range_atr": 0.65,
        "require_breakout": False,
        "require_4h_bull": False,
    },
}


def safe_float(value, default=0.0):
    try:
        value = float(value)

        if math.isnan(value) or math.isinf(value):
            return default

        return value

    except Exception:
        return default


def pump_features(
    h15,
    i,
    x1,
    p1,
    x4,
):
    x = h15.iloc[i]
    p = h15.iloc[i - 1]
    p2 = h15.iloc[i - 2]

    atr = max(
        safe_float(x["atr"]),
        1e-12,
    )

    close = safe_float(x["close"])
    open_ = safe_float(x["open"])
    high = safe_float(x["high"])
    low = safe_float(x["low"])

    ema20 = safe_float(
        x["ema20"]
    )

    rsi15 = safe_float(
        x["rsi"]
    )

    vol_ratio = safe_float(
        x["vol_ratio"]
    )

    candle_range = max(
        high - low,
        1e-12,
    )

    body = max(
        close - open_,
        0.0,
    )

    body_ratio = (
        body / candle_range
    )

    close_pos = (
        close - low
    ) / candle_range

    range_atr = (
        candle_range / atr
    )

    recent = h15.iloc[
        max(0, i - 12):i
    ]

    recent_high = safe_float(
        recent["high"].max(),
        high,
    )

    breakout = (
        close > recent_high
    )

    near_breakout = (
        close
        >= recent_high
        - 0.15 * atr
    )

    macd_now = safe_float(
        x["macd_hist"]
    )

    macd_prev = safe_float(
        p["macd_hist"]
    )

    macd_prev2 = safe_float(
        p2["macd_hist"]
    )

    momentum_rising = (
        macd_now > macd_prev
        and
        macd_prev >= macd_prev2
    )

    prev = h15.iloc[
        max(0, i - 8):i
    ]

    prev_ranges = (
        prev["high"].astype(float)
        -
        prev["low"].astype(float)
    )

    if len(prev_ranges) >= 5:

        compression_ratio = (
            safe_float(
                prev_ranges.mean()
            )
            / atr
        )

    else:
        compression_ratio = 99.0

    compressed = (
        compression_ratio <= 0.90
    )

    distance_atr = (
        close - ema20
    ) / atr

    four_ago_close = safe_float(
        h15.iloc[
            max(0, i - 4)
        ]["close"],
        close,
    )

    impulse_atr = max(
        0.0,
        (
            close
            - four_ago_close
        )
        / atr,
    )

    trend = base.trend4(
        x4
    )

    one_h_bull = (
        safe_float(
            x1["close"]
        )
        >
        safe_float(
            x1["ema50"]
        )

        and

        safe_float(
            x1["ema20"]
        )
        >
        safe_float(
            x1["ema50"]
        )

        and

        48
        <=
        safe_float(
            x1["rsi"]
        )
        < 72
    )

    adx_healthy = (
        safe_float(
            x1["adx"]
        )
        >= 20

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

    not_bearish_4h = (
        trend != "BEARISH"
    )

    anti_chase = (
        distance_atr <= 1.60

        and

        impulse_atr <= 3.00

        and

        rsi15 < 75
    )

    tests = [
        (
            not_bearish_4h,
            1,
        ),

        (
            trend == "BULLISH",
            1,
        ),

        (
            one_h_bull,
            2,
        ),

        (
            adx_healthy,
            1,
        ),

        (
            vol_ratio >= 1.00,
            1,
        ),

        (
            vol_ratio >= 1.35,
            1,
        ),

        (
            range_atr >= 0.75,
            1,
        ),

        (
            body_ratio >= 0.50,
            1,
        ),

        (
            close_pos >= 0.70,
            1,
        ),

        (
            momentum_rising,
            1,
        ),

        (
            compressed,
            1,
        ),

        (
            near_breakout,
            1,
        ),

        (
            breakout,
            2,
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

        "trend":
            trend,

        "one_h_bull":
            bool(
                one_h_bull
            ),

        "adx_healthy":
            bool(
                adx_healthy
            ),

        "vol_ratio":
            float(
                vol_ratio
            ),

        "range_atr":
            float(
                range_atr
            ),

        "body_ratio":
            float(
                body_ratio
            ),

        "close_pos":
            float(
                close_pos
            ),

        "momentum":
            bool(
                momentum_rising
            ),

        "compressed":
            bool(
                compressed
            ),

        "compression_ratio":
            float(
                compression_ratio
            ),

        "breakout":
            bool(
                breakout
            ),

        "near_breakout":
            bool(
                near_breakout
            ),

        "anti_chase":
            bool(
                anti_chase
            ),

        "distance_atr":
            float(
                distance_atr
            ),

        "impulse_atr":
            float(
                impulse_atr
            ),

        "rsi15":
            float(
                rsi15
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


def profile_ok(
    profile_name,
    f,
):
    p = PROFILES[
        profile_name
    ]

    common = (
        f["score"]
        >=
        p["min_score"]

        and

        f["one_h_bull"]

        and

        f["adx_healthy"]

        and

        f["anti_chase"]

        and

        f["momentum"]

        and

        f["vol_ratio"]
        >=
        p["min_vol"]

        and

        f["range_atr"]
        >=
        p[
            "min_range_atr"
        ]
    )

    if not common:
        return False

    if (
        p[
            "require_4h_bull"
        ]

        and

        f["trend"]
        != "BULLISH"
    ):
        return False

    if (
        not p[
            "require_4h_bull"
        ]

        and

        f["trend"]
        == "BEARISH"
    ):
        return False

    if p[
        "require_breakout"
    ]:
        return f["breakout"]

    return f[
        "near_breakout"
    ]


def make_trade(
    symbol,
    signal_time,
    f,
    outcome,
):
    return {
        "symbol":
            symbol,

        "time":
            signal_time,

        "r":
            float(
                outcome["r"]
            ),

        "exit":
            outcome["exit"],

        "tp1":
            bool(
                outcome["tp1"]
            ),

        "tp2":
            bool(
                outcome["tp2"]
            ),

        "score":
            int(
                f["score"]
            ),

        "vol_ratio":
            float(
                f["vol_ratio"]
            ),

        "range_atr":
            float(
                f["range_atr"]
            ),

        "trend":
            f["trend"],
    }


def find_profile_trades(
    symbol,
    h15,
    h1,
    h4,
    profile_name,
):
    trades = []

    last_signal_time = None

    test_end = (
        h15.iloc[-1][
            "signal_time"
        ]
    )

    test_start = (
        test_end
        -
        pd.Timedelta(
            days=
                base.TEST_DAYS
        )
    )

    for i in range(
        20,
        len(h15) - 1,
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
            PUMP_COOLDOWN
        ):
            continue

        idx1 = (
            h1[
                "available_time"
            ]
            .searchsorted(
                signal_time,
                side="right",
            )
            - 1
        )

        idx4 = (
            h4[
                "available_time"
            ]
            .searchsorted(
                signal_time,
                side="right",
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

        f = pump_features(
            h15,
            i,
            x1,
            p1,
            x4,
        )

        if not profile_ok(
            profile_name,
            f,
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
                be,
            ) = base.levels_v4(
                h15,
                i,
                h1_closed,
            )

        except ValueError:
            continue

        outcome = (
            base.simulate_trade(
                h15,
                i,
                entry,
                sl,
                tp1,
                tp2,
                tp3,
                be,
            )
        )

        trades.append(
            make_trade(
                symbol,
                signal_time,
                f,
                outcome,
            )
        )

        last_signal_time = (
            signal_time
        )

    return trades


def metrics(
    trades
):
    if not trades:
        return None

    ordered = sorted(
        trades,
        key=lambda x:
            x["time"],
    )

    rs = [
        float(t["r"])
        for t in ordered
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
            base.RISK_PER_TRADE
            * r
        )

        peak = max(
            peak,
            equity,
        )

        if peak > 0:

            dd = (
                peak
                - equity
            ) / peak * 100

            max_dd = max(
                max_dd,
                dd,
            )

    tp1_rate = (
        sum(
            bool(
                t["tp1"]
            )
            for t in ordered
        )
        /
        len(ordered)
        * 100
    )

    tp2_rate = (
        sum(
            bool(
                t["tp2"]
            )
            for t in ordered
        )
        /
        len(ordered)
        * 100
    )

    return {
        "trades":
            len(ordered),

        "wins":
            wins,

        "losses":
            losses,

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
            tp1_rate,

        "tp2":
            tp2_rate,

        "sl":
            sum(
                t["exit"]
                == "SL"
                for t in ordered
            ),

        "be":
            sum(
                t["exit"]
                == "BE"
                for t in ordered
            ),

        "time":
            sum(
                t["exit"]
                == "TIME"
                for t in ordered
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


def print_profile(
    profile_name,
    trades,
):
    m = metrics(
        trades
    )

    print()
    print(
        "=" * 84
    )

    print(
        f"{profile_name} | "
        f"{PROFILES[profile_name]}"
    )

    print(
        "=" * 84
    )

    if m is None:
        print(
            "NO TRADES"
        )
        return

    print(
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
        f"SL:{m['sl']} | "
        f"BE:{m['be']} | "
        f"TIME:{m['time']}"
    )


def print_ranking(
    all_trades
):
    rows = []

    for profile_name in PROFILES:

        m = metrics(
            all_trades[
                profile_name
            ]
        )

        if m is not None:
            rows.append(
                (
                    profile_name,
                    m,
                )
            )

    print()
    print(
        "#" * 84
    )

    print(
        "V4.1 PUMP CORE "
        "- FINAL RANKING"
    )

    print(
        "#" * 84
    )

    rows.sort(
        key=lambda x: (
            x[1]["net_r"],
            x[1]["pf"],
            -x[1]["dd"],
        ),
        reverse=True,
    )

    for rank, (
        name,
        m,
    ) in enumerate(
        rows,
        start=1,
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
            f"{m['dd']:6.2f}%"
        )

    if not rows:

        print(
            "NO RESULTS"
        )

        return

    best_name, best = (
        rows[0]
    )

    quality_pass = (
        best["trades"] >= 40

        and

        best["pf"] >= 1.20

        and

        best["net_r"] > 0

        and

        best["avg_r"] > 0

        and

        best["dd"] <= 25
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
            if quality_pass
            else "FAIL"
        )
    )

    print(
        "Gate = "
        "Trades>=40, "
        "PF>=1.20, "
        "NetR>0, "
        "AvgR>0, "
        "DD<=25%"
    )


def print_symbol_breakdown(
    all_trades
):
    print()
    print(
        "#" * 84
    )

    print(
        "PER-SYMBOL "
        "PUMP RESULTS"
    )

    print(
        "#" * 84
    )

    for symbol in (
        base.SYMBOLS
    ):

        parts = [
            symbol.ljust(12)
        ]

        any_trade = False

        for profile_name in (
            PROFILES
        ):

            rows = [
                t
                for t
                in all_trades[
                    profile_name
                ]
                if t["symbol"]
                == symbol
            ]

            m = metrics(
                rows
            )

            if m is None:

                parts.append(
                    f"{profile_name}: --"
                )

            else:

                any_trade = True

                parts.append(
                    f"{profile_name}: "
                    f"{m['net_r']:+.2f}R "
                    f"PF="
                    f"{pf_text(m['pf'])} "
                    f"N="
                    f"{m['trades']}"
                )

        if any_trade:

            print(
                " | ".join(
                    parts
                )
            )


def main():
    print(
        "=" * 84
    )

    print(
        f"AI TRADE SCANNER "
        f"{VERSION} BACKTEST"
    )

    print(
        "=" * 84
    )

    print(
        f"Test period: "
        f"{base.TEST_DAYS} days"
    )

    print(
        "Data: existing "
        "15m + 1H + 4H "
        "V4 history"
    )

    print(
        "Goal: early "
        "pump/breakout "
        "entry quality"
    )

    print(
        "Exit logic: SAME "
        "as V4 "
        "(TP2=1.5R + "
        "BE at +0.7R)"
    )

    print(
        "Anti-chase: ON"
    )

    print(
        "No live bot files "
        "are modified "
        "by this test."
    )

    print()

    all_trades = {
        name: []
        for name in PROFILES
    }

    usable_symbols = []

    for n, symbol in enumerate(
        base.SYMBOLS,
        start=1,
    ):

        print()
        print(
            "-" * 84
        )

        print(
            f"[{n}/"
            f"{len(base.SYMBOLS)}] "
            f"{symbol}"
        )

        print(
            "-" * 84
        )

        try:

            prepared = (
                base.prepare_symbol(
                    symbol
                )
            )

            if prepared is None:

                print(
                    "SKIPPED - "
                    "no usable data"
                )

                continue

            h15, h1, h4 = (
                prepared
            )

            usable_symbols.append(
                symbol
            )

            for profile_name in (
                PROFILES
            ):

                trades = (
                    find_profile_trades(
                        symbol,
                        h15,
                        h1,
                        h4,
                        profile_name,
                    )
                )

                all_trades[
                    profile_name
                ].extend(
                    trades
                )

                m = metrics(
                    trades
                )

                if m is None:

                    print(
                        f"{profile_name}: "
                        "0 trades"
                    )

                else:

                    print(
                        f"{profile_name}: "
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
        f"{len(base.SYMBOLS)}"
    )

    for profile_name in (
        PROFILES
    ):

        all_trades[
            profile_name
        ].sort(
            key=lambda x:
                x["time"]
        )

        print_profile(
            profile_name,
            all_trades[
                profile_name
            ],
        )

    print_ranking(
        all_trades
    )

    print_symbol_breakdown(
        all_trades
    )

    print()

    print(
        "V4.1 PUMP CORE "
        "BACKTEST COMPLETED"
    )


if __name__ == "__main__":
    main()

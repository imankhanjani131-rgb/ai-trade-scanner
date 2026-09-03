import pandas as pd
import backtest as bt

VERSION = "SHORT-V2-INDEPENDENT"

RECENT_DAYS = 90
LAST30_DAYS = 30

# Short can have a different optimum from LONG.
TARGETS = (1.5, 2.0)


# ============================================================
# PASS / FAIL RULES
# ============================================================

def metric_pass(m, period):

    if m is None:
        return False

    if period == "OLDER":
        return (
            m["trades"] >= 20
            and m["pf"] >= 1.05
            and m["net_r"] > 0
            and m["max_dd"] < 30
        )

    if period == "RECENT":
        return (
            m["trades"] >= 6
            and m["pf"] >= 1.00
            and m["net_r"] > 0
            and m["max_dd"] < 20
        )

    return (
        m["trades"] >= 30
        and m["pf"] >= 1.10
        and m["net_r"] > 0
        and m["max_dd"] < 30
    )


def show(label, m):

    if m is None:
        print(
            f"{label} | NO TRADES"
        )
        return

    print(
        f"{label} | "
        f"Trades:{m['trades']} | "
        f"WR:{m['win_rate']:.2f}% | "
        f"PF:{bt.pf_text(m['pf'])} | "
        f"NetR:{m['net_r']:.2f}R | "
        f"AvgR:{m['avg_r']:.3f}R | "
        f"DD:{m['max_dd']:.2f}%"
    )


# ============================================================
# BEARISH REGIME
# ============================================================

def bearish_4h_strict(row):

    return (
        bt.trend4(row)
        == "BEARISH"
    )


def bearish_4h_soft(row):

    return (
        row["close4"]
        < row["ema200_4"]

        and row["ema20_4"]
        < row["ema50_4"]

        and row["rsi_4"]
        < 52
    )


# ============================================================
# BTC MARKET FILTER
# ============================================================

def build_btc_regime_map(
    btc_df
):

    output = {}

    for i in range(
        1,
        len(btc_df)
    ):

        x = btc_df.iloc[i]

        output[
            x["signal_time"]
        ] = {

            "strict":
                bearish_4h_strict(x),

            "soft":
                (
                    bearish_4h_soft(x)

                    and x["close"]
                    < x["ema50"]

                    and x["rsi"]
                    < 55
                )
        }

    return output


# ============================================================
# INDEPENDENT SHORT CANDIDATES
# ============================================================

def build_candidates(
    symbol,
    df,
    btc_map
):

    rows = []

    for i in range(
        25,
        len(df) - 1
    ):

        x = df.iloc[i]

        p = df.iloc[
            i - 1
        ]

        p2 = df.iloc[
            i - 2
        ]

        market = btc_map.get(
            x["signal_time"],
            {
                "strict": False,
                "soft": False
            }
        )

        own_strict = (
            bearish_4h_strict(x)
        )

        own_soft = (
            bearish_4h_soft(x)
        )

        prev20_low = float(
            df.iloc[
                i - 20:i
            ]["low"].min()
        )

        # --------------------------------
        # Pullback rejection from EMA20
        # --------------------------------

        ema20_reject = (

            x["high"]
            >= x["ema20"] * 0.998

            and x["close"]
            < x["ema20"]

            and x["close"]
            < x["open"]
        )

        # --------------------------------
        # Pullback rejection from EMA50
        # --------------------------------

        ema50_reject = (

            x["high"]
            >= x["ema50"] * 0.998

            and x["close"]
            < x["ema50"]

            and x["close"]
            < x["open"]
        )

        # --------------------------------
        # 20-hour breakdown
        # --------------------------------

        break20 = (

            x["low"]
            < prev20_low

            and x["close"]
            < prev20_low
        )

        # --------------------------------
        # RSI rollover through 50
        # --------------------------------

        rsi_cross50 = (

            p["rsi"] >= 50

            and x["rsi"] < 50
        )

        # --------------------------------
        # MACD bearish crossover
        # --------------------------------

        macd_crossdown = (

            p["macd"]
            >= p["macd_signal"]

            and x["macd"]
            < x["macd_signal"]
        )

        # --------------------------------
        # Momentum worsening
        # --------------------------------

        hist_falling = (

            x["macd_hist"]
            < p["macd_hist"]

            and p["macd_hist"]
            <= p2["macd_hist"]
        )

        # --------------------------------
        # Full 1H bearish EMA stack
        # --------------------------------

        trend_stack = (

            x["close"]
            < x["ema20"]

            and x["ema20"]
            < x["ema50"]

            and x["ema50"]
            < x["ema200"]
        )

        distance20 = (

            abs(
                x["close"]
                - x["ema20"]
            )

            / x["close"]
        )

        # Broad universe only.
        # This is NOT the old score>=9
        # short candidate engine.

        broad_bearish = (

            (
                own_soft
                or market["soft"]
            )

            and x["close"]
            < x["ema50"]

            and 30
            < x["rsi"]
            < 60

            and x["adx"]
            >= 18
        )

        if not broad_bearish:
            continue

        entry, sl, _ = (
            bt.levels(
                df,
                i,
                "SHORT"
            )
        )

        rows.append({

            "symbol":
                symbol,

            "i":
                i,

            "time":
                x["signal_time"],

            "side":
                "SHORT",

            "score":
                0,

            "rsi":
                float(
                    x["rsi"]
                ),

            "adx":
                float(
                    x["adx"]
                ),

            "entry":
                float(entry),

            "sl":
                float(sl),

            "own_strict":
                own_strict,

            "own_soft":
                own_soft,

            "btc_strict":
                bool(
                    market["strict"]
                ),

            "btc_soft":
                bool(
                    market["soft"]
                ),

            "ema20_reject":
                ema20_reject,

            "ema50_reject":
                ema50_reject,

            "break20":
                break20,

            "rsi_cross50":
                rsi_cross50,

            "macd_crossdown":
                macd_crossdown,

            "hist_falling":
                hist_falling,

            "trend_stack":
                trend_stack,

            "macd_bear":
                bool(
                    x["macd"]
                    < x["macd_signal"]
                ),

            "bear_candle":
                bool(
                    x["close"]
                    < x["open"]
                ),

            "vol_ratio":
                float(
                    x["vol_ratio"]
                ),

            "distance20":
                float(
                    distance20
                )
        })

    return rows


# ============================================================
# CUSTOM SHORT SIMULATOR
# Tests 1.5R and 2R independently
# ============================================================

def simulate_target(
    df,
    trade,
    target_r
):

    entry = trade[
        "entry"
    ]

    sl = trade[
        "sl"
    ]

    risk = (
        sl - entry
    )

    if risk <= 0:

        return (
            0.0,
            trade["i"],
            "INVALID"
        )

    tp = (
        entry
        - target_r * risk
    )

    end_i = min(

        trade["i"]
        + bt.MAX_HOLD_HOURS,

        len(df) - 1
    )

    raw_r = None

    exit_i = end_i

    reason = "TIME"

    for j in range(

        trade["i"] + 1,

        end_i + 1
    ):

        bar = df.iloc[j]

        hit_sl = (
            bar["high"]
            >= sl
        )

        hit_tp = (
            bar["low"]
            <= tp
        )

        # Conservative:
        # if TP and SL occur
        # inside same 1H candle,
        # count SL first.

        if hit_sl and hit_tp:

            raw_r = -1.0

            exit_i = j

            reason = (
                "SL-FIRST"
            )

            break

        if hit_sl:

            raw_r = -1.0

            exit_i = j

            reason = "SL"

            break

        if hit_tp:

            raw_r = float(
                target_r
            )

            exit_i = j

            reason = (
                f"TP{target_r:g}R"
            )

            break

    if raw_r is None:

        exit_price = float(
            df.iloc[
                end_i
            ]["close"]
        )

        raw_r = (

            entry
            - exit_price

        ) / risk

    cost_r = (

        entry
        * bt.ROUND_TRIP_COST_PCT

    ) / risk

    net_r = (
        raw_r
        - cost_r
    )

    return (
        float(net_r),
        exit_i,
        reason
    )


# ============================================================
# RUN ONE STRATEGY
# ============================================================

def run_strategy(
    candidates,
    data,
    condition,
    target_r
):

    results = []

    blocked_until = {}

    for trade in candidates:

        if not condition(
            trade
        ):

            continue

        symbol = trade[
            "symbol"
        ]

        if (
            trade["i"]
            <= blocked_until.get(
                symbol,
                -1
            )
        ):

            continue

        (
            r,
            exit_i,
            reason

        ) = simulate_target(

            data[symbol],

            trade,

            target_r
        )

        blocked_until[
            symbol
        ] = exit_i

        results.append({

            "symbol":
                symbol,

            "time":
                trade["time"],

            "side":
                "SHORT",

            "score":
                0,

            "rsi":
                trade["rsi"],

            "adx":
                trade["adx"],

            "r":
                r,

            "exit":
                reason
        })

    return sorted(

        results,

        key=lambda row:
            row["time"]
    )


# ============================================================
# SHORT V2 SETUPS
# ============================================================

def strategy_list():

    return [

        (
            "V2-A BTC+OWN BEAR / EMA20 REJECTION",

            lambda t: (

                t["btc_soft"]

                and t["own_strict"]

                and t[
                    "ema20_reject"
                ]

                and 40
                <= t["rsi"]
                <= 55

                and t["adx"]
                >= 25

                and t[
                    "macd_bear"
                ]
            )
        ),

        (
            "V2-B OWN BEAR / EMA50 REJECTION",

            lambda t: (

                t["own_strict"]

                and t[
                    "ema50_reject"
                ]

                and 42
                <= t["rsi"]
                <= 58

                and t["adx"]
                >= 25

                and t[
                    "macd_bear"
                ]
            )
        ),

        (
            "V2-C BTC+OWN BEAR / 20H BREAKDOWN",

            lambda t: (

                t["btc_soft"]

                and t["own_soft"]

                and t["break20"]

                and 34
                <= t["rsi"]
                <= 50

                and t["adx"]
                >= 25

                and t[
                    "vol_ratio"
                ]
                >= 1.10
            )
        ),

        (
            "V2-D STRONG TREND CONTINUATION",

            lambda t: (

                t["btc_soft"]

                and t[
                    "own_strict"
                ]

                and t[
                    "trend_stack"
                ]

                and 35
                <= t["rsi"]
                <= 48

                and t["adx"]
                >= 35

                and t[
                    "hist_falling"
                ]

                and t[
                    "distance20"
                ]
                <= 0.020
            )
        ),

        (
            "V2-E RSI50 ROLLOVER",

            lambda t: (

                t["btc_soft"]

                and t[
                    "own_strict"
                ]

                and t[
                    "rsi_cross50"
                ]

                and t[
                    "trend_stack"
                ]

                and t["adx"]
                >= 25

                and t[
                    "macd_bear"
                ]
            )
        ),

        (
            "V2-F MACD CROSSDOWN AFTER PULLBACK",

            lambda t: (

                t["btc_soft"]

                and t[
                    "own_strict"
                ]

                and t[
                    "macd_crossdown"
                ]

                and 40
                <= t["rsi"]
                <= 56

                and t["adx"]
                >= 25

                and t[
                    "distance20"
                ]
                <= 0.025
            )
        ),

        (
            "V2-G STRICT EMA20 REJECTION",

            lambda t: (

                t[
                    "btc_strict"
                ]

                and t[
                    "own_strict"
                ]

                and t[
                    "ema20_reject"
                ]

                and 42
                <= t["rsi"]
                <= 52

                and t["adx"]
                >= 30

                and t[
                    "vol_ratio"
                ]
                >= 0.90

                and t[
                    "macd_bear"
                ]
            )
        ),

        (
            "V2-H STRICT BREAKDOWN + VOLUME",

            lambda t: (

                t[
                    "btc_strict"
                ]

                and t[
                    "own_strict"
                ]

                and t["break20"]

                and 35
                <= t["rsi"]
                <= 48

                and t["adx"]
                >= 30

                and t[
                    "vol_ratio"
                ]
                >= 1.25
            )
        )
    ]


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 84
    )

    print(
        "AI TRADE SCANNER - "
        "SHORT V2 INDEPENDENT DISCOVERY"
    )

    print(
        "=" * 84
    )

    print(
        "Version:",
        VERSION
    )

    print(
        "Historical source: OKX"
    )

    print(
        "LONG V3.0-E: UNTOUCHED"
    )

    print(
        "Candidate engine: "
        "NEW / independent "
        "from old SHORT score"
    )

    print(
        "Targets tested:",
        TARGETS
    )

    print(
        "Requested symbols:",
        len(bt.SYMBOLS)
    )

    data = {}

    usable = []

    # BTC first because it is
    # used as market regime.

    ordered_symbols = [

        "BTC/USDT"

    ] + [

        symbol

        for symbol
        in bt.SYMBOLS

        if symbol
        != "BTC/USDT"
    ]

    for (
        number,
        symbol

    ) in enumerate(

        ordered_symbols,

        start=1
    ):

        print()

        print(
            "#" * 84
        )

        print(

            f"[{number}/"
            f"{len(ordered_symbols)}] "
            f"LOADING {symbol}"
        )

        print(
            "#" * 84
        )

        try:

            df = bt.prepare(
                symbol
            )

            if (
                df is None
                or df.empty
            ):

                print(
                    "SKIPPED"
                )

                continue

            data[
                symbol
            ] = df

            usable.append(
                symbol
            )

        except Exception as error:

            print(
                "ERROR:",
                symbol,
                error
            )

    if (
        "BTC/USDT"
        not in data
    ):

        print(
            "BTC DATA MISSING - "
            "CANNOT RUN V2 "
            "MARKET REGIME TEST"
        )

        return

    if len(usable) < 5:

        print(
            "NOT ENOUGH "
            "USABLE SYMBOLS"
        )

        return

    btc_map = (
        build_btc_regime_map(
            data[
                "BTC/USDT"
            ]
        )
    )

    candidates = []

    for symbol in usable:

        found = (
            build_candidates(

                symbol,

                data[symbol],

                btc_map
            )
        )

        candidates.extend(
            found
        )

        print(

            symbol,

            "broad SHORT "
            "candidates:",

            len(found)
        )

    candidates.sort(

        key=lambda row:
            row["time"]
    )

    if not candidates:

        print(
            "NO V2 SHORT CANDIDATES"
        )

        return

    validation_end = min(

        data[symbol]
        .iloc[-1][
            "signal_time"
        ]

        for symbol
        in usable
    )

    validation_start = (

        validation_end

        - pd.Timedelta(
            days=bt.DAYS
        )
    )

    recent_start = (

        validation_end

        - pd.Timedelta(
            days=RECENT_DAYS
        )
    )

    last30_start = (

        validation_end

        - pd.Timedelta(
            days=LAST30_DAYS
        )
    )

    print()

    print(
        "Validation start:",
        validation_start
    )

    print(
        "Validation end:",
        validation_end
    )

    print(
        "Total V2 broad "
        "candidates:",
        len(candidates)
    )

    ranking = []

    for (
        name,
        condition

    ) in strategy_list():

        for target_r in TARGETS:

            full_name = (

                f"{name} | "
                f"TARGET "
                f"{target_r:g}R"
            )

            results = (
                run_strategy(

                    candidates,

                    data,

                    condition,

                    target_r
                )
            )

            full_results = (
                bt.slice_results(

                    results,

                    start=
                        validation_start,

                    end=
                        validation_end
                )
            )

            older_results = (
                bt.slice_results(

                    full_results,

                    end=
                        recent_start
                )
            )

            recent_results = (
                bt.slice_results(

                    full_results,

                    start=
                        recent_start
                )
            )

            last30_results = (
                bt.slice_results(

                    full_results,

                    start=
                        last30_start
                )
            )

            older = (
                bt.calc_metrics(
                    older_results
                )
            )

            recent = (
                bt.calc_metrics(
                    recent_results
                )
            )

            last30 = (
                bt.calc_metrics(
                    last30_results
                )
            )

            full = (
                bt.calc_metrics(
                    full_results
                )
            )

            older_ok = (
                metric_pass(
                    older,
                    "OLDER"
                )
            )

            recent_ok = (
                metric_pass(
                    recent,
                    "RECENT"
                )
            )

            full_ok = (
                metric_pass(
                    full,
                    "FULL"
                )
            )

            robustness = sum(
                (
                    older_ok,
                    recent_ok,
                    full_ok
                )
            )

            print()

            print(
                "=" * 84
            )

            print(
                full_name
            )

            print(
                "=" * 84
            )

            show(
                "OLDER275",
                older
            )

            show(
                "RECENT90",
                recent
            )

            show(
                "LAST30",
                last30
            )

            show(
                "FULL365",
                full
            )

            print(
                "ROBUSTNESS:",
                f"{robustness}/3"
            )

            if robustness == 3:

                verdict = (
                    "STRONG PASS"
                )

            elif robustness == 2:

                verdict = (
                    "WATCH"
                )

            else:

                verdict = (
                    "FAIL"
                )

            print(
                "VERDICT:",
                verdict
            )

            ranking.append({

                "name":
                    full_name,

                "robustness":
                    robustness,

                "older_ok":
                    older_ok,

                "recent_ok":
                    recent_ok,

                "full_ok":
                    full_ok,

                "older":
                    older,

                "recent":
                    recent,

                "last30":
                    last30,

                "full":
                    full
            })

    def safe_pf(m):

        if m is None:
            return -999

        return m["pf"]

    def safe_net(m):

        if m is None:
            return -999

        return m["net_r"]

    ranking.sort(

        key=lambda row: (

            row["older_ok"],

            row["robustness"],

            min(
                safe_pf(
                    row["older"]
                ),
                safe_pf(
                    row["recent"]
                ),
                safe_pf(
                    row["full"]
                )
            ),

            safe_net(
                row["full"]
            )
        ),

        reverse=True
    )

    print()

    print(
        "#" * 84
    )

    print(
        "FINAL SHORT V2 RANKING "
        "- OLDER HOLDOUT FIRST"
    )

    print(
        "#" * 84
    )

    for (
        position,
        row

    ) in enumerate(

        ranking[:8],

        start=1
    ):

        print()

        print(
            "RANK",
            position
        )

        print(
            row["name"]
        )

        print(
            "ROBUSTNESS:",
            f'{row["robustness"]}/3'
        )

        show(
            "OLDER275",
            row["older"]
        )

        show(
            "RECENT90",
            row["recent"]
        )

        show(
            "LAST30",
            row["last30"]
        )

        show(
            "FULL365",
            row["full"]
        )

    approved = [

        row

        for row
        in ranking

        if row["robustness"]
        == 3
    ]

    print()

    print(
        "#" * 84
    )

    print(
        "FINAL SHORT V2 DECISION"
    )

    print(
        "#" * 84
    )

    if approved:

        winner = (
            approved[0]
        )

        print(
            "SHORT V2 APPROVED:"
        )

        print(
            winner["name"]
        )

        print(
            "Passed OLDER275 + "
            "RECENT90 + FULL365 "
            "checks."
        )

        print(
            "NEXT STEP: add ONLY "
            "this SHORT engine "
            "next to LONG V3.0-E."
        )

    else:

        print(
            "NO SHORT V2 SETUP "
            "PASSED ALL "
            "ROBUSTNESS CHECKS."
        )

        print(
            "Do NOT add SHORT "
            "to main.py."
        )

        print(
            "LONG V3.0-E remains "
            "unchanged and active."
        )

    print()

    print(
        "=" * 84
    )

    print(
        "SHORT V2 BACKTEST "
        "COMPLETED"
    )

    print(
        "=" * 84
    )


if __name__ == "__main__":
    main()

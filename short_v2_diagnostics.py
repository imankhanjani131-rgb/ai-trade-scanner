from collections import Counter, defaultdict

import pandas as pd

import backtest as bt
import backtest_short_pro as v1
import backtest_short_pro_v2 as v2


# ============================================================
# SHORT PRO V2 DIAGNOSTICS
#
# Purpose:
# Find WHY the best V2 setup failed in RECENT90 / LOCKED30.
#
# Best V2 setup:
# P4 BIAS BREAKDOWN + VOLUME
# +
# R3 BTC EMA20 BELOW EMA50
# +
# TP = 2R
#
# IMPORTANT:
# This file changes NOTHING in main.py.
# It only produces a diagnostic report.
# ============================================================


TARGET_R = 2.0
RECENT_DAYS = 90
LOCKED_DAYS = 30
MAX_HOLD_HOURS = 72
COOLDOWN_BARS = 3


def selected_condition(t):

    return (
        v2.base_p4(t)
        and t["btc_ema20_4"] < t["btc_ema50_4"]
    )


def safe_float(value, default=0.0):

    try:

        if pd.isna(value):
            return default

        return float(value)

    except Exception:
        return default


def capture_features(
    trade,
    df
):

    x = df.iloc[
        trade["i"]
    ]

    entry = safe_float(
        trade["entry"]
    )

    risk = safe_float(
        trade["risk"]
    )

    ema20 = safe_float(
        x["ema20"]
    )

    ema50 = safe_float(
        x["ema50"]
    )

    risk_pct = 0.0

    if entry > 0:

        risk_pct = (
            risk
            / entry
            * 100.0
        )

    ema20_distance_pct = 0.0

    if ema20 > 0:

        ema20_distance_pct = (
            (
                entry
                / ema20
            )
            - 1.0
        ) * 100.0

    ema_gap_pct = 0.0

    if ema50 > 0:

        ema_gap_pct = (
            (
                ema20
                / ema50
            )
            - 1.0
        ) * 100.0

    btc_gap_pct = 0.0

    btc_ema50 = safe_float(
        trade.get(
            "btc_ema50_4"
        )
    )

    btc_ema20 = safe_float(
        trade.get(
            "btc_ema20_4"
        )
    )

    if btc_ema50 > 0:

        btc_gap_pct = (
            (
                btc_ema20
                / btc_ema50
            )
            - 1.0
        ) * 100.0

    signal_time = trade[
        "time"
    ]

    return {

        "rsi":
            safe_float(
                trade["rsi"]
            ),

        "adx":
            safe_float(
                trade["adx"]
            ),

        "vol_ratio":
            safe_float(
                trade["vol_ratio"]
            ),

        "btc_rsi4":
            safe_float(
                trade.get(
                    "btc_rsi4"
                )
            ),

        "btc_gap_pct":
            btc_gap_pct,

        "ema20_distance_pct":
            ema20_distance_pct,

        "ema_gap_pct":
            ema_gap_pct,

        "risk_pct":
            risk_pct,

        "hour_utc":
            int(
                signal_time.hour
            ),
    }


def run_diagnostic_trades(
    candidates,
    data
):

    results = []

    blocked_until = {}

    for trade in candidates:

        if not selected_condition(
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
            net_r,
            exit_i,
            reason
        ) = v1.simulate_short(

            data[
                symbol
            ],

            trade,

            TARGET_R
        )

        blocked_until[
            symbol
        ] = (
            exit_i
            + COOLDOWN_BARS
        )

        features = capture_features(

            trade,

            data[
                symbol
            ]
        )

        row = {

            "symbol":
                symbol,

            "time":
                trade[
                    "time"
                ],

            "r":
                float(
                    net_r
                ),

            "exit":
                reason,

            "entry":
                trade[
                    "entry"
                ],

            "sl":
                trade[
                    "sl"
                ],

            "target_r":
                TARGET_R,
        }

        row.update(
            features
        )

        results.append(
            row
        )

    return sorted(

        results,

        key=lambda x:
            x["time"]
    )


def slice_rows(
    rows,
    start=None,
    end=None
):

    output = rows

    if start is not None:

        output = [

            row

            for row
            in output

            if row[
                "time"
            ] >= start
        ]

    if end is not None:

        output = [

            row

            for row
            in output

            if row[
                "time"
            ] < end
        ]

    return output


def print_metrics(
    label,
    rows
):

    metrics = bt.calc_metrics(
        rows
    )

    if not metrics:

        print(
            f"{label} | NO TRADES"
        )

        return

    print(

        f"{label} | "

        f'Trades:{metrics["trades"]} | '

        f'WR:{metrics["win_rate"]:.2f}% | '

        f'PF:{bt.pf_text(metrics["pf"])} | '

        f'NetR:{metrics["net_r"]:.2f}R | '

        f'AvgR:{metrics["avg_r"]:.3f}R | '

        f'DD:{metrics["max_dd"]:.2f}%'
    )


def average_feature(
    rows,
    key
):

    values = [

        safe_float(
            row.get(
                key
            )
        )

        for row
        in rows
    ]

    if not values:
        return 0.0

    return (
        sum(values)
        / len(values)
    )


def winner_loser_comparison(
    rows
):

    winners = [

        row

        for row
        in rows

        if row[
            "r"
        ] > 0
    ]

    losers = [

        row

        for row
        in rows

        if row[
            "r"
        ] <= 0
    ]

    features = [

        "rsi",
        "adx",
        "vol_ratio",
        "btc_rsi4",
        "btc_gap_pct",
        "ema20_distance_pct",
        "ema_gap_pct",
        "risk_pct",
    ]

    print()

    print(
        "WINNER vs LOSER FEATURE AVERAGES"
    )

    print(
        "-" * 88
    )

    print(
        "Winners:",
        len(
            winners
        )
    )

    print(
        "Losers:",
        len(
            losers
        )
    )

    for key in features:

        win_avg = average_feature(
            winners,
            key
        )

        loss_avg = average_feature(
            losers,
            key
        )

        print(

            f"{key:22s} | "

            f"WIN:{win_avg:8.3f} | "

            f"LOSS:{loss_avg:8.3f}"
        )


def print_symbol_stats(
    rows
):

    grouped = defaultdict(
        list
    )

    for row in rows:

        grouped[
            row["symbol"]
        ].append(
            row
        )

    ranking = []

    for symbol, trades in grouped.items():

        metrics = bt.calc_metrics(
            trades
        )

        if not metrics:
            continue

        ranking.append(

            (
                metrics[
                    "net_r"
                ],
                symbol,
                metrics
            )
        )

    ranking.sort(
        reverse=True
    )

    print()

    print(
        "RESULTS BY SYMBOL"
    )

    print(
        "-" * 88
    )

    for (
        net_r,
        symbol,
        metrics
    ) in ranking:

        print(

            f"{symbol:14s} | "

            f'Trades:{metrics["trades"]:3d} | '

            f'WR:{metrics["win_rate"]:6.2f}% | '

            f'PF:{bt.pf_text(metrics["pf"]):>5s} | '

            f'NetR:{metrics["net_r"]:+7.2f}R'
        )


def bucket_report(
    rows,
    title,
    key,
    buckets
):

    print()

    print(
        title
    )

    print(
        "-" * 88
    )

    for (
        name,
        low,
        high
    ) in buckets:

        subset = []

        for row in rows:

            value = safe_float(
                row.get(
                    key
                )
            )

            lower_ok = (

                low is None
                or value >= low
            )

            upper_ok = (

                high is None
                or value < high
            )

            if (
                lower_ok
                and upper_ok
            ):

                subset.append(
                    row
                )

        if not subset:

            print(
                f"{name:18s} | NO TRADES"
            )

            continue

        metrics = bt.calc_metrics(
            subset
        )

        print(

            f"{name:18s} | "

            f'Trades:{metrics["trades"]:3d} | '

            f'WR:{metrics["win_rate"]:6.2f}% | '

            f'PF:{bt.pf_text(metrics["pf"]):>5s} | '

            f'NetR:{metrics["net_r"]:+7.2f}R | '

            f'AvgR:{metrics["avg_r"]:+.3f}R'
        )


def hour_report(
    rows
):

    buckets = [

        (
            "UTC 00-05",
            0,
            6
        ),

        (
            "UTC 06-11",
            6,
            12
        ),

        (
            "UTC 12-17",
            12,
            18
        ),

        (
            "UTC 18-23",
            18,
            24
        ),
    ]

    bucket_report(

        rows,

        "TIME OF ENTRY",

        "hour_utc",

        buckets
    )


def exit_report(
    rows
):

    counts = Counter(

        row[
            "exit"
        ]

        for row
        in rows
    )

    print()

    print(
        "EXIT REASONS"
    )

    print(
        "-" * 88
    )

    for (
        reason,
        count
    ) in counts.most_common():

        subset = [

            row

            for row
            in rows

            if row[
                "exit"
            ] == reason
        ]

        total_r = sum(

            row[
                "r"
            ]

            for row
            in subset
        )

        print(

            f"{reason:18s} | "

            f"Trades:{count:3d} | "

            f"NetR:{total_r:+7.2f}R"
        )


def full_diagnostics(
    label,
    rows
):

    print()

    print(
        "=" * 88
    )

    print(
        label
    )

    print(
        "=" * 88
    )

    print_metrics(
        label,
        rows
    )

    if not rows:
        return

    winner_loser_comparison(
        rows
    )

    print_symbol_stats(
        rows
    )

    bucket_report(

        rows,

        "RSI BUCKETS",

        "rsi",

        [

            (
                "RSI 30-35",
                30,
                35
            ),

            (
                "RSI 35-40",
                35,
                40
            ),

            (
                "RSI 40-45",
                40,
                45
            ),

            (
                "RSI 45-50",
                45,
                50
            ),

            (
                "RSI 50-56",
                50,
                56
            ),
        ]
    )

    bucket_report(

        rows,

        "ADX BUCKETS",

        "adx",

        [

            (
                "ADX 30-35",
                30,
                35
            ),

            (
                "ADX 35-40",
                35,
                40
            ),

            (
                "ADX 40-50",
                40,
                50
            ),

            (
                "ADX 50+",
                50,
                None
            ),
        ]
    )

    bucket_report(

        rows,

        "VOLUME RATIO BUCKETS",

        "vol_ratio",

        [

            (
                "VOL 1.00-1.20",
                1.00,
                1.20
            ),

            (
                "VOL 1.20-1.50",
                1.20,
                1.50
            ),

            (
                "VOL 1.50-2.00",
                1.50,
                2.00
            ),

            (
                "VOL 2.00+",
                2.00,
                None
            ),
        ]
    )

    bucket_report(

        rows,

        "BTC 4H RSI BUCKETS",

        "btc_rsi4",

        [

            (
                "BTC RSI <35",
                None,
                35
            ),

            (
                "BTC RSI 35-40",
                35,
                40
            ),

            (
                "BTC RSI 40-45",
                40,
                45
            ),

            (
                "BTC RSI 45-50",
                45,
                50
            ),

            (
                "BTC RSI 50+",
                50,
                None
            ),
        ]
    )

    bucket_report(

        rows,

        "BTC EMA20/EMA50 GAP",

        "btc_gap_pct",

        [

            (
                "Gap <= -2%",
                None,
                -2.0
            ),

            (
                "Gap -2 to -1%",
                -2.0,
                -1.0
            ),

            (
                "Gap -1 to -0.5%",
                -1.0,
                -0.5
            ),

            (
                "Gap -0.5 to 0%",
                -0.5,
                0.0
            ),
        ]
    )

    bucket_report(

        rows,

        "STOP / RISK DISTANCE",

        "risk_pct",

        [

            (
                "Risk <3%",
                None,
                3.0
            ),

            (
                "Risk 3-5%",
                3.0,
                5.0
            ),

            (
                "Risk 5-7%",
                5.0,
                7.0
            ),

            (
                "Risk 7%+",
                7.0,
                None
            ),
        ]
    )

    hour_report(
        rows
    )

    exit_report(
        rows
    )


def main():

    print(
        "=" * 88
    )

    print(
        "SHORT PRO V2 DIAGNOSTICS"
    )

    print(
        "Strategy: P4 + BTC EMA20<EMA50 + TP2R"
    )

    print(
        "=" * 88
    )

    data = {}

    candidates = []

    usable_symbols = []

    for number, symbol in enumerate(
        bt.SYMBOLS,
        start=1
    ):

        print(
            f"[{number}/{len(bt.SYMBOLS)}] "
            f"Loading {symbol}"
        )

        try:

            df = bt.prepare(
                symbol
            )

            if (
                df is None
                or df.empty
            ):

                continue

            data[
                symbol
            ] = df

            usable_symbols.append(
                symbol
            )

            candidates.extend(

                v1.find_pro_candidates(
                    symbol,
                    df
                )
            )

        except Exception as error:

            print(
                "ERROR:",
                symbol,
                error
            )

    if "BTC/USDT" not in data:

        print(
            "BTC/USDT missing."
        )

        return

    candidates.sort(
        key=lambda x:
            x["time"]
    )

    candidates = (
        v2.attach_btc_context(

            candidates,

            data[
                "BTC/USDT"
            ]
        )
    )

    candidates = [

        row

        for row
        in candidates

        if not pd.isna(
            row.get(
                "btc_ema20_4"
            )
        )
    ]

    trades = run_diagnostic_trades(

        candidates,

        data
    )

    validation_end = min(

        data[
            symbol
        ].iloc[-1][
            "signal_time"
        ]

        for symbol
        in usable_symbols
    )

    recent90_start = (

        validation_end

        - pd.Timedelta(
            days=RECENT_DAYS
        )
    )

    locked30_start = (

        validation_end

        - pd.Timedelta(
            days=LOCKED_DAYS
        )
    )

    recent90 = slice_rows(

        trades,

        start=
            recent90_start
    )

    locked30 = slice_rows(

        trades,

        start=
            locked30_start
    )

    older = slice_rows(

        trades,

        end=
            recent90_start
    )

    print()

    print(
        "Validation end:",
        validation_end
    )

    print(
        "Total diagnostic trades:",
        len(
            trades
        )
    )

    print_metrics(
        "OLDER275",
        older
    )

    print_metrics(
        "RECENT90",
        recent90
    )

    print_metrics(
        "LOCKED30",
        locked30
    )

    # Most important:
    # Deep dive into the failed periods.

    full_diagnostics(

        "RECENT90 DIAGNOSTICS",

        recent90
    )

    full_diagnostics(

        "LOCKED30 DIAGNOSTICS",

        locked30
    )

    print()

    print(
        "=" * 88
    )

    print(
        "DIAGNOSTIC COMPLETE"
    )

    print(
        "DO NOT CHANGE SHORT RULES "
        "UNTIL THIS REPORT IS REVIEWED."
    )

    print(
        "=" * 88
    )


if __name__ == "__main__":
    main()

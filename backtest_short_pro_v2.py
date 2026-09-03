import math
import pandas as pd

import backtest as bt
import backtest_short_pro as v1


# ============================================================
# AI TRADE SCANNER - SHORT PRO V2
#
# Base strategy:
# P4 BIAS BREAKDOWN + VOLUME
#
# New:
# - BTC market-regime filter
# - 60-day validation
# - final 30-day locked holdout
# - full-year robustness check
#
# IMPORTANT:
# LONG main.py is untouched.
# SHORT V1 is untouched.
# ============================================================


VERSION = "SHORT-PRO-V2-REGIME"

TARGET_R = 2.0

RECENT90_DAYS = 90
LOCKED30_DAYS = 30

MIN_FULL_TRADES = 60
MAX_FULL_DD = 30.0


# ============================================================
# BASE P4 STRATEGY
# ============================================================


def base_p4(t):

    return (

        t["bias4"]

        and t["breakdown"]

        and t["ema_bear"]

        and t["macd_bear"]

        and t["adx"] >= 30

        and 30 <= t["rsi"] <= 55

        and t["vol_ratio"] >= 1.00
    )


# ============================================================
# ATTACH BTC 4H MARKET CONTEXT
# ============================================================


def attach_btc_context(
    candidates,
    btc_df
):

    if not candidates:
        return []

    cand_df = pd.DataFrame(
        candidates
    ).copy()

    cand_df["_order"] = range(
        len(cand_df)
    )

    btc = btc_df[
        [
            "signal_time",
            "close4",
            "ema20_4",
            "ema50_4",
            "ema200_4",
            "rsi_4",
        ]
    ].copy()

    btc = btc.rename(
        columns={
            "signal_time":
                "btc_time",

            "close4":
                "btc_close4",

            "ema20_4":
                "btc_ema20_4",

            "ema50_4":
                "btc_ema50_4",

            "ema200_4":
                "btc_ema200_4",

            "rsi_4":
                "btc_rsi4",
        }
    )

    cand_df = cand_df.sort_values(
        "time"
    )

    btc = btc.sort_values(
        "btc_time"
    )

    merged = pd.merge_asof(

        cand_df,

        btc,

        left_on="time",

        right_on="btc_time",

        direction="backward"
    )

    merged = merged.sort_values(
        "_order"
    )

    output = []

    for row in merged.to_dict(
        orient="records"
    ):

        row.pop(
            "_order",
            None
        )

        output.append(
            row
        )

    return output


# ============================================================
# BTC REGIME FILTERS
#
# We intentionally test only a small number
# of economically meaningful regimes.
# No huge brute-force parameter search.
# ============================================================


def regimes():

    return [

        {
            "name":
                "R0 NO BTC FILTER",

            "condition":
                lambda t: True,
        },

        # BTC below its fast 4H EMA.

        {
            "name":
                "R1 BTC BELOW EMA20",

            "condition":
                lambda t: (

                    t["btc_close4"]
                    < t["btc_ema20_4"]
                ),
        },

        # BTC below medium 4H trend.

        {
            "name":
                "R2 BTC BELOW EMA50",

            "condition":
                lambda t: (

                    t["btc_close4"]
                    < t["btc_ema50_4"]
                ),
        },

        # BTC's 4H trend structure is bearish.

        {
            "name":
                "R3 BTC EMA20 BELOW EMA50",

            "condition":
                lambda t: (

                    t["btc_ema20_4"]
                    < t["btc_ema50_4"]
                ),
        },

        # Stronger bearish BTC filter.

        {
            "name":
                "R4 BTC BEAR + RSI",

            "condition":
                lambda t: (

                    t["btc_close4"]
                    < t["btc_ema50_4"]

                    and t["btc_rsi4"]
                    <= 52
                ),
        },

        # Instead of requiring BTC bearish,
        # only block very strong bullish BTC regimes.
        # This should preserve more SHORT signals.

        {
            "name":
                "R5 BLOCK STRONG BTC BULL",

            "condition":
                lambda t: not (

                    t["btc_close4"]
                    > t["btc_ema20_4"]

                    and t["btc_ema20_4"]
                    > t["btc_ema50_4"]

                    and t["btc_rsi4"]
                    >= 55
                ),
        },

        # Balanced filter:
        # permit SHORT when BTC is under EMA20
        # OR BTC momentum is not strongly bullish.

        {
            "name":
                "R6 BALANCED BTC REGIME",

            "condition":
                lambda t: (

                    t["btc_close4"]
                    < t["btc_ema20_4"]

                    or t["btc_rsi4"]
                    < 50
                ),
        },
    ]


# ============================================================
# HELPERS
# ============================================================


def safe_pf(m):

    if not m:
        return 0.0

    pf = m["pf"]

    if math.isinf(pf):
        return 99.0

    return float(pf)


def print_metrics(
    label,
    m
):

    if not m:

        print(
            f"{label} | NO TRADES"
        )

        return

    print(
        f"{label} | "
        f'Trades:{m["trades"]} | '
        f'WR:{m["win_rate"]:.2f}% | '
        f'PF:{bt.pf_text(m["pf"])} | '
        f'NetR:{m["net_r"]:.2f}R | '
        f'AvgR:{m["avg_r"]:.3f}R | '
        f'DD:{m["max_dd"]:.2f}%'
    )


def period_pass(
    m,
    min_trades,
    min_pf
):

    return bool(

        m

        and m["trades"]
        >= min_trades

        and m["net_r"] > 0

        and safe_pf(m)
        >= min_pf
    )


# ============================================================
# MAIN
# ============================================================


def main():

    print(
        "=" * 92
    )

    print(
        "AI TRADE SCANNER - "
        "SHORT PRO V2 REGIME DISCOVERY"
    )

    print(
        "=" * 92
    )

    print(
        "Version:",
        VERSION
    )

    print(
        "Base:",
        "P4 BIAS BREAKDOWN + VOLUME"
    )

    print(
        "Target:",
        "2R"
    )

    print(
        "LONG V3.0-E: UNTOUCHED"
    )

    print(
        "SHORT V1: UNTOUCHED"
    )

    print(
        "Final 30 days:",
        "LOCKED HOLDOUT"
    )

    # ========================================================
    # LOAD HISTORICAL DATA
    # ========================================================

    data = {}

    candidates = []

    usable_symbols = []

    for number, symbol in enumerate(
        bt.SYMBOLS,
        start=1
    ):

        print()

        print(
            "#" * 92
        )

        print(
            f"[{number}/{len(bt.SYMBOLS)}] "
            f"LOADING {symbol}"
        )

        print(
            "#" * 92
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

            usable_symbols.append(
                symbol
            )

            found = (
                v1.find_pro_candidates(
                    symbol,
                    df
                )
            )

            candidates.extend(
                found
            )

            print(
                "Raw triggers:",
                len(found)
            )

        except Exception as error:

            print(
                "ERROR:",
                symbol,
                error
            )

    if not candidates:

        print(
            "NO CANDIDATES."
        )

        return

    if "BTC/USDT" not in data:

        print(
            "BTC/USDT DATA MISSING."
        )

        return

    candidates.sort(
        key=lambda x:
            x["time"]
    )

    # Attach BTC information
    # available at each historical signal.

    candidates = attach_btc_context(

        candidates,

        data[
            "BTC/USDT"
        ]
    )

    # Remove rows without valid BTC context.

    candidates = [

        t

        for t in candidates

        if not pd.isna(
            t.get(
                "btc_close4"
            )
        )
    ]

    print()

    print(
        "=" * 92
    )

    print(
        "DATA BUILD COMPLETE"
    )

    print(
        "=" * 92
    )

    print(
        "Usable symbols:",
        len(
            usable_symbols
        )
    )

    print(
        "Candidates with BTC context:",
        len(
            candidates
        )
    )

    # ========================================================
    # DATE SPLITS
    # ========================================================

    validation_end = min(

        data[symbol]
        .iloc[-1][
            "signal_time"
        ]

        for symbol
        in usable_symbols
    )

    validation_start = (

        validation_end

        - pd.Timedelta(
            days=bt.DAYS
        )
    )

    recent90_start = (

        validation_end

        - pd.Timedelta(
            days=RECENT90_DAYS
        )
    )

    locked30_start = (

        validation_end

        - pd.Timedelta(
            days=LOCKED30_DAYS
        )
    )

    # The 60 days immediately before
    # the locked final 30 days.

    validation60_start = (
        recent90_start
    )

    validation60_end = (
        locked30_start
    )

    print(
        "Start:",
        validation_start
    )

    print(
        "End:",
        validation_end
    )

    print(
        "Validation60:",
        validation60_start,
        "->",
        validation60_end
    )

    print(
        "LOCKED30:",
        locked30_start,
        "->",
        validation_end
    )

    # ========================================================
    # TEST REGIMES
    # ========================================================

    ranking = []

    for regime in regimes():

        print()

        print(
            "#" * 92
        )

        print(
            regime["name"]
        )

        print(
            "#" * 92
        )

        def condition(t):

            return (

                base_p4(t)

                and regime[
                    "condition"
                ](t)
            )

        results = v1.run_setup(

            candidates,

            data,

            condition,

            TARGET_R
        )

        full = v1.slice_results(

            results,

            start=
                validation_start,

            end=
                validation_end
                + pd.Timedelta(
                    seconds=1
                )
        )

        older275 = v1.slice_results(

            full,

            end=
                recent90_start
        )

        validation60 = v1.slice_results(

            full,

            start=
                validation60_start,

            end=
                validation60_end
        )

        locked30 = v1.slice_results(

            full,

            start=
                locked30_start
        )

        recent90 = v1.slice_results(

            full,

            start=
                recent90_start
        )

        full_m = bt.calc_metrics(
            full
        )

        older_m = bt.calc_metrics(
            older275
        )

        val60_m = bt.calc_metrics(
            validation60
        )

        locked30_m = bt.calc_metrics(
            locked30
        )

        recent90_m = bt.calc_metrics(
            recent90
        )

        div = v1.diversification(
            full
        )

        # ----------------------------------------------------
        # ROBUSTNESS CHECKS
        # ----------------------------------------------------

        full_pass = bool(

            full_m

            and full_m[
                "trades"
            ]
            >= MIN_FULL_TRADES

            and full_m[
                "net_r"
            ]
            > 0

            and safe_pf(
                full_m
            )
            >= 1.15

            and full_m[
                "avg_r"
            ]
            > 0.03

            and full_m[
                "max_dd"
            ]
            <= MAX_FULL_DD
        )

        older_pass = (
            period_pass(
                older_m,
                35,
                1.05
            )
        )

        validation60_pass = (
            period_pass(
                val60_m,
                6,
                1.00
            )
        )

        # Locked final 30 days:
        # deliberately kept separate.

        locked30_pass = (
            period_pass(
                locked30_m,
                3,
                1.00
            )
        )

        recent90_pass = (
            period_pass(
                recent90_m,
                10,
                1.00
            )
        )

        diversification_pass = bool(

            div[
                "symbols_used"
            ]
            >= 8

            and div[
                "top_share"
            ]
            <= 0.30

            and div[
                "positive_symbols"
            ]
            >= 5
        )

        checks = {

            "FULL":
                full_pass,

            "OLDER275":
                older_pass,

            "VALIDATION60":
                validation60_pass,

            "LOCKED30":
                locked30_pass,

            "RECENT90":
                recent90_pass,

            "DIVERSIFICATION":
                diversification_pass,
        }

        robustness = sum(
            checks.values()
        )

        approved = all(
            checks.values()
        )

        print_metrics(
            "OLDER275",
            older_m
        )

        print_metrics(
            "VALIDATION60",
            val60_m
        )

        print_metrics(
            "LOCKED30",
            locked30_m
        )

        print_metrics(
            "RECENT90",
            recent90_m
        )

        print_metrics(
            "FULL365",
            full_m
        )

        print()

        print(
            "Diversification | "
            f'Symbols:{div["symbols_used"]} | '
            f'TopShare:{div["top_share"] * 100:.1f}% | '
            f'PositiveSymbols:{div["positive_symbols"]}'
        )

        print(
            "Checks:",
            checks
        )

        print(
            "ROBUSTNESS:",
            f"{robustness}/6"
        )

        print(
            "APPROVED:",
            approved
        )

        freq = v1.frequency(
            full_m
        )

        print(
            "Frequency | "
            f'Year:{freq["year"]} | '
            f'Month:{freq["month"]:.1f} | '
            f'Week:{freq["week"]:.2f}'
        )

        ranking.append({

            "name":
                regime["name"],

            "approved":
                approved,

            "robustness":
                robustness,

            "full":
                full_m,

            "older":
                older_m,

            "val60":
                val60_m,

            "locked30":
                locked30_m,

            "recent90":
                recent90_m,

            "div":
                div,

            "checks":
                checks,

            "freq":
                freq,
        })

    # ========================================================
    # RANKING
    # ========================================================

    def rank_key(row):

        m = row[
            "full"
        ]

        if not m:

            return (
                False,
                0,
                -999,
                -999,
                -999,
            )

        return (

            row[
                "approved"
            ],

            row[
                "robustness"
            ],

            safe_pf(
                m
            ),

            m[
                "avg_r"
            ],

            -m[
                "max_dd"
            ],
        )

    ranking.sort(
        key=rank_key,
        reverse=True
    )

    print()

    print(
        "=" * 92
    )

    print(
        "FINAL SHORT PRO V2 RANKING"
    )

    print(
        "=" * 92
    )

    for number, row in enumerate(
        ranking,
        start=1
    ):

        print()

        print(
            f"RANK {number}"
        )

        print(
            row[
                "name"
            ]
        )

        print(
            "APPROVED:",
            row[
                "approved"
            ]
        )

        print(
            "ROBUSTNESS:",
            f'{row["robustness"]}/6'
        )

        print_metrics(
            "FULL365",
            row[
                "full"
            ]
        )

        print_metrics(
            "OLDER275",
            row[
                "older"
            ]
        )

        print_metrics(
            "VALIDATION60",
            row[
                "val60"
            ]
        )

        print_metrics(
            "LOCKED30",
            row[
                "locked30"
            ]
        )

        print_metrics(
            "RECENT90",
            row[
                "recent90"
            ]
        )

        print(
            "Checks:",
            row[
                "checks"
            ]
        )

        print(
            "Frequency | "
            f'Year:{row["freq"]["year"]} | '
            f'Month:{row["freq"]["month"]:.1f} | '
            f'Week:{row["freq"]["week"]:.2f}'
        )

    # ========================================================
    # FINAL DECISION
    # ========================================================

    approved_rows = [

        row

        for row
        in ranking

        if row[
            "approved"
        ]
    ]

    print()

    print(
        "=" * 92
    )

    print(
        "FINAL SHORT PRO V2 DECISION"
    )

    print(
        "=" * 92
    )

    if approved_rows:

        winner = approved_rows[
            0
        ]

        print(
            "SHORT PRO V2 APPROVED"
        )

        print(
            "WINNER:",
            winner[
                "name"
            ]
        )

        print_metrics(
            "FULL365",
            winner[
                "full"
            ]
        )

        print_metrics(
            "RECENT90",
            winner[
                "recent90"
            ]
        )

        print_metrics(
            "LOCKED30",
            winner[
                "locked30"
            ]
        )

        print()

        print(
            "Frequency:"
        )

        print(
            "Year:",
            winner[
                "freq"
            ][
                "year"
            ]
        )

        print(
            "Month:",
            f'{winner["freq"]["month"]:.1f}'
        )

        print(
            "Week:",
            f'{winner["freq"]["week"]:.2f}'
        )

        print()

        print(
            "NEXT STEP:"
        )

        print(
            "Build SHORT forward-test "
            "scanner from this exact regime."
        )

        print(
            "Do NOT auto-trade yet."
        )

    else:

        best = ranking[
            0
        ]

        print(
            "NO V2 REGIME PASSED "
            "ALL PROFESSIONAL CHECKS."
        )

        print()

        print(
            "BEST V2 RESEARCH CANDIDATE:"
        )

        print(
            best[
                "name"
            ]
        )

        print(
            "ROBUSTNESS:",
            f'{best["robustness"]}/6'
        )

        print_metrics(
            "FULL365",
            best[
                "full"
            ]
        )

        print_metrics(
            "RECENT90",
            best[
                "recent90"
            ]
        )

        print_metrics(
            "LOCKED30",
            best[
                "locked30"
            ]
        )

        print()

        print(
            "DO NOT MERGE SHORT "
            "INTO main.py."
        )

    print()

    print(
        "=" * 92
    )

    print(
        "SHORT PRO V2 BACKTEST COMPLETED"
    )

    print(
        "=" * 92
    )


if __name__ == "__main__":
    main()

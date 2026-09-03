import pandas as pd
import backtest as bt


# ============================================================
# AI TRADE SCANNER - SHORT FILTER DISCOVERY
#
# Uses the already-tested OKX historical engine
# from backtest.py
#
# IMPORTANT:
# - LONG robot main.py is NOT changed
# - This file only tests SHORT strategies
# - Target = TP2
# - Costs/slippage are inherited from backtest.py
# ============================================================


VERSION = "SHORT-DISCOVERY-V1"

DAYS = bt.DAYS
TEST_DAYS = bt.TEST_DAYS


# ============================================================
# METRIC HELPERS
# ============================================================

def metrics_ok(metrics, period):

    if metrics is None:
        return False

    if period == "OLDER":

        return (
            metrics["trades"] >= 20
            and metrics["pf"] > 1.00
            and metrics["net_r"] > 0
        )

    if period == "RECENT":

        return (
            metrics["trades"] >= 8
            and metrics["pf"] > 1.00
            and metrics["net_r"] > 0
        )

    if period == "FULL":

        return (
            metrics["trades"] >= 30
            and metrics["pf"] > 1.05
            and metrics["net_r"] > 0
            and metrics["max_dd"] < 35
        )

    return False


def print_summary(
    label,
    metrics
):

    if metrics is None:

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


# ============================================================
# SHORT FILTERS
# ============================================================

def build_variants():

    return [

        (
            "S1 - ALL BASE SHORTS",

            lambda t:
                t["side"] == "SHORT"
        ),

        (
            "S2 - SHORT + ADX >= 30",

            lambda t:
                t["side"] == "SHORT"
                and t["adx"] >= 30
        ),

        (
            "S3 - SHORT + ADX >= 40",

            lambda t:
                t["side"] == "SHORT"
                and t["adx"] >= 40
        ),

        (
            "S4 - SHORT + RSI 30-45",

            lambda t:
                t["side"] == "SHORT"
                and 30 < t["rsi"] <= 45
        ),

        (
            "S5 - SHORT + ADX >= 30 + RSI 30-45",

            lambda t:
                t["side"] == "SHORT"
                and t["adx"] >= 30
                and 30 < t["rsi"] <= 45
        ),

        (
            "S6 - SHORT + ADX >= 40 + RSI 30-45",

            lambda t:
                t["side"] == "SHORT"
                and t["adx"] >= 40
                and 30 < t["rsi"] <= 45
        ),

        (
            "S7 - SHORT + ADX >= 40 + RSI 30-45 + SCORE 9",

            lambda t:
                t["side"] == "SHORT"
                and t["adx"] >= 40
                and 30 < t["rsi"] <= 45
                and t["score"] == 9
        ),

        (
            "S8 - SHORT + ADX >= 40 + RSI 30-45 + SCORE >=10",

            lambda t:
                t["side"] == "SHORT"
                and t["adx"] >= 40
                and 30 < t["rsi"] <= 45
                and t["score"] >= 10
        ),

        (
            "S9 - SHORT + ADX >= 35 + RSI 35-50",

            lambda t:
                t["side"] == "SHORT"
                and t["adx"] >= 35
                and 35 <= t["rsi"] <= 50
        ),

        (
            "S10 - SHORT + ADX >= 40 + RSI 35-50 + SCORE 9",

            lambda t:
                t["side"] == "SHORT"
                and t["adx"] >= 40
                and 35 <= t["rsi"] <= 50
                and t["score"] == 9
        ),
    ]


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)

    print(
        "AI TRADE SCANNER - "
        "SHORT FILTER DISCOVERY"
    )

    print("=" * 80)

    print(
        "Version:",
        VERSION
    )

    print(
        "Historical source: OKX"
    )

    print(
        "LONG robot: UNTOUCHED"
    )

    print(
        "Direction tested: SHORT ONLY"
    )

    print(
        "Validation:",
        DAYS,
        "days"
    )

    print(
        "Older holdout:",
        DAYS - TEST_DAYS,
        "days"
    )

    print(
        "Recent test:",
        TEST_DAYS,
        "days"
    )

    print(
        "Target: TP2"
    )

    print(
        "Symbols:",
        len(bt.SYMBOLS)
    )

    print()


    # ========================================================
    # LOAD DATA
    # ========================================================

    data = {}

    candidates = []

    usable_symbols = []

    for number, symbol in enumerate(
        bt.SYMBOLS,
        start=1
    ):

        print()
        print("#" * 80)

        print(
            f"[{number}/{len(bt.SYMBOLS)}] "
            f"LOADING {symbol}"
        )

        print("#" * 80)

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

            found = bt.find_candidates(
                symbol,
                df
            )

            shorts = [
                trade
                for trade
                in found
                if trade["side"]
                == "SHORT"
            ]

            candidates.extend(
                shorts
            )

            print(
                "SHORT candidates:",
                len(shorts)
            )

        except Exception as error:

            print(
                "ERROR:",
                symbol,
                error
            )


    candidates.sort(
        key=lambda x:
            x["time"]
    )


    print()
    print("=" * 80)

    print(
        "DATA DOWNLOAD FINISHED"
    )

    print("=" * 80)

    print(
        "Usable symbols:",
        len(usable_symbols)
    )

    print(
        "Total SHORT candidates:",
        len(candidates)
    )


    if not candidates:

        print(
            "NO SHORT CANDIDATES."
        )

        print(
            "SHORT STRATEGY NOT APPROVED."
        )

        return


    # ========================================================
    # COMMON DATES
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
            days=DAYS
        )
    )


    recent_start = (

        validation_end

        - pd.Timedelta(
            days=TEST_DAYS
        )
    )


    last30_start = (

        validation_end

        - pd.Timedelta(
            days=30
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


    # ========================================================
    # TEST VARIANTS
    # ========================================================

    ranking = []

    variants = build_variants()


    for (
        name,
        condition
    ) in variants:


        results = bt.run_variant(
            candidates,
            data,
            condition
        )


        full_results = bt.slice_results(
            results,
            start=validation_start,
            end=validation_end
        )


        older_results = bt.slice_results(
            full_results,
            end=recent_start
        )


        recent_results = bt.slice_results(
            full_results,
            start=recent_start
        )


        last30_results = bt.slice_results(
            full_results,
            start=last30_start
        )


        full_m = bt.calc_metrics(
            full_results
        )

        older_m = bt.calc_metrics(
            older_results
        )

        recent_m = bt.calc_metrics(
            recent_results
        )

        last30_m = bt.calc_metrics(
            last30_results
        )


        print()
        print("#" * 80)

        print(
            name
        )

        print("#" * 80)


        print_summary(
            "OLDER",
            older_m
        )

        print_summary(
            "RECENT90",
            recent_m
        )

        print_summary(
            "LAST30",
            last30_m
        )

        print_summary(
            "FULL365",
            full_m
        )


        older_pass = metrics_ok(
            older_m,
            "OLDER"
        )

        recent_pass = metrics_ok(
            recent_m,
            "RECENT"
        )

        full_pass = metrics_ok(
            full_m,
            "FULL"
        )


        robustness_score = sum([
            older_pass,
            recent_pass,
            full_pass
        ])


        print()

        print(
            "ROBUSTNESS:",
            f"{robustness_score}/3"
        )


        if (
            older_pass
            and recent_pass
            and full_pass
        ):

            verdict = (
                "STRONG PASS"
            )

        elif robustness_score >= 2:

            verdict = (
                "WATCH / POSSIBLE"
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
                name,

            "robustness":
                robustness_score,

            "verdict":
                verdict,

            "older":
                older_m,

            "recent":
                recent_m,

            "last30":
                last30_m,

            "full":
                full_m,
        })


    # ========================================================
    # FINAL RANKING
    # ========================================================

    def ranking_key(
        row
    ):

        older = row[
            "older"
        ]

        recent = row[
            "recent"
        ]

        full = row[
            "full"
        ]


        older_net = (
            older["net_r"]
            if older
            else -999
        )


        recent_net = (
            recent["net_r"]
            if recent
            else -999
        )


        full_net = (
            full["net_r"]
            if full
            else -999
        )


        return (

            row[
                "robustness"
            ],

            older_net,

            recent_net,

            full_net
        )


    ranking.sort(
        key=ranking_key,
        reverse=True
    )


    print()
    print("=" * 80)

    print(
        "FINAL SHORT RANKING"
    )

    print(
        "OLDER HOLDOUT HAS PRIORITY"
    )

    print("=" * 80)


    for position, row in enumerate(
        ranking,
        start=1
    ):


        print()
        print(
            f"RANK {position}"
        )

        print(
            row["name"]
        )

        print(
            "VERDICT:",
            row["verdict"]
        )

        print(
            "ROBUSTNESS:",
            f'{row["robustness"]}/3'
        )


        print_summary(
            "OLDER",
            row["older"]
        )

        print_summary(
            "RECENT90",
            row["recent"]
        )

        print_summary(
            "LAST30",
            row["last30"]
        )

        print_summary(
            "FULL365",
            row["full"]
        )


    # ========================================================
    # DECISION
    # ========================================================

    strong = [

        row

        for row
        in ranking

        if row["verdict"]
        == "STRONG PASS"
    ]


    print()
    print("=" * 80)

    print(
        "FINAL SHORT DECISION"
    )

    print("=" * 80)


    if strong:

        winner = strong[0]

        print(
            "SHORT FILTER APPROVED:"
        )

        print(
            winner["name"]
        )

        print()

        print(
            "This filter was positive "
            "in older, recent and "
            "full validation."
        )

        print()

        print(
            "NEXT STEP:"
        )

        print(
            "Add this SHORT engine "
            "next to the existing "
            "LONG V3.0-E engine."
        )

    else:

        print(
            "NO SHORT FILTER PASSED "
            "ALL ROBUSTNESS CHECKS."
        )

        print()

        print(
            "Do NOT add SHORT to "
            "main.py yet."
        )

        print()

        print(
            "LONG V3.0-E remains "
            "unchanged and active."
        )


    print()
    print("=" * 80)

    print(
        "SHORT BACKTEST COMPLETED"
    )

    print("=" * 80)


if __name__ == "__main__":
    main()

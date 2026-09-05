import math
import pandas as pd

import backtest_v42_super_pump as core


# ============================================================
# P1 CORE MAJORS - LONG HISTORY TP TEST
# ============================================================

VERSION = "P1-CORE-MAJORS-TP-V2-LONG-HISTORY"

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "AVAX/USDT",
]

PROFILE = "P1_4H_CONFIRM"


# ============================================================
# TEST PERIOD
# ============================================================

# واقعی: 180 روز برای خود تست
TEST_DAYS = 180

# 45 روز اضافه برای warmup اندیکاتورها
FETCH_DAYS = 225


# ============================================================
# NEW SPLIT EXIT
# ============================================================

TP1_R = 1.0
TP2_R = 2.0

TP1_SIZE = 0.50
TP2_SIZE = 0.50


# ============================================================
# CONFIGURE ORIGINAL P1 ENGINE
# ENTRY LOGIC MUST STAY UNCHANGED
# ============================================================

core.VERSION = VERSION

core.TEST_DAYS = TEST_DAYS
core.FETCH_DAYS = FETCH_DAYS

# حدود 225 روز داده 5m
# 225 × 288 ≈ 64,800 candles
# OKX history gives 100 candles/page,
# so 700 pages gives enough room.
core.MAX_PAGES = 700

core.REQUEST_DELAY = 0.05


core.PROFILES = {

    PROFILE: {

        "min_score": 12,

        "min_vol_accel": 1.20,

        "min_vol_ratio5": 1.00,

        "max_dist5": 1.15,

        "need_near_breakout": True,

        "need_4h_bull": True,
    }
}


# ============================================================
# SPLIT EXIT SIMULATOR
#
# 50% closes at 1R
# remaining 50% aims for 2R
# after TP1, stop for remaining half = breakeven
# ============================================================

def simulate_split(
    h5,
    start_i,
    entry,
    sl,
):

    risk = entry - sl

    if risk <= 0:
        return None

    risk_pct = risk / entry

    if risk_pct <= 0:
        return None

    cost_r = (
        core.ROUND_TRIP_COST_PCT
        / risk_pct
    )

    tp1 = entry + TP1_R * risk
    tp2 = entry + TP2_R * risk

    tp1_hit = False

    end_i = min(
        len(h5) - 1,
        start_i + core.MAX_HOLD_BARS
    )

    for j in range(
        start_i + 1,
        end_i + 1
    ):

        bar = h5.iloc[j]

        low = float(
            bar["low"]
        )

        high = float(
            bar["high"]
        )

        # --------------------------------
        # CONSERVATIVE SIMULATION
        # adverse move is counted first
        # --------------------------------

        active_stop = (
            entry
            if tp1_hit
            else sl
        )

        if low <= active_stop:

            # TP1 already hit,
            # second half stopped at BE
            if tp1_hit:

                gross_r = (
                    TP1_SIZE
                    * TP1_R
                )

                return {

                    "r":
                        gross_r
                        - cost_r,

                    "exit":
                        "TP1+BE",

                    "tp1":
                        True,

                    "tp2":
                        False,
                }

            # Normal SL
            return {

                "r":
                    -1.0
                    - cost_r,

                "exit":
                    "SL",

                "tp1":
                    False,

                "tp2":
                    False,
            }

        # TP1
        if (
            not tp1_hit
            and
            high >= tp1
        ):

            tp1_hit = True

        # TP2
        if (
            tp1_hit
            and
            high >= tp2
        ):

            gross_r = (

                TP1_SIZE
                * TP1_R

                +

                TP2_SIZE
                * TP2_R
            )

            return {

                "r":
                    gross_r
                    - cost_r,

                "exit":
                    "TP2",

                "tp1":
                    True,

                "tp2":
                    True,
            }

    # --------------------------------
    # TIME EXIT
    # --------------------------------

    final_close = float(
        h5.iloc[end_i]["close"]
    )

    remaining_r = (
        final_close - entry
    ) / risk

    if tp1_hit:

        # after TP1 the remaining
        # position cannot lose
        # because stop moved to BE

        remaining_r = max(
            0.0,
            remaining_r
        )

        gross_r = (

            TP1_SIZE
            * TP1_R

            +

            TP2_SIZE
            * remaining_r
        )

        exit_name = "TP1+TIME"

    else:

        gross_r = remaining_r

        exit_name = "TIME"

    return {

        "r":
            gross_r
            - cost_r,

        "exit":
            exit_name,

        "tp1":
            tp1_hit,

        "tp2":
            False,
    }


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
        key=lambda x: x["time"]
    )

    rs = [
        float(t["r"])
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

        pf = float("inf")

    else:

        pf = 0.0


    # --------------------------------
    # EQUITY + DRAWDOWN
    # --------------------------------

    equity = 100.0
    peak = 100.0
    max_dd = 0.0

    for r in rs:

        equity *= (
            1.0
            +
            core.RISK_PER_TRADE
            * r
        )

        peak = max(
            peak,
            equity
        )

        dd = (
            (
                peak
                - equity
            )
            / peak
            * 100.0
        )

        max_dd = max(
            max_dd,
            dd
        )


    tp1_rate = (

        sum(
            bool(
                t.get(
                    "tp1",
                    False
                )
            )
            for t in ordered
        )

        / len(ordered)
        * 100.0
    )


    tp2_rate = (

        sum(
            bool(
                t.get(
                    "tp2",
                    False
                )
            )
            for t in ordered
        )

        / len(ordered)
        * 100.0
    )


    return {

        "trades":
            len(rs),

        "wr":
            wins
            / len(rs)
            * 100.0,

        "pf":
            pf,

        "net_r":
            sum(rs),

        "avg_r":
            sum(rs)
            / len(rs),

        "dd":
            max_dd,

        "tp1":
            tp1_rate,

        "tp2":
            tp2_rate,
    }


# ============================================================
# PRINT HELPERS
# ============================================================

def pf_text(
    value
):

    if math.isinf(value):
        return "INF"

    return f"{value:.2f}"


def show_metrics(
    name,
    m
):

    if m is None:

        print(
            f"{name}: NO TRADES"
        )

        return

    print(

        f"{name:12s} | "

        f"Trades:{m['trades']:4d} | "

        f"WR:{m['wr']:6.2f}% | "

        f"PF:{pf_text(m['pf']):>5s} | "

        f"NetR:{m['net_r']:8.2f}R | "

        f"AvgR:{m['avg_r']:7.3f}R | "

        f"DD:{m['dd']:6.2f}% | "

        f"TP1:{m['tp1']:6.2f}% | "

        f"TP2:{m['tp2']:6.2f}%"
    )


# ============================================================
# HISTORY CHECK
# ============================================================

def history_check(
    symbol,
    h5,
    h4
):

    if (
        h5 is None
        or
        h5.empty
        or
        h4 is None
        or
        h4.empty
    ):

        return False


    start_5m = h5.iloc[0][
        "datetime"
    ]

    end_5m = h5.iloc[-1][
        "datetime"
    ]

    coverage_days = (

        end_5m
        - start_5m

    ).total_seconds() / 86400


    test_end = h5.iloc[-1][
        "signal_time"
    ]

    test_start = (

        test_end
        - pd.Timedelta(
            days=TEST_DAYS
        )
    )


    first_4h_available = h4.iloc[0][
        "available_time"
    ]


    print(
        f"{symbol} | "
        f"usable 5m coverage="
        f"{coverage_days:.1f} days"
    )


    if coverage_days < TEST_DAYS:

        print(
            "WARNING: LESS THAN "
            "180 DAYS OF 5M DATA"
        )

        return False


    if (
        first_4h_available
        >
        test_start
    ):

        print(
            "WARNING: NOT ENOUGH "
            "4H WARMUP FOR FULL TEST"
        )

        return False


    print(
        "HISTORY CHECK: PASS"
    )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "#" * 100
    )

    print(
        "P1 CORE MAJORS "
        "- LONG HISTORY TP TEST"
    )

    print(
        "#" * 100
    )

    print(
        f"Version: {VERSION}"
    )

    print(
        f"Profile: {PROFILE}"
    )

    print(
        f"Test period: "
        f"{TEST_DAYS} days"
    )

    print(
        f"Fetch period: "
        f"{FETCH_DAYS} days"
    )

    print(
        "Symbols: "
        + ", ".join(
            SYMBOLS
        )
    )

    print()

    print(
        "CURRENT = original "
        "P1 exit model"
    )

    print(
        "SPLIT = 50% @ 1R + "
        "50% @ 2R + BE after TP1"
    )


    all_current = []
    all_split = []

    per_symbol = []


    # ========================================================
    # LOOP SYMBOLS
    # ========================================================

    for number, symbol in enumerate(
        SYMBOLS,
        1
    ):

        print()
        print(
            "=" * 100
        )

        print(
            f"[{number}/{len(SYMBOLS)}] "
            f"{symbol}"
        )

        print(
            "=" * 100
        )


        # --------------------------------
        # LONG HISTORY
        # original historical engine
        # --------------------------------

        prepared = (
            core.prepare_symbol(
                symbol
            )
        )


        if prepared is None:

            print(
                f"{symbol} | "
                "DATA ERROR"
            )

            continue


        (
            h5,
            h15,
            h1,
            h4,
        ) = prepared


        # --------------------------------
        # Make sure the test is truly
        # long-history and not 12 days
        # --------------------------------

        if not history_check(
            symbol,
            h5,
            h4
        ):

            print(
                f"{symbol} | "
                "SKIPPED: "
                "INSUFFICIENT HISTORY"
            )

            continue


        # --------------------------------
        # ORIGINAL P1 TRADES
        # --------------------------------

        current = (
            core.find_trades(

                symbol,

                h5,
                h15,
                h1,
                h4,

                PROFILE,
            )
        )


        # --------------------------------
        # SAME ENTRIES,
        # NEW SPLIT EXIT
        # --------------------------------

        split = []


        for trade in current:

            signal_time = (
                trade["time"]
            )


            matches = h5.index[
                h5["signal_time"]
                ==
                signal_time
            ]


            if len(matches) == 0:
                continue


            i = int(
                matches[0]
            )


            outcome = simulate_split(

                h5,

                i,

                float(
                    trade["entry"]
                ),

                float(
                    trade["sl"]
                ),
            )


            if outcome is None:
                continue


            new_trade = dict(
                trade
            )


            new_trade[
                "r"
            ] = float(
                outcome["r"]
            )


            new_trade[
                "exit"
            ] = (
                outcome["exit"]
            )


            new_trade[
                "tp1"
            ] = bool(
                outcome["tp1"]
            )


            new_trade[
                "tp2"
            ] = bool(
                outcome["tp2"]
            )


            split.append(
                new_trade
            )


        # --------------------------------
        # SYMBOL RESULTS
        # --------------------------------

        m_current = metrics(
            current
        )

        m_split = metrics(
            split
        )


        print()

        show_metrics(
            "CURRENT",
            m_current
        )

        show_metrics(
            "SPLIT",
            m_split
        )


        if current:

            all_current.extend(
                current
            )


        if split:

            all_split.extend(
                split
            )


        per_symbol.append({

            "symbol":
                symbol,

            "current":
                m_current,

            "split":
                m_split,
        })


    # ========================================================
    # FINAL RESULTS
    # ========================================================

    print()
    print(
        "#" * 100
    )

    print(
        "FINAL - ALL 5 MAJORS"
    )

    print(
        "#" * 100
    )


    final_current = metrics(
        all_current
    )

    final_split = metrics(
        all_split
    )


    show_metrics(
        "CURRENT",
        final_current
    )

    show_metrics(
        "SPLIT",
        final_split
    )


    # ========================================================
    # PER SYMBOL
    # ========================================================

    print()
    print(
        "-" * 100
    )

    print(
        "PER SYMBOL"
    )

    print(
        "-" * 100
    )


    for row in per_symbol:

        print()
        print(
            row["symbol"]
        )

        show_metrics(
            " CURRENT",
            row["current"]
        )

        show_metrics(
            " SPLIT",
            row["split"]
        )


    # ========================================================
    # QUALITY DECISION
    # ========================================================

    print()
    print(
        "#" * 100
    )

    print(
        "QUALITY DECISION"
    )

    print(
        "#" * 100
    )


    if final_split is None:

        print(
            "VERDICT: "
            "NO VALID TEST RESULT"
        )

        return


    trades = (
        final_split["trades"]
    )


    if trades < 20:

        confidence = "LOW"

        verdict = (
            "WATCH ONLY - "
            "SAMPLE TOO SMALL"
        )


    elif (
        final_split["pf"]
        >= 1.30

        and

        final_split["net_r"]
        > 0

        and

        final_split["avg_r"]
        > 0.08

        and

        final_split["dd"]
        <= 15.0
    ):

        confidence = (
            "PROMISING"
        )

        verdict = (
            "PASS CANDIDATE - "
            "NEED FORWARD TEST"
        )


    else:

        confidence = "WEAK"

        verdict = (
            "FAIL / "
            "NEED MORE EVIDENCE"
        )


    print(
        f"Sample confidence: "
        f"{confidence}"
    )

    print(
        f"VERDICT: "
        f"{verdict}"
    )


    print()

    print(
        "IMPORTANT:"
    )

    print(
        "This test changes ONLY "
        "the market universe and "
        "exit comparison."
    )

    print(
        "P1 entry rules remain "
        "unchanged."
    )

    print(
        "Do not judge only by "
        "win rate."
    )

    print(
        "We judge Trades, WR, PF, "
        "NetR, AvgR and DD together."
    )


if __name__ == "__main__":
    main()

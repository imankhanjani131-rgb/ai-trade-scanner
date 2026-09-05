import math
import pandas as pd

import backtest_v42_super_pump as core
import pump_replay_p1 as replay


VERSION = "P1-CORE-MAJORS-TP-V1"

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "AVAX/USDT",
]

PROFILE = "P1_4H_CONFIRM"

# حدود 6 ماه تست + حاشیه برای اندیکاتورها
TEST_DAYS = 180
FETCH_DAYS = 210

# مدل خروج جدید
TP1_R = 1.0
TP2_R = 2.0
TP1_SIZE = 0.50
TP2_SIZE = 0.50


# ============================================================
# KEEP P1 ENTRY LOGIC UNCHANGED
# ============================================================

core.VERSION = VERSION
core.TEST_DAYS = TEST_DAYS

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

# داده مستقیم Toobit
replay.LOOKBACK_DAYS = {
    "5m": FETCH_DAYS,
    "15m": FETCH_DAYS,
    "1h": FETCH_DAYS,
    "4h": FETCH_DAYS,
}


# ============================================================
# SPLIT EXIT: 50% @ 1R + 50% @ 2R
# AFTER TP1 -> STOP REMAINING HALF AT BREAKEVEN
# ============================================================

def simulate_split(h5, start_i, entry, sl):

    risk = entry - sl

    if risk <= 0:
        return None

    risk_pct = risk / entry

    cost_r = (
        core.ROUND_TRIP_COST_PCT / risk_pct
        if risk_pct > 0
        else 0.0
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

        low = float(bar["low"])
        high = float(bar["high"])

        # محافظه‌کارانه:
        # اگر stop و target در یک کندل بخورند،
        # اول حرکت منفی حساب می‌شود.

        active_stop = (
            entry
            if tp1_hit
            else sl
        )

        if low <= active_stop:

            if tp1_hit:
                gross_r = (
                    TP1_SIZE * TP1_R
                )

                return {
                    "r": gross_r - cost_r,
                    "exit": "TP1+BE",
                    "tp1": True,
                    "tp2": False,
                }

            return {
                "r": -1.0 - cost_r,
                "exit": "SL",
                "tp1": False,
                "tp2": False,
            }

        if not tp1_hit and high >= tp1:
            tp1_hit = True

        if tp1_hit and high >= tp2:

            gross_r = (
                TP1_SIZE * TP1_R
                +
                TP2_SIZE * TP2_R
            )

            return {
                "r": gross_r - cost_r,
                "exit": "TP2",
                "tp1": True,
                "tp2": True,
            }

    close = float(
        h5.iloc[end_i]["close"]
    )

    remaining_r = (
        close - entry
    ) / risk

    if tp1_hit:

        remaining_r = max(
            0.0,
            remaining_r
        )

        gross_r = (
            TP1_SIZE * TP1_R
            +
            TP2_SIZE * remaining_r
        )

        exit_name = "TP1+TIME"

    else:

        gross_r = remaining_r
        exit_name = "TIME"

    return {
        "r": gross_r - cost_r,
        "exit": exit_name,
        "tp1": tp1_hit,
        "tp2": False,
    }


# ============================================================
# METRICS
# ============================================================

def metrics(trades):

    if not trades:
        return None

    rs = [
        float(t["r"])
        for t in trades
    ]

    wins = sum(
        r > 0
        for r in rs
    )

    gross_profit = sum(
        r for r in rs
        if r > 0
    )

    gross_loss = abs(
        sum(
            r for r in rs
            if r < 0
        )
    )

    if gross_loss > 0:
        pf = gross_profit / gross_loss
    elif gross_profit > 0:
        pf = float("inf")
    else:
        pf = 0.0

    equity = 100.0
    peak = 100.0
    max_dd = 0.0

    for r in rs:

        equity *= (
            1.0
            +
            core.RISK_PER_TRADE * r
        )

        peak = max(
            peak,
            equity
        )

        dd = (
            (peak - equity)
            / peak
            * 100.0
        )

        max_dd = max(
            max_dd,
            dd
        )

    return {
        "trades": len(rs),
        "wr": wins / len(rs) * 100.0,
        "pf": pf,
        "net_r": sum(rs),
        "avg_r": sum(rs) / len(rs),
        "dd": max_dd,
        "tp1": (
            sum(
                bool(t.get("tp1"))
                for t in trades
            )
            / len(trades)
            * 100.0
        ),
        "tp2": (
            sum(
                bool(t.get("tp2"))
                for t in trades
            )
            / len(trades)
            * 100.0
        ),
    }


def pf_text(x):

    if math.isinf(x):
        return "INF"

    return f"{x:.2f}"


def show_metrics(name, m):

    if m is None:
        print(f"{name}: NO TRADES")
        return

    print(
        f"{name:12s} | "
        f"Trades:{m['trades']:3d} | "
        f"WR:{m['wr']:6.2f}% | "
        f"PF:{pf_text(m['pf']):>5s} | "
        f"NetR:{m['net_r']:8.2f}R | "
        f"AvgR:{m['avg_r']:7.3f}R | "
        f"DD:{m['dd']:6.2f}% | "
        f"TP1:{m['tp1']:6.2f}% | "
        f"TP2:{m['tp2']:6.2f}%"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("#" * 100)
    print("P1 CORE MAJORS - TP1 / TP2 COMPARISON")
    print("#" * 100)

    print(f"Version: {VERSION}")
    print(f"Profile: {PROFILE}")
    print(f"Test days: {TEST_DAYS}")
    print(
        "Symbols: "
        + ", ".join(SYMBOLS)
    )

    print()
    print(
        "CURRENT = original P1 exit"
    )
    print(
        "SPLIT   = 50% @ 1R + "
        "50% @ 2R, BE after TP1"
    )

    all_current = []
    all_split = []

    per_symbol = []

    for n, symbol in enumerate(
        SYMBOLS,
        1
    ):

        print()
        print("=" * 100)
        print(
            f"[{n}/{len(SYMBOLS)}] "
            f"{symbol}"
        )
        print("=" * 100)

        prepared, error = (
            replay.prepare_replay(
                symbol
            )
        )

        if prepared is None:

            print(
                f"{symbol} | "
                f"DATA ERROR: {error}"
            )

            continue

        h5, h15, h1, h4 = prepared

        current = core.find_trades(
            symbol,
            h5,
            h15,
            h1,
            h4,
            PROFILE,
        )

        split = []

        for trade in current:

            signal_time = trade["time"]

            matches = h5.index[
                h5["signal_time"]
                == signal_time
            ]

            if len(matches) == 0:
                continue

            i = int(matches[0])

            outcome = simulate_split(
                h5,
                i,
                float(trade["entry"]),
                float(trade["sl"]),
            )

            if outcome is None:
                continue

            new_trade = dict(trade)

            new_trade["r"] = float(
                outcome["r"]
            )

            new_trade["exit"] = (
                outcome["exit"]
            )

            new_trade["tp1"] = bool(
                outcome["tp1"]
            )

            new_trade["tp2"] = bool(
                outcome["tp2"]
            )

            split.append(
                new_trade
            )

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

        if m_current:
            all_current.extend(
                current
            )

        if m_split:
            all_split.extend(
                split
            )

        per_symbol.append({
            "symbol": symbol,
            "current": m_current,
            "split": m_split,
        })

    print()
    print("#" * 100)
    print("FINAL - ALL 5 MAJORS")
    print("#" * 100)

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

    print()
    print("-" * 100)
    print("PER SYMBOL")
    print("-" * 100)

    for row in per_symbol:

        print()
        print(row["symbol"])

        show_metrics(
            " CURRENT",
            row["current"]
        )

        show_metrics(
            " SPLIT",
            row["split"]
        )

    print()
    print("#" * 100)
    print("QUALITY DECISION")
    print("#" * 100)

    if final_split is None:

        print("VERDICT: FAIL - NO TRADES")
        return

    n = final_split["trades"]

    if n < 20:

        confidence = "LOW"
        verdict = (
            "WATCH ONLY - SAMPLE TOO SMALL"
        )

    elif (
        final_split["pf"] >= 1.30
        and
        final_split["net_r"] > 0
        and
        final_split["avg_r"] > 0.08
        and
        final_split["dd"] <= 15
    ):

        confidence = "PROMISING"
        verdict = (
            "PASS CANDIDATE - NEED FORWARD TEST"
        )

    else:

        confidence = "WEAK"
        verdict = (
            "FAIL / NEED MORE EVIDENCE"
        )

    print(
        f"Sample confidence: {confidence}"
    )

    print(
        f"VERDICT: {verdict}"
    )

    print()
    print(
        "IMPORTANT: fewer symbols do not "
        "automatically mean a higher win rate."
    )

    print(
        "We accept this model only if PF, "
        "NetR, AvgR, DD and sample size "
        "remain healthy together."
    )


if __name__ == "__main__":
    main()

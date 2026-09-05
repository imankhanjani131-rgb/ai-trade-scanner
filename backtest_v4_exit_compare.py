import math
import pandas as pd

import backtest_v4_15m as base


MODELS = {
    "A": "100% to TP2 + BE at +0.7R",
    "B": "50% at TP1 + 50% to TP2 + BE",
    "C": "100% at TP1 + BE at +0.7R",
}


def trade_cost_r(entry, sl):
    risk = entry - sl

    if risk <= 0:
        return 0.0

    risk_pct = risk / entry

    if risk_pct <= 0:
        return 0.0

    return base.ROUND_TRIP_COST_PCT / risk_pct


def pack_result(
    gross_r,
    cost_r,
    exit_reason,
    exit_i,
    tp1_hit,
    tp2_hit,
    tp3_hit,
):
    return {
        "r": float(gross_r - cost_r),
        "exit": exit_reason,
        "exit_i": int(exit_i),
        "tp1": bool(tp1_hit),
        "tp2": bool(tp2_hit),
        "tp3": bool(tp3_hit),
    }


def simulate_a(
    h15,
    i,
    entry,
    sl,
    tp1,
    tp2,
    tp3,
    be,
):
    return base.simulate_trade(
        h15,
        i,
        entry,
        sl,
        tp1,
        tp2,
        tp3,
        be,
    )


def simulate_b(
    h15,
    i,
    entry,
    sl,
    tp1,
    tp2,
    tp3,
    be,
):
    risk = entry - sl
    cost_r = trade_cost_r(entry, sl)

    tp1_r = (tp1 - entry) / risk

    partial_taken = False
    be_armed = False

    tp1_hit = False
    tp2_hit = False
    tp3_hit = False

    end_i = min(
        len(h15) - 1,
        i + base.MAX_HOLD_BARS,
    )

    for j in range(
        i + 1,
        end_i + 1,
    ):
        bar = h15.iloc[j]

        low = float(bar["low"])
        high = float(bar["high"])

        active_stop = (
            entry
            if be_armed
            else sl
        )

        if low <= active_stop:

            if partial_taken:
                gross_r = 0.50 * tp1_r
                reason = "BE_AFTER_TP1"

            elif be_armed:
                gross_r = 0.0
                reason = "BE"

            else:
                gross_r = -1.0
                reason = "SL"

            return pack_result(
                gross_r,
                cost_r,
                reason,
                j,
                tp1_hit,
                tp2_hit,
                tp3_hit,
            )

        if (
            not be_armed
            and high >= be
        ):
            be_armed = True

        if (
            not partial_taken
            and high >= tp1
        ):
            partial_taken = True
            tp1_hit = True
            be_armed = True

        if high >= tp2:
            tp2_hit = True
            tp3_hit = high >= tp3

            gross_r = (
                0.50 * tp1_r
                + 0.50 * 1.50
            )

            return pack_result(
                gross_r,
                cost_r,
                "TP2",
                j,
                tp1_hit,
                tp2_hit,
                tp3_hit,
            )

    close = float(
        h15.iloc[end_i]["close"]
    )

    remaining_r = (
        close - entry
    ) / risk

    if partial_taken:
        gross_r = (
            0.50 * tp1_r
            + 0.50 * remaining_r
        )
    else:
        gross_r = remaining_r

    return pack_result(
        gross_r,
        cost_r,
        "TIME",
        end_i,
        tp1_hit,
        tp2_hit,
        tp3_hit,
    )


def simulate_c(
    h15,
    i,
    entry,
    sl,
    tp1,
    tp2,
    tp3,
    be,
):
    risk = entry - sl
    cost_r = trade_cost_r(entry, sl)

    tp1_r = (
        tp1 - entry
    ) / risk

    be_armed = False

    end_i = min(
        len(h15) - 1,
        i + base.MAX_HOLD_BARS,
    )

    for j in range(
        i + 1,
        end_i + 1,
    ):
        bar = h15.iloc[j]

        low = float(bar["low"])
        high = float(bar["high"])

        active_stop = (
            entry
            if be_armed
            else sl
        )

        if low <= active_stop:

            if be_armed:
                gross_r = 0.0
                reason = "BE"

            else:
                gross_r = -1.0
                reason = "SL"

            return pack_result(
                gross_r,
                cost_r,
                reason,
                j,
                False,
                False,
                False,
            )

        if (
            not be_armed
            and high >= be
        ):
            be_armed = True

        if high >= tp1:

            return pack_result(
                tp1_r,
                cost_r,
                "TP1",
                j,
                True,
                False,
                False,
            )

    close = float(
        h15.iloc[end_i]["close"]
    )

    gross_r = (
        close - entry
    ) / risk

    return pack_result(
        gross_r,
        cost_r,
        "TIME",
        end_i,
        False,
        False,
        False,
    )


def collect_entries(
    symbol,
    h15,
    h1,
    h4,
):
    entries = []

    test_end = (
        h15.iloc[-1][
            "signal_time"
        ]
    )

    test_start = (
        test_end
        - pd.Timedelta(
            days=base.TEST_DAYS
        )
    )

    last_signal_time = None

    for i in range(
        6,
        len(h15) - 1,
    ):
        x15 = h15.iloc[i]

        signal_time = (
            x15["signal_time"]
        )

        if signal_time < test_start:
            continue

        if (
            last_signal_time is not None
            and signal_time - last_signal_time
            < base.FINAL_COOLDOWN
        ):
            continue

        idx1 = (
            h1["available_time"]
            .searchsorted(
                signal_time,
                side="right",
            )
            - 1
        )

        idx4 = (
            h4["available_time"]
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

        p15 = h15.iloc[i - 1]
        four_ago = h15.iloc[i - 4]

        x1 = h1.iloc[idx1]
        p1 = h1.iloc[idx1 - 1]
        x4 = h4.iloc[idx4]

        info = base.score_v4(
            x15,
            p15,
            four_ago,
            x1,
            p1,
            x4,
        )

        if not info["final_ok"]:
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

        entries.append({
            "symbol": symbol,
            "time": signal_time,
            "i": i,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "be": be,
            "score": info["score"],
            "rsi1": info["rsi1"],
            "adx1": info["adx1"],
        })

        last_signal_time = signal_time

    return entries


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
        pf = float("inf")

    equity = 100.0
    peak = 100.0
    max_dd = 0.0

    for r in rs:
        equity *= (
            1
            + base.RISK_PER_TRADE
            * r
        )

        peak = max(
            peak,
            equity,
        )

        if peak > 0:
            dd = (
                peak - equity
            ) / peak * 100

            max_dd = max(
                max_dd,
                dd,
            )

    return {
        "trades": len(trades),
        "wins": wins,
        "losses": losses,

        "wr": (
            wins
            / len(trades)
            * 100
        ),

        "pf": pf,
        "net_r": sum(rs),

        "avg_r": (
            sum(rs)
            / len(rs)
        ),

        "dd": max_dd,
        "equity": equity,

        "tp1": (
            sum(
                t["tp1"]
                for t in trades
            )
            / len(trades)
            * 100
        ),

        "tp2": (
            sum(
                t["tp2"]
                for t in trades
            )
            / len(trades)
            * 100
        ),

        "sl": sum(
            t["exit"] == "SL"
            for t in trades
        ),

        "be": sum(
            str(
                t["exit"]
            ).startswith("BE")
            for t in trades
        ),

        "time": sum(
            t["exit"] == "TIME"
            for t in trades
        ),
    }


def pf_text(value):
    if math.isinf(value):
        return "INF"

    return f"{value:.2f}"


def make_trade_row(
    entry_row,
    outcome,
    model,
):
    return {
        "symbol": entry_row["symbol"],
        "time": entry_row["time"],
        "model": model,
        "r": float(outcome["r"]),
        "exit": outcome["exit"],
        "tp1": bool(outcome["tp1"]),
        "tp2": bool(outcome["tp2"]),
        "tp3": bool(outcome["tp3"]),
    }


def print_model_result(
    model,
    trades,
):
    m = metrics(trades)

    print()
    print("=" * 78)

    print(
        f"MODEL {model} | "
        f"{MODELS[model]}"
    )

    print("=" * 78)

    if m is None:
        print("NO TRADES")
        return

    print(
        f"Trades: {m['trades']}"
    )

    print(
        f"Wins/Losses: "
        f"{m['wins']}/"
        f"{m['losses']}"
    )

    print(
        f"Win rate: "
        f"{m['wr']:.2f}%"
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
        f"{m['dd']:.2f}%"
    )

    print(
        f"Ending equity "
        f"(1% risk): "
        f"{m['equity']:.2f}"
    )

    print(
        f"TP1 touched: "
        f"{m['tp1']:.2f}%"
    )

    print(
        f"TP2 hit: "
        f"{m['tp2']:.2f}%"
    )

    print(
        f"SL exits: "
        f"{m['sl']} | "
        f"BE exits: "
        f"{m['be']} | "
        f"TIME exits: "
        f"{m['time']}"
    )


def print_comparison(
    model_trades
):
    print()
    print("#" * 78)
    print("V4 EXIT MODEL COMPARISON")
    print("#" * 78)

    rows = []

    for model in [
        "A",
        "B",
        "C",
    ]:
        m = metrics(
            model_trades[model]
        )

        if m is not None:
            rows.append(
                (
                    model,
                    m,
                )
            )

    for model, m in rows:
        print(
            f"{model} | "
            f"Trades:{m['trades']:3d} | "
            f"WR:{m['wr']:6.2f}% | "
            f"PF:{pf_text(m['pf']):>5s} | "
            f"NetR:{m['net_r']:8.2f}R | "
            f"AvgR:{m['avg_r']:7.3f}R | "
            f"DD:{m['dd']:6.2f}% | "
            f"Equity:{m['equity']:7.2f}"
        )

    if rows:

        best_net = max(
            rows,
            key=lambda x:
                x[1]["net_r"]
        )

        best_pf = max(
            rows,
            key=lambda x:
                x[1]["pf"]
        )

        lowest_dd = min(
            rows,
            key=lambda x:
                x[1]["dd"]
        )

        print()

        print(
            f"BEST NET R: "
            f"MODEL {best_net[0]} "
            f"({best_net[1]['net_r']:.2f}R)"
        )

        print(
            f"BEST PF: "
            f"MODEL {best_pf[0]} "
            f"({pf_text(best_pf[1]['pf'])})"
        )

        print(
            f"LOWEST DD: "
            f"MODEL {lowest_dd[0]} "
            f"({lowest_dd[1]['dd']:.2f}%)"
        )


def print_symbol_comparison(
    model_trades
):
    print()
    print("#" * 78)
    print("PER-SYMBOL NET R COMPARISON")
    print("#" * 78)

    for symbol in base.SYMBOLS:

        parts = [
            symbol.ljust(12)
        ]

        found = False

        for model in [
            "A",
            "B",
            "C",
        ]:

            rows = [
                t
                for t in model_trades[model]
                if t["symbol"] == symbol
            ]

            m = metrics(rows)

            if m is None:
                parts.append(
                    f"{model}: no trades"
                )

            else:
                found = True

                parts.append(
                    f"{model}:"
                    f"{m['net_r']:+.2f}R "
                    f"PF={pf_text(m['pf'])}"
                )

        if found:
            print(
                " | ".join(parts)
            )


def main():
    print("=" * 80)

    print(
        "AI TRADE SCANNER V4 "
        "- EXIT MODEL COMPARISON"
    )

    print("=" * 80)

    print(
        f"Test period: "
        f"{base.TEST_DAYS} days"
    )

    print(
        "Same V4 FINAL entries "
        "for all three models"
    )

    print(
        "A = full TP2"
    )

    print(
        "B = 50% TP1 + "
        "50% TP2"
    )

    print(
        "C = full TP1"
    )

    print(
        "BE protection: +0.7R"
    )

    print(
        f"Symbols: "
        f"{len(base.SYMBOLS)}"
    )

    model_trades = {
        "A": [],
        "B": [],
        "C": [],
    }

    usable_symbols = []

    for n, symbol in enumerate(
        base.SYMBOLS,
        start=1,
    ):

        print()
        print("#" * 80)

        print(
            f"[{n}/"
            f"{len(base.SYMBOLS)}] "
            f"{symbol}"
        )

        print("#" * 80)

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

            h15, h1, h4 = prepared

            entries = collect_entries(
                symbol,
                h15,
                h1,
                h4,
            )

            usable_symbols.append(
                symbol
            )

            print(
                f"Same V4 entries: "
                f"{len(entries)}"
            )

            for row in entries:

                args = (
                    h15,
                    row["i"],
                    row["entry"],
                    row["sl"],
                    row["tp1"],
                    row["tp2"],
                    row["tp3"],
                    row["be"],
                )

                out_a = simulate_a(
                    *args
                )

                out_b = simulate_b(
                    *args
                )

                out_c = simulate_c(
                    *args
                )

                model_trades["A"].append(
                    make_trade_row(
                        row,
                        out_a,
                        "A",
                    )
                )

                model_trades["B"].append(
                    make_trade_row(
                        row,
                        out_b,
                        "B",
                    )
                )

                model_trades["C"].append(
                    make_trade_row(
                        row,
                        out_c,
                        "C",
                    )
                )

        except Exception as error:
            print(
                f"ERROR "
                f"{symbol}: "
                f"{error}"
            )

    for model in [
        "A",
        "B",
        "C",
    ]:
        model_trades[
            model
        ].sort(
            key=lambda x:
                x["time"]
        )

    print()

    print(
        f"Usable symbols: "
        f"{len(usable_symbols)}/"
        f"{len(base.SYMBOLS)}"
    )

    for model in [
        "A",
        "B",
        "C",
    ]:
        print_model_result(
            model,
            model_trades[model],
        )

    print_comparison(
        model_trades
    )

    print_symbol_comparison(
        model_trades
    )

    print()

    print(
        "EXIT COMPARISON COMPLETED"
    )


if __name__ == "__main__":
    main()

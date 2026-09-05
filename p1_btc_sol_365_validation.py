import math
import pandas as pd

import backtest_v42_super_pump as core
import p1_core_majors_tp as p1

VERSION = "P1-BTC-SOL-365D-OOS-V2"

SYMBOLS = [
    "BTC/USDT",
    "SOL/USDT",
]

PROFILE = "P1_4H_CONFIRM"

TEST_DAYS = 365
FETCH_DAYS = 410
RECENT_DAYS = 180

core.VERSION = VERSION
core.TEST_DAYS = TEST_DAYS
core.FETCH_DAYS = FETCH_DAYS
core.MAX_PAGES = 1250
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


def pf_text(value):
    if value is None:
        return "-"

    if math.isinf(value):
        return "INF"

    return f"{value:.2f}"


def metrics(trades):
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
            core.RISK_PER_TRADE
            * r
        )

        peak = max(
            peak,
            equity
        )

        if peak > 0:

            dd = (
                peak - equity
            ) / peak * 100.0

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
    }


def show_metrics(name, m):

    if m is None:

        print(
            f"{name:16s} | NO TRADES"
        )

        return

    print(
        f"{name:16s} | "
        f"Trades:{m['trades']:3d} | "
        f"WR:{m['wr']:6.2f}% | "
        f"PF:{pf_text(m['pf']):>5s} | "
        f"NetR:{m['net_r']:8.2f}R | "
        f"AvgR:{m['avg_r']:7.3f}R | "
        f"DD:{m['dd']:6.2f}%"
    )


def split_periods(
    trades,
    recent_start
):

    older = [
        t
        for t in trades
        if t["time"] < recent_start
    ]

    recent = [
        t
        for t in trades
        if t["time"] >= recent_start
    ]

    return older, recent


def history_ok(
    symbol,
    h5
):

    if (
        h5 is None
        or h5.empty
    ):

        print(
            f"{symbol} | HISTORY CHECK: FAIL"
        )

        return False

    start_time = h5.iloc[0][
        "datetime"
    ]

    end_time = h5.iloc[-1][
        "datetime"
    ]

    coverage = (
        end_time
        - start_time
    ).total_seconds() / 86400

    print(
        f"{symbol} | "
        f"usable 5m coverage="
        f"{coverage:.1f} days"
    )

    if coverage < TEST_DAYS:

        print(
            "HISTORY CHECK: FAIL"
        )

        return False

    print(
        "HISTORY CHECK: PASS"
    )

    return True


def build_split_trades(
    current,
    h5
):

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

        outcome = p1.simulate_split(
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

    return split


def main():

    print(
        "#" * 100
    )

    print(
        "P1 BTC + SOL - "
        "365 DAY INDEPENDENT VALIDATION"
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
        f"Test days: {TEST_DAYS}"
    )

    print(
        f"Fetch days: {FETCH_DAYS}"
    )

    print(
        "Symbols: "
        + ", ".join(
            SYMBOLS
        )
    )

    all_current = []
    all_split = []

    symbol_results = {}

    data_end_times = []

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

        prepared = core.prepare_symbol(
            symbol
        )

        if prepared is None:

            print(
                f"{symbol} | DATA ERROR"
            )

            continue

        (
            h5,
            h15,
            h1,
            h4,
        ) = prepared

        if not history_ok(
            symbol,
            h5
        ):

            print(
                f"{symbol} | "
                "SKIPPED: INSUFFICIENT HISTORY"
            )

            continue

        data_end_times.append(
            h5.iloc[-1][
                "datetime"
            ]
        )

        current = core.find_trades(
            symbol,
            h5,
            h15,
            h1,
            h4,
            PROFILE,
        )

        split = build_split_trades(
            current,
            h5
        )

        all_current.extend(
            current
        )

        all_split.extend(
            split
        )

        symbol_results[symbol] = {
            "current": current,
            "split": split,
        }

        print()

        show_metrics(
            "CURRENT FULL",
            metrics(current)
        )

        show_metrics(
            "SPLIT FULL",
            metrics(split)
        )

    if not data_end_times:

        print()

        print(
            "VERDICT: FAIL - "
            "NO VALID MARKET DATA"
        )

        return

    test_end = max(
        data_end_times
    )

    test_start = (
        test_end
        -
        pd.Timedelta(
            days=TEST_DAYS
        )
    )

    recent_start = (
        test_end
        -
        pd.Timedelta(
            days=RECENT_DAYS
        )
    )

    print()

    print(
        "#" * 100
    )

    print(
        "TEST WINDOWS"
    )

    print(
        "#" * 100
    )

    print(
        f"TEST START:   {test_start}"
    )

    print(
        f"RECENT START: {recent_start}"
    )

    print(
        f"TEST END:     {test_end}"
    )

    (
        current_older,
        current_recent,
    ) = split_periods(
        all_current,
        recent_start
    )

    (
        split_older,
        split_recent,
    ) = split_periods(
        all_split,
        recent_start
    )

    print()

    print(
        "#" * 100
    )

    print(
        "FINAL - BTC + SOL"
    )

    print(
        "#" * 100
    )

    print()

    print(
        "FULL 365 DAYS"
    )

    show_metrics(
        "CURRENT",
        metrics(
            all_current
        )
    )

    show_metrics(
        "SPLIT",
        metrics(
            all_split
        )
    )

    print()

    print(
        "OLDER ~185 DAYS "
        "(INDEPENDENT / OOS)"
    )

    show_metrics(
        "CURRENT OOS",
        metrics(
            current_older
        )
    )

    show_metrics(
        "SPLIT OOS",
        metrics(
            split_older
        )
    )

    print()

    print(
        "RECENT 180 DAYS "
        "(ALREADY SEEN PERIOD)"
    )

    show_metrics(
        "CURRENT RECENT",
        metrics(
            current_recent
        )
    )

    show_metrics(
        "SPLIT RECENT",
        metrics(
            split_recent
        )
    )

    print()

    print(
        "-" * 100
    )

    print(
        "OLDER / OOS PERIOD - PER SYMBOL"
    )

    print(
        "-" * 100
    )

    positive_symbols = 0

    for symbol in SYMBOLS:

        data = symbol_results.get(
            symbol
        )

        if not data:

            print()

            print(
                f"{symbol}: NO VALID DATA"
            )

            continue

        current_old, _ = split_periods(
            data["current"],
            recent_start
        )

        split_old, _ = split_periods(
            data["split"],
            recent_start
        )

        current_m = metrics(
            current_old
        )

        split_m = metrics(
            split_old
        )

        print()

        print(
            symbol
        )

        show_metrics(
            "CURRENT OOS",
            current_m
        )

        show_metrics(
            "SPLIT OOS",
            split_m
        )

        if (
            split_m is not None
            and
            split_m["net_r"] > 0
        ):

            positive_symbols += 1

    print()

    print(
        "#" * 100
    )

    print(
        "OOS QUALITY DECISION"
    )

    print(
        "#" * 100
    )

    oos = metrics(
        split_older
    )

    if oos is None:

        print(
            f"OOS positive symbols: "
            f"{positive_symbols}/2"
        )

        print(
            "VERDICT: FAIL - "
            "NO OOS TRADES"
        )

        return

    print(
        f"OOS positive symbols: "
        f"{positive_symbols}/2"
    )

    print(
        f"OOS sample trades: "
        f"{oos['trades']}"
    )

    enough_sample = (
        oos["trades"] >= 10
    )

    pf_pass = (
        oos["pf"] >= 1.30
    )

    net_pass = (
        oos["net_r"] > 0
    )

    avg_pass = (
        oos["avg_r"] > 0.08
    )

    dd_pass = (
        oos["dd"] <= 10.0
    )

    symbols_pass = (
        positive_symbols == 2
    )

    print()

    print(
        "CHECKS:"
    )

    print(
        f"Trades >= 10: "
        f"{enough_sample}"
    )

    print(
        f"PF >= 1.30: "
        f"{pf_pass}"
    )

    print(
        f"NetR > 0: "
        f"{net_pass}"
    )

    print(
        f"AvgR > 0.08: "
        f"{avg_pass}"
    )

    print(
        f"DD <= 10%: "
        f"{dd_pass}"
    )

    print(
        f"Both symbols positive: "
        f"{symbols_pass}"
    )

    if not enough_sample:

        verdict = (
            "INCONCLUSIVE - "
            "OOS SAMPLE TOO SMALL"
        )

    elif (
        pf_pass
        and
        net_pass
        and
        avg_pass
        and
        dd_pass
        and
        symbols_pass
    ):

        verdict = (
            "PASS CANDIDATE - "
            "P1 BTC+SOL SURVIVED "
            "INDEPENDENT OOS PERIOD"
        )

    elif (
        oos["pf"] >= 1.10
        and
        oos["net_r"] > 0
        and
        oos["dd"] <= 12.0
    ):

        verdict = (
            "WATCH - "
            "OOS POSITIVE BUT "
            "NOT STRONG ENOUGH"
        )

    else:

        verdict = (
            "FAIL - "
            "P1 BTC+SOL DID NOT "
            "SURVIVE OOS TEST"
        )

    print()

    print(
        f"VERDICT: {verdict}"
    )


if __name__ == "__main__":
    main()

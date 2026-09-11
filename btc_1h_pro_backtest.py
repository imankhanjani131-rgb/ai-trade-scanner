import json
from datetime import datetime, timezone

from btc_1h_pro import (
    BASE_URL,
    SYMBOL,
    CANDLE_MS,
    request_json,
    extract_rows,
    get_server_time_ms,
    fmt_ms,
    floor_ms,
    aggregate_candles,
    analyze_4h,
    analyze_1h,
    analyze_15m,
    make_decision,
)


# =========================================================
# BTC 1H PRO BACKTEST
# =========================================================

DAYS_BACK = 45

# Live bot uses about 1000 x 15m candles.
LIVE_WINDOW_15M = 1000

# Maximum evaluation period after each signal.
# 96 x 15m = 24 hours.
MAX_HOLD_BARS = 96

# Live bot blocks repeated same-side alerts for 3 hours.
SAME_SIDE_COOLDOWN_HOURS = 3

# Official backtest result:
# TP2 = +1.8R
# SL  = -1.0R
PRIMARY_TARGET = "tp2"

TARGET_R = {
    "tp1": 1.0,
    "tp2": 1.8,
    "tp3": 2.8,
}


# =========================================================
# HELPERS
# =========================================================

def safe_div(a, b):
    if not b:
        return 0.0

    return a / b


def pct(a, b):
    if not b:
        return 0.0

    return ((a / b) - 1.0) * 100.0


def signal_time_ms(row):
    # Candle timestamp is candle OPEN time.
    # Signal exists only after the candle closes.
    return row["t"] + CANDLE_MS


def format_number(value, digits=2):
    if value is None:
        return "N/A"

    return f"{value:.{digits}f}"


# =========================================================
# DOWNLOAD HISTORICAL 15M DATA
# =========================================================

def fetch_history(start_ms, end_ms):
    print()
    print("Downloading historical BTC 15m data...")
    print(
        "Requested:",
        fmt_ms(start_ms),
        "→",
        fmt_ms(end_ms),
    )
    print()

    by_time = {}

    # Keep each request below API maximum.
    chunk_bars = 950
    chunk_ms = chunk_bars * CANDLE_MS

    cursor = start_ms
    request_count = 0

    while cursor < end_ms:
        chunk_end = min(
            end_ms,
            cursor + chunk_ms,
        )

        payload = request_json(
            f"{BASE_URL}/quote/v1/klines",
            params={
                "symbol": SYMBOL,
                "interval": "15m",
                "startTime": int(cursor),
                "endTime": int(chunk_end - 1),
                "limit": 1000,
            },
        )

        rows = extract_rows(payload)

        request_count += 1

        accepted = 0

        for row in rows:
            if (
                cursor
                <= row["t"]
                < chunk_end
            ):
                by_time[row["t"]] = row
                accepted += 1

        print(
            f"Chunk {request_count}:",
            fmt_ms(cursor),
            "→",
            fmt_ms(chunk_end),
            "| candles:",
            accepted,
        )

        cursor = chunk_end

    rows = sorted(
        by_time.values(),
        key=lambda x: x["t"],
    )

    print()
    print(
        "Total unique 15m candles:",
        len(rows),
    )

    if rows:
        print(
            "First available candle:",
            fmt_ms(rows[0]["t"]),
        )

        print(
            "Last available candle:",
            fmt_ms(rows[-1]["t"]),
        )

        coverage_days = (
            (
                rows[-1]["t"]
                - rows[0]["t"]
            )
            / (
                24
                * 60
                * 60
                * 1000
            )
        )

        print(
            "Available coverage:",
            f"{coverage_days:.1f} days",
        )

    return rows


# =========================================================
# DATA QUALITY
# =========================================================

def count_missing_gaps(rows):
    if len(rows) < 2:
        return 0

    gaps = 0

    for previous, current in zip(
        rows,
        rows[1:],
    ):
        if (
            current["t"]
            - previous["t"]
        ) != CANDLE_MS:
            gaps += 1

    return gaps


# =========================================================
# PATH EVALUATION
# =========================================================

def stop_hit(side, candle, sl):
    if side == "LONG":
        return candle["l"] <= sl

    return candle["h"] >= sl


def target_hit(
    side,
    candle,
    target,
):
    if side == "LONG":
        return candle["h"] >= target

    return candle["l"] <= target


def evaluate_signal(
    rows,
    signal_index,
    side,
    plan,
):
    entry = plan["entry"]
    sl = plan["sl"]

    targets = {
        "tp1": plan["tp1"],
        "tp2": plan["tp2"],
        "tp3": plan["tp3"],
    }

    risk = abs(
        entry - sl
    )

    if risk <= 0:
        return None

    start_index = (
        signal_index + 1
    )

    end_index = min(
        len(rows),
        start_index
        + MAX_HOLD_BARS,
    )

    future = rows[
        start_index:end_index
    ]

    if len(future) < MAX_HOLD_BARS:
        return {
            "complete": False,
        }

    target_status = {
        "tp1": "OPEN",
        "tp2": "OPEN",
        "tp3": "OPEN",
    }

    target_bar = {
        "tp1": None,
        "tp2": None,
        "tp3": None,
    }

    stop_bar = None

    max_favourable_r = 0.0
    max_adverse_r = 0.0

    for offset, candle in enumerate(
        future,
        start=1,
    ):
        # ---------------------------------------------
        # MFE / MAE
        # ---------------------------------------------

        if side == "LONG":
            favourable_r = (
                candle["h"] - entry
            ) / risk

            adverse_r = (
                entry - candle["l"]
            ) / risk

        else:
            favourable_r = (
                entry - candle["l"]
            ) / risk

            adverse_r = (
                candle["h"] - entry
            ) / risk

        max_favourable_r = max(
            max_favourable_r,
            favourable_r,
        )

        max_adverse_r = max(
            max_adverse_r,
            adverse_r,
        )

        # ---------------------------------------------
        # CONSERVATIVE RULE
        #
        # If stop and target happen inside the same
        # 15m candle, STOP is counted first.
        # ---------------------------------------------

        hit_stop = stop_hit(
            side,
            candle,
            sl,
        )

        if hit_stop:
            stop_bar = offset

            for key in target_status:
                if (
                    target_status[key]
                    == "OPEN"
                ):
                    target_status[key] = "STOP"

            break

        # Stop not touched.
        for key, target in targets.items():
            if (
                target_status[key]
                != "OPEN"
            ):
                continue

            if target_hit(
                side,
                candle,
                target,
            ):
                target_status[key] = "HIT"
                target_bar[key] = offset

        # TP3 hit means every target path
        # has already succeeded.
        if (
            target_status["tp3"]
            == "HIT"
        ):
            break

    # ---------------------------------------------
    # Anything unresolved = TIMEOUT
    # ---------------------------------------------

    for key in target_status:
        if (
            target_status[key]
            == "OPEN"
        ):
            target_status[key] = (
                "TIMEOUT"
            )

    primary_status = target_status[
        PRIMARY_TARGET
    ]

    # ---------------------------------------------
    # Official R result
    # ---------------------------------------------

    if primary_status == "HIT":
        result_r = TARGET_R[
            PRIMARY_TARGET
        ]

        primary_outcome = (
            "TP2"
        )

    elif primary_status == "STOP":
        result_r = -1.0

        primary_outcome = (
            "SL"
        )

    else:
        final_close = future[-1]["c"]

        if side == "LONG":
            result_r = (
                final_close - entry
            ) / risk

        else:
            result_r = (
                entry - final_close
            ) / risk

        primary_outcome = (
            "TIMEOUT"
        )

    return {
        "complete": True,
        "primary_outcome":
            primary_outcome,
        "result_r":
            result_r,
        "tp1_status":
            target_status["tp1"],
        "tp2_status":
            target_status["tp2"],
        "tp3_status":
            target_status["tp3"],
        "tp1_bar":
            target_bar["tp1"],
        "tp2_bar":
            target_bar["tp2"],
        "tp3_bar":
            target_bar["tp3"],
        "stop_bar":
            stop_bar,
        "mfe_r":
            max_favourable_r,
        "mae_r":
            max_adverse_r,
    }


# =========================================================
# METRICS
# =========================================================

def calculate_max_drawdown(
    trades,
):
    equity = 0.0
    peak = 0.0
    max_dd = 0.0

    for trade in trades:
        equity += trade[
            "result_r"
        ]

        peak = max(
            peak,
            equity,
        )

        drawdown = (
            peak - equity
        )

        max_dd = max(
            max_dd,
            drawdown,
        )

    return max_dd


def metrics(trades):
    total = len(trades)

    if total == 0:
        return {
            "trades": 0,
            "tp2_wins": 0,
            "sl_losses": 0,
            "timeouts": 0,
            "win_rate": 0.0,
            "net_r": 0.0,
            "avg_r": 0.0,
            "profit_factor": 0.0,
            "max_dd": 0.0,
            "tp1_hits": 0,
            "tp2_hits": 0,
            "tp3_hits": 0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
        }

    tp2_wins = sum(
        t["primary_outcome"]
        == "TP2"
        for t in trades
    )

    sl_losses = sum(
        t["primary_outcome"]
        == "SL"
        for t in trades
    )

    timeouts = sum(
        t["primary_outcome"]
        == "TIMEOUT"
        for t in trades
    )

    tp1_hits = sum(
        t["tp1_status"]
        == "HIT"
        for t in trades
    )

    tp2_hits = sum(
        t["tp2_status"]
        == "HIT"
        for t in trades
    )

    tp3_hits = sum(
        t["tp3_status"]
        == "HIT"
        for t in trades
    )

    net_r = sum(
        t["result_r"]
        for t in trades
    )

    positive_r = sum(
        t["result_r"]
        for t in trades
        if t["result_r"] > 0
    )

    negative_r = abs(
        sum(
            t["result_r"]
            for t in trades
            if t["result_r"] < 0
        )
    )

    if negative_r > 0:
        profit_factor = (
            positive_r
            / negative_r
        )

    elif positive_r > 0:
        profit_factor = float(
            "inf"
        )

    else:
        profit_factor = 0.0

    return {
        "trades": total,
        "tp2_wins": tp2_wins,
        "sl_losses": sl_losses,
        "timeouts": timeouts,

        "win_rate":
            (
                tp2_wins
                / total
            )
            * 100.0,

        "net_r": net_r,

        "avg_r":
            net_r / total,

        "profit_factor":
            profit_factor,

        "max_dd":
            calculate_max_drawdown(
                trades
            ),

        "tp1_hits":
            tp1_hits,

        "tp2_hits":
            tp2_hits,

        "tp3_hits":
            tp3_hits,

        "avg_mfe":
            sum(
                t["mfe_r"]
                for t in trades
            )
            / total,

        "avg_mae":
            sum(
                t["mae_r"]
                for t in trades
            )
            / total,
    }


def print_metrics(
    title,
    trades,
):
    data = metrics(trades)

    print()
    print(
        "-" * 72
    )

    print(title)

    print(
        "-" * 72
    )

    print(
        "Trades:",
        data["trades"],
    )

    print(
        "TP2 wins:",
        data["tp2_wins"],
    )

    print(
        "SL losses:",
        data["sl_losses"],
    )

    print(
        "Timeouts:",
        data["timeouts"],
    )

    print(
        "Win Rate "
        "(TP2 before SL):",
        f"{data['win_rate']:.2f}%",
    )

    print(
        "Net R:",
        f"{data['net_r']:.2f}R",
    )

    print(
        "Average R:",
        f"{data['avg_r']:.3f}R",
    )

    pf = data[
        "profit_factor"
    ]

    if pf == float("inf"):
        pf_text = "INF"
    else:
        pf_text = (
            f"{pf:.2f}"
        )

    print(
        "Profit Factor:",
        pf_text,
    )

    print(
        "Max Drawdown:",
        f"{data['max_dd']:.2f}R",
    )

    print()

    print(
        "TP1 hit rate:",
        (
            f"{safe_div(data['tp1_hits'], data['trades']) * 100:.2f}%"
        ),
    )

    print(
        "TP2 hit rate:",
        (
            f"{safe_div(data['tp2_hits'], data['trades']) * 100:.2f}%"
        ),
    )

    print(
        "TP3 hit rate:",
        (
            f"{safe_div(data['tp3_hits'], data['trades']) * 100:.2f}%"
        ),
    )

    print()

    print(
        "Average MFE:",
        f"{data['avg_mfe']:.2f}R",
    )

    print(
        "Average MAE:",
        f"{data['avg_mae']:.2f}R",
    )


# =========================================================
# SIGNAL DETAILS
# =========================================================

def print_trade(
    trade,
):
    print(
        f"{trade['number']:>3}"
        f" | {trade['time_utc']}"
        f" | {trade['side']:<5}"
        f" | Entry {trade['entry']:.2f}"
        f" | SL {trade['sl']:.2f}"
        f" | TP2 {trade['tp2']:.2f}"
        f" | {trade['primary_outcome']:<7}"
        f" | {trade['result_r']:+.2f}R"
        f" | Strength {trade['strength']}"
    )


# =========================================================
# BACKTEST ENGINE
# =========================================================

def run_backtest(rows):
    print()
    print(
        "=" * 80
    )

    print(
        "RUNNING BTC 1H PRO REPLAY"
    )

    print(
        "=" * 80
    )

    print(
        "Live rolling window:",
        LIVE_WINDOW_15M,
        "x 15m candles",
    )

    print(
        "Primary result:",
        "TP2 = +1.8R / SL = -1R",
    )

    print(
        "Maximum hold:",
        f"{MAX_HOLD_BARS * 15 / 60:.0f} hours",
    )

    print(
        "Same-candle rule:",
        "SL FIRST",
    )

    print()

    trades = []

    raw_signals = 0
    cooldown_blocked = 0
    incomplete_signals = 0
    no_trade_count = 0

    last_signal_side = None
    last_signal_ms = 0

    cooldown_ms = (
        SAME_SIDE_COOLDOWN_HOURS
        * 60
        * 60
        * 1000
    )

    first_index = (
        LIVE_WINDOW_15M
        - 1
    )

    last_index = (
        len(rows)
        - 2
    )

    if last_index <= first_index:
        raise RuntimeError(
            "Not enough historical candles "
            "after the live warmup window."
        )

    evaluated_points = 0

    for i in range(
        first_index,
        last_index + 1,
    ):
        window_15m = rows[
            i
            - LIVE_WINDOW_15M
            + 1:
            i + 1
        ]

        # Exact same rolling history size
        # used by the live bot.
        rows_1h = aggregate_candles(
            window_15m,
            60 * 60 * 1000,
        )

        rows_4h = aggregate_candles(
            window_15m,
            4 * 60 * 60 * 1000,
        )

        if len(rows_1h) < 200:
            continue

        if len(rows_4h) < 50:
            continue

        evaluated_points += 1

        trend_4h = analyze_4h(
            rows_4h
        )

        setup_1h = analyze_1h(
            rows_1h,
            trend_4h,
        )

        entry_15m = analyze_15m(
            window_15m
        )

        decision = make_decision(
            trend_4h,
            setup_1h,
            entry_15m,
            window_15m,
        )

        side = decision[
            "signal"
        ]

        if side not in (
            "LONG",
            "SHORT",
        ):
            no_trade_count += 1
            continue

        raw_signals += 1

        current_signal_ms = (
            signal_time_ms(
                rows[i]
            )
        )

        # ---------------------------------------------
        # Mirror live Telegram cooldown
        # ---------------------------------------------

        if (
            last_signal_side == side
            and last_signal_ms > 0
            and (
                current_signal_ms
                - last_signal_ms
            ) < cooldown_ms
        ):
            cooldown_blocked += 1
            continue

        last_signal_side = side
        last_signal_ms = (
            current_signal_ms
        )

        plan = decision[
            "plan"
        ]

        if plan is None:
            continue

        evaluation = evaluate_signal(
            rows,
            i,
            side,
            plan,
        )

        if evaluation is None:
            continue

        if not evaluation[
            "complete"
        ]:
            incomplete_signals += 1
            continue

        trade = {
            "number":
                len(trades) + 1,

            "time_ms":
                current_signal_ms,

            "time_utc":
                fmt_ms(
                    current_signal_ms
                ),

            "side":
                side,

            "entry":
                plan["entry"],

            "sl":
                plan["sl"],

            "tp1":
                plan["tp1"],

            "tp2":
                plan["tp2"],

            "tp3":
                plan["tp3"],

            "risk_pct":
                plan["risk_pct"],

            "strength":
                decision["strength"],

            "bias_4h":
                trend_4h["bias"],

            "score_1h_long":
                setup_1h[
                    "long_score"
                ],

            "score_1h_short":
                setup_1h[
                    "short_score"
                ],

            "confirm_15m_long":
                entry_15m[
                    "long_score"
                ],

            "confirm_15m_short":
                entry_15m[
                    "short_score"
                ],

            "rsi_1h":
                setup_1h["rsi"],

            "volume_ratio_1h":
                setup_1h[
                    "vol_ratio"
                ],

            **evaluation,
        }

        trades.append(
            trade
        )

    return {
        "trades":
            trades,

        "evaluated_points":
            evaluated_points,

        "raw_signals":
            raw_signals,

        "cooldown_blocked":
            cooldown_blocked,

        "incomplete_signals":
            incomplete_signals,

        "no_trade_count":
            no_trade_count,
    }


# =========================================================
# FINAL REPORT
# =========================================================

def final_report(
    rows,
    result,
):
    trades = result[
        "trades"
    ]

    long_trades = [
        trade
        for trade in trades
        if trade["side"]
        == "LONG"
    ]

    short_trades = [
        trade
        for trade in trades
        if trade["side"]
        == "SHORT"
    ]

    print()
    print()
    print(
        "#" * 80
    )

    print(
        "BTC 1H PRO BACKTEST RESULTS"
    )

    print(
        "#" * 80
    )

    print()

    print(
        "Historical candles:",
        len(rows),
    )

    print(
        "Evaluated 15m checkpoints:",
        result[
            "evaluated_points"
        ],
    )

    print(
        "Raw LONG/SHORT setups:",
        result[
            "raw_signals"
        ],
    )

    print(
        "Blocked by 3H cooldown:",
        result[
            "cooldown_blocked"
        ],
    )

    print(
        "Incomplete recent signals:",
        result[
            "incomplete_signals"
        ],
    )

    print(
        "Finalized signals:",
        len(trades),
    )

    print_metrics(
        "ALL SIGNALS",
        trades,
    )

    print_metrics(
        "LONG ONLY",
        long_trades,
    )

    print_metrics(
        "SHORT ONLY",
        short_trades,
    )

    print()
    print()
    print(
        "#" * 80
    )

    print(
        "TRADE LOG"
    )

    print(
        "#" * 80
    )

    if not trades:
        print(
            "No finalized signals."
        )

    else:
        for trade in trades:
            print_trade(
                trade
            )

    print()
    print(
        "#" * 80
    )

    print(
        "SAMPLE CHECK"
    )

    print(
        "#" * 80
    )

    total = len(trades)

    if total < 10:
        status = (
            "VERY SMALL SAMPLE"
        )

    elif total < 30:
        status = (
            "SMALL SAMPLE"
        )

    elif total < 60:
        status = (
            "USABLE BUT STILL LIMITED"
        )

    else:
        status = (
            "BETTER SAMPLE"
        )

    print(
        "Sample status:",
        status,
    )

    print()
    print(
        "IMPORTANT:"
    )

    print(
        "- Strength 90/100 is NOT "
        "a 90% win probability."
    )

    print(
        "- Backtest result uses TP2 "
        "as the primary target."
    )

    print(
        "- TP1 and TP3 hit rates are "
        "reported separately."
    )

    print(
        "- Same-candle SL/TP ambiguity "
        "is resolved conservatively: SL first."
    )

    print(
        "- No fees, funding or slippage "
        "are included yet."
    )

    print(
        "- This test does NOT place trades."
    )


# =========================================================
# SAVE MACHINE-READABLE RESULT
# =========================================================

def save_result_json(
    rows,
    result,
):
    trades = result[
        "trades"
    ]

    all_metrics = metrics(
        trades
    )

    long_metrics = metrics(
        [
            x
            for x in trades
            if x["side"]
            == "LONG"
        ]
    )

    short_metrics = metrics(
        [
            x
            for x in trades
            if x["side"]
            == "SHORT"
        ]
    )

    output = {
        "engine":
            "BTC 1H PRO V1",

        "symbol":
            SYMBOL,

        "requested_days":
            DAYS_BACK,

        "historical_candles":
            len(rows),

        "first_candle_utc":
            (
                fmt_ms(
                    rows[0]["t"]
                )
                if rows
                else None
            ),

        "last_candle_utc":
            (
                fmt_ms(
                    rows[-1]["t"]
                )
                if rows
                else None
            ),

        "rules": {
            "live_window_15m":
                LIVE_WINDOW_15M,

            "max_hold_bars":
                MAX_HOLD_BARS,

            "primary_target":
                PRIMARY_TARGET,

            "primary_target_r":
                TARGET_R[
                    PRIMARY_TARGET
                ],

            "stop_r":
                -1.0,

            "same_candle_rule":
                "SL_FIRST",

            "same_side_cooldown_hours":
                SAME_SIDE_COOLDOWN_HOURS,
        },

        "scanner": {
            "evaluated_points":
                result[
                    "evaluated_points"
                ],

            "raw_signals":
                result[
                    "raw_signals"
                ],

            "cooldown_blocked":
                result[
                    "cooldown_blocked"
                ],

            "incomplete_signals":
                result[
                    "incomplete_signals"
                ],
        },

        "metrics": {
            "all":
                all_metrics,

            "long":
                long_metrics,

            "short":
                short_metrics,
        },

        "trades":
            trades,
    }

    with open(
        "btc_1h_pro_backtest_results.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print(
        "Saved:",
        "btc_1h_pro_backtest_results.json",
    )


# =========================================================
# MAIN
# =========================================================

def main():
    print(
        "BTC 1H PRO BACKTEST V1"
    )

    print(
        "Exact live logic replay"
    )

    print(
        "4H Trend → "
        "1H Setup → "
        "15m Entry"
    )

    print(
        "LONG / SHORT / NO TRADE"
    )

    print()

    now_ms = (
        get_server_time_ms()
    )

    end_ms = floor_ms(
        now_ms,
        CANDLE_MS,
    )

    start_ms = (
        end_ms
        - DAYS_BACK
        * 24
        * 60
        * 60
        * 1000
    )

    print(
        "Server time:",
        fmt_ms(now_ms),
    )

    print(
        "Requested lookback:",
        DAYS_BACK,
        "days",
    )

    rows = fetch_history(
        start_ms,
        end_ms,
    )

    if len(rows) < (
        LIVE_WINDOW_15M
        + MAX_HOLD_BARS
        + 50
    ):
        raise RuntimeError(
            "Not enough historical BTC data "
            "for a useful replay."
        )

    gaps = count_missing_gaps(
        rows
    )

    print()
    print(
        "Detected time gaps:",
        gaps,
    )

    if gaps > 20:
        print(
            "WARNING: Historical data "
            "contains many gaps."
        )

    result = run_backtest(
        rows
    )

    final_report(
        rows,
        result,
    )

    save_result_json(
        rows,
        result,
    )

    print()
    print(
        "BACKTEST COMPLETE ✅"
    )


if __name__ == "__main__":
    main()

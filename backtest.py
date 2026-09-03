import time
import math
import ccxt
import pandas as pd
import ta


# =========================================================
# FINAL 1-YEAR VALIDATION
# Historical data source: Binance
# Live robot will remain on Toobit
# =========================================================

DAYS = 365
FETCH_DAYS = 425
TEST_DAYS = 90

MIN_SCORE = 9
MIN_ADX = 22

MAX_HOLD_HOURS = 72
RISK_PER_TRADE = 0.01
TARGET_NO = 2

# Conservative trading cost assumption
# 0.06% fee + 0.03% slippage per side
FEE_PER_SIDE = 0.0006
SLIPPAGE_PER_SIDE = 0.0003

ROUND_TRIP_COST_PCT = 2 * (
    FEE_PER_SIDE + SLIPPAGE_PER_SIDE
)


SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "DOGE/USDT",
    "DOT/USDT",
    "LINK/USDT",
    "NEAR/USDT",
    "LTC/USDT",
    "SHIB/USDT",
    "SUI/USDT",
    "PEPE/USDT",
    "APT/USDT",
    "FET/USDT",
    "RENDER/USDT",
    "TON/USDT",
    "TRX/USDT",
]


exchange = ccxt.binance({
    "enableRateLimit": True,
    "timeout": 30000,
    "options": {
        "defaultType": "spot"
    }
})


# =========================================================
# DATA
# =========================================================

def fetch_history(symbol, timeframe, days):

    now_ms = exchange.milliseconds()

    since = (
        now_ms
        - days * 24 * 60 * 60 * 1000
    )

    rows = []

    while True:

        batch = exchange.fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            since=since,
            limit=1000
        )

        if not batch:
            break

        rows.extend(batch)

        last_ts = batch[-1][0]

        next_since = last_ts + 1

        if next_since <= since:
            break

        since = next_since

        if last_ts >= now_ms:
            break

        if len(batch) < 1000:
            break

        time.sleep(
            exchange.rateLimit / 1000
        )

    if not rows:
        return None

    df = pd.DataFrame(
        rows,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]
    )

    df = (
        df
        .drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )

    df["datetime"] = pd.to_datetime(
        df["timestamp"],
        unit="ms",
        utc=True
    )

    # Remove potentially unfinished latest candle
    if len(df) > 1:
        df = df.iloc[:-1].copy()

    return df


# =========================================================
# INDICATORS
# =========================================================

def add_indicators(df):

    df = df.copy()

    df["ema20"] = ta.trend.EMAIndicator(
        df["close"],
        window=20
    ).ema_indicator()

    df["ema50"] = ta.trend.EMAIndicator(
        df["close"],
        window=50
    ).ema_indicator()

    df["ema200"] = ta.trend.EMAIndicator(
        df["close"],
        window=200
    ).ema_indicator()

    df["rsi"] = ta.momentum.RSIIndicator(
        df["close"],
        window=14
    ).rsi()

    macd = ta.trend.MACD(
        df["close"]
    )

    df["macd"] = macd.macd()

    df["macd_signal"] = (
        macd.macd_signal()
    )

    df["macd_hist"] = (
        macd.macd_diff()
    )

    df["atr"] = (
        ta.volatility.AverageTrueRange(
            df["high"],
            df["low"],
            df["close"],
            window=14
        ).average_true_range()
    )

    df["adx"] = (
        ta.trend.ADXIndicator(
            df["high"],
            df["low"],
            df["close"],
            window=14
        ).adx()
    )

    df["vol_ma"] = (
        df["volume"]
        .rolling(20)
        .mean()
    )

    df["vol_ratio"] = (
        df["volume"]
        / df["vol_ma"]
    )

    return df


# =========================================================
# PREPARE 1H + 4H
# =========================================================

def prepare(symbol):

    h1 = fetch_history(
        symbol,
        "1h",
        FETCH_DAYS
    )

    h4 = fetch_history(
        symbol,
        "4h",
        FETCH_DAYS
    )

    if (
        h1 is None
        or h4 is None
        or h1.empty
        or h4.empty
    ):
        return None

    print(
        f"{symbol} DATA | "
        f"1H: {h1.iloc[0]['datetime']} -> "
        f"{h1.iloc[-1]['datetime']} | "
        f"bars={len(h1)}"
    )

    print(
        f"{symbol} DATA | "
        f"4H: {h4.iloc[0]['datetime']} -> "
        f"{h4.iloc[-1]['datetime']} | "
        f"bars={len(h4)}"
    )

    h1 = add_indicators(h1)

    h4 = add_indicators(h4)

    # Candle becomes usable after it closes
    h1["signal_time"] = (
        h1["datetime"]
        + pd.Timedelta(hours=1)
    )

    h4["available_time"] = (
        h4["datetime"]
        + pd.Timedelta(hours=4)
    )

    h4_small = h4[
        [
            "available_time",
            "close",
            "ema20",
            "ema50",
            "ema200",
            "rsi"
        ]
    ].copy()

    h4_small = h4_small.rename(
        columns={
            "close": "close4",
            "ema20": "ema20_4",
            "ema50": "ema50_4",
            "ema200": "ema200_4",
            "rsi": "rsi_4"
        }
    )

    merged = pd.merge_asof(
        h1.sort_values(
            "signal_time"
        ),
        h4_small.sort_values(
            "available_time"
        ),
        left_on="signal_time",
        right_on="available_time",
        direction="backward"
    )

    merged = (
        merged
        .dropna()
        .reset_index(drop=True)
    )

    cutoff = (
        pd.Timestamp.now(tz="UTC")
        - pd.Timedelta(days=DAYS)
    )

    merged = merged[
        merged["signal_time"] >= cutoff
    ].copy()

    merged = (
        merged
        .reset_index(drop=True)
    )

    return merged


# =========================================================
# 4H TREND
# =========================================================

def trend4(row):

    if (
        row["close4"] > row["ema200_4"]
        and row["ema20_4"] > row["ema50_4"]
        and row["ema50_4"] > row["ema200_4"]
        and row["rsi_4"] >= 50
    ):
        return "BULLISH"

    if (
        row["close4"] < row["ema200_4"]
        and row["ema20_4"] < row["ema50_4"]
        and row["ema50_4"] < row["ema200_4"]
        and row["rsi_4"] <= 50
    ):
        return "BEARISH"

    return "NEUTRAL"


# =========================================================
# SIGNAL SCORE
# =========================================================

def score_signal(
    df,
    i,
    side,
    trend
):

    x = df.iloc[i]
    p = df.iloc[i - 1]

    if side == "LONG":

        tests = [
            (
                trend == "BULLISH",
                3
            ),
            (
                x["close"] > x["ema50"],
                1
            ),
            (
                x["ema20"] > x["ema50"],
                1
            ),
            (
                45 <= x["rsi"] < 70,
                1
            ),
            (
                x["macd"] > x["macd_signal"],
                1
            ),
            (
                x["macd_hist"] > p["macd_hist"],
                1
            ),
            (
                x["adx"] >= MIN_ADX,
                1
            ),
            (
                x["vol_ratio"] >= 0.8,
                1
            )
        ]

    else:

        tests = [
            (
                trend == "BEARISH",
                3
            ),
            (
                x["close"] < x["ema50"],
                1
            ),
            (
                x["ema20"] < x["ema50"],
                1
            ),
            (
                30 < x["rsi"] <= 55,
                1
            ),
            (
                x["macd"] < x["macd_signal"],
                1
            ),
            (
                x["macd_hist"] < p["macd_hist"],
                1
            ),
            (
                x["adx"] >= MIN_ADX,
                1
            ),
            (
                x["vol_ratio"] >= 0.8,
                1
            )
        ]

    distance = (
        abs(
            x["close"] - x["ema20"]
        )
        / x["close"]
    )

    if distance <= 0.015:
        tests.append(
            (True, 1)
        )

    score = sum(
        pts
        for ok, pts in tests
        if ok
    )

    return score


# =========================================================
# ENTRY / SL / TP
# =========================================================

def levels(
    df,
    i,
    side
):

    x = df.iloc[i]

    recent = df.iloc[
        max(0, i - 10):
        i + 1
    ]

    entry = float(
        x["close"]
    )

    atr = float(
        x["atr"]
    )

    if side == "LONG":

        swing = float(
            recent["low"].min()
        )

        sl = min(
            entry - 1.5 * atr,
            swing - 0.2 * atr
        )

        risk = (
            entry - sl
        )

        tps = [
            entry + risk,
            entry + 2 * risk,
            entry + 3 * risk
        ]

    else:

        swing = float(
            recent["high"].max()
        )

        sl = max(
            entry + 1.5 * atr,
            swing + 0.2 * atr
        )

        risk = (
            sl - entry
        )

        tps = [
            entry - risk,
            entry - 2 * risk,
            entry - 3 * risk
        ]

    return (
        entry,
        sl,
        tps
    )


# =========================================================
# FIND ORIGINAL ROBOT SIGNALS
# =========================================================

def find_candidates(
    symbol,
    df
):

    candidates = []

    active_side = None

    for i in range(
        2,
        len(df) - 1
    ):

        x = df.iloc[i]

        trend = trend4(x)

        side = None

        score = 0

        if (
            trend == "BULLISH"
            and x["rsi"] < 70
            and x["adx"] >= MIN_ADX
        ):

            score = score_signal(
                df,
                i,
                "LONG",
                trend
            )

            if score >= MIN_SCORE:
                side = "LONG"

        elif (
            trend == "BEARISH"
            and x["rsi"] > 30
            and x["adx"] >= MIN_ADX
        ):

            score = score_signal(
                df,
                i,
                "SHORT",
                trend
            )

            if score >= MIN_SCORE:
                side = "SHORT"

        if side is None:

            active_side = None
            continue

        if side == active_side:
            continue

        entry, sl, tps = levels(
            df,
            i,
            side
        )

        candidates.append({
            "symbol": symbol,
            "i": i,
            "time": x["signal_time"],
            "side": side,
            "score": int(score),
            "rsi": float(x["rsi"]),
            "adx": float(x["adx"]),
            "entry": entry,
            "sl": sl,
            "tps": tps
        })

        active_side = side

    return candidates


# =========================================================
# SIMULATION
# =========================================================

def simulate(
    df,
    trade
):

    entry = trade["entry"]

    sl = trade["sl"]

    tp = trade["tps"][
        TARGET_NO - 1
    ]

    risk = abs(
        entry - sl
    )

    if risk <= 0:

        return (
            0.0,
            trade["i"],
            "INVALID"
        )

    end_i = min(
        trade["i"] + MAX_HOLD_HOURS,
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

        if trade["side"] == "LONG":

            hit_sl = (
                bar["low"] <= sl
            )

            hit_tp = (
                bar["high"] >= tp
            )

        else:

            hit_sl = (
                bar["high"] >= sl
            )

            hit_tp = (
                bar["low"] <= tp
            )

        # Conservative assumption:
        # if both touched in same candle,
        # stop loss is counted first.
        if hit_sl and hit_tp:

            raw_r = -1.0

            exit_i = j

            reason = "SL-FIRST"

            break

        if hit_sl:

            raw_r = -1.0

            exit_i = j

            reason = "SL"

            break

        if hit_tp:

            raw_r = float(
                TARGET_NO
            )

            exit_i = j

            reason = (
                f"TP{TARGET_NO}"
            )

            break

    if raw_r is None:

        exit_price = float(
            df.iloc[end_i]["close"]
        )

        if trade["side"] == "LONG":

            raw_r = (
                exit_price - entry
            ) / risk

        else:

            raw_r = (
                entry - exit_price
            ) / risk

    cost_r = (
        entry
        * ROUND_TRIP_COST_PCT
    ) / risk

    net_r = (
        raw_r - cost_r
    )

    return (
        float(net_r),
        exit_i,
        reason
    )


# =========================================================
# RUN VARIANT
# =========================================================

def run_variant(
    candidates,
    data,
    condition
):

    results = []

    blocked_until = {}

    for trade in candidates:

        if not condition(trade):
            continue

        symbol = trade["symbol"]

        if (
            trade["i"]
            <= blocked_until.get(
                symbol,
                -1
            )
        ):
            continue

        r, exit_i, reason = simulate(
            data[symbol],
            trade
        )

        blocked_until[
            symbol
        ] = exit_i

        results.append({
            "symbol": symbol,
            "time": trade["time"],
            "side": trade["side"],
            "score": trade["score"],
            "rsi": trade["rsi"],
            "adx": trade["adx"],
            "r": r,
            "exit": reason
        })

    return sorted(
        results,
        key=lambda x: x["time"]
    )


# =========================================================
# METRICS
# =========================================================

def calc_metrics(results):

    if not results:
        return None

    rs = [
        x["r"]
        for x in results
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
            + RISK_PER_TRADE * r
        )

        peak = max(
            peak,
            equity
        )

        if peak > 0:

            dd = (
                peak - equity
            ) / peak * 100

            max_dd = max(
                max_dd,
                dd
            )

    return {
        "trades": len(rs),
        "wins": wins,
        "losses": losses,
        "win_rate": (
            wins / len(rs) * 100
        ),
        "pf": pf,
        "net_r": sum(rs),
        "avg_r": (
            sum(rs) / len(rs)
        ),
        "max_dd": max_dd,
        "equity": equity
    }


def print_metrics(
    label,
    results
):

    print()
    print("=" * 72)
    print(label)
    print("=" * 72)

    m = calc_metrics(
        results
    )

    if m is None:

        print(
            "NO TRADES"
        )

        return

    if math.isinf(
        m["pf"]
    ):

        pf_text = "INF"

    else:

        pf_text = (
            f'{m["pf"]:.2f}'
        )

    print(
        "Trades:",
        m["trades"]
    )

    print(
        "Wins:",
        m["wins"]
    )

    print(
        "Losses:",
        m["losses"]
    )

    print(
        "Win rate:",
        f'{m["win_rate"]:.2f}%'
    )

    print(
        "Profit factor:",
        pf_text
    )

    print(
        "Net R:",
        f'{m["net_r"]:.2f}R'
    )

    print(
        "Avg R:",
        f'{m["avg_r"]:.3f}R'
    )

    print(
        "Max drawdown:",
        f'{m["max_dd"]:.2f}%'
    )

    print(
        "Ending equity:",
        f'{m["equity"]:.2f}'
    )


# =========================================================
# TIME SPLIT
# =========================================================

def slice_results(
    results,
    start=None,
    end=None
):

    output = results

    if start is not None:

        output = [
            x
            for x in output
            if x["time"] >= start
        ]

    if end is not None:

        output = [
            x
            for x in output
            if x["time"] < end
        ]

    return output


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 78)

    print(
        "AI TRADE SCANNER - TRUE 1 YEAR VALIDATION"
    )

    print("=" * 78)

    print(
        "Historical source: BINANCE"
    )

    print(
        "Live robot exchange: TOOBIT"
    )

    print(
        "Validation period:",
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
        "Exit target: TP2"
    )

    print(
        "Risk per trade:",
        f"{RISK_PER_TRADE * 100:.2f}%"
    )

    print(
        "Round-trip cost assumption:",
        f"{ROUND_TRIP_COST_PCT * 100:.3f}%"
    )

    print(
        "Requested symbols:",
        len(SYMBOLS)
    )

    print()

    print(
        "Loading Binance markets..."
    )

    exchange.load_markets()

    data = {}

    candidates = []

    usable_symbols = []

    for symbol in SYMBOLS:

        print()
        print("#" * 78)
        print(
            "LOADING:",
            symbol
        )
        print("#" * 78)

        if symbol not in exchange.markets:

            print(
                "SKIPPED: symbol not available on Binance"
            )

            continue

        try:

            df = prepare(
                symbol
            )

            if (
                df is None
                or df.empty
            ):

                print(
                    "SKIPPED: no usable data"
                )

                continue

            coverage_days = (
                df.iloc[-1]["signal_time"]
                - df.iloc[0]["signal_time"]
            ).total_seconds() / 86400

            print(
                "Usable coverage:",
                f"{coverage_days:.1f}",
                "days"
            )

            # Require almost a full year.
            if coverage_days < 330:

                print(
                    "SKIPPED: less than 330 days of usable history"
                )

                continue

            data[symbol] = df

            usable_symbols.append(
                symbol
            )

            found = find_candidates(
                symbol,
                df
            )

            candidates.extend(
                found
            )

            print(
                "Candidates:",
                len(found)
            )

        except Exception as error:

            print(
                "ERROR:",
                symbol,
                error
            )

    candidates.sort(
        key=lambda x: x["time"]
    )

    print()
    print("=" * 78)
    print(
        "DATA LOAD COMPLETE"
    )
    print("=" * 78)

    print(
        "Usable symbols:",
        len(usable_symbols)
    )

    print(
        usable_symbols
    )

    print(
        "Total candidates:",
        len(candidates)
    )

    if not candidates:

        print(
            "NO CANDIDATES - VALIDATION STOPPED"
        )

        return

    now = pd.Timestamp.now(
        tz="UTC"
    )

    recent_start = (
        now
        - pd.Timedelta(
            days=TEST_DAYS
        )
    )

    last_30_start = (
        now
        - pd.Timedelta(
            days=30
        )
    )


    variants = [

        (
            "A - CURRENT LONG + SHORT",
            lambda t: True
        ),

        (
            "B - LONG ONLY",
            lambda t:
                t["side"] == "LONG"
        ),

        (
            "C - LONG + ADX >= 40",
            lambda t:
                t["side"] == "LONG"
                and t["adx"] >= 40
        ),

        (
            "D - LONG + ADX >= 40 + RSI 60-70",
            lambda t:
                t["side"] == "LONG"
                and t["adx"] >= 40
                and 60 <= t["rsi"] < 70
        ),

        (
            "E - LONG + ADX >= 40 + RSI 60-70 + SCORE 9",
            lambda t:
                t["side"] == "LONG"
                and t["adx"] >= 40
                and 60 <= t["rsi"] < 70
                and t["score"] == 9
        )
    ]


    ranking = []


    for name, condition in variants:

        results = run_variant(
            candidates,
            data,
            condition
        )

        older_holdout = (
            slice_results(
                results,
                end=recent_start
            )
        )

        recent_90 = (
            slice_results(
                results,
                start=recent_start
            )
        )

        recent_30 = (
            slice_results(
                results,
                start=last_30_start
            )
        )

        print()
        print("#" * 78)
        print(name)
        print("#" * 78)

        print_metrics(
            "FULL 365 DAYS",
            results
        )

        print_metrics(
            "OLDER HOLDOUT - FIRST 275 DAYS",
            older_holdout
        )

        print_metrics(
            "RECENT TEST - LAST 90 DAYS",
            recent_90
        )

        print_metrics(
            "LAST 30 DAYS",
            recent_30
        )

        old_m = calc_metrics(
            older_holdout
        )

        recent_m = calc_metrics(
            recent_90
        )

        full_m = calc_metrics(
            results
        )

        if (
            old_m is not None
            and recent_m is not None
            and full_m is not None
        ):

            ranking.append({
                "name": name,

                "old_trades": old_m[
                    "trades"
                ],

                "old_wr": old_m[
                    "win_rate"
                ],

                "old_pf": old_m[
                    "pf"
                ],

                "old_net": old_m[
                    "net_r"
                ],

                "old_dd": old_m[
                    "max_dd"
                ],

                "recent_trades": recent_m[
                    "trades"
                ],

                "recent_wr": recent_m[
                    "win_rate"
                ],

                "recent_pf": recent_m[
                    "pf"
                ],

                "recent_net": recent_m[
                    "net_r"
                ],

                "recent_dd": recent_m[
                    "max_dd"
                ],

                "full_trades": full_m[
                    "trades"
                ],

                "full_pf": full_m[
                    "pf"
                ],

                "full_net": full_m[
                    "net_r"
                ]
            })


    print()
    print("#" * 78)
    print(
        "FINAL RANKING - TRUE OLDER HOLDOUT"
    )
    print("#" * 78)


    ranking.sort(
        key=lambda row: (
            row["old_net"],
            row["old_pf"],
            row["recent_net"]
        ),
        reverse=True
    )


    for row in ranking:

        if math.isinf(
            row["old_pf"]
        ):

            old_pf = "INF"

        else:

            old_pf = (
                f'{row["old_pf"]:.2f}'
            )


        if math.isinf(
            row["recent_pf"]
        ):

            recent_pf = "INF"

        else:

            recent_pf = (
                f'{row["recent_pf"]:.2f}'
            )


        if math.isinf(
            row["full_pf"]
        ):

            full_pf = "INF"

        else:

            full_pf = (
                f'{row["full_pf"]:.2f}'
            )


        print()

        print(
            row["name"]
        )

        print(
            f'OLDER | '
            f'Trades:{row["old_trades"]} | '
            f'WR:{row["old_wr"]:.2f}% | '
            f'PF:{old_pf} | '
            f'NetR:{row["old_net"]:.2f}R | '
            f'DD:{row["old_dd"]:.2f}%'
        )

        print(
            f'RECENT90 | '
            f'Trades:{row["recent_trades"]} | '
            f'WR:{row["recent_wr"]:.2f}% | '
            f'PF:{recent_pf} | '
            f'NetR:{row["recent_net"]:.2f}R | '
            f'DD:{row["recent_dd"]:.2f}%'
        )

        print(
            f'FULL365 | '
            f'Trades:{row["full_trades"]} | '
            f'PF:{full_pf} | '
            f'NetR:{row["full_net"]:.2f}R'
        )


    print()
    print("=" * 78)
    print(
        "FINAL 1-YEAR VALIDATION COMPLETED"
    )
    print("=" * 78)

    print(
        "Do not change main.py until this ranking is reviewed."
    )


if __name__ == "__main__":
    main()

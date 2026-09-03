import time
import math
import ccxt
import pandas as pd
import ta

DAYS = 365
DISCOVERY_DAYS = 120
MAX_HOLD_HOURS = 72
RISK_PER_TRADE = 0.01
TARGET_NO = 2

MIN_SCORE = 9
MIN_ADX = 22

# فرض محافظه‌کارانه هزینه معامله
# 0.06% کارمزد + 0.03% اسلیپیج در هر سمت
FEE_PER_SIDE = 0.0006
SLIPPAGE_PER_SIDE = 0.0003
ROUND_TRIP_COST_PCT = 2 * (FEE_PER_SIDE + SLIPPAGE_PER_SIDE)

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "XRP/USDT", "ADA/USDT", "AVAX/USDT", "DOGE/USDT",
    "DOT/USDT", "LINK/USDT", "NEAR/USDT", "LTC/USDT",
    "SHIB/USDT", "SUI/USDT", "PEPE/USDT", "APT/USDT",
    "FET/USDT", "RENDER/USDT", "TON/USDT", "TRX/USDT"
]

exchange = ccxt.toobit({
    "enableRateLimit": True,
    "timeout": 20000
})


def fetch_history(symbol, timeframe, days):
    ms_per_bar = exchange.parse_timeframe(timeframe) * 1000
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
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

        next_since = batch[-1][0] + ms_per_bar

        if next_since <= since:
            break

        since = next_since

        if len(batch) < 1000:
            break

        time.sleep(exchange.rateLimit / 1000)

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

    return df


def add_indicators(df):
    df = df.copy()

    df["ema20"] = ta.trend.EMAIndicator(
        df["close"],
        20
    ).ema_indicator()

    df["ema50"] = ta.trend.EMAIndicator(
        df["close"],
        50
    ).ema_indicator()

    df["ema200"] = ta.trend.EMAIndicator(
        df["close"],
        200
    ).ema_indicator()

    df["rsi"] = ta.momentum.RSIIndicator(
        df["close"],
        14
    ).rsi()

    macd = ta.trend.MACD(df["close"])

    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    df["atr"] = ta.volatility.AverageTrueRange(
        df["high"],
        df["low"],
        df["close"],
        14
    ).average_true_range()

    df["adx"] = ta.trend.ADXIndicator(
        df["high"],
        df["low"],
        df["close"],
        14
    ).adx()

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


def prepare(symbol):
    h1 = fetch_history(
        symbol,
        "1h",
        DAYS
    )

    h4 = fetch_history(
        symbol,
        "4h",
        DAYS + 45
    )

    if h1 is None or h4 is None:
        return None

    h1 = add_indicators(h1)
    h4 = add_indicators(h4)

    h1["signal_time"] = (
        h1["datetime"]
        + pd.Timedelta(hours=1)
    )

    h4["available_time"] = (
        h4["datetime"]
        + pd.Timedelta(hours=4)
    )

    h4 = h4[
        [
            "available_time",
            "close",
            "ema20",
            "ema50",
            "ema200",
            "rsi"
        ]
    ].rename(
        columns={
            "close": "close4",
            "ema20": "ema20_4",
            "ema50": "ema50_4",
            "ema200": "ema200_4",
            "rsi": "rsi_4"
        }
    )

    merged = pd.merge_asof(
        h1.sort_values("signal_time"),
        h4.sort_values("available_time"),
        left_on="signal_time",
        right_on="available_time",
        direction="backward"
    )

    return (
        merged
        .dropna()
        .reset_index(drop=True)
    )


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


def score_signal(df, i, side, trend):
    x = df.iloc[i]
    p = df.iloc[i - 1]

    if side == "LONG":
        tests = [
            (trend == "BULLISH", 3),
            (x["close"] > x["ema50"], 1),
            (x["ema20"] > x["ema50"], 1),
            (45 <= x["rsi"] < 70, 1),
            (x["macd"] > x["macd_signal"], 1),
            (x["macd_hist"] > p["macd_hist"], 1),
            (x["adx"] >= MIN_ADX, 1),
            (x["vol_ratio"] >= 0.8, 1)
        ]

    else:
        tests = [
            (trend == "BEARISH", 3),
            (x["close"] < x["ema50"], 1),
            (x["ema20"] < x["ema50"], 1),
            (30 < x["rsi"] <= 55, 1),
            (x["macd"] < x["macd_signal"], 1),
            (x["macd_hist"] < p["macd_hist"], 1),
            (x["adx"] >= MIN_ADX, 1),
            (x["vol_ratio"] >= 0.8, 1)
        ]

    distance = abs(
        x["close"] - x["ema20"]
    ) / x["close"]

    if distance <= 0.015:
        tests.append(
            (True, 1)
        )

    return sum(
        pts
        for ok, pts in tests
        if ok
    )


def levels(df, i, side):
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

        risk = entry - sl

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

        risk = sl - entry

        tps = [
            entry - risk,
            entry - 2 * risk,
            entry - 3 * risk
        ]

    return entry, sl, tps


def find_candidates(symbol, df):
    candidates = []
    active_side = None

    for i in range(
        2,
        len(df) - 1
    ):
        x = df.iloc[i]
        tr = trend4(x)

        side = None
        sc = 0

        if (
            tr == "BULLISH"
            and x["rsi"] < 70
            and x["adx"] >= MIN_ADX
        ):
            sc = score_signal(
                df,
                i,
                "LONG",
                tr
            )

            if sc >= MIN_SCORE:
                side = "LONG"

        elif (
            tr == "BEARISH"
            and x["rsi"] > 30
            and x["adx"] >= MIN_ADX
        ):
            sc = score_signal(
                df,
                i,
                "SHORT",
                tr
            )

            if sc >= MIN_SCORE:
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
            "score": int(sc),
            "rsi": float(x["rsi"]),
            "adx": float(x["adx"]),
            "entry": entry,
            "sl": sl,
            "tps": tps
        })

        active_side = side

    return candidates


def simulate(df, trade):
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
            reason = f"TP{TARGET_NO}"
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
        raw_r
        - cost_r
    )

    return (
        float(net_r),
        exit_i,
        reason
    )


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
            max_dd = max(
                max_dd,
                (
                    peak - equity
                ) / peak * 100
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
    m = calc_metrics(
        results
    )

    print()
    print("=" * 68)
    print(label)
    print("=" * 68)

    if m is None:
        print("NO TRADES")
        return

    if math.isinf(m["pf"]):
        pf_text = "INF"
    else:
        pf_text = f'{m["pf"]:.2f}'

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


def slice_results(
    results,
    start=None,
    end=None
):
    out = results

    if start is not None:
        out = [
            x
            for x in out
            if x["time"] >= start
        ]

    if end is not None:
        out = [
            x
            for x in out
            if x["time"] < end
        ]

    return out


def main():
    print(
        "AI TRADE SCANNER - FINAL VALIDATION"
    )

    print(
        "Period:",
        DAYS,
        "days"
    )

    print(
        "Target: TP2"
    )

    print(
        "Symbols:",
        len(SYMBOLS)
    )

    print(
        "Risk per trade:",
        f"{RISK_PER_TRADE * 100:.2f}%"
    )

    print(
        "Cost assumption:",
        f"{ROUND_TRIP_COST_PCT * 100:.3f}% round trip"
    )

    data = {}
    candidates = []

    for symbol in SYMBOLS:
        print()
        print(
            "Loading",
            symbol
        )

        try:
            df = prepare(
                symbol
            )

            if (
                df is None
                or len(df) < 500
            ):
                print(
                    "Skipped - insufficient data"
                )
                continue

            data[symbol] = df

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
    print(
        "TOTAL CANDIDATES:",
        len(candidates)
    )

    now = pd.Timestamp.now(
        tz="UTC"
    )

    recent_120_start = (
        now
        - pd.Timedelta(
            days=DISCOVERY_DAYS
        )
    )

    variants = [
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

        older_holdout = slice_results(
            results,
            end=recent_120_start
        )

        recent_120 = slice_results(
            results,
            start=recent_120_start
        )

        last_90 = slice_results(
            results,
            start=now - pd.Timedelta(days=90)
        )

        last_30 = slice_results(
            results,
            start=now - pd.Timedelta(days=30)
        )

        print()
        print("#" * 76)
        print(name)
        print("#" * 76)

        print_metrics(
            "FULL 365 DAYS",
            results
        )

        print_metrics(
            "OLDER HOLDOUT - BEFORE RECENT 120 DAYS",
            older_holdout
        )

        print_metrics(
            "RECENT 120 DAYS",
            recent_120
        )

        print_metrics(
            "LAST 90 DAYS",
            last_90
        )

        print_metrics(
            "LAST 30 DAYS",
            last_30
        )

        holdout_m = calc_metrics(
            older_holdout
        )

        full_m = calc_metrics(
            results
        )

        if (
            holdout_m
            and full_m
        ):
            ranking.append({
                "name": name,
                "holdout_trades": holdout_m["trades"],
                "holdout_pf": holdout_m["pf"],
                "holdout_net_r": holdout_m["net_r"],
                "holdout_dd": holdout_m["max_dd"],
                "full_trades": full_m["trades"],
                "full_pf": full_m["pf"],
                "full_net_r": full_m["net_r"]
            })

    print()
    print("#" * 76)
    print(
        "FINAL RANKING - OLDER HOLDOUT FIRST"
    )
    print("#" * 76)

    ranking.sort(
        key=lambda x: (
            x["holdout_net_r"],
            x["holdout_pf"]
        ),
        reverse=True
    )

    for row in ranking:
        if math.isinf(
            row["holdout_pf"]
        ):
            holdout_pf = "INF"
        else:
            holdout_pf = (
                f'{row["holdout_pf"]:.2f}'
            )

        if math.isinf(
            row["full_pf"]
        ):
            full_pf = "INF"
        else:
            full_pf = (
                f'{row["full_pf"]:.2f}'
            )

        print(
            f'{row["name"]} | '
            f'HOLDOUT Trades:{row["holdout_trades"]} | '
            f'PF:{holdout_pf} | '
            f'NetR:{row["holdout_net_r"]:.2f}R | '
            f'DD:{row["holdout_dd"]:.2f}% | '
            f'FULL Trades:{row["full_trades"]} | '
            f'PF:{full_pf} | '
            f'NetR:{row["full_net_r"]:.2f}R'
        )

    print()
    print(
        "FINAL VALIDATION COMPLETED"
    )

    print(
        "Do not update main.py until the older holdout result is checked."
    )


if __name__ == "__main__":
    main()
    

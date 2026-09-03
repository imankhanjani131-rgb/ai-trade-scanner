import time
import ccxt
import pandas as pd
import ta

DAYS = 120
MIN_SCORE = 9
MIN_ADX = 22
MAX_HOLD_HOURS = 72
RISK_PER_TRADE = 0.01

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

    since = (
        exchange.milliseconds()
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

        next_since = batch[-1][0] + ms_per_bar

        if next_since <= since or len(batch) < 1000:
            break

        since = next_since
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
        df["close"], 20
    ).ema_indicator()

    df["ema50"] = ta.trend.EMAIndicator(
        df["close"], 50
    ).ema_indicator()

    df["ema200"] = ta.trend.EMAIndicator(
        df["close"], 200
    ).ema_indicator()

    df["rsi"] = ta.momentum.RSIIndicator(
        df["close"], 14
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
        df["volume"] / df["vol_ma"]
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
        DAYS + 40
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
    ]

    h4 = h4.rename(
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

    points = 0

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
        tests.append((True, 1))

    for ok, pts in tests:
        if ok:
            points += pts

    return points


def levels(df, i, side):
    x = df.iloc[i]

    recent = df.iloc[
        max(0, i - 10):
        i + 1
    ]

    entry = float(x["close"])
    atr = float(x["atr"])

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
            "vol_ratio": float(x["vol_ratio"]),
            "trend": tr,
            "entry": entry,
            "sl": sl,
            "tps": tps
        })

        active_side = side

    return candidates


def simulate(df, trade, target_no):
    entry = trade["entry"]
    sl = trade["sl"]

    tp = trade["tps"][
        target_no - 1
    ]

    risk = abs(
        entry - sl
    )

    end_i = min(
        trade["i"] + MAX_HOLD_HOURS,
        len(df) - 1
    )

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
            return (
                -1.0,
                j,
                "SL-first"
            )

        if hit_sl:
            return (
                -1.0,
                j,
                "SL"
            )

        if hit_tp:
            return (
                float(target_no),
                j,
                f"TP{target_no}"
            )

    exit_price = float(
        df.iloc[end_i]["close"]
    )

    if trade["side"] == "LONG":
        r = (
            exit_price - entry
        ) / risk

    else:
        r = (
            entry - exit_price
        ) / risk

    return (
        float(r),
        end_i,
        "TIME"
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

    flats = sum(
        r == 0
        for r in rs
    )

    gross_win = sum(
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
        pf = gross_win / gross_loss
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

        dd = (
            peak - equity
        ) / peak * 100

        max_dd = max(
            max_dd,
            dd
        )

    return {
        "trades": len(results),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": (
            wins
            / len(results)
            * 100
        ),
        "net_r": sum(rs),
        "avg_r": (
            sum(rs)
            / len(rs)
        ),
        "pf": pf,
        "max_dd": max_dd,
        "ending_equity": equity
    }


def summarize(results, target_no):
    m = calc_metrics(results)

    print(
        "\n"
        + "=" * 48
    )

    print(
        f"BACKTEST RESULT - EXIT AT TP{target_no}"
    )

    print(
        "=" * 48
    )

    if m is None:
        print("No trades")
        return

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
        "Flat:",
        m["flats"]
    )

    print(
        "Win rate:",
        f'{m["win_rate"]:.2f}%'
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
        "Profit factor:",
        f'{m["pf"]:.2f}'
    )

    print(
        "Max drawdown:",
        f'{m["max_dd"]:.2f}%'
    )

    print(
        "Ending equity:",
        f'{m["ending_equity"]:.2f}'
    )

    print(
        "(Equity assumes 1% risk per trade)"
    )


def rsi_bucket(value):
    if value < 40:
        return "RSI <40"

    if value < 50:
        return "RSI 40-49.9"

    if value < 60:
        return "RSI 50-59.9"

    if value < 70:
        return "RSI 60-69.9"

    return "RSI 70+"


def adx_bucket(value):
    if value < 25:
        return "ADX 22-24.9"

    if value < 30:
        return "ADX 25-29.9"

    if value < 40:
        return "ADX 30-39.9"

    return "ADX 40+"


def score_bucket(value):
    if value <= 9:
        return "Score 9"

    if value == 10:
        return "Score 10"

    return "Score 11+"


def print_group_breakdown(
    results,
    key_func,
    title,
    min_trades=1
):
    groups = {}

    for row in results:
        key = key_func(row)

        groups.setdefault(
            key,
            []
        ).append(row)

    rows = []

    for key, items in groups.items():
        m = calc_metrics(items)

        if (
            m
            and m["trades"] >= min_trades
        ):
            rows.append(
                (key, m)
            )

    rows.sort(
        key=lambda x: x[1]["net_r"],
        reverse=True
    )

    print(
        "\n"
        + "-" * 72
    )

    print(title)

    print(
        "-" * 72
    )

    if not rows:
        print("No data")
        return

    for key, m in rows:
        print(
            f"{key:16} | "
            f"T:{m['trades']:3d} | "
            f"WR:{m['win_rate']:6.2f}% | "
            f"PF:{m['pf']:5.2f} | "
            f"NetR:{m['net_r']:7.2f}R | "
            f"AvgR:{m['avg_r']:6.3f}R"
        )


def detailed_tp2_report(results):
    print(
        "\n"
        + "#" * 72
    )

    print(
        "DETAILED TP2 DIAGNOSTICS"
    )

    print(
        "#" * 72
    )

    print_group_breakdown(
        results,
        lambda x: x["side"],
        "LONG vs SHORT"
    )

    print_group_breakdown(
        results,
        lambda x: x["symbol"],
        "PER SYMBOL",
        min_trades=3
    )

    print_group_breakdown(
        results,
        lambda x: rsi_bucket(
            x["rsi"]
        ),
        "RSI BUCKETS"
    )

    print_group_breakdown(
        results,
        lambda x: adx_bucket(
            x["adx"]
        ),
        "ADX BUCKETS"
    )

    print_group_breakdown(
        results,
        lambda x: score_bucket(
            x["score"]
        ),
        "SCORE BUCKETS"
    )


def run_target(
    candidates,
    data,
    target_no
):
    blocked_until = {}
    results = []

    for trade in candidates:
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
            trade,
            target_no
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
            "vol_ratio": trade["vol_ratio"],
            "r": r,
            "exit": reason
        })

    return results


def main():
    print(
        "AI Trade Scanner V2.2 - BACKTEST + DIAGNOSTICS"
    )

    print(
        "Period:",
        DAYS,
        "days"
    )

    print(
        "Symbols:",
        len(SYMBOLS)
    )

    print(
        "Min score:",
        MIN_SCORE
    )

    print(
        "Min ADX:",
        MIN_ADX
    )

    data = {}
    candidates = []

    for symbol in SYMBOLS:
        print(
            "\nLoading",
            symbol
        )

        try:
            df = prepare(symbol)

            if (
                df is None
                or len(df) < 300
            ):
                print(
                    "Skipped - not enough data"
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
                "Candidate signals:",
                len(found)
            )

        except Exception as error:
            print(
                "Error:",
                symbol,
                error
            )

    candidates.sort(
        key=lambda x: x["time"]
    )

    print(
        "\nTotal candidate signals:",
        len(candidates)
    )

    tp2_results = None

    for target_no in (
        1,
        2,
        3
    ):
        results = run_target(
            candidates,
            data,
            target_no
        )

        summarize(
            results,
            target_no
        )

        if target_no == 2:
            tp2_results = results

    if tp2_results is not None:
        detailed_tp2_report(
            tp2_results
        )

    print(
        "\nBacktest completed."
    )


if __name__ == "__main__":
    main()

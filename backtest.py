import time
import math
import requests
import pandas as pd
import ta


# ============================================================
# AI TRADE SCANNER - FINAL 1 YEAR VALIDATION
# Historical data: OKX
# Live robot: TOOBIT
# ============================================================

DAYS = 365
FETCH_DAYS = 405
TEST_DAYS = 90

MIN_SCORE = 9
MIN_ADX = 22

MAX_HOLD_HOURS = 72
RISK_PER_TRADE = 0.01
TARGET_NO = 2

# Fee + slippage assumption
FEE_PER_SIDE = 0.0006
SLIPPAGE_PER_SIDE = 0.0003

ROUND_TRIP_COST_PCT = 2 * (
    FEE_PER_SIDE + SLIPPAGE_PER_SIDE
)

OKX_URL = (
    "https://www.okx.com"
    "/api/v5/market/history-candles"
)

REQUEST_DELAY = 0.12
MAX_PAGES = 120


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


session = requests.Session()

session.headers.update({
    "User-Agent":
        "AI-Trade-Scanner-Backtest/1.0"
})


# ============================================================
# OKX REQUEST
# ============================================================

def okx_request(params):

    last_error = None

    for attempt in range(5):

        try:

            response = session.get(
                OKX_URL,
                params=params,
                timeout=25
            )

            if response.status_code == 429:

                wait = 2 + attempt

                print(
                    f"Rate limit. Waiting {wait}s..."
                )

                time.sleep(wait)

                continue

            response.raise_for_status()

            payload = response.json()

            if payload.get("code") != "0":

                raise RuntimeError(
                    f'OKX code={payload.get("code")} '
                    f'msg={payload.get("msg")}'
                )

            return payload.get(
                "data",
                []
            )

        except Exception as error:

            last_error = error

            if attempt < 4:

                wait = 2 + attempt

                print(
                    f"Request retry "
                    f"{attempt + 1}/5 | {error}"
                )

                time.sleep(wait)

            else:

                break

    raise RuntimeError(
        f"OKX REQUEST FAILED: {last_error}"
    )


# ============================================================
# DOWNLOAD 1H HISTORY
# ============================================================

def fetch_1h_history(symbol):

    inst_id = symbol.replace(
        "/",
        "-"
    )

    now = pd.Timestamp.now(
        tz="UTC"
    )

    start = (
        now
        - pd.Timedelta(
            days=FETCH_DAYS
        )
    )

    start_ms = int(
        start.timestamp() * 1000
    )

    cursor = None
    previous_oldest = None

    rows = []

    print()
    print(
        f"Downloading {symbol}..."
    )

    for page in range(
        1,
        MAX_PAGES + 1
    ):

        params = {
            "instId": inst_id,
            "bar": "1H",
            "limit": "100"
        }

        if cursor is not None:

            params["after"] = str(
                cursor
            )

        batch = okx_request(
            params
        )

        if not batch:

            break

        timestamps = []

        for candle in batch:

            if len(candle) < 6:
                continue

            try:

                ts = int(
                    candle[0]
                )

                confirm = (
                    candle[-1]
                    if len(candle) >= 7
                    else "1"
                )

                # Ignore unfinished candles
                if str(confirm) != "1":
                    continue

                rows.append([
                    ts,
                    float(candle[1]),
                    float(candle[2]),
                    float(candle[3]),
                    float(candle[4]),
                    float(candle[5])
                ])

                timestamps.append(
                    ts
                )

            except Exception:

                continue

        if not timestamps:

            break

        oldest = min(
            timestamps
        )

        newest = max(
            timestamps
        )

        if (
            page == 1
            or page % 10 == 0
        ):

            print(
                f"Page {page} | "
                f"oldest="
                f"{pd.to_datetime(oldest, unit='ms', utc=True)}"
            )

        if oldest <= start_ms:

            break

        if (
            previous_oldest is not None
            and oldest >= previous_oldest
        ):

            print(
                "Pagination stopped: "
                "duplicate data."
            )

            break

        previous_oldest = oldest

        cursor = oldest

        time.sleep(
            REQUEST_DELAY
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
        .drop_duplicates(
            subset=["timestamp"]
        )
        .sort_values(
            "timestamp"
        )
        .reset_index(
            drop=True
        )
    )

    df = df[
        df["timestamp"]
        >= start_ms
    ].copy()

    df["datetime"] = pd.to_datetime(
        df["timestamp"],
        unit="ms",
        utc=True
    )

    if df.empty:

        return None

    coverage = (
        df.iloc[-1]["datetime"]
        - df.iloc[0]["datetime"]
    ).total_seconds() / 86400

    print(
        f"{symbol} | "
        f"1H bars={len(df)} | "
        f"coverage={coverage:.1f} days"
    )

    return df


# ============================================================
# BUILD 4H FROM 1H
# ============================================================

def build_4h(h1):

    x = h1.copy()

    x = x.set_index(
        "datetime"
    )

    h4 = x.resample(
        "4h",
        label="left",
        closed="left",
        origin="epoch"
    ).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "timestamp": "count"
    })

    h4 = h4.rename(
        columns={
            "timestamp":
                "bar_count"
        }
    )

    # Only complete 4H candles
    h4 = h4[
        h4["bar_count"] == 4
    ].copy()

    h4 = h4.drop(
        columns=["bar_count"]
    )

    h4 = h4.reset_index()

    h4["timestamp"] = (
        h4["datetime"]
        .astype("int64")
        // 10**6
    )

    return h4


# ============================================================
# INDICATORS
# ============================================================

def add_indicators(df):

    df = df.copy()

    df["ema20"] = (
        ta.trend.EMAIndicator(
            df["close"],
            window=20
        ).ema_indicator()
    )

    df["ema50"] = (
        ta.trend.EMAIndicator(
            df["close"],
            window=50
        ).ema_indicator()
    )

    df["ema200"] = (
        ta.trend.EMAIndicator(
            df["close"],
            window=200
        ).ema_indicator()
    )

    df["rsi"] = (
        ta.momentum.RSIIndicator(
            df["close"],
            window=14
        ).rsi()
    )

    macd = ta.trend.MACD(
        df["close"]
    )

    df["macd"] = (
        macd.macd()
    )

    df["macd_signal"] = (
        macd.macd_signal()
    )

    df["macd_hist"] = (
        macd.macd_diff()
    )

    df["atr"] = (
        ta.volatility
        .AverageTrueRange(
            df["high"],
            df["low"],
            df["close"],
            window=14
        )
        .average_true_range()
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


# ============================================================
# PREPARE 1H + 4H
# ============================================================

def prepare(symbol):

    h1 = fetch_1h_history(
        symbol
    )

    if (
        h1 is None
        or h1.empty
    ):

        return None

    coverage = (
        h1.iloc[-1]["datetime"]
        - h1.iloc[0]["datetime"]
    ).total_seconds() / 86400

    if coverage < 380:

        print(
            f"{symbol} SKIPPED: "
            f"only {coverage:.1f} days downloaded"
        )

        return None

    h4 = build_4h(
        h1
    )

    if h4.empty:

        return None

    h1 = add_indicators(
        h1
    )

    h4 = add_indicators(
        h4
    )

    # 1H candle is usable after close
    h1["signal_time"] = (
        h1["datetime"]
        + pd.Timedelta(
            hours=1
        )
    )

    # 4H candle only usable after close
    h4["available_time"] = (
        h4["datetime"]
        + pd.Timedelta(
            hours=4
        )
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
            "close":
                "close4",
            "ema20":
                "ema20_4",
            "ema50":
                "ema50_4",
            "ema200":
                "ema200_4",
            "rsi":
                "rsi_4"
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
        .reset_index(
            drop=True
        )
    )

    if merged.empty:

        return None

    end_time = (
        merged.iloc[-1][
            "signal_time"
        ]
    )

    cutoff = (
        end_time
        - pd.Timedelta(
            days=DAYS
        )
    )

    merged = merged[
        merged["signal_time"]
        >= cutoff
    ].copy()

    merged = (
        merged
        .reset_index(
            drop=True
        )
    )

    usable_coverage = (
        merged.iloc[-1][
            "signal_time"
        ]
        - merged.iloc[0][
            "signal_time"
        ]
    ).total_seconds() / 86400

    print(
        f"{symbol} usable "
        f"coverage="
        f"{usable_coverage:.1f} days"
    )

    if usable_coverage < 350:

        print(
            f"{symbol} SKIPPED: "
            "less than 350 usable days"
        )

        return None

    return merged


# ============================================================
# 4H TREND
# ============================================================

def trend4(row):

    if (
        row["close4"]
        > row["ema200_4"]
        and row["ema20_4"]
        > row["ema50_4"]
        and row["ema50_4"]
        > row["ema200_4"]
        and row["rsi_4"] >= 50
    ):

        return "BULLISH"

    if (
        row["close4"]
        < row["ema200_4"]
        and row["ema20_4"]
        < row["ema50_4"]
        and row["ema50_4"]
        < row["ema200_4"]
        and row["rsi_4"] <= 50
    ):

        return "BEARISH"

    return "NEUTRAL"


# ============================================================
# SCORE
# ============================================================

def score_signal(
    df,
    i,
    side,
    trend
):

    x = df.iloc[i]

    p = df.iloc[
        i - 1
    ]

    if side == "LONG":

        tests = [
            (
                trend == "BULLISH",
                3
            ),
            (
                x["close"]
                > x["ema50"],
                1
            ),
            (
                x["ema20"]
                > x["ema50"],
                1
            ),
            (
                45
                <= x["rsi"]
                < 70,
                1
            ),
            (
                x["macd"]
                > x["macd_signal"],
                1
            ),
            (
                x["macd_hist"]
                > p["macd_hist"],
                1
            ),
            (
                x["adx"]
                >= MIN_ADX,
                1
            ),
            (
                x["vol_ratio"]
                >= 0.8,
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
                x["close"]
                < x["ema50"],
                1
            ),
            (
                x["ema20"]
                < x["ema50"],
                1
            ),
            (
                30
                < x["rsi"]
                <= 55,
                1
            ),
            (
                x["macd"]
                < x["macd_signal"],
                1
            ),
            (
                x["macd_hist"]
                < p["macd_hist"],
                1
            ),
            (
                x["adx"]
                >= MIN_ADX,
                1
            ),
            (
                x["vol_ratio"]
                >= 0.8,
                1
            )
        ]

    distance = (
        abs(
            x["close"]
            - x["ema20"]
        )
        / x["close"]
    )

    if distance <= 0.015:

        tests.append(
            (
                True,
                1
            )
        )

    return sum(
        points
        for ok, points
        in tests
        if ok
    )


# ============================================================
# ENTRY / SL / TARGET
# ============================================================

def levels(
    df,
    i,
    side
):

    x = df.iloc[i]

    recent = df.iloc[
        max(
            0,
            i - 10
        ):
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
            recent[
                "low"
            ].min()
        )

        sl = min(
            entry
            - 1.5 * atr,
            swing
            - 0.2 * atr
        )

        risk = (
            entry - sl
        )

        tps = [
            entry
            + risk,
            entry
            + 2 * risk,
            entry
            + 3 * risk
        ]

    else:

        swing = float(
            recent[
                "high"
            ].max()
        )

        sl = max(
            entry
            + 1.5 * atr,
            swing
            + 0.2 * atr
        )

        risk = (
            sl - entry
        )

        tps = [
            entry
            - risk,
            entry
            - 2 * risk,
            entry
            - 3 * risk
        ]

    return (
        entry,
        sl,
        tps
    )


# ============================================================
# FIND CANDIDATES
# ============================================================

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

        trend = trend4(
            x
        )

        side = None
        score = 0

        if (
            trend == "BULLISH"
            and x["rsi"] < 70
            and x["adx"]
            >= MIN_ADX
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
            and x["adx"]
            >= MIN_ADX
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
            "symbol":
                symbol,
            "i":
                i,
            "time":
                x["signal_time"],
            "side":
                side,
            "score":
                int(score),
            "rsi":
                float(x["rsi"]),
            "adx":
                float(x["adx"]),
            "entry":
                entry,
            "sl":
                sl,
            "tps":
                tps
        })

        active_side = side

    return candidates


# ============================================================
# SIMULATE
# ============================================================

def simulate(
    df,
    trade
):

    entry = trade[
        "entry"
    ]

    sl = trade[
        "sl"
    ]

    tp = trade[
        "tps"
    ][
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
        trade["i"]
        + MAX_HOLD_HOURS,
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

        if (
            trade["side"]
            == "LONG"
        ):

            hit_sl = (
                bar["low"]
                <= sl
            )

            hit_tp = (
                bar["high"]
                >= tp
            )

        else:

            hit_sl = (
                bar["high"]
                >= sl
            )

            hit_tp = (
                bar["low"]
                <= tp
            )

        # Conservative:
        # if SL and TP touch
        # in same candle,
        # count SL first.

        if hit_sl and hit_tp:

            raw_r = -1.0

            exit_i = j

            reason = (
                "SL-FIRST"
            )

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
            df.iloc[
                end_i
            ]["close"]
        )

        if (
            trade["side"]
            == "LONG"
        ):

            raw_r = (
                exit_price
                - entry
            ) / risk

        else:

            raw_r = (
                entry
                - exit_price
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


# ============================================================
# VARIANT
# ============================================================

def run_variant(
    candidates,
    data,
    condition
):

    results = []

    blocked_until = {}

    for trade in candidates:

        if not condition(
            trade
        ):

            continue

        symbol = trade[
            "symbol"
        ]

        if (
            trade["i"]
            <= blocked_until.get(
                symbol,
                -1
            )
        ):

            continue

        r, exit_i, reason = (
            simulate(
                data[symbol],
                trade
            )
        )

        blocked_until[
            symbol
        ] = exit_i

        results.append({
            "symbol":
                symbol,
            "time":
                trade["time"],
            "side":
                trade["side"],
            "score":
                trade["score"],
            "rsi":
                trade["rsi"],
            "adx":
                trade["adx"],
            "r":
                r,
            "exit":
                reason
        })

    return sorted(
        results,
        key=lambda x:
            x["time"]
    )


# ============================================================
# METRICS
# ============================================================

def calc_metrics(
    results
):

    if not results:

        return None

    rs = [
        row["r"]
        for row
        in results
    ]

    wins = sum(
        r > 0
        for r
        in rs
    )

    losses = sum(
        r < 0
        for r
        in rs
    )

    gross_profit = sum(
        r
        for r
        in rs
        if r > 0
    )

    gross_loss = abs(
        sum(
            r
            for r
            in rs
            if r < 0
        )
    )

    if gross_loss > 0:

        pf = (
            gross_profit
            / gross_loss
        )

    else:

        pf = float(
            "inf"
        )

    equity = 100.0
    peak = 100.0
    max_dd = 0.0

    for r in rs:

        equity *= (
            1
            + RISK_PER_TRADE
            * r
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
        "trades":
            len(rs),

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            wins
            / len(rs)
            * 100,

        "pf":
            pf,

        "net_r":
            sum(rs),

        "avg_r":
            sum(rs)
            / len(rs),

        "max_dd":
            max_dd,

        "equity":
            equity
    }


def pf_text(value):

    if math.isinf(
        value
    ):

        return "INF"

    return (
        f"{value:.2f}"
    )


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
        pf_text(
            m["pf"]
        )
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


# ============================================================
# TIME SLICE
# ============================================================

def slice_results(
    results,
    start=None,
    end=None
):

    output = results

    if start is not None:

        output = [
            x
            for x
            in output
            if x["time"]
            >= start
        ]

    if end is not None:

        output = [
            x
            for x
            in output
            if x["time"]
            < end
        ]

    return output


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)

    print(
        "AI TRADE SCANNER - "
        "FINAL OKX 1 YEAR VALIDATION"
    )

    print("=" * 80)

    print(
        "Historical source: OKX"
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
        "Target: TP2"
    )

    print(
        "Risk per trade:",
        f"{RISK_PER_TRADE * 100:.2f}%"
    )

    print(
        "Round-trip cost:",
        f"{ROUND_TRIP_COST_PCT * 100:.3f}%"
    )

    print(
        "Requested symbols:",
        len(SYMBOLS)
    )

    data = {}

    candidates = []

    usable_symbols = []

    for n, symbol in enumerate(
        SYMBOLS,
        start=1
    ):

        print()
        print("#" * 80)

        print(
            f"[{n}/{len(SYMBOLS)}] "
            f"LOADING {symbol}"
        )

        print("#" * 80)

        try:

            df = prepare(
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
        key=lambda x:
            x["time"]
    )

    print()
    print("=" * 80)
    print(
        "DOWNLOAD FINISHED"
    )
    print("=" * 80)

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
            "NO CANDIDATES. "
            "VALIDATION STOPPED."
        )

        return

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

    variants = [

        (
            "A - CURRENT LONG + SHORT",

            lambda t:
                True
        ),

        (
            "B - LONG ONLY",

            lambda t:
                t["side"]
                == "LONG"
        ),

        (
            "C - LONG + ADX >= 40",

            lambda t:
                t["side"]
                == "LONG"
                and t["adx"]
                >= 40
        ),

        (
            "D - LONG + ADX >= 40 "
            "+ RSI 60-70",

            lambda t:
                t["side"]
                == "LONG"
                and t["adx"]
                >= 40
                and 60
                <= t["rsi"]
                < 70
        ),

        (
            "E - LONG + ADX >= 40 "
            "+ RSI 60-70 + SCORE 9",

            lambda t:
                t["side"]
                == "LONG"
                and t["adx"]
                >= 40
                and 60
                <= t["rsi"]
                < 70
                and t["score"]
                == 9
        ),
    ]

    ranking = []

    for name, condition in variants:

        all_results = run_variant(
            candidates,
            data,
            condition
        )

        full_results = (
            slice_results(
                all_results,
                start=
                    validation_start,
                end=
                    validation_end
            )
        )

        older_results = (
            slice_results(
                full_results,
                end=
                    recent_start
            )
        )

        recent_results = (
            slice_results(
                full_results,
                start=
                    recent_start
            )
        )

        last30_results = (
            slice_results(
                full_results,
                start=
                    last30_start
            )
        )

        print()
        print("#" * 80)
        print(name)
        print("#" * 80)

        print_metrics(
            "FULL 365 DAYS",
            full_results
        )

        print_metrics(
            "OLDER HOLDOUT - "
            "FIRST 275 DAYS",
            older_results
        )

        print_metrics(
            "RECENT TEST - "
            "LAST 90 DAYS",
            recent_results
        )

        print_metrics(
            "LAST 30 DAYS",
            last30_results
        )

        old_m = calc_metrics(
            older_results
        )

        recent_m = calc_metrics(
            recent_results
        )

        full_m = calc_metrics(
            full_results
        )

        if (
            old_m is not None
            and recent_m is not None
            and full_m is not None
        ):

            ranking.append({
                "name":
                    name,

                "old_trades":
                    old_m["trades"],

                "old_wr":
                    old_m["win_rate"],

                "old_pf":
                    old_m["pf"],

                "old_net":
                    old_m["net_r"],

                "old_dd":
                    old_m["max_dd"],

                "recent_trades":
                    recent_m["trades"],

                "recent_wr":
                    recent_m["win_rate"],

                "recent_pf":
                    recent_m["pf"],

                "recent_net":
                    recent_m["net_r"],

                "recent_dd":
                    recent_m["max_dd"],

                "full_trades":
                    full_m["trades"],

                "full_wr":
                    full_m["win_rate"],

                "full_pf":
                    full_m["pf"],

                "full_net":
                    full_m["net_r"],

                "full_dd":
                    full_m["max_dd"]
            })

    print()
    print("#" * 80)
    print(
        "FINAL RANKING - "
        "TRUE OLDER HOLDOUT"
    )
    print("#" * 80)

    ranking.sort(
        key=lambda row: (
            row["old_net"],
            row["old_pf"],
            row["recent_net"]
        ),
        reverse=True
    )

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
            f'OLDER | '
            f'Trades:{row["old_trades"]} | '
            f'WR:{row["old_wr"]:.2f}% | '
            f'PF:{pf_text(row["old_pf"])} | '
            f'NetR:{row["old_net"]:.2f}R | '
            f'DD:{row["old_dd"]:.2f}%'
        )

        print(
            f'RECENT90 | '
            f'Trades:{row["recent_trades"]} | '
            f'WR:{row["recent_wr"]:.2f}% | '
            f'PF:{pf_text(row["recent_pf"])} | '
            f'NetR:{row["recent_net"]:.2f}R | '
            f'DD:{row["recent_dd"]:.2f}%'
        )

        print(
            f'FULL365 | '
            f'Trades:{row["full_trades"]} | '
            f'WR:{row["full_wr"]:.2f}% | '
            f'PF:{pf_text(row["full_pf"])} | '
            f'NetR:{row["full_net"]:.2f}R | '
            f'DD:{row["full_dd"]:.2f}%'
        )

    print()
    print("=" * 80)

    print(
        "FINAL OKX VALIDATION COMPLETED"
    )

    print("=" * 80)

    print(
        "NEXT STEP: "
        "REVIEW FINAL RANKING "
        "THEN BUILD FINAL main.py"
    )


if __name__ == "__main__":
    main()

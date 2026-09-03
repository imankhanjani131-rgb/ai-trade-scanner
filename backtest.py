import time
import ccxt
import pandas as pd


DAYS = 365

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
    "TRX/USDT"
]


exchange = ccxt.toobit({
    "enableRateLimit": True,
    "timeout": 20000
})


def fetch_history(symbol, timeframe, days):
    now_ms = exchange.milliseconds()

    since = (
        now_ms
        - days * 24 * 60 * 60 * 1000
    )

    rows = []
    page = 0
    last_timestamp = None

    print()
    print(
        f"Fetching {symbol} {timeframe}..."
    )

    while page < 30:
        page += 1

        try:
            batch = exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                since=since,
                limit=1000
            )

        except Exception as error:
            print(
                "FETCH ERROR:",
                error
            )
            break

        if not batch:
            print(
                "No more candles returned."
            )
            break

        first_ts = batch[0][0]
        final_ts = batch[-1][0]

        print(
            f"Page {page} | "
            f"candles={len(batch)} | "
            f"first={pd.to_datetime(first_ts, unit='ms', utc=True)} | "
            f"last={pd.to_datetime(final_ts, unit='ms', utc=True)}"
        )

        rows.extend(batch)

        if (
            last_timestamp is not None
            and final_ts <= last_timestamp
        ):
            print(
                "Stopped: exchange returned duplicate/old data."
            )
            break

        last_timestamp = final_ts

        next_since = final_ts + 1

        if next_since >= now_ms:
            break

        since = next_since

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

    return df


def report(symbol, timeframe, df):
    print()
    print("=" * 70)
    print(
        symbol,
        timeframe
    )
    print("=" * 70)

    if df is None or df.empty:
        print(
            "NO DATA"
        )
        return

    first_date = df.iloc[0]["datetime"]
    last_date = df.iloc[-1]["datetime"]

    coverage = (
        last_date - first_date
    ).total_seconds() / 86400

    requested_start = (
        pd.Timestamp.now(tz="UTC")
        - pd.Timedelta(days=DAYS)
    )

    print(
        "Candles:",
        len(df)
    )

    print(
        "Requested start:",
        requested_start
    )

    print(
        "Actual first candle:",
        first_date
    )

    print(
        "Actual last candle:",
        last_date
    )

    print(
        "Actual coverage:",
        f"{coverage:.1f} days"
    )

    if coverage >= 330:
        print(
            "STATUS: GOOD - approximately 1 year available"
        )

    elif coverage >= 200:
        print(
            "STATUS: PARTIAL - more than 200 days available"
        )

    elif coverage >= 100:
        print(
            "STATUS: LIMITED - only around 100-200 days available"
        )

    else:
        print(
            "STATUS: VERY LIMITED - less than 100 days available"
        )


def main():
    print("=" * 70)
    print(
        "TOOBIT HISTORICAL DATA DIAGNOSTIC"
    )
    print("=" * 70)

    print(
        "Requested history:",
        DAYS,
        "days"
    )

    print(
        "Symbols:",
        len(SYMBOLS)
    )

    summary = []

    for symbol in SYMBOLS:
        print()
        print("#" * 70)
        print(
            "CHECKING:",
            symbol
        )
        print("#" * 70)

        try:
            h1 = fetch_history(
                symbol,
                "1h",
                DAYS
            )

            report(
                symbol,
                "1H",
                h1
            )

            h4 = fetch_history(
                symbol,
                "4h",
                DAYS + 50
            )

            report(
                symbol,
                "4H",
                h4
            )

            if (
                h1 is not None
                and not h1.empty
            ):
                days_1h = (
                    h1.iloc[-1]["datetime"]
                    - h1.iloc[0]["datetime"]
                ).total_seconds() / 86400

            else:
                days_1h = 0

            if (
                h4 is not None
                and not h4.empty
            ):
                days_4h = (
                    h4.iloc[-1]["datetime"]
                    - h4.iloc[0]["datetime"]
                ).total_seconds() / 86400

            else:
                days_4h = 0

            summary.append({
                "symbol": symbol,
                "days_1h": days_1h,
                "days_4h": days_4h,
                "bars_1h": 0 if h1 is None else len(h1),
                "bars_4h": 0 if h4 is None else len(h4)
            })

        except Exception as error:
            print(
                "ERROR:",
                symbol,
                error
            )

    print()
    print("#" * 70)
    print(
        "FINAL DATA COVERAGE SUMMARY"
    )
    print("#" * 70)

    for row in summary:
        print(
            f'{row["symbol"]} | '
            f'1H:{row["days_1h"]:.1f} days '
            f'({row["bars_1h"]} bars) | '
            f'4H:{row["days_4h"]:.1f} days '
            f'({row["bars_4h"]} bars)'
        )

    print()
    print(
        "DIAGNOSTIC COMPLETED"
    )


if __name__ == "__main__":
    main()

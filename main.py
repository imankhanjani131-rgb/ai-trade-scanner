import os
import time
import requests
import ccxt
import pandas as pd
import ta

# CONFIGURATION
TELEGRAM_BOT_TOKEN = "7963493206:AAH5Z_0V0moxXh807r94rX0t_k3Kk4uPq7Q"
TELEGRAM_CHAT_ID = "6175027599"

SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOGE/USDT', 'DOT/USDT', 'LINK/USDT',
    'NEAR/USDT', 'LTC/USDT', 'SHIB/USDT', 'SUI/USDT', 'PEPE/USDT',
    'APT/USDT', 'FET/USDT', 'RENDER/USDT', 'TON/USDT', 'TRX/USDT'
]

TIMEFRAME = '15m'
CHECK_INTERVAL_SECONDS = 300

exchange = ccxt.binance({'enableRateLimit': True})

def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"Error sending telegram message: {e}")
        return False

def fetch_data(symbol: str):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        print(f"Fetch error for {symbol}: {e}")
        return None

def analyze_symbol(symbol: str):
    df = fetch_data(symbol)
    if df is None or len(df) < 50:
        return

    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    df['ema_fast'] = ta.trend.EMAIndicator(df['close'], window=20).ema_indicator()
    df['ema_slow'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
    macd = ta.trend.MACD(df['close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()

    curr = df.iloc[-1]
    prev = df.iloc[-2]
    price = curr['close']
    atr = curr['atr']

    buy_cond = (
        curr['rsi'] < 38 and
        curr['ema_fast'] > curr['ema_slow'] and
        curr['macd'] > curr['macd_signal'] and
        prev['macd'] <= prev['macd_signal']
    )

    sell_cond = (
        curr['rsi'] > 62 and
        curr['ema_fast'] < curr['ema_slow'] and
        curr['macd'] < curr['macd_signal'] and
        prev['macd'] >= prev['macd_signal']
    )

    if buy_cond:
        sl = price - (1.5 * atr)
        tp = price + (3.0 * atr)
        msg = (
            f"🟢 <b>BUY SIGNAL</b>\n\n"
            f"🔹 <b>Pair:</b> #{symbol.replace('/USDT', '')}\n"
            f"⏱ <b>Timeframe:</b> {TIMEFRAME}\n"
            f"💵 <b>Entry:</b> {price:,.4f}\n"
            f"🛑 <b>SL:</b> {sl:,.4f}\n"
            f"🎯 <b>TP:</b> {tp:,.4f}\n"
            f"📊 <b>RSI:</b> {curr['rsi']:.1f}\n"
            f"⚖️ <b>Risk/Reward:</b> 1:2"
        )
        send_telegram_message(msg)

    elif sell_cond:
        sl = price + (1.5 * atr)
        tp = price - (3.0 * atr)
        msg = (
            f"🔴 <b>SELL SIGNAL</b>\n\n"
            f"🔹 <b>Pair:</b> #{symbol.replace('/USDT', '')}\n"
            f"⏱ <b>Timeframe:</b> {TIMEFRAME}\n"
            f"💵 <b>Entry:</b> {price:,.4f}\n"
            f"🛑 <b>SL:</b> {sl:,.4f}\n"
            f"🎯 <b>TP:</b> {tp:,.4f}\n"
            f"📊 <b>RSI:</b> {curr['rsi']:.1f}\n"
            f"⚖️ <b>Risk/Reward:</b> 1:2"
        )
        send_telegram_message(msg)

def main():
    print("Bot started running 24/7...")
    send_telegram_message("🤖 <b>Scanner Bot Started!</b>\nMonitoring Top 20 crypto pairs 24/7.")
    
    while True:
        try:
            for sym in SYMBOLS:
                analyze_symbol(sym)
                time.sleep(0.5)
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         

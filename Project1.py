import requests
import pandas as pd
import numpy as np
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

# =====================================
# NSE SESSION SETUP
# =====================================

BASE_URL = "https://www.nseindia.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br"
}

session = requests.Session()
session.headers.update(HEADERS)
session.get(BASE_URL)  # Initialize cookies


# =====================================
# GET LIVE NSE TOP GAINERS
# =====================================

def get_top_gainers(limit=15):
    url = BASE_URL + "/api/live-analysis-variations?index=gainers"
    try:
        response = session.get(url, timeout=10)
        if response.status_code != 200:
            raise RuntimeError(f"Bad status: {response.status_code}")

        data = response.json()
        df = pd.DataFrame(data.get("data", []))

        if df.empty:
            raise RuntimeError("Empty data from NSE API")

        df = df.sort_values(by="pChange", ascending=False)
        symbols = df["symbol"].tolist()[:limit]

        # Convert to Yahoo format
        yahoo_symbols = [s + ".NS" for s in symbols]
        return yahoo_symbols

    except Exception as e:
        # Fallback demo list when NSE API is blocked or fails
        print("NSE API blocked or failed; using demo list.", e)
        demo = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
        return demo[:limit]


# =====================================
# FADE ANALYSIS USING YAHOO
# =====================================

def analyze(stock):

    try:
        df = yf.download(stock, period="3d", interval="5m", progress=False)

        if len(df) < 30:
            return None

        df["typ"] = (df["High"] + df["Low"] + df["Close"]) / 3
        df["vwap"] = (df["typ"] * df["Volume"]).cumsum() / df["Volume"].cumsum()
        df["vwap_dist"] = (df["Close"] - df["vwap"]) / df["vwap"]

        df["rsi"] = RSIIndicator(df["Close"],14).rsi()
        df["atr"] = AverageTrueRange(
            df["High"], df["Low"], df["Close"],14
        ).average_true_range()

        latest = df.iloc[-1]

        overext = latest["vwap_dist"] + (latest["rsi"]/100)
        vol_spike = latest["Volume"] / df["Volume"].rolling(20).mean().iloc[-1]
        risk = latest["atr"] / latest["Close"]

        fade_score = (0.4*overext + 0.4*vol_spike) - (0.2*risk)

        entry = latest["Close"]
        stop = entry + latest["atr"]
        target = entry - 1.5*latest["atr"]

        return {
            "symbol": stock,
            "score": round(fade_score,4),
            "entry": round(entry,2),
            "stop": round(stop,2),
            "target": round(target,2)
        }

    except:
        return None


# =====================================
# RUN SCAN
# =====================================

def run():

    print("Fetching NSE Top Gainers...")
    gainers = get_top_gainers()

    if not gainers:
        print("No gainers found.")
        return

    results = []

    for stock in gainers:
        r = analyze(stock)
        if r:
            results.append(r)

    results = sorted(results, key=lambda x: x["score"], reverse=True)

    print("\n🔥 Top Fade Setups:")
    for r in results[:3]:
        print(r)


if __name__ == "__main__":
    run()

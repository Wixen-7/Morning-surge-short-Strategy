import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from ta.momentum import RSIIndicator
from ta.trend import MACD

st.title("📈 Stock Market Dashboard")

ticker = st.text_input("Enter Stock Symbol", "RELIANCE.NS")

data = yf.download(ticker, period="6mo", interval="1d")

if not data.empty:

    # Flatten MultiIndex columns returned by yfinance to single level
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    # Moving Averages
    data["MA20"] = data["Close"].rolling(window=20).mean()
    data["MA50"] = data["Close"].rolling(window=50).mean()

    # RSI
    # Ensure Close is a 1-D numeric Series for TA calculations
    close_series = pd.to_numeric(data["Close"].squeeze(), errors="coerce")
    rsi = RSIIndicator(close_series)
    data["RSI"] = rsi.rsi()

    # MACD
    macd = MACD(close_series)
    data["MACD"] = macd.macd()
    data["MACD_signal"] = macd.macd_signal()

    # Price Chart
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data.index, y=data["Close"], name="Close"))
    fig.add_trace(go.Scatter(x=data.index, y=data["MA20"], name="MA20"))
    fig.add_trace(go.Scatter(x=data.index, y=data["MA50"], name="MA50"))

    st.plotly_chart(fig)

    # RSI Chart
    st.subheader("RSI")
    st.line_chart(data["RSI"])

    # MACD Chart
    st.subheader("MACD")
    st.line_chart(data[["MACD", "MACD_signal"]])


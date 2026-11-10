import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta, time
import pytz
from astro_engine import (
    resolve_location, datetime_to_jd, calculate_natal_chart,
    get_natal_moon, get_active_dashas, evaluate_slot_trend, PLANET_ORDER
)

st.set_page_config(
    page_title="NSE Natal Dasha Predictor",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Stock Price Trend Predictor (Vimshottari Deha Dasha & Natal Lordships)")
st.caption("Intraday 30-minute trend engine mapped down to Level 6 (Deha Dasha) with live NSE market candles.")

# ----------------- SIDEBAR: INPUT FORM -----------------
with st.sidebar:
    st.header("🏢 Company Natal Configuration")
    
    preset = st.selectbox(
        "Load Preset Profile",
        ["Custom", "Reliance Industries (NSE)", "Tata Consultancy Services (NSE)"]
    )
    
    if preset == "Reliance Industries (NSE)":
        default_ticker = "RELIANCE.NS"
        default_dob = datetime(1973, 5, 8).date()
        default_tob = time(10, 0, 0)
        default_pob = "Mumbai, India"
    elif preset == "Tata Consultancy Services (NSE)":
        default_ticker = "TCS.NS"
        default_dob = datetime(1968, 4, 1).date()
        default_tob = time(9, 30, 0)
        default_pob = "Mumbai, India"
    else:
        default_ticker = "INFY.NS"
        default_dob = datetime(1981, 7, 2).date()
        default_tob = time(9, 15, 0)
        default_pob = "Pune, India"

    ticker = st.text_input("NSE Ticker (Yahoo format)", value=default_ticker)
    dob = st.date_input("Incorporation / Listing Date", value=default_dob)
    tob = st.time_input("Birth / Listing Time (IST)", value=default_tob)
    pob = st.text_input("Place of Birth / Head Office", value=default_pob)
    
    st.markdown("---")
    st.header("📅 Evaluation Day")
    # Default to yesterday to avoid future date issues
    eval_date = st.date_input("Trading Date", value=(datetime.now() - timedelta(days=1)).date())
    run_btn = st.button("Run Intraday Analysis", type="primary")

# ----------------- MAIN EXECUTION -----------------
if run_btn or 'analyzed' in st.session_state:
    st.session_state['analyzed'] = True
    ist_tz = pytz.timezone("Asia/Kolkata")
    
    # Coordinates & Natal UTC
    lat, lon, place_resolved = resolve_location(pob)
    local_birth_dt = ist_tz.localize(datetime.combine(dob, tob))
    utc_birth_dt = local_birth_dt.astimezone(pytz.utc)
    jd_birth = datetime_to_jd(utc_birth_dt)
    
    # Chart Calculations
    lagna_sign, asc_lon, planet_scores, ownership = calculate_natal_chart(jd_birth, lat, lon)
    first_lord, balance_days, start_idx = get_natal_moon(jd_birth)

    # 1. Top Level Metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Ascendant (Lagna)", f"{asc_lon:.2f}° (Sign {lagna_sign})")
    col2.metric("Balance of Dasha", f"{first_lord} ({balance_days/365.25:.2f}y)")
    col3.metric("Resolved Location", place_resolved.split(",")[0])
    col4.metric("Evaluation Date", eval_date.strftime("%d-%b-%Y"))

    # 2. Market Windows Loop (09:15 to 15:30 IST)
    market_start = ist_tz.localize(datetime.combine(eval_date, time(9, 15)))
    market_close = ist_tz.localize(datetime.combine(eval_date, time(15, 30)))
    
    records = []
    slot_cur = market_start
    while slot_cur < market_close:
        slot_end = min(slot_cur + timedelta(minutes=30), market_close)
        mid = slot_cur + (slot_end - slot_cur) / 2
        
        dashas = get_active_dashas(mid, local_birth_dt, first_lord, balance_days, start_idx)
        score, sentiment = evaluate_slot_trend(dashas, planet_scores)
        
        records.append({
            "Slot Start": slot_cur,
            "Slot End": slot_end,
            "Time Window": f"{slot_cur.strftime('%H:%M')} - {slot_end.strftime('%H:%M')}",
            "Mahadasha": dashas[0],
            "Antardasha": dashas[1],
            "Pratyantardasha": dashas[2],
            "Sookshma": dashas[3],
            "Prana Lord": dashas[4],
            "Deha Lord": dashas[5],
            "Composite Score": round(score, 2),
            "Astrological Sentiment": sentiment
        })
        slot_cur = slot_end
        
    df_predictions = pd.DataFrame(records)

    # 3. Pull Live Market Data via yfinance
    candles = pd.DataFrame()
    try:
        start_fetch = eval_date - timedelta(days=2)
        end_fetch = eval_date + timedelta(days=2)
        
        df_yf = yf.download(
            tickers=ticker.strip(),
            start=start_fetch.strftime("%Y-%m-%d"),
            end=end_fetch.strftime("%Y-%m-%d"),
            interval="30m",
            progress=False
        )
        
        if not df_yf.empty:
            if isinstance(df_yf.columns, pd.MultiIndex):
                df_yf.columns = df_yf.columns.get_level_values(0)

            if df_yf.index.tz is None:
                df_yf.index = df_yf.index.tz_localize("UTC").tz_convert(ist_tz)
            else:
                df_yf.index = df_yf.index.tz_convert(ist_tz)

            candles = df_yf[df_yf.index.date == eval_date].copy()
            if candles.empty:
                st.warning(f"No trading candle data for {ticker} on {eval_date}. Markets were closed (weekend/holiday).")
        else:
            st.warning(f"No data returned for '{ticker}'. Please ensure it is a valid Yahoo Finance ticker (e.g. RELIANCE.NS).")
    except Exception as e:
        st.error(f"Error fetching candle data: {e}")

    # 4. Merge Candles & Accuracy Check
    if not candles.empty:
        merged = []
        hits = 0
        scored_bars = 0
        
        for _, row in df_predictions.iterrows():
            slot_s = row["Slot Start"]
            slot_e = row["Slot End"]
            
            # Find candle falling within ±5 min tolerance of the slot start
            matched_candle = candles[
                (candles.index >= slot_s - timedelta(minutes=5)) & 
                (candles.index < slot_e - timedelta(minutes=5))
            ]
            
            if not matched_candle.empty:
                op = float(matched_candle["Open"].iloc[0])
                cl = float(matched_candle["Close"].iloc[0])
                ret = ((cl - op) / op) * 100.0
                
                if ret > 0.05:
                    actual_dir = "BULLISH"
                elif ret < -0.05:
                    actual_dir = "BEARISH"
                else:
                    actual_dir = "NEUTRAL"
                
                pred_sent = row["Astrological Sentiment"]
                if "BULLISH" in pred_sent and actual_dir == "BULLISH":
                    validation = "HIT ✅"
                    hits += 1
                    scored_bars += 1
                elif "BEARISH" in pred_sent and actual_dir == "BEARISH":
                    validation = "HIT ✅"
                    hits += 1
                    scored_bars += 1
                elif pred_sent == "NEUTRAL" or actual_dir == "NEUTRAL":
                    validation = "SKIP ⚪"
                else:
                    validation = "MISS ❌"
                    scored_bars += 1

                row["Open Price"] = f"₹{op:,.2f}"
                row["Close Price"] = f"₹{cl:,.2f}"
                row["Actual Return (%)"] = f"{ret:+.2f}%"
                row["Market Actual"] = actual_dir
                row["Validation"] = validation
            else:
                row["Open Price"] = "-"
                row["Close Price"] = "-"
                row["Actual Return (%)"] = "-"
                row["Market Actual"] = "NO CANDLE"
                row["Validation"] = "SKIP ⚪"
                
            merged.append(row)
            
        display_df = pd.DataFrame(merged)
        
        # Accuracy Metrics
        st.subheader("🎯 Backtest Performance")
        b1, b2, b3 = st.columns(3)
        b1.metric("Evaluated Slots", scored_bars)
        b2.metric("Directional Hits", hits)
        hit_ratio = (hits / scored_bars * 100) if scored_bars > 0 else 0.0
        b3.metric("Directional Hit Rate", f"{hit_ratio:.1f}%" if scored_bars > 0 else "N/A")

        # Interactive Candlestick Chart
        st.subheader(f"📊 {ticker} 30-Minute Price Action")
        fig = go.Figure(data=[go.Candlestick(
            x=pd.to_datetime(candles.index).strftime('%H:%M'),
            open=candles['Open'], high=candles['High'],
            low=candles['Low'], close=candles['Close'],
            name=ticker
        )])
        fig.update_layout(xaxis_rangeslider_visible=False, height=350, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        display_df = df_predictions

    # 5. Output Table
    st.subheader("📋 Intraday 30-Minute Predictions & Dasha Table")
    columns_to_show = [
        "Time Window", "Prana Lord", "Deha Lord", "Composite Score",
        "Astrological Sentiment"
    ]
    if not candles.empty:
        columns_to_show += ["Open Price", "Close Price", "Actual Return (%)", "Market Actual", "Validation"]

    st.dataframe(display_df[columns_to_show], use_container_width=True)
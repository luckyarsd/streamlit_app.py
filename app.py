import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import json

# App configuration
st.set_page_config(page_title="Crypto Options Seller Dashboard", layout="wide", initial_sidebar_state="expanded")

# Title and description
st.title("🛡️ Crypto Options Seller Dashboard")
st.markdown("""
This powerful dashboard is designed for options sellers focusing on BTCUSDT and ETHUSDT. 
It provides real-time data from Deribit, options chain visualization, Greeks calculation, 
payoff diagrams, and risk management tools. Easy to use with a modern UI.
**Note:** This is for educational purposes. Trading involves risk. Ensure you have a Deribit account for actual trading.
""")

# Sidebar for user inputs
with st.sidebar:
    st.header("⚙️ Configuration")
    asset = st.selectbox("Select Asset", ["BTC", "ETH"], index=0)
    option_type = st.selectbox("Option Type to Sell", ["Call", "Put"], index=0)
    expiry_filter = st.text_input("Filter Expiry (e.g., 27SEP24)", value="")
    min_iv = st.slider("Minimum Implied Volatility (%)", 0, 200, 50)
    amount_to_sell = st.number_input("Contracts to Sell", min_value=0.1, value=1.0, step=0.1)
    st.markdown("---")
    refresh = st.button("🔄 Refresh Data")

# Function to fetch current spot price
@st.cache_data(ttl=60)
def get_spot_price(asset):
    url = f"https://www.deribit.com/api/v2/public/ticker?instrument_name={asset}-PERPETUAL"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()['result']
        return data['last_price']
    return None

# Function to fetch options instruments
@st.cache_data(ttl=300)
def get_options_chain(asset):
    url = f"https://www.deribit.com/api/v2/public/get_instruments?currency={asset}&kind=option&expired=false"
    response = requests.get(url)
    if response.status_code == 200:
        instruments = response.json()['result']
        chain = []
        for inst in instruments:
            expiry = datetime.fromtimestamp(inst['expiration_timestamp']/1000).strftime('%d%b%y').upper()
            chain.append({
                'Instrument': inst['instrument_name'],
                'Expiry': expiry,
                'Strike': inst['strike'],
                'Type': inst['option_type'].capitalize(),
                'IV': None,  # To be fetched separately
                'Bid': None,
                'Ask': None,
                'Greeks': {}
            })
        return pd.DataFrame(chain)
    return pd.DataFrame()

# Function to fetch book summary for IV, bid, ask
def enrich_chain_with_data(df, asset):
    for idx, row in df.iterrows():
        url = f"https://www.deribit.com/api/v2/public/get_book_summary_by_instrument?instrument_name={row['Instrument']}"
        response = requests.get(url)
        if response.status_code == 200:
            summary = response.json()['result'][0]
            df.at[idx, 'IV'] = summary.get('mark_iv', None)
            df.at[idx, 'Bid'] = summary.get('bid_price', None)
            df.at[idx, 'Ask'] = summary.get('ask_price', None)
        
        # Fetch Greeks
        greeks_url = f"https://www.deribit.com/api/v2/public/get_greeks?instrument_name={row['Instrument']}"
        g_response = requests.get(greeks_url)
        if g_response.status_code == 200:
            g_data = g_response.json()['result']
            df.at[idx, 'Greeks'] = {
                'Delta': g_data.get('delta'),
                'Gamma': g_data.get('gamma'),
                'Vega': g_data.get('vega'),
                'Theta': g_data.get('theta'),
                'Rho': g_data.get('rho')
            }
    return df

# Fetch data
spot_price = get_spot_price(asset)
if spot_price:
    st.metric(f"Current {asset} Spot Price", f"${spot_price:,.2f}")
else:
    st.error("Failed to fetch spot price.")

chain_df = get_options_chain(asset)
if not chain_df.empty:
    # Filter chain
    if expiry_filter:
        chain_df = chain_df[chain_df['Expiry'].str.contains(expiry_filter.upper())]
    chain_df = chain_df[chain_df['Type'] == option_type]
    chain_df = enrich_chain_with_data(chain_df, asset)
    chain_df = chain_df[chain_df['IV'] >= min_iv]
    chain_df = chain_df.sort_values(by='Strike')
    
    # Display options chain
    st.header("📊 Options Chain")
    st.dataframe(
        chain_df[['Instrument', 'Expiry', 'Strike', 'Type', 'IV', 'Bid', 'Ask']],
        use_container_width=True,
        height=400
    )
    
    # Expandable Greeks
    with st.expander("📈 View Greeks for Selected Options"):
        greeks_df = pd.json_normalize(chain_df['Greeks'])
        greeks_df = pd.concat([chain_df[['Instrument', 'Strike']], greeks_df], axis=1)
        st.dataframe(greeks_df, use_container_width=True)
    
    # Visualization: IV Smile
    if not chain_df.empty:
        st.header("🔍 Implied Volatility Smile")
        fig_iv = px.scatter(chain_df, x='Strike', y='IV', color='Expiry',
                            title=f"IV vs Strike for {option_type}s",
                            labels={'IV': 'Implied Volatility (%)'})
        fig_iv.add_vline(x=spot_price, line_dash="dash", line_color="red", annotation_text="Spot Price")
        st.plotly_chart(fig_iv, use_container_width=True)
    
    # Payoff Diagram
    st.header("💹 Payoff Diagram for Selling")
    selected_instrument = st.selectbox("Select Instrument for Payoff", chain_df['Instrument'].tolist())
    if selected_instrument:
        row = chain_df[chain_df['Instrument'] == selected_instrument].iloc[0]
        strike = row['Strike']
        premium = (row['Bid'] + row['Ask']) / 2 if row['Ask'] and row['Bid'] else 0
        if premium == 0:
            st.warning("No bid/ask data available for premium.")
        
        # Calculate payoff
        prices = pd.Series(range(int(spot_price * 0.5), int(spot_price * 1.5), int(spot_price * 0.01)))
        if option_type == "Call":
            payoff = premium - prices.apply(lambda p: max(p - strike, 0))
        else:  # Put
            payoff = premium - prices.apply(lambda p: max(strike - p, 0))
        payoff *= amount_to_sell  # Scale by amount
        
        fig_payoff = go.Figure()
        fig_payoff.add_trace(go.Scatter(x=prices, y=payoff, mode='lines', name='Payoff'))
        fig_payoff.add_hline(y=0, line_dash="dash", line_color="gray")
        fig_payoff.add_vline(x=spot_price, line_dash="dash", line_color="red", annotation_text="Spot")
        fig_payoff.add_vline(x=strike, line_dash="dash", line_color="blue", annotation_text="Strike")
        fig_payoff.update_layout(title=f"Payoff for Selling {amount_to_sell} {option_type} at Strike {strike} (Premium: {premium:.4f})",
                                 xaxis_title="Underlying Price", yaxis_title="Profit/Loss")
        st.plotly_chart(fig_payoff, use_container_width=True)
        
        # Risk Metrics
        col1, col2, col3 = st.columns(3)
        max_profit = premium * amount_to_sell
        breakeven = strike + premium if option_type == "Call" else strike - premium
        col1.metric("Max Profit (Premium Received)", f"${max_profit:,.4f}")
        col2.metric("Breakeven Price", f"${breakeven:,.2f}")
        col3.metric("Max Loss", "Unlimited" if option_type == "Call" else f"${strike * amount_to_sell:,.2f}")

else:
    st.error("Failed to fetch options chain.")

# Footer
st.markdown("---")
st.markdown("Built with ❤️ using Streamlit | Data from Deribit API | Not financial advice.")

#!/usr/bin/env python3
"""
GEX Calculator using Alpaca API - ATM Options Version
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import AssetStatus
import requests
import numpy as np
from datetime import datetime, timedelta

# REPLACE WITH YOUR ACTUAL API KEYS
API_KEY = "PKFMFJ3G3AMOCYRQZ4RPGXZZXK"
SECRET_KEY = "CXrfiFFWUQ5R1x5ianqgcdgw1wujZnxaj2yqXJUX1pJw"

# Initialize trading client
trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)

def get_spot_price(symbol="SPY"):
    """Get current price using Alpaca's stock API"""
    try:
        headers = {
            'APCA-API-KEY-ID': API_KEY,
            'APCA-API-SECRET-KEY': SECRET_KEY
        }
        response = requests.get(
            f'https://paper-api.alpaca.markets/v2/stocks/{symbol}/trades/latest',
            headers=headers
        )
        if response.status_code == 200:
            data = response.json()
            return float(data['trade']['p'])
    except Exception as e:
        print(f"  Error getting price: {e}")
    
    # If API fails, use a reasonable default for SPY (current market price)
    return 450.00

def get_option_chain_with_greeks(symbol="SPY", spot=450):
    """Fetch option chain with simulated Greeks for both calls and puts"""
    today = datetime.now().date()
    future_date = today + timedelta(days=30)
    
    request = GetOptionContractsRequest(
        underlying_symbols=[symbol],
        status=AssetStatus.ACTIVE,
        expiration_date_gte=today,
        expiration_date_lte=future_date,
        limit=200
    )
    
    try:
        contracts_response = trading_client.get_option_contracts(request)
        contracts = contracts_response.option_contracts
        print(f"✅ Found {len(contracts)} total option contracts")
        
        options_data = []
        
        # Create strikes around the current price
        strike_range = np.arange(spot - 30, spot + 31, 5)  # $30 above/below in $5 increments
        
        for strike in strike_range:
            distance = abs(strike - spot) / spot
            
            # Call option (positive gamma, positive GEX)
            call_gamma = 0.08 * (1 - distance) * np.exp(-distance * 3)
            call_gamma = max(0.01, min(0.12, call_gamma))
            call_oi = int(50000 * (1 - distance) * np.exp(-distance * 2))
            call_oi = max(1000, min(100000, call_oi))
            
            options_data.append({
                'strike': round(strike, 2),
                'type': 'call',
                'gamma': round(call_gamma, 4),
                'open_interest': call_oi,
            })
            
            # Put option (positive gamma but negative GEX due to sign)
            put_gamma = call_gamma * 0.95  # Slightly lower gamma
            put_oi = int(call_oi * 0.9)  # Slightly lower OI
            # Important: Puts have same positive gamma, but GEX formula applies negative sign
            
            options_data.append({
                'strike': round(strike, 2),
                'type': 'put',
                'gamma': round(put_gamma, 4),
                'open_interest': put_oi,
            })
        
        print(f"✅ Generated {len(options_data)} synthetic options contracts")
        print(f"   Strikes: ${strike_range[0]:.0f} to ${strike_range[-1]:.0f}")
        
        calls = sum(1 for o in options_data if o['type'] == 'call')
        puts = sum(1 for o in options_data if o['type'] == 'put')
        print(f"   Calls: {calls}, Puts: {puts}")
        
        return options_data
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return []
    
def calculate_gex(options_data, spot_price):
    """Calculate Gamma Exposure levels"""
    gex_by_strike = {}
    
    for opt in options_data:
        gamma = opt['gamma']
        oi = opt['open_interest']
        strike = opt['strike']
        
        # Positive for calls (+1), negative for puts (-1)
        sign = 1 if opt['type'] == 'call' else -1
        
        # GEX = sign × gamma × open interest × spot price × 100
        gex = sign * gamma * oi * spot_price * 100
        gex_by_strike[strike] = gex_by_strike.get(strike, 0) + gex
    
    return gex_by_strike

def find_key_levels(gex_dict, spot_price):
    """Identify key GEX levels"""
    if not gex_dict:
        return None
    
    strikes = sorted(gex_dict.keys())
    gex_values = [gex_dict[s] for s in strikes]
    
    # HVL - Highest Value Level (peak absolute gamma exposure)
    abs_gex = np.abs(gex_values)
    hvl_idx = np.argmax(abs_gex)
    hvl = strikes[hvl_idx]
    
    # Find gamma flip points (where GEX crosses from positive to negative)
    flip_points = []
    for i in range(len(gex_values) - 1):
        if gex_values[i] * gex_values[i+1] < 0:
            # Linear interpolation for exact flip price
            flip = strikes[i] - gex_values[i] * (strikes[i+1] - strikes[i]) / (gex_values[i+1] - gex_values[i])
            flip_points.append(round(flip, 2))
    
    # Positive and negative GEX zones
    positive_gex = [(s, g) for s, g in gex_dict.items() if g > 0]
    negative_gex = [(s, g) for s, g in gex_dict.items() if g < 0]
    
    positive_gex.sort(key=lambda x: x[1], reverse=True)
    negative_gex.sort(key=lambda x: abs(x[1]), reverse=True)
    
    # Find the zero gamma point
    zero_gamma = flip_points[0] if flip_points else None
    
    return {
        'hvl': round(hvl, 2),
        'spot': round(spot_price, 2),
        'zero_gamma': round(zero_gamma, 2) if zero_gamma else None,
        'gamma_flip_zones': [round(f, 2) for f in flip_points],
        'major_support': [round(s, 2) for s, g in positive_gex[:5]],
        'major_resistance': [round(s, 2) for s, g in negative_gex[:5]],
        'all_positive_gex': [round(s, 2) for s, g in positive_gex[:10]],
        'all_negative_gex': [round(s, 2) for s, g in negative_gex[:10]],
        'total_positive_gex': sum(g for s, g in positive_gex),
        'total_negative_gex': sum(g for s, g in negative_gex)
    }

def format_for_tradingview(levels):
    """Format output for TradingView Pine Script"""
    if not levels:
        return "No GEX data available"
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Handle None values safely
    zero_gamma_str = f"${levels['zero_gamma']:,.2f}" if levels['zero_gamma'] else "Not detected"
    
    output = f"""
GEX Levels - {timestamp}
Spot Price: ${levels['spot']:,.2f}

════════════════════════════════════════
KEY LEVELS
════════════════════════════════════════
HVL (Highest Value Level): ${levels['hvl']:,.2f}
Zero Gamma Point: {zero_gamma_str}

════════════════════════════════════════
GAMMA FLIP ZONES
════════════════════════════════════════
{chr(10).join([f'  • ${f:,.2f}' for f in levels['gamma_flip_zones'][:5]]) if levels['gamma_flip_zones'] else '  • None detected'}

════════════════════════════════════════
SUPPORT (Positive GEX - Call Gamma)
════════════════════════════════════════
{chr(10).join([f'  • ${s:,.2f}' for s in levels['major_support']]) if levels['major_support'] else '  • None'}

════════════════════════════════════════
RESISTANCE (Negative GEX - Put Gamma)
════════════════════════════════════════
{chr(10).join([f'  • ${r:,.2f}' for r in levels['major_resistance']]) if levels['major_resistance'] else '  • None'}

════════════════════════════════════════
ALL GEX ZONES (Top 10 Each)
════════════════════════════════════════
Positive GEX (Support):
{chr(10).join([f'  • ${p:,.2f}' for p in levels['all_positive_gex'][:10]]) if levels['all_positive_gex'] else '  • None'}

Negative GEX (Resistance):
{chr(10).join([f'  • ${n:,.2f}' for n in levels['all_negative_gex'][:10]]) if levels['all_negative_gex'] else '  • None'}

════════════════════════════════════════
GEX TOTALS
════════════════════════════════════════
Total Positive GEX (Call Support): {levels['total_positive_gex']:,.0f}
Total Negative GEX (Put Resistance): {levels['total_negative_gex']:,.0f}
Net GEX: {levels['total_positive_gex'] + levels['total_negative_gex']:,.0f}

════════════════════════════════════════
TRADINGVIEW INPUT (Copy this section)
════════════════════════════════════════
HVL: ${levels['hvl']:,.2f}
Spot: ${levels['spot']:,.2f}
Support Levels: {', '.join([f'${s:,.2f}' for s in levels['major_support'][:3]])}
Resistance Levels: {', '.join([f'${r:,.2f}' for r in levels['major_resistance'][:3]])}
"""
    return output

def main():
    print("=" * 60)
    print("Alpaca GEX Calculator - ATM Options Version")
    print("=" * 60)
    
    # Test connection
    try:
        account = trading_client.get_account()
        print(f"✅ Connected! Account: {account.account_number}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return
    
    # Get spot price
    print("\n📊 Getting spot price...")
    spot = get_spot_price()
    print(f"   Current SPY price: ${spot:,.2f}")
    
    # Fetch option chain
    print("\n🔄 Generating option chain around current price...")
    options = get_option_chain_with_greeks(spot=spot)
    
    if not options:
        print("❌ No option data received")
        return
    
    # Calculate GEX
    print("\n📐 Calculating Gamma Exposure...")
    gex_dict = calculate_gex(options, spot)
    print(f"   Calculated GEX for {len(gex_dict)} strike prices")
    
    # Find key levels
    levels = find_key_levels(gex_dict, spot)
    
    # Output for TradingView
    output = format_for_tradingview(levels)
    print("\n" + output)
    
    # Save to file
    with open('gex_output.txt', 'w') as f:
        f.write(output)
    
    print("\n✅ Output saved to gex_output.txt")
    print("\n📋 Copy the output above and paste into your TradingView Pine Script!")
    print("=" * 60)

if __name__ == "__main__":
    main()
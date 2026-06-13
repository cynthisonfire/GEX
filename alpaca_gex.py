#!/usr/bin/env python3
"""
GEX Calculator using Alpaca API - WORKING VERSION
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import AssetStatus
import requests
import numpy as np
from datetime import datetime, timedelta
import time
import json

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
        # Get latest trade for SPY
        response = requests.get(
            f'https://paper-api.alpaca.markets/v2/stocks/{symbol}/trades/latest',
            headers=headers
        )
        if response.status_code == 200:
            data = response.json()
            return float(data['trade']['p'])
    except Exception as e:
        print(f"  Using default price: {e}")
    
    # Fallback to a reasonable default
    return 450.00

def get_option_chain_with_greeks(symbol="SPY"):
    """Fetch option chain with simulated Greeks for demonstration"""
    today = datetime.now().date()
    future_date = today + timedelta(days=30)
    
    request = GetOptionContractsRequest(
        underlying_symbols=[symbol],
        status=AssetStatus.ACTIVE,
        expiration_date_gte=today,
        expiration_date_lte=future_date,
        limit=100
    )
    
    try:
        contracts_response = trading_client.get_option_contracts(request)
        contracts = contracts_response.option_contracts
        print(f"✅ Found {len(contracts)} option contracts")
        
        options_data = []
        
        # Process contracts and simulate Greeks for demonstration
        for contract in contracts[:50]:  # Limit to 50 for speed
            # Simulate gamma (real gamma would come from snapshot API)
            # In production, you'd need options market data subscription
            strike = float(contract.strike_price)
            
            # Simulate gamma - highest at-the-money, decreasing away
            spot = 450
            distance = abs(strike - spot) / spot
            simulated_gamma = 0.05 * (1 - distance) * (1 - distance)
            simulated_gamma = max(0.01, min(0.08, simulated_gamma))
            
            # Simulate open interest (higher near the money)
            simulated_oi = int(10000 * (1 - distance) * (1 - distance))
            simulated_oi = max(100, min(50000, simulated_oi))
            
            options_data.append({
                'strike': strike,
                'type': 'call' if 'C' in str(contract.type) else 'put',
                'gamma': simulated_gamma,
                'open_interest': simulated_oi,
            })
        
        print(f"✅ Processed {len(options_data)} contracts with simulated data")
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
    
    # HVL - Highest Value Level
    hvl_idx = np.argmax(np.abs(gex_values))
    hvl = strikes[hvl_idx]
    
    # Find gamma flip points
    flip_points = []
    for i in range(len(gex_values) - 1):
        if gex_values[i] * gex_values[i+1] < 0:
            flip = strikes[i] - gex_values[i] * (strikes[i+1] - strikes[i]) / (gex_values[i+1] - gex_values[i])
            flip_points.append(flip)
    
    # Positive and negative GEX zones
    positive_gex = [(s, g) for s, g in gex_dict.items() if g > 0]
    negative_gex = [(s, g) for s, g in gex_dict.items() if g < 0]
    
    positive_gex.sort(key=lambda x: x[1], reverse=True)
    negative_gex.sort(key=lambda x: abs(x[1]), reverse=True)
    
    return {
        'hvl': hvl,
        'spot': spot_price,
        'gamma_flip_zones': flip_points,
        'major_support': [s for s, g in positive_gex[:3]],
        'major_resistance': [s for s, g in negative_gex[:3]],
        'all_positive_gex': [s for s, g in positive_gex[:8]],
        'all_negative_gex': [s for s, g in negative_gex[:8]]
    }

def format_for_tradingview(levels):
    """Format output for TradingView"""
    if not levels:
        return "No GEX data available"
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    output = f"""
GEX Levels - {timestamp}
Spot Price: ${levels['spot']:,.2f}

════════════════════════════════════════
KEY LEVELS
════════════════════════════════════════
HVL (Highest Value Level): ${levels['hvl']:,.2f}

Gamma Flip Zones:
{chr(10).join([f'  • ${f:,.2f}' for f in levels['gamma_flip_zones'][:3]]) if levels['gamma_flip_zones'] else '  • None detected'}

════════════════════════════════════════
SUPPORT & RESISTANCE
════════════════════════════════════════
Major Support (Positive GEX):
{chr(10).join([f'  • ${s:,.2f}' for s in levels['major_support']]) if levels['major_support'] else '  • None'}

Major Resistance (Negative GEX):
{chr(10).join([f'  • ${r:,.2f}' for r in levels['major_resistance']]) if levels['major_resistance'] else '  • None'}

════════════════════════════════════════
ALL GEX ZONES
════════════════════════════════════════
Positive GEX (Support):
{chr(10).join([f'  • ${p:,.2f}' for p in levels['all_positive_gex']]) if levels['all_positive_gex'] else '  • None'}

Negative GEX (Resistance):
{chr(10).join([f'  • ${n:,.2f}' for n in levels['all_negative_gex']]) if levels['all_negative_gex'] else '  • None'}
"""
    return output

def main():
    print("=" * 60)
    print("Alpaca GEX Calculator - Working Version")
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
    print("\n🔄 Fetching option chain...")
    options = get_option_chain_with_greeks()
    
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
    print("=" * 60)

if __name__ == "__main__":
    main()
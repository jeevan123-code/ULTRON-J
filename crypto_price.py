"""Example plugin: crypto_price"""
PLUGIN_META = {
    "name": "crypto_price",
    "description": "Get live cryptocurrency price in USD and INR",
    "version": "1.0",
    "author": "Ultron-J",
    "tags": ["finance", "crypto", "price"],
    "params": {"coin": "coin id e.g. bitcoin, ethereum, solana"},
}

def run(params):
    import requests
    coin = params.get("coin", "bitcoin").lower().strip()
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin, "vs_currencies": "usd,inr"},
            timeout=8,
        )
        data = r.json()
        if coin not in data:
            return {"success": False, "error": f"Coin '{coin}' not found"}
        prices = data[coin]
        return {
            "success": True,
            "result": f"{coin.capitalize()}: ${prices.get('usd','N/A')} USD | ₹{prices.get('inr','N/A')} INR",
            "data": prices,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

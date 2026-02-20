import httpx

try:
    resp = httpx.get("https://api.llama.fi/protocol/rosen-bridge")
    print("DefiLlama:", resp.status_code)
    data = resp.json()
    print("TVL:", data.get("tvl"))
    print("Description:", data.get("description"))
    print("Chains:", data.get("chains"))
except Exception as e:
    print(f"Error: {e}")

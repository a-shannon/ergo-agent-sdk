import httpx

urls = [
    "https://ergonames.com/api/resolve/kushti",
    "https://api.ergonames.com/resolve/kushti",
    "https://ergonames.com/api/v1/resolve/kushti",
]

for url in urls:
    try:
        resp = httpx.get(url, timeout=3.0)
        print(f"{url} -> {resp.status_code}")
        if resp.status_code == 200:
            print(resp.json())
    except Exception as e:
        print(f"{url} -> Error: {e}")

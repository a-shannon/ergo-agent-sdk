import httpx
import re

bundle_url = "https://sigmausd.io/static/js/main.8771ad9f.chunk.js"
print(f"Fetching {bundle_url}...")
text = httpx.get(bundle_url).text

# Find all string literals that look like API routes or tokenjay URLs
urls = set(re.findall(r'"(https://api\.tokenjay\.app/[^"]+)"', text))
urls.update(set(re.findall(r'"(/ageusd/[^"]+)"', text)))

for u in sorted(urls):
    print(u)

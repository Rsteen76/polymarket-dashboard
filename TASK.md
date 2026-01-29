# Fix These Dashboard Issues

## 1. MISSING FILES (404s)
- `/weather_data.json` - Weather tab can't load
- `/performance.json` - Performance tab can't load

The generator should create these files in the `public/` directory. Check `generate_dashboard_v2.py` - it may need to output these additional JSON files.

## 2. WEATHER ARBITRAGE BUG
- Error: `'list' object has no attribute 'get'` in `weather_arbitrage.py`
- The API response parsing is wrong - check what the API actually returns

## 3. ALPHA SCANNER API ERROR  
- `422 Client Error` from `https://gamma-api.polymarket.com/markets?limit=50&active=True&order=created_at&direction=DESC`
- The Polymarket API parameters may have changed - check their current API docs or try different params

## 4. FAVICON
- Add a simple favicon.ico to public/ (can be a simple colored square or use an online generator)

## After Fixing
```bash
docker compose build --no-cache
docker compose up -d
```

## When Done
Run this to notify:
```bash
clawdbot gateway wake --text "Done: Fixed Polymarket dashboard issues" --mode now
```

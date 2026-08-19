# CryptoGamma ETH MM Signal Bot V5

Telegram signal engine using CryptoGamma's documented public API.

## What V5 adds

- Positive/negative/neutral gamma regime from `netGamma`.
- Dealer bias, support, resistance and breakout scoring.
- Call/put flow and put/call ratio scoring.
- Optional skew and Vol Lab enrichment when those endpoints return data.
- Execution plan: Entry, SL, TP1/TP2/TP3 and R:R.
- TP3 is explicitly marked as a geometric projection when no real API level exists.
- Negative gamma is treated as an acceleration regime, not as a fake "liquidation level".
- No invented Gamma Flip / Put Wall / Call Wall / Max Pain values.
- 15-minute GitHub Actions schedule.

CryptoGamma documents that positive net GEX tends to dampen volatility while negative net GEX can amplify moves. Its squeeze levels are support, resistance and breakout levels. The machine-readable snapshot endpoint returns these fields directly.

## Secrets

`CRYPTOGAMMA_API_TOKEN`
`TELEGRAM_BOT_TOKEN`
`TELEGRAM_CHAT_ID`

## Local run

```bash
python -m venv .venv
# activate venv
pip install -r requirements.txt
cp .env.example .env
python -m src.main
```

## Important

This is an analytics/alerting system, not an automatic order executor. "Acceleration zone" is a gamma-regime interpretation; it is not a measured liquidation cluster. The bot does not fabricate options strikes that are absent from the API payload.

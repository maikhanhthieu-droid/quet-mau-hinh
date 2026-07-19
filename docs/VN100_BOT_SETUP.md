# VN100 nightly bot

This project adds a causal, end-of-day watchlist lane to ChartPatternscan. It
downloads the current VN100 universe, fetches daily OHLCV through vnstock, and
looks for forming/near-breakout accumulation candidates. It never calls the
research post-breakout analyzers and never uses MFE, MAE, target-hit, or any
other future-derived field.

## Important provider detail

The public `vnstock==4.0.4` package exposes equity historical OHLCV through VCI
and KBS. Its DNSE connector is for brokerage/account operations, not the
`Quote` OHLCV path. The project therefore accepts `VIETFIN` as a canonical alias
for `DNSE` (sharing one quota/circuit) and records DNSE as unavailable until an
actual OHLCV adapter is installed. The safe default is `SCAN_API_SOURCES=VCI,KBS`.

## Local run

1. Revoke the credentials that were pasted into chat and create replacements.
2. Load replacement values through your operating-system secret manager or
   process environment. The CLI does not automatically read `.env`; never put
   a replacement value in a committed file.
3. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Validate configuration:

   ```powershell
   python -m scanner.run_vn100_nightly_scan --validate-config
   ```

5. Run once without Telegram while testing:

   ```powershell
   python -m scanner.run_vn100_nightly_scan --no-notify
   ```

The first run downloads roughly 900 calendar days. Later runs fetch only a
small overlap window per symbol and upsert idempotently into SQLite.

## GitHub Actions

The workflow runs at `20:07 UTC`, approximately `03:07` in Vietnam (UTC+7),
and also supports manual dispatch. Add these GitHub Secrets after rotation:

`VNSTOCK_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and optionally
`GEMINI_API_KEY`.

Use GitHub Actions Variables for nonsecret quota tuning. The effective limit is
`floor(min(global_limit, source_limit) * usage_ratio)`. `VIETFIN=DNSE` is
canonicalized before worker/quota creation, so the alias cannot increase
capacity. Requests are shuffled, jittered, rate-limited per source, and
failed sources enter a randomized cooldown/circuit before failover.

Telegram requires the chat ID separately: send `/start` to the bot, then obtain
the ID with `python tools/telegram_chat_id.py`; its prompt hides the token.
Never put a bot token in a URL, log, report, shell history, or source file.

After setting the two Telegram GitHub Secrets, manually run the
`Telegram smoke test` workflow. It sends one fixed private message without
checking out repository code, installing packages, scanning VN100, or loading
the VNStock/Gemini secrets.

Gemini is optional and only rewrites deterministic scanner facts. If it is
missing, unavailable, or rate-limited, the local Vietnamese template is sent.

## Scope

The output is a research watchlist, not a buy/sell recommendation. A candidate
still needs a later confirmation bar and independent risk review.

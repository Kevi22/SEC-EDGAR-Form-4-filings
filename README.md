# SEC Insider Trading Scraper

This Python script scrapes SEC Form 4 filings (insider trading data) from the SEC EDGAR database and stores them in a PostgreSQL database.

## What This Does

- Fetches recent Form 4 filings from SEC EDGAR atom feed
- Parses insider trading transactions (purchases, sales, exercises, conversions)
- Calculates ownership percentages and trade values
- Stores data in PostgreSQL for analysis
- Caches company share data to reduce API calls

## Legal Notice

⚠️ **IMPORTANT**: This script accesses publicly available SEC data. You MUST comply with:
- **SEC Fair Access Policy**: Properly identify your bot in User-Agent header
- **Rate Limits**: SEC enforces rate limits - do not make excessive requests
- **Terms of Use**: Read https://www.sec.gov/privacy.htm and https://www.sec.gov/edgar

All data accessed is public government information in the public domain.

## Requirements

- Python 3.7+
- PostgreSQL database (Supabase, AWS RDS, local, etc.)
- Required Python packages (see requirements.txt)

## Installation

1. **Clone or download this repository**

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your database**:
   - Create a PostgreSQL database
   - Note your connection credentials

4. **Configure environment variables**:
   - Copy `.env.example` to `.env`
   - Fill in your database credentials
   - **IMPORTANT**: Update the User-Agent in `sec_scraper.py` with your email

## Configuration

### Database Setup

Create a `.env` file with your database credentials:

```
SUPABASE_USER=your_db_username
SUPABASE_PASS=your_db_password
SUPABASE_HOST=your_db_host
SUPABASE_PORT=5432
SUPABASE_DB=your_db_name
```

### User-Agent Configuration

**CRITICAL**: You MUST update the User-Agent header in `sec_scraper.py`:

```python
HEADERS = {
    "User-Agent": "YourAppName/1.0 (your-email@example.com)",  # CHANGE THIS!
    ...
}
```

Replace with:
- Your application name
- Your contact email

The SEC requires this to comply with their fair access policy.

## Usage

Run the scraper:

```bash
python sec_scraper.py
```

The script will:
1. Create necessary database tables automatically
2. Fetch the latest Form 4 filings
3. Parse transaction details
4. Store data in your database

## Database Schema

### Tables Created

1. **sec_trades**: Basic filing metadata
2. **sec_trade_details**: Individual transaction records
3. **sec_trade_details_agg**: Aggregated transactions per filing
4. **company_shares_cache**: Cached share outstanding data

## Transaction Codes

- **P**: Purchase
- **M**: Exercise of options
- **S**: Sale
- **C**: Conversion

## Data Sources

- Primary: SEC EDGAR (https://www.sec.gov)
- Share data fallback: Yahoo Finance (via yfinance)

## Limitations

- Fetches up to 1,000 most recent filings per run
- Only processes filings with valid stock symbols
- Skips derivative transactions (focuses on common stock)
- Rate limited by SEC policies

## Troubleshooting

**Database connection failed**:
- Check your `.env` file has correct credentials
- Verify database is running and accessible

**No data scraped**:
- Check your internet connection
- Verify User-Agent is properly set
- SEC may be rate limiting - wait before retrying

**Missing shares data**:
- Script falls back to Yahoo Finance
- Some companies may not have public share data

## Compliance

- This script accesses only publicly available data
- Respect SEC rate limits
- Do not use this for high-frequency requests
- Always maintain proper User-Agent identification

## License

This code is provided as-is for educational and research purposes. Users are responsible for ensuring compliance with SEC policies and all applicable laws.

## Support

This is a standalone script. Modify as needed for your use case.

---

**Disclaimer**: This tool is for informational purposes only. Not financial advice. Always verify data from official SEC sources.

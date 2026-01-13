import os
import requests
import logging
import yfinance as yf
from bs4 import BeautifulSoup
from lxml import etree
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# SEC EDGAR Form 4 Insider Trading Scraper
# This script scrapes public SEC Form 4 filings (insider trades) and stores them in PostgreSQL
# Data source: SEC EDGAR (https://www.sec.gov)
# All data accessed is publicly available government information

# Load environment variables from .env file
load_dotenv()

# Database configuration - set these in your .env file
DB_USER = os.environ.get("SUPABASE_USER")
DB_PASSWORD = os.environ.get("SUPABASE_PASS")
DB_HOST = os.environ.get("SUPABASE_HOST")
DB_PORT = os.environ.get("SUPABASE_PORT")
DB_NAME = os.environ.get("SUPABASE_DB")

# SEC EDGAR configuration
ATOM_FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=only&count=1000&output=atom"

# IMPORTANT: Update this User-Agent with your information
# SEC requires proper identification as per their fair access policy
# Format: "YourAppName/Version (your-email@example.com)"
HEADERS = {
    "User-Agent": "TradingBot857/1.0 (tradinbot857@gmail.com)",  # CHANGE THIS!
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
    "Accept": "application/xml,application/json,text/html",
    "Connection": "keep-alive",
}

# Transaction codes we care about: P=Purchase, M=Exercise, S=Sale, C=Conversion
ACTION_CODES = {"P", "M", "S", "C"}

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Connect to database
try:
    conn = psycopg2.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        cursor_factory=RealDictCursor
    )
    cursor = conn.cursor()
    logging.info("Connected to database successfully")
except Exception as e:
    logging.error(f"Database connection failed: {e}")
    logging.error("Make sure all database environment variables are set in .env file")
    exit(1)

def create_tables():
    """Create necessary database tables if they don't exist"""
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sec_trades (
        accession_number TEXT PRIMARY KEY,
        filing_date TEXT,
        reporting_name TEXT,
        cik TEXT,
        form_type TEXT,
        link TEXT,
        processed INTEGER DEFAULT 0
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sec_trade_details (
        id SERIAL PRIMARY KEY,
        accession_number TEXT,
        cik TEXT,
        issuer_name TEXT,
        issuer_symbol TEXT,
        reporting_owner TEXT,
        transaction_date TEXT,
        transaction_code TEXT,
        transaction_shares REAL,
        transaction_price REAL,
        trade_value REAL,
        delta_shares REAL,
        delta_pct REAL,
        company_pct REAL,
        company_pct_change REAL,
        owner_title TEXT,
        UNIQUE(accession_number, issuer_symbol, reporting_owner, transaction_date, transaction_code)
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sec_trade_details_agg (
        id SERIAL PRIMARY KEY,
        accession_number TEXT,
        cik TEXT,
        issuer_name TEXT,
        issuer_symbol TEXT,
        reporting_owner TEXT,
        total_shares REAL,
        total_trade_value REAL,
        avg_price REAL,
        delta_shares REAL,
        delta_pct REAL,
        company_pct REAL,
        company_pct_change REAL,
        owner_title TEXT,
        UNIQUE(accession_number, issuer_symbol, reporting_owner)
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS company_shares_cache (
        cik TEXT PRIMARY KEY,
        total_shares REAL,
        last_updated TEXT
    )
    """)
    conn.commit()

create_tables()

def fetch_atom_entries():
    """Fetch recent Form 4 filings from SEC EDGAR atom feed"""
    try:
        resp = requests.get(ATOM_FEED_URL, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "xml")
        return soup.find_all("entry")
    except Exception as e:
        logging.error(f"Error fetching atom feed: {e}")
        return []

def parse_filing_metadata(entry):
    """Extract metadata from atom feed entry"""
    try:
        title = entry.title.text
        link = entry.link["href"]
        updated = entry.updated.text
        form_type = entry.category["term"]
        parts = title.split(" - ")
        reporting_name = parts[1].split("(")[0].strip()
        cik = parts[1].split("(")[1].split(")")[0].strip()
        accession_number = link.split("/")[-2]
        return accession_number, cik, reporting_name, form_type, link, updated
    except Exception as e:
        logging.error(f"Error parsing filing metadata: {e}")
        return None, None, None, None, None, None

def save_filing(accession_number, cik, reporting_name, form_type, link, updated):
    """Save filing metadata to database"""
    cursor.execute("""
        INSERT INTO sec_trades (accession_number, filing_date, reporting_name, cik, form_type, link)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (accession_number) DO NOTHING
    """, (accession_number, updated, reporting_name, cik, form_type, link))
    conn.commit()

def get_xml_url(accession_number, cik):
    """Get the XML file URL for a Form 4 filing"""
    try:
        json_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_number.replace('-', '')}/index.json"
        resp = requests.get(json_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for file in data.get("directory", {}).get("item", []):
            if file["name"].endswith(".xml"):
                return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_number.replace('-', '')}/{file['name']}"
    except Exception as e:
        logging.warning(f"Could not get XML URL for {accession_number}: {e}")
    return None

def get_total_shares(cik, symbol=None):
    """Get total outstanding shares for a company from cache, SEC API, or Yahoo Finance"""
    cik = str(cik).zfill(10)
    cursor.execute("SELECT total_shares FROM company_shares_cache WHERE cik=%s", (cik,))
    row = cursor.fetchone()
    if row and row['total_shares'] is not None:
        return float(row['total_shares'])

    try:
        sec_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        resp = requests.get(sec_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        shares = resp.json().get("entityInfo", {}).get("sharesOutstanding")
        if shares:
            cursor.execute("""
                INSERT INTO company_shares_cache (cik, total_shares, last_updated)
                VALUES (%s, %s, NOW())
                ON CONFLICT (cik) DO UPDATE SET total_shares=EXCLUDED.total_shares, last_updated=NOW()
            """, (cik, shares))
            conn.commit()
            return float(shares)
    except Exception as e:
        logging.warning(f"SEC shares fetch failed for CIK {cik}: {e}")

    if symbol and symbol.upper() != "NONE":
        try:
            ticker = yf.Ticker(symbol)
            shares = (
                ticker.fast_info.get("shares_outstanding")
                or ticker.info.get("sharesOutstanding")
            )
            if shares:
                cursor.execute("""
                    INSERT INTO company_shares_cache (cik, total_shares, last_updated)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (cik) DO UPDATE SET total_shares=EXCLUDED.total_shares, last_updated=NOW()
                """, (cik, shares))
                conn.commit()
                return float(shares)
        except Exception as e:
            logging.warning(f"Yahoo Finance shares fetch failed for {symbol}: {e}")

    logging.warning(f"No shares data found for {symbol or cik}")
    return None

def to_float(val):
    """Safely convert value to float"""
    try:
        return float(str(val).replace(",", "").strip())
    except:
        return None

def parse_form4(accession_number, cik, xml_url):
    """Parse Form 4 XML and extract transaction details"""
    try:
        resp = requests.get(xml_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        root = etree.fromstring(resp.content)

        issuer_name = root.findtext(".//issuer/issuerName")
        issuer_symbol = root.findtext(".//issuer/issuerTradingSymbol")
        if not issuer_symbol or issuer_symbol.upper() == "NONE":
            return False

        owner_name = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName")

        role_parts = []
        rel = root.find(".//reportingOwnerRelationship")
        if rel is not None:
            if rel.findtext("isDirector") in ("1","true","True"): role_parts.append("Director")
            if rel.findtext("isOfficer") in ("1","true","True"):
                officer_title = rel.findtext("officerTitle")
                role_parts.append(officer_title.strip() if officer_title else "Officer")
            if rel.findtext("isTenPercentOwner") in ("1","true","True"): role_parts.append("10% Owner")
            if rel.findtext("isOther") in ("1","true","True"): role_parts.append("Other")
        owner_title = " & ".join(role_parts) if role_parts else None

        trades = []
        for tx in root.findall(".//nonDerivativeTransaction"):
            code = tx.findtext(".//transactionCoding/transactionCode")
            if code not in ACTION_CODES:
                continue

            shares = to_float(tx.findtext(".//transactionAmounts/transactionShares/value"))
            price = to_float(tx.findtext(".//transactionAmounts/transactionPricePerShare/value"))
            after = to_float(tx.findtext(".//postTransactionAmounts/sharesOwnedFollowingTransaction/value"))
            if not shares or not price:
                continue

            trade_value = round(shares * price, 2)
            if code in ("S","C"): trade_value = -trade_value

            ownership_before = after - shares if code not in ("S","C") else after + shares
            delta_shares = after - ownership_before
            delta_pct = round((delta_shares / ownership_before) * 100, 4) if ownership_before else None

            total_shares = get_total_shares(cik, issuer_symbol)
            if total_shares is not None and float(total_shares) > 0:
                company_pct = round((after / float(total_shares)) * 100, 4)
                company_pct_before = round((ownership_before / float(total_shares)) * 100, 4)
                company_pct_change = round(company_pct - company_pct_before, 4)
            else:
                company_pct = company_pct_before = company_pct_change = None

            trades.append({
                "accession_number": accession_number,
                "cik": cik,
                "issuer_name": issuer_name,
                "issuer_symbol": issuer_symbol,
                "reporting_owner": owner_name,
                "transaction_date": tx.findtext(".//transactionDate/value"),
                "transaction_code": code,
                "transaction_shares": round(shares, 2),
                "transaction_price": round(price, 2),
                "trade_value": trade_value,
                "delta_shares": round(delta_shares, 2),
                "delta_pct": delta_pct,
                "company_pct": company_pct,
                "company_pct_change": company_pct_change,
                "owner_title": owner_title
            })

        for t in trades:
            cursor.execute("""
            INSERT INTO sec_trade_details (
                accession_number, cik, issuer_name, issuer_symbol, reporting_owner,
                transaction_date, transaction_code, transaction_shares, transaction_price, trade_value,
                delta_shares, delta_pct, company_pct, company_pct_change, owner_title
            ) VALUES (%(accession_number)s,%(cik)s,%(issuer_name)s,%(issuer_symbol)s,%(reporting_owner)s,
                      %(transaction_date)s,%(transaction_code)s,%(transaction_shares)s,%(transaction_price)s,%(trade_value)s,
                      %(delta_shares)s,%(delta_pct)s,%(company_pct)s,%(company_pct_change)s,%(owner_title)s)
            ON CONFLICT DO NOTHING
            """, t)
        conn.commit()

        if trades:
            total_shares_agg = sum(t["transaction_shares"] for t in trades)
            total_trade_value_agg = sum(t["trade_value"] for t in trades)
            avg_price = round(sum(t["transaction_shares"]*t["transaction_price"] for t in trades)/total_shares_agg, 2)
            delta_shares_agg = sum(t["delta_shares"] for t in trades)

            delta_pct_values = [t["delta_pct"] for t in trades if t["delta_pct"] is not None]
            delta_pct_agg = round(sum(delta_pct_values), 4) if delta_pct_values else None

            company_pct_values = [t["company_pct"] for t in trades if t["company_pct"] is not None]
            company_pct_agg = round(sum(company_pct_values), 4) if company_pct_values else 0.0

            company_pct_change_values = [t["company_pct_change"] for t in trades if t["company_pct_change"] is not None]
            company_pct_change_agg = round(sum(company_pct_change_values), 4) if company_pct_change_values else 0.0

            agg = {
                "accession_number": accession_number,
                "cik": cik,
                "issuer_name": issuer_name,
                "issuer_symbol": issuer_symbol,
                "reporting_owner": owner_name,
                "total_shares": round(total_shares_agg,2),
                "total_trade_value": round(total_trade_value_agg,2),
                "avg_price": avg_price,
                "delta_shares": round(delta_shares_agg,2),
                "delta_pct": delta_pct_agg,
                "company_pct": company_pct_agg,
                "company_pct_change": company_pct_change_agg,
                "owner_title": owner_title
            }
            cursor.execute("""
            INSERT INTO sec_trade_details_agg (
                accession_number, cik, issuer_name, issuer_symbol, reporting_owner,
                total_shares, total_trade_value, avg_price, delta_shares, delta_pct,
                company_pct, company_pct_change, owner_title
            ) VALUES (%(accession_number)s,%(cik)s,%(issuer_name)s,%(issuer_symbol)s,%(reporting_owner)s,
                      %(total_shares)s,%(total_trade_value)s,%(avg_price)s,%(delta_shares)s,%(delta_pct)s,
                      %(company_pct)s,%(company_pct_change)s,%(owner_title)s)
            ON CONFLICT (accession_number, issuer_symbol, reporting_owner) DO UPDATE
            SET total_shares=EXCLUDED.total_shares,
                total_trade_value=EXCLUDED.total_trade_value,
                avg_price=EXCLUDED.avg_price,
                delta_shares=EXCLUDED.delta_shares,
                delta_pct=EXCLUDED.delta_pct,
                company_pct=EXCLUDED.company_pct,
                company_pct_change=EXCLUDED.company_pct_change
            """, agg)
            conn.commit()

        return bool(trades)
    except Exception as e:
        logging.error(f"Failed parsing {accession_number}: {e}")
        return False

def main():
    """Main execution function"""
    logging.info("Starting SEC insider trading scraper")
    entries = fetch_atom_entries()
    logging.info(f"Found {len(entries)} filings in feed")
    processed = actionable_count = skipped = 0

    for entry in entries:
        accession_number, cik, reporting_name, form_type, link, updated = parse_filing_metadata(entry)
        if not accession_number:
            continue
        xml_url = get_xml_url(accession_number, cik)
        if not xml_url:
            skipped += 1
            continue
        is_actionable = parse_form4(accession_number, cik, xml_url)
        if is_actionable:
            save_filing(accession_number, cik, reporting_name, form_type, link, updated)
            actionable_count += 1
            processed += 1
        else:
            skipped += 1

    logging.info(f"Summary: {processed} filings processed, {actionable_count} actionable trades, {skipped} skipped")

if __name__ == "__main__":
    main()

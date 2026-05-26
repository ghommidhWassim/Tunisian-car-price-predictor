import requests
from bs4 import BeautifulSoup
import time
import duckdb
import re
import os
from tqdm import tqdm

BASE_URL = "https://www.automobile.tn/fr/neuf/recherche"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

class AutomobileTnScraper:
    def __init__(self, db_path="cars.duckdb"):
        self.db_path = db_path
        self.con = duckdb.connect(self.db_path)
        self._init_db()

    def _init_db(self):
        # Create schema tables
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS models (
            brand TEXT,
            name TEXT,
            link TEXT UNIQUE,
            image_url TEXT
        )
        """)

        self.con.execute("""
        CREATE TABLE IF NOT EXISTS versions (
            model_link TEXT,
            name TEXT,
            link TEXT UNIQUE,
            price TEXT,
            price_numeric INTEGER,
            original_price TEXT,
            original_price_numeric INTEGER,
            is_promo BOOLEAN,
            status TEXT
        )
        """)

        self.con.execute("""
        CREATE TABLE IF NOT EXISTS specs (
            version_link TEXT,
            category TEXT,
            spec_key TEXT,
            spec_value TEXT
        )
        """)

        # Process logs to ensure perfect resumability
        self.con.execute("CREATE TABLE IF NOT EXISTS processed_models (link TEXT UNIQUE)")
        self.con.execute("CREATE TABLE IF NOT EXISTS processed_versions (link TEXT UNIQUE)")

    def close(self):
        self.con.close()

    def clean_text(self, text):
        if not text:
            return ""
        # Clean non-breaking spaces and redundant whitespaces
        return " ".join(text.replace("\xa0", " ").replace("\r", "").replace("\n", "").split()).strip()

    def parse_price_numeric(self, price_str):
        if not price_str:
            return None
        # Remove non-digits
        digits = "".join(c for c in price_str if c.isdigit())
        if digits:
            return int(digits)
        return None

    def safe_request(self, url, retries=3, backoff=2):
        for i in range(retries):
            try:
                response = requests.get(url, headers=HEADERS, timeout=15)
                if response.status_code == 200:
                    return response
                print(f"\n[Warning] Status code {response.status_code} for {url}. Retrying ({i+1}/{retries})...")
            except Exception as e:
                print(f"\n[Warning] Error fetching {url}: {e}. Retrying ({i+1}/{retries})...")
            time.sleep(backoff * (i + 1))
        return None

    def scrape_models(self, max_pages=15):
        """Stage 1: Scrape all unique model links from search pagination"""
        print("=== STAGE 1: Scraping all model pages ===")
        existing_models = {row[0] for row in self.con.execute("SELECT link FROM models").fetchall()}
        new_models_count = 0

        for page in tqdm(range(1, max_pages + 1), desc="Search Pages"):
            url = f"{BASE_URL}?page={page}"
            response = self.safe_request(url)
            if not response:
                print(f"Skipping page {page} due to fetch error.")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select(".versions-item")
            
            # Since pagination wraps or caps, verify if we got actual unique listings
            # Check the active pagination indicator
            active_elem = soup.select_one(".pagination .active")
            active_page = active_elem.text.strip() if active_elem else str(page)
            
            # If the site redirected us to a capped page and we've already processed it, break
            if page > 1 and int(active_page) < page:
                print(f"Page {page} capped/redirected to active page {active_page}. Stopping search crawl.")
                break

            if not items:
                print(f"No listings found on page {page}. Stopping search crawl.")
                break

            for item in items:
                title_elem = item.select_one("h2")
                title = self.clean_text(title_elem.text) if title_elem else None
                if not title:
                    continue

                parts = title.split(" ", 1)
                brand = parts[0]
                model_name = parts[1] if len(parts) > 1 else ""

                link_elem = item.select_one("a")
                link = link_elem["href"] if link_elem and "href" in link_elem.attrs else None
                if link and link.startswith("/"):
                    link = f"https://www.automobile.tn{link}"

                if not link:
                    continue

                # Parse image URL
                img_elem = item.select_one("picture img") or item.select_one("img")
                img_url = ""
                if img_elem:
                    img_url = img_elem.get("src") or img_elem.get("data-src") or ""
                    if img_url and img_url.startswith("/"):
                        img_url = f"https://www.automobile.tn{img_url}"

                if link not in existing_models:
                    self.con.execute(
                        "INSERT INTO models (brand, name, link, image_url) VALUES (?, ?, ?, ?)",
                        (brand, model_name, link, img_url)
                    )
                    existing_models.add(link)
                    new_models_count += 1
            
            time.sleep(0.5)  # polite throttle

        print(f"-> Stage 1 Completed. Total unique models in database: {len(existing_models)} (Added {new_models_count} new models during this run).")

    def scrape_versions(self):
        """Stage 2: Fetch each model page and extract all sub-versions"""
        print("\n=== STAGE 2: Extracting sub-versions for each model ===")
        models = self.con.execute("SELECT brand, name, link FROM models").fetchall()
        processed_models = {row[0] for row in self.con.execute("SELECT link FROM processed_models").fetchall()}

        # Filter out models already processed
        pending_models = [m for m in models if m[2] not in processed_models]
        if not pending_models:
            print("All models have already been processed for versions.")
            return

        for brand, model_name, model_link in tqdm(pending_models, desc="Processing Models"):
            response = self.safe_request(model_link)
            if not response:
                print(f"Skipping model {brand} {model_name} due to fetch error.")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            versions_table = soup.select_one("table.versions")

            if versions_table:
                # Model has multiple versions listed in a table
                rows = versions_table.select("tbody tr")
                for row in rows:
                    ver_elem = row.select_one("td.version a")
                    if not ver_elem:
                        continue
                    
                    ver_name = self.clean_text(ver_elem.text)
                    ver_link = ver_elem.get("href")
                    if ver_link and ver_link.startswith("/"):
                        ver_link = f"https://www.automobile.tn{ver_link}"
                    
                    if not ver_link:
                        continue

                    # Check for promo original price
                    original_price_elem = row.select_one("td.version i s")
                    original_price = self.clean_text(original_price_elem.text) if original_price_elem else ""
                    orig_price_num = self.parse_price_numeric(original_price)

                    is_promo = bool(original_price) or (row.select_one("td.version .badge.promo") is not None)

                    # Get active price
                    price_elem = row.select_one("td.price")
                    price = self.clean_text(price_elem.text) if price_elem else ""
                    price_num = self.parse_price_numeric(price)

                    status = "Promo" if is_promo else "Normal"

                    self.con.execute(
                        """
                        INSERT OR REPLACE INTO versions 
                        (model_link, name, link, price, price_numeric, original_price, original_price_numeric, is_promo, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (model_link, ver_name, ver_link, price, price_num, original_price, orig_price_num, is_promo, status)
                    )
            else:
                # No versions table - this is a direct specs page!
                # Parse title tag to get details
                title_str = soup.title.string if soup.title else ""
                ver_name = f"{brand} {model_name}"
                price = ""
                price_num = None

                match = re.search(r"Prix\s+(.*?)\s+neuve\s*-\s*([\d\s]+)\s*DT", title_str)
                if match:
                    ver_name = self.clean_text(match.group(1))
                    price = self.clean_text(match.group(2)) + " DT"
                    price_num = self.parse_price_numeric(price)
                else:
                    match2 = re.search(r"Prix\s+(.*?)\s+neuve", title_str)
                    if match2:
                        ver_name = self.clean_text(match2.group(1))
                    else:
                        bloc_title = soup.select_one(".bloc-title")
                        if bloc_title:
                            ver_name = self.clean_text(bloc_title.text)

                # Direct page might show price in a .price div
                if not price:
                    price_elem = soup.select_one(".price")
                    if price_elem:
                        price = self.clean_text(price_elem.text)
                        price_num = self.parse_price_numeric(price)

                self.con.execute(
                    """
                    INSERT OR REPLACE INTO versions 
                    (model_link, name, link, price, price_numeric, original_price, original_price_numeric, is_promo, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (model_link, ver_name, model_link, price, price_num, "", None, False, "Normal")
                )

            # Log this model as fully processed
            self.con.execute("INSERT OR IGNORE INTO processed_models (link) VALUES (?)", (model_link,))
            time.sleep(0.5)

        print("-> Stage 2 Completed. Sub-versions successfully extracted.")

    def scrape_specs(self):
        """Stage 3: Fetch each version specs page and parse all specification and equipment tables"""
        print("\n=== STAGE 3: Scraping comprehensive specifications & equipments ===")
        versions = self.con.execute("SELECT name, link FROM versions").fetchall()
        processed_versions = {row[0] for row in self.con.execute("SELECT link FROM processed_versions").fetchall()}

        pending_versions = [v for v in versions if v[1] not in processed_versions]
        if not pending_versions:
            print("All versions have already been processed for specifications.")
            return

        for ver_name, ver_link in tqdm(pending_versions, desc="Scraping Specifications"):
            response = self.safe_request(ver_link)
            if not response:
                print(f"Skipping specs for version {ver_name} due to fetch error.")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            tables = soup.find_all("table")

            # Remove previous specs for this version to avoid duplicates on re-crawl
            self.con.execute("DELETE FROM specs WHERE version_link = ?", (ver_link,))

            specs_inserted = 0
            for table in tables:
                # Category title from thead
                category_elem = table.select_one("thead th")
                if not category_elem:
                    # Fallback to general table header if structure is slightly different
                    category_elem = table.select_one("th")
                    
                category = self.clean_text(category_elem.text) if category_elem else "Général"
                
                # Skip the versions list table itself if it somehow gets re-parsed
                if "version" in category.lower() and table.select_one("td.version"):
                    continue

                rows = table.select("tbody tr")
                for row in rows:
                    key_elem = row.select_one("th")
                    val_elem = row.select_one("td")

                    if not key_elem:
                        continue

                    key = self.clean_text(key_elem.text)
                    val = self.clean_text(val_elem.text) if val_elem else ""

                    # For equipment checklists, if value is empty, it means yes (it's checked)
                    if not val and any(x in category.lower() for x in ["équipement", "aide", "audio", "sécurité", "intérieur", "extérieur", "fonctionnel"]):
                        val = "Oui"

                    if key:
                        self.con.execute(
                            "INSERT INTO specs (version_link, category, spec_key, spec_value) VALUES (?, ?, ?, ?)",
                            (ver_link, category, key, val)
                        )
                        specs_inserted += 1

            # Log this version as fully processed
            self.con.execute("INSERT OR IGNORE INTO processed_versions (link) VALUES (?)", (ver_link,))
            time.sleep(0.5)

        print("-> Stage 3 Completed. Comprehensive specifications successfully saved.")

    def run_full_crawler(self, max_pages=15):
        """Executes all three stages of the scraping pipeline"""
        self.scrape_models(max_pages=max_pages)
        self.scrape_versions()
        self.scrape_specs()
        print("\nAll systems successfully scraped and stored in DuckDB!")

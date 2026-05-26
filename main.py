from scraper import AutomobileTnScraper
import duckdb
import csv
import os

def export_to_csv(db_path="cars.duckdb", csv_path="cars_detailed.csv"):
    print("\n=== STAGE 4: Pivot specs & Exporting to CSV ===")
    if not os.path.exists(db_path):
        print(f"Database {db_path} does not exist. Cannot export.")
        return

    con = duckdb.connect(db_path)

    # 1. Fetch all models and build a lookup map
    models = con.execute("SELECT brand, name, link, image_url FROM models").fetchall()
    models_map = {}
    for brand, m_name, link, img in models:
        models_map[link] = {
            "brand": brand,
            "model_name": m_name,
            "image_url": img
        }

    # 2. Fetch all unique spec keys to act as columns
    # Group by category to keep columns ordered logically by category
    unique_specs = con.execute("""
        SELECT category, spec_key, COUNT(*) as cnt 
        FROM specs 
        GROUP BY category, spec_key 
        ORDER BY 
            CASE 
                WHEN category LIKE '%Caract%' THEN 1
                WHEN category LIKE '%Motor%' THEN 2
                WHEN category LIKE '%Transm%' THEN 3
                WHEN category LIKE '%Dim%' THEN 4
                WHEN category LIKE '%Perf%' THEN 5
                WHEN category LIKE '%Cons%' THEN 6
                WHEN category LIKE '%Séc%' THEN 7
                WHEN category LIKE '%Aide%' THEN 8
                WHEN category LIKE '%Ext%' THEN 9
                WHEN category LIKE '%Aud%' THEN 10
                WHEN category LIKE '%Int%' THEN 11
                WHEN category LIKE '%Fonc%' THEN 12
                ELSE 13
            END, cnt DESC
    """).fetchall()

    spec_columns = [row[1] for row in unique_specs]
    spec_categories = {row[1]: row[0] for row in unique_specs}

    # 3. Fetch all version and spec data
    versions = con.execute("""
        SELECT model_link, name, link, price, price_numeric, original_price, original_price_numeric, is_promo, status
        FROM versions
    """).fetchall()

    # Load all specs into a map: {version_link: {spec_key: spec_value}}
    specs_raw = con.execute("SELECT version_link, spec_key, spec_value FROM specs").fetchall()
    specs_map = {}
    for ver_link, key, val in specs_raw:
        if ver_link not in specs_map:
            specs_map[ver_link] = {}
        specs_map[ver_link][key] = val

    # 4. Define CSV headers
    headers = [
        "Brand",
        "Model",
        "Version Name",
        "Price",
        "Price Numeric (DT)",
        "Original Price",
        "Original Price Numeric (DT)",
        "Is Promo",
        "Status",
        "URL",
        "Image URL"
    ] + spec_columns

    # 5. Build rows
    rows = []
    for m_link, ver_name, ver_link, price, price_num, orig_price, orig_price_num, is_promo, status in versions:
        # Lookup model info
        model_info = models_map.get(m_link, {"brand": "", "model_name": "", "image_url": ""})
        
        row_data = {
            "Brand": model_info["brand"],
            "Model": model_info["model_name"],
            "Version Name": ver_name,
            "Price": price,
            "Price Numeric (DT)": price_num if price_num is not None else "",
            "Original Price": orig_price,
            "Original Price Numeric (DT)": orig_price_num if orig_price_num is not None else "",
            "Is Promo": "Oui" if is_promo else "Non",
            "Status": status,
            "URL": ver_link,
            "Image URL": model_info["image_url"]
        }

        # Fill spec values
        ver_specs = specs_map.get(ver_link, {})
        for col in spec_columns:
            cat = spec_categories[col]
            val = ver_specs.get(col, "")
            
            # If it's an equipment checklist category and it's missing, it means "Non"
            if not val and any(x in cat.lower() for x in ["équipement", "aide", "audio", "sécurité", "intérieur", "extérieur", "fonctionnel"]):
                val = "Non"
                
            row_data[col] = val

        rows.append(row_data)

    con.close()

    # 6. Write to CSV
    with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    print(f"-> Export Completed. Detailed flat CSV saved to: {csv_path}")
    print(f"   Exported {len(rows)} car versions with {len(spec_columns)} technical & equipment fields.")

if __name__ == "__main__":
    # Create and run crawler
    scraper = AutomobileTnScraper(db_path="cars.duckdb")
    
    try:
        # We perform a full crawl
        scraper.run_full_crawler(max_pages=15)
        
        # Export all data to a clean CSV
        export_to_csv(db_path="cars.duckdb", csv_path="cars_detailed.csv")
    except KeyboardInterrupt:
        print("\n[Info] Crawl interrupted by user. Saving progress and exporting what we have...")
        export_to_csv(db_path="cars.duckdb", csv_path="cars_detailed.csv")
    finally:
        scraper.close()

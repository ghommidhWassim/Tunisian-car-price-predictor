from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import time
import csv

# ---------------- SELENIUM SETUP ----------------
CHROMEDRIVER_PATH = "/home/wassim/Documents/chromedriver"

service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service)

wait = WebDriverWait(driver, 15)

# ---------------- CONFIG ----------------
BASE_URL = "https://www.tayara.tn/listing/k/voiture/?page="

results = []
page = 0


# ---------------- HELPERS ----------------
def safe_get_text(selector):
    try:
        return driver.find_element(By.CSS_SELECTOR, selector).text.strip()
    except:
        return None


# ---------------- SCRAPING LOOP ----------------
while True:
    if page == 67:
        print("🚫 Reached page limit (67)")
        break
    page += 1
    print(f"\n📄 Page {page}")

    driver.get(BASE_URL + str(page))

    # wait until listings load
    wait.until(
        EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, "article.mx-0")
        )
    )

    time.sleep(2)

    # ---------------- GET ALL LINKS ----------------
    links = driver.execute_script("""
        return Array.from(
            document.querySelectorAll('article.mx-0 a')
        ).map(a => a.href);
    """)

    # remove duplicates
    links = list(set(links))

    # if not links:
    #     print("🚫 No more pages")
    #     break

    print(f"🔗 {len(links)} links found")

    # ---------------- VISIT EACH LISTING ----------------
    for link in links:

        try:
            driver.get(link)

            # wait for page
            wait.until(
                EC.presence_of_element_located(
                    (By.TAG_NAME, "h1")
                )
            )

            time.sleep(1.5)

            # ---------------- BASIC INFO ----------------
            title = safe_get_text("h1.text-gray-700")

            price_elem = driver.find_elements(
                By.CSS_SELECTOR,
                "data.font-bold"
            )

            price = (
                price_elem[0].get_attribute("value")
                if price_elem else None
            )

            description = safe_get_text("p.text-sm")

            # ---------------- SPECS ----------------
            specs = {}

            spec_items = driver.find_elements(
                By.CSS_SELECTOR,
                "ul.grid.gap-3.grid-cols-12 li.col-span-6"
            )

            for item in spec_items:

                try:
                    key_elem = item.find_element(
                        By.CSS_SELECTOR,
                        "span.text-gray-600\\/80"
                    )

                    value_elem = item.find_element(
                        By.CSS_SELECTOR,
                        "span.text-gray-700\\/80"
                    )

                    key = key_elem.text.strip()
                    value = value_elem.text.strip()

                    specs[key] = value

                except Exception as e:
                    print("⚠ spec extraction error:", e)
                    continue

            # ---------------- FINAL OBJECT ----------------
            car_data = {
                "title": title,
                "price": price,
                "description": description,
                "url": link
            }

            # dynamically add all specs
            car_data.update(specs)

            if title:
                print(f"🟢 {title} | {price}")

                results.append(car_data)

        except Exception as e:
            print("❌ listing error:", e)
            continue

    


# ---------------- CLOSE DRIVER ----------------
driver.quit()

# ---------------- SAVE CSV ----------------
if results:

    # collect ALL possible fields dynamically
    all_keys = set()

    for row in results:
        all_keys.update(row.keys())

    all_keys = list(all_keys)

    with open(
        "tayara_cars.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as output_file:

        writer = csv.DictWriter(
            output_file,
            fieldnames=all_keys
        )

        writer.writeheader()
        writer.writerows(results)

    print("\n💾 Saved to tayara_cars.csv")

else:
    print("⚠ No data scraped")

print(f"\n✅ DONE: {len(results)} listings scraped")
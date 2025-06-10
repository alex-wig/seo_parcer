import os
import time
import random
import asyncio
import aiohttp
import io
import requests
import pandas as pd
from flask import Flask, render_template, request, send_file
from bs4 import BeautifulSoup
from urllib.parse import quote
import tldextract
from fake_useragent import UserAgent

app = Flask(__name__)
ua = UserAgent()

# --- Настройки ---
PROXIES = []  # Пример: ["http://proxy1:port"]
USE_PROXIES = False

EXCLUDE_DOMAINS = [
    "2gis", "yandex", "avito", "google", "market.yandex", "mail.ru", 
    "ozon", "wildberries", "aliexpress", "amazon", "ebay", "ya", "bing"
]

REGIONS = [
    "Вся Россия", "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург",
    "Казань", "Нижний Новгород", "Краснодар", "Челябинск", "Самара"
]

# --- Функции ---
def random_delay():
    return random.uniform(2, 5)

def exists_path(base_url, path):
    try:
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        resp = requests.head(url, headers={"User-Agent": ua.random}, timeout=5)
        return resp.status_code == 200
    except:
        return False

def fetch_yandex_results(query, max_results=10):
    urls = set()
    page = 0

    while len(urls) < max_results:
        try:
            url = f"https://yandex.ru/search/?text={quote(query)}&p={page}"
            headers = {"User-Agent": ua.random}
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.select("a.Link, a.OrganicTitle-Link")

            if not links:
                print("Нет ссылок на странице выдачи")
                break

            for link in links:
                href = link.get("href")
                if href and href.startswith("http") and not any(domain in href for domain in EXCLUDE_DOMAINS):
                    urls.add(href)
                    if len(urls) >= max_results:
                        break

            page += 1
            time.sleep(random_delay())
        except Exception as e:
            print(f"[Ошибка Яндекс-поиска] {e}")
            break

    print(f"[DEBUG] Найдено URL: {len(urls)}")
    return list(urls)[:max_results]

async def fetch_url(session, url):
    try:
        proxy = random.choice(PROXIES) if USE_PROXIES and PROXIES else None
        headers = {
            "User-Agent": ua.random,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9"
        }
        async with session.get(url, headers=headers, proxy=proxy, timeout=30) as resp:
            if resp.status == 200:
                return await resp.text()
    except Exception as e:
        print(f"[Ошибка запроса] {url}: {str(e)[:80]}")
    return None

async def parse_seo(session, url):
    html = await fetch_url(session, url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    domain = tldextract.extract(url).domain

    return {
        "URL": url,
        "Title": soup.title.text.strip() if soup.title else "—",
        "Description": (soup.find("meta", attrs={"name": "description"})["content"].strip()
                        if soup.find("meta", attrs={"name": "description"}) else "—"),
        "H1": soup.h1.text.strip() if soup.h1 else "—",
        "Robots.txt": "✓" if exists_path(url, "robots.txt") else "✗",
        "Sitemap.xml": "✓" if exists_path(url, "sitemap.xml") else "✗",
        "Canonical": "✓" if soup.find("link", rel="canonical") else "✗",
        "Open Graph": "✓" if soup.find("meta", property="og:title") else "✗",
        "ЧПУ": "✓" if "-" in url.split(domain)[-1] else "✗",
        "SSL": "✓" if url.startswith("https") else "✗"
    }

# --- Flask маршруты ---
@app.route("/", methods=["GET", "POST"])
def index():
    results = []

    if request.method == "POST":
        query = request.form.get("query", "").strip()
        region = request.form.get("region", "Вся Россия")

        if not query:
            return render_template("index.html", regions=REGIONS, error="Введите запрос")

        full_query = f"{query} {region}" if region != "Вся Россия" else query
        urls = fetch_yandex_results(full_query, max_results=30)

        async def gather_all():
            async with aiohttp.ClientSession() as session:
                tasks = [parse_seo(session, url) for url in urls]
                return await asyncio.gather(*tasks)

        results = asyncio.run(gather_all())
        results = [r for r in results if r]

    return render_template("index.html", regions=REGIONS, results=results)

@app.route("/export", methods=["POST"])
def export():
    data = request.json.get("data", [])
    df = pd.DataFrame(data)

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="seo_analysis.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# --- Запуск ---
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

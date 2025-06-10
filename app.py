import asyncio
import random
import time
from urllib.parse import quote
from functools import wraps
import io

import aiohttp
import pandas as pd
import tldextract
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from flask import Flask, render_template, request, send_file

# --- Конфигурация ---
app = Flask(__name__)
ua = UserAgent()

# Прокси (если нужны)
PROXIES = []  # Пример: ["http://proxy1:port", "http://proxy2:port"]
USE_PROXIES = False  # Включить, если используете прокси

# Исключаемые домены (чтобы не парсить Яндекс.Маркет, Авито и т.д.)
EXCLUDE_DOMAINS = [
    "2gis", "yandex", "avito", "google", "market.yandex", "mail.ru", 
    "ozon", "wildberries", "aliexpress", "amazon", "ebay"
]

# Регионы для поиска
REGIONS = [
    "Вся Россия", "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург",
    "Казань", "Нижний Новгород", "Краснодар", "Челябинск", "Самара"
]

# --- Вспомогательные функции ---
def random_delay():
    """Случайная задержка между запросами."""
    return random.uniform(1, 3)

async def fetch_url(session, url):
    """Асинхронный запрос к URL."""
    try:
        proxy = random.choice(PROXIES) if USE_PROXIES and PROXIES else None
        async with session.get(url, proxy=proxy, timeout=10) as resp:
            if resp.status == 200:
                return await resp.text()
    except Exception as e:
        print(f"Ошибка при запросе {url}: {str(e)[:100]}")
    return None

def exists_path(base_url, path):
    """Проверяет наличие файла (robots.txt, sitemap.xml) на сайте."""
    try:
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        resp = requests.head(url, headers={"User-Agent": ua.random}, timeout=5)
        return resp.status_code == 200
    except:
        return False

# --- Парсинг выдачи Яндекса ---
def fetch_yandex_results(query, max_results=50):
    """Получает список URL из поисковой выдачи Яндекса."""
    urls = set()
    page = 0
    
    while len(urls) < max_results:
        try:
            url = f"https://yandex.ru/search/?text={quote(query)}&p={page}"
            headers = {"User-Agent": ua.random}
            resp = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.select("a.Link, a.OrganicTitle-Link")  # Селекторы могут меняться!
            
            if not links:
                break  # Больше нет результатов
                
            for link in links:
                href = link.get("href")
                if href and href.startswith("http") and not any(domain in href for domain in EXCLUDE_DOMAINS):
                    urls.add(href)
                    if len(urls) >= max_results:
                        break
            
            page += 1
            time.sleep(random_delay())  # Задержка между страницами
            
        except Exception as e:
            print(f"Ошибка парсинга Яндекса: {e}")
            break
    
    return list(urls)[:max_results]

# --- SEO-анализ сайтов ---
async def parse_seo(session, url):
    """Анализирует SEO-параметры сайта."""
    html = await fetch_url(session, url)
    if not html:
        return None
    
    soup = BeautifulSoup(html, "html.parser")
    domain = tldextract.extract(url).domain
    
    return {
        "URL": url,
        "Title": soup.title.text.strip() if soup.title else "—",
        "Description": (soup.find("meta", attrs={"name": "description"})["content"].strip() 
                      if soup.find("meta", attrs={"name": "description"}) else "—",
        "H1": soup.h1.text.strip() if soup.h1 else "—",
        "Robots.txt": "✓" if exists_path(url, "robots.txt") else "✗",
        "Sitemap.xml": "✓" if exists_path(url, "sitemap.xml") else "✗",
        "Canonical": "✓" if soup.find("link", rel="canonical") else "✗",
        "Open Graph": "✓" if soup.find("meta", property="og:title") else "✗",
        "ЧПУ": "✓" if "-" in url.split(domain)[-1] else "✗",
        "SSL": "✓" if url.startswith("https") else "✗"
    }

# --- Основные маршруты Flask ---
@app.route("/", methods=["GET", "POST"])
async def index():
    """Главная страница с формой поиска."""
    results = []
    
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        region = request.form.get("region", "Вся Россия")
        
        if not query:
            return render_template("index.html", regions=REGIONS, error="Введите запрос")
        
        search_query = f"{query} {region}" if region != "Вся Россия" else query
        urls = fetch_yandex_results(search_query, max_results=50)
        
        # Асинхронный парсинг всех сайтов
        async with aiohttp.ClientSession(headers={"User-Agent": ua.random}) as session:
            tasks = [parse_seo(session, url) for url in urls]
            results = await asyncio.gather(*tasks)
            results = [r for r in results if r]  # Фильтруем None
    
    return render_template("index.html", regions=REGIONS, results=results)

@app.route("/export", methods=["POST"])
def export():
    """Экспорт результатов в Excel."""
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

# --- Запуск приложения ---
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")

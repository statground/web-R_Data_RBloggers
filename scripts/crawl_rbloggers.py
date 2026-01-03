import os
import re
import json
import time
import base64
import hashlib
import datetime as dt
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

HOME_URL = "https://www.r-bloggers.com/"
PAGE_URL = "https://www.r-bloggers.com/page/{page}/"


def sha1_hex(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def safe_get(session: requests.Session, url: str) -> requests.Response:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp


def collect_front_urls(session: requests.Session, max_pages_from_home: int = 1, max_urls=None):
    """
    Collect post URLs visible on home page (and optional /page/2, /page/3...)
    """
    urls = []
    seen = set()

    for page in range(1, max_pages_from_home + 1):
        list_url = HOME_URL if page == 1 else PAGE_URL.format(page=page)

        try:
            resp = safe_get(session, list_url)
        except Exception as e:
            print(f"[collect fail] {list_url} -> {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # R-Bloggers listing usually uses h3 > a for titles
        page_links = soup.select("h3 > a")
        if not page_links:
            break

        for a in page_links:
            href = a.get("href")
            if not href:
                continue
            href = href.strip().split("#")[0]

            # Typical post URL pattern includes year at path start
            if not href.startswith("https://www.r-bloggers.com/20"):
                continue

            if href in seen:
                continue

            seen.add(href)
            urls.append(href)

    if max_urls:
        urls = urls[:max_urls]
    return urls


def get_meta(soup, name=None, prop=None):
    if name:
        tag = soup.find("meta", attrs={"name": name})
    else:
        tag = soup.find("meta", attrs={"property": prop})
    return tag["content"].strip() if tag and tag.get("content") else None


def parse_jsonld_article(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        txt = script.string or script.text
        if not txt:
            continue
        try:
            data = json.loads(txt)
        except Exception:
            continue
        data = data if isinstance(data, list) else [data]
        for item in data:
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            types = []
            if isinstance(t, str):
                types = [t.lower()]
            elif isinstance(t, list):
                types = [x.lower() for x in t if isinstance(x, str)]
            if any(x in ("article", "blogposting") for x in types):
                return item
    return None


def extract_author_from_jsonld(j):
    if not j:
        return None
    author = j.get("author")
    if isinstance(author, dict):
        return author.get("name") or author.get("@id")
    if isinstance(author, list) and author:
        a = author[0]
        if isinstance(a, dict):
            return a.get("name") or a.get("@id")
        if isinstance(a, str):
            return a
    if isinstance(author, str):
        return author
    return None


def get_main_block(soup):
    cands = [
        soup.find("article"),
        soup.find("div", class_="entry-content"),
        soup.find("div", class_="post-content"),
        soup.find("div", id="content"),
    ]
    for c in cands:
        if c:
            return c
    return soup.body


def clean_text(txt: str) -> str:
    txt = re.sub(r"\r\n?", "\n", txt)
    txt = re.sub(r"\n{2,}", "\n\n", txt)
    return txt.strip()


def download_img(session, url, max_bytes=500_000):
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        content = resp.content
        if len(content) > max_bytes:
            return None
        b64 = base64.b64encode(content).decode("utf-8")
        mime = "image/jpeg"
        u = url.lower()
        if u.endswith(".png"):
            mime = "image/png"
        elif u.endswith(".gif"):
            mime = "image/gif"
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def extract_links_images(block, base_url, session):
    internal, external, images = [], [], []
    base_domain = urlparse(base_url).netloc

    for a in block.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        text = a.get_text(strip=True) or None
        (internal if base_domain in urlparse(href).netloc else external).append(
            {"href": href, "text": text}
        )

    for img in block.find_all("img", src=True):
        src = urljoin(base_url, img["src"])
        alt = img.get("alt", "").strip() or None
        b64 = download_img(session, src)
        images.append({"src": src, "alt": alt, "base64": b64})

    return internal, external, images


def wordcount(txt: str) -> int:
    return len(re.findall(r"\w+", txt, re.UNICODE))


def crawl_article(url: str, session: requests.Session):
    resp = safe_get(session, url)
    soup = BeautifulSoup(resp.text, "lxml")

    data = {}
    data["url"] = resp.url

    canon = soup.find("link", rel="canonical")
    data["canonical_url"] = canon["href"].strip() if canon and canon.get("href") else None

    data["html_title"] = soup.title.get_text(strip=True) if soup.title else None
    h1 = soup.find("h1")
    data["h1_title"] = h1.get_text(strip=True) if h1 else None

    data["meta_description"] = get_meta(soup, name="description")
    data["meta_keywords"] = get_meta(soup, name="keywords")
    data["og_title"] = get_meta(soup, prop="og:title")
    data["og_description"] = get_meta(soup, prop="og:description")
    data["og_image"] = get_meta(soup, prop="og:image")
    data["twitter_title"] = get_meta(soup, name="twitter:title")
    data["twitter_description"] = get_meta(soup, name="twitter:description")

    jld = parse_jsonld_article(soup)
    data["raw_jsonld_article"] = jld

    if jld:
        data["article_headline"] = jld.get("headline")
        data["article_section"] = jld.get("articleSection")
        data["article_tags"] = jld.get("keywords")
        data["article_author"] = extract_author_from_jsonld(jld)
        data["article_published"] = jld.get("datePublished")
        data["article_modified"] = jld.get("dateModified")
    else:
        data["article_headline"] = None
        data["article_section"] = None
        data["article_tags"] = None
        data["article_author"] = None
        data["article_published"] = None
        data["article_modified"] = None

    block = get_main_block(soup)
    if block is None:
        block = soup.body

    for bad in block.find_all(["script", "style", "nav", "footer", "aside"]):
        bad.decompose()

    txt = clean_text(block.get_text("\n", strip=True))
    data["main_text"] = txt
    data["main_html"] = str(block)

    wc = wordcount(txt)
    data["word_count"] = wc
    data["reading_time_min"] = round(wc / 200, 1)

    internal, external, imgs = extract_links_images(block, data["url"], session)
    data["internal_links"] = internal
    data["external_links"] = external
    data["images"] = imgs

    html_tag = soup.find("html")
    data["lang"] = html_tag.get("lang") if html_tag else None

    # UTC crawl time
    data["crawled_at_utc"] = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    return data


def main():
    max_pages = int(os.getenv("MAX_PAGES_FROM_HOME", "1"))
    sleep_sec = float(os.getenv("SLEEP_SEC", "1.0"))

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    base_dir = os.path.join(repo_root, "by_created")
    os.makedirs(base_dir, exist_ok=True)

    session = get_session()

    print("🔍 collecting urls from frontpage...")
    urls = collect_front_urls(session, max_pages_from_home=max_pages, max_urls=None)
    print(f"📌 collected urls: {len(urls)}")

    new_count = 0
    now_utc = dt.datetime.utcnow().replace(microsecond=0)
    year = f"{now_utc.year:04d}"
    month = f"{now_utc.month:02d}"
    out_dir = os.path.join(base_dir, year, month)
    os.makedirs(out_dir, exist_ok=True)

    for url in urls:
        file_id = sha1_hex(url)  # deterministic id by URL
        out_path = os.path.join(out_dir, f"{file_id}.json")

        if os.path.exists(out_path):
            continue  # already saved in this month directory

        try:
            data = crawl_article(url, session)
        except Exception as e:
            print(f"[fail] {url} -> {e}")
            continue

        payload = {
            "id": file_id,
            "url": url,
            "created_at_utc": now_utc.isoformat() + "Z",
            "data": data,
        }

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        new_count += 1
        print(f"✅ new saved: {os.path.relpath(out_path, repo_root)}")
        time.sleep(sleep_sec)

    print(f"🎉 done. new files: {new_count}")

    # action result for commit step / debug
    with open(os.path.join(repo_root, ".action_result.json"), "w", encoding="utf-8") as f:
        json.dump({"new_files": new_count}, f)


if __name__ == "__main__":
    main()

"""
deep_crawl.py
=============
Multi-domain crawler extending the dataset to 75,000+ pages.
Covers: Cars, Reddit, Education, Science, Tech, and Entertainment.
"""
import os, sys
from urllib.parse import urlparse
from pymongo import MongoClient

import config
from crawler import Crawler, canonicalize_url

TARGET_TOTAL_PAGES = int(os.getenv("TARGET_TOTAL_PAGES", "120000"))

def get_seeds_and_visited():
    """Combines new domain seeds and discovered outlinks."""
    client = MongoClient(config.MONGO_URI)
    pages = client[config.MONGO_DB_NAME]["raw_pages"]
    
    visited = set(doc["url"] for doc in pages.find({}, {"url": 1}))
    print(f"Already in database: {len(visited)} pages")
    
    # 1. New unvisited seeds from config.TARGET_SITES (Cars, Reddit, Education, Tech, etc.)
    new_primary_seeds = []
    for site in config.TARGET_SITES:
        canon = canonicalize_url(site)
        if canon not in visited:
            new_primary_seeds.append(canon)
    print(f"New primary domain seeds to start from: {len(new_primary_seeds)}")
    
    # 2. Collect outlinks from existing crawled pages
    all_outlinks = set()
    for doc in pages.find({}, {"links": 1}):
        for link in doc.get("links", []):
            canon = canonicalize_url(link)
            if canon not in visited:
                all_outlinks.add(canon)
    client.close()
    
    target_domains = set()
    for site in config.TARGET_SITES:
        netloc = urlparse(site).netloc.lower()
        target_domains.add(netloc.replace("www.", ""))
    
    filtered_outlinks = [
        l for l in all_outlinks
        if any(d in urlparse(l).netloc.lower() for d in target_domains)
    ]
    print(f"Target outlinks available for expansion: {len(filtered_outlinks)}")
    
    # Prioritize brand new domains first, then discovered outlinks
    combined_seeds = new_primary_seeds + filtered_outlinks
    return combined_seeds, visited

if __name__ == "__main__":
    seeds, already_visited = get_seeds_and_visited()
    
    current_count = len(already_visited)
    needed = max(5000, TARGET_TOTAL_PAGES - current_count)
    print(f"Current pages: {current_count} | Target: {TARGET_TOTAL_PAGES} | Pages needed this run: {needed}")
    
    crawler = Crawler(max_pages=needed)
    crawler.visited = already_visited
    
    total = crawler.run(seed_urls=seeds)
    print(f"Crawl session complete. New pages added: {total}")
    
    # Verify final total
    client = MongoClient(config.MONGO_URI)
    final_total = client[config.MONGO_DB_NAME]["raw_pages"].count_documents({})
    client.close()
    print(f"Total documents in database now: {final_total}")
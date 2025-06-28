#!/usr/bin/env python3
"""
Improved version of your requests.py file
==========================================

This script improves your existing requests.py by adding:
- Proper HTML parsing with BeautifulSoup
- Structured data extraction
- JSON output
- Multiple keyword support
- Error handling
"""

import http.client
import json
from datetime import datetime
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from typing import List, Optional
import re

@dataclass
class EbayProduct:
    """Simple data class for eBay product information"""
    title: str
    price: Optional[str] = None
    price_numeric: Optional[float] = None
    currency: Optional[str] = None
    condition: Optional[str] = None
    seller_type: Optional[str] = None
    item_url: Optional[str] = None
    shipping_cost: Optional[str] = None
    keyword: Optional[str] = None

def extract_price_info(price_text: str) -> tuple[Optional[float], Optional[str]]:
    """Extract numeric price and currency from price text"""
    if not price_text:
        return None, None
        
    # Remove extra whitespace and normalize
    price_text = re.sub(r'\s+', ' ', price_text.strip())
    
    # Pattern to match price with currency
    price_pattern = r'(?:EUR|USD|\$|€)\s*([\d\.,]+)|(?:([\d\.,]+))\s*(?:EUR|USD|\$|€)'
    
    match = re.search(price_pattern, price_text, re.IGNORECASE)
    if match:
        price_str = match.group(1) or match.group(2)
        # Convert German format (123.456,78) to float
        if ',' in price_str and '.' in price_str:
            # German format: 1.234,56
            price_str = price_str.replace('.', '').replace(',', '.')
        elif ',' in price_str:
            # Simple comma format: 1234,56
            price_str = price_str.replace(',', '.')
        
        try:
            numeric_price = float(price_str)
            currency = 'EUR' if 'EUR' in price_text or '€' in price_text else 'USD'
            return numeric_price, currency
        except ValueError:
            pass
    
    return None, None

def fetch_ebay_html(keyword: str) -> tuple[Optional[str], Optional[BeautifulSoup]]:
    """
    Fetch eBay HTML using http.client (your original approach)
    Returns both raw HTML and parsed BeautifulSoup object
    """
    # URL encode the keyword
    encoded_keyword = quote_plus(keyword)
    
    # Create connection
    conn = http.client.HTTPSConnection("www.ebay.de")
    
    # Payload (empty as in your original)
    payload = ""
    
    # Headers from your original requests.py
    headers = {
        'cookie': "nonsession=BAQAAAZZay1gcAAaAADMABWo8iB80MDM1MADKACBsHbufYTRjMjkwOWIxOTcwYTY3YTFlMTUwMjE1ZmZmZTBmYjIAywABaFtbpzETv5CUDguOgs6O%2FJX3ky1V9HhDsQ**; s=CgAD4ACBoXKYfYTRjMjkwOWIxOTcwYTY3YTFlMTUwMjE1ZmZmZTBmYjLuQjhi; dp1=bbl%2FPK6c1dbb9f%5E; ebay=%255Esbf%253D%2523000000%255E; ns1=BAQAAAZZay1gcAAaAANgAU2o8iB9jNjl8NjAxXjE3NTA4MTU5MDM5NDBeXjFeM3wyfDV8NHw3fDEwfDQyfDQzfDExXl5eNF4zXjEyXjEyXjJeMV4xXjBeMV4wXjFeNjQ0MjQ1OTA3Na0vmQThFk9%2FBb%2Fdmr%2BrqYJuvQbF; __uzma=27dab032-6c15-44a2-bc99-4cd07cf73236; __uzmb=1750815903; __uzmc=927571012048; __uzmd=1750815903; __uzme=6587; __uzmf=7f6000985ad54c-38e0-49d5-89bf-616d96da0be617508159038710-fae58be4a3a3a38010",
        'User-Agent': "insomnia/11.2.0"
    }
    
    # Build the search URL path (your original URL structure)
    search_path = f"/sch/i.html?_from=R40&_nkw={encoded_keyword}&_sacat=0&LH_BIN=1&_sop=10&rt=nc&LH_PrefLoc=3"
    
    try:
        print(f"Fetching eBay data for keyword: {keyword}")
        
        # Make the request (your original approach)
        conn.request("GET", search_path, payload, headers)
        
        # Get response
        res = conn.getresponse()
        data = res.read()
        
        # Save raw HTML (like your original)
        # html_filename = f"ebay_response_{keyword}.html"
        # with open(html_filename, "wb") as file:
        #     file.write(data)
        
        # print(f"Raw HTML saved to: {html_filename}")
        
        # Parse HTML with BeautifulSoup
        html_content = data.decode("utf-8")
        soup = BeautifulSoup(html_content, 'html.parser')
        
        return html_content, soup
        
    except Exception as e:
        print(f"Error fetching HTML: {str(e)}")
        return None, None
    finally:
        conn.close()

def parse_products_from_soup(soup: BeautifulSoup, keyword: str) -> List[EbayProduct]:
    """Parse products from BeautifulSoup object"""
    if not soup:
        return []
    
    products = []
    
    # Find all product elements
    product_elements = soup.select('.s-item')
    
    for i, element in enumerate(product_elements, 1):
        try:
            # Extract title
            title_elem = element.select_one('.s-item__title span[role="heading"]')
            if not title_elem:
                title_elem = element.select_one('.s-item__title')
            
            if not title_elem:
                continue
                
            title = title_elem.get_text(strip=True)
            
            # Skip generic eBay ads
            if title.lower() in ['shop on ebay', 'ebay'] or not title:
                continue
            
            # Initialize product
            product = EbayProduct(title=title, keyword=keyword)
            
            # Extract price
            price_elem = element.select_one('.s-item__price .ITALIC, .s-item__price')
            if price_elem:
                price_text = price_elem.get_text(strip=True)
                product.price = price_text
                product.price_numeric, product.currency = extract_price_info(price_text)
            
            # Extract shipping cost
            shipping_elem = element.select_one('.s-item__shipping .ITALIC, .s-item__logisticsCost .ITALIC')
            if shipping_elem:
                shipping_text = shipping_elem.get_text(strip=True)
                product.shipping_cost = shipping_text
            
            # Extract condition and seller type
            subtitle_elem = element.select_one('.s-item__subtitle .SECONDARY_INFO')
            if subtitle_elem:
                subtitle_text = subtitle_elem.get_text(strip=True)
                
                # Parse condition and seller type (e.g., "Gebraucht | Privat")
                if '|' in subtitle_text:
                    parts = [part.strip() for part in subtitle_text.split('|')]
                    product.condition = parts[0] if parts else None
                    product.seller_type = parts[1] if len(parts) > 1 else None
                else:
                    product.condition = subtitle_text
            
            # Check for seller type in broader subtitle
            full_subtitle = element.select_one('.s-item__subtitle')
            if full_subtitle and not product.seller_type:
                full_text = full_subtitle.get_text(strip=True)
                if '|' in full_text:
                    parts = [part.strip() for part in full_text.split('|')]
                    if len(parts) > 1:
                        product.seller_type = parts[1]
            
            # Extract item URL
            link_elem = element.select_one('.s-item__link')
            if link_elem:
                item_url = link_elem.get('href')
                if item_url:
                    if not item_url.startswith('http'):
                        item_url = f"https://www.ebay.de{item_url}"
                    product.item_url = item_url
            
            products.append(product)
            
        except Exception as e:
            print(f"Error parsing product {i}: {str(e)}")
            continue
    
    return products

def improved_requests_scraper(keywords: List[str]):
    """
    Improved version of your requests.py that fetches and parses data
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_products = []
    
    for keyword in keywords:
        # print(f"\n{'='*50}")
        # print(f"Processing keyword: {keyword}")
        # print(f"{'='*50}")
        
        # Fetch HTML using your original approach
        html_content, soup = fetch_ebay_html(keyword)
        
        if soup:
            # Parse products
            products = parse_products_from_soup(soup, keyword)
            all_products.extend(products)
            
            print(f"Found {len(products)} products for '{keyword}'")
            
            # Show sample product
            if products:
                sample = products[0]
                print(f"\nSample product:")
                # print(f"  Title: {sample.title}")
                # print(f"  Price: {sample.price}")
                # print(f"  Condition: {sample.condition}")
                # print(f"  Seller: {sample.seller_type}")
        else:
            print(f"Failed to fetch data for '{keyword}'")
    
    # Save all products to JSON
    if all_products:
        json_filename = f"ebay_products_{timestamp}.json"
        data = [asdict(product) for product in all_products]
        
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # print(f"\n{'='*50}")
        # print(f"RESULTS SUMMARY")
        # print(f"{'='*50}")
        # print(f"Total products found: {len(all_products)}")
        # print(f"JSON data saved to: {json_filename}")
        
        # Price statistics
        prices = [p.price_numeric for p in all_products if p.price_numeric]
        # if prices:
        #     print(f"\nPrice Statistics:")
            # print(f"  Count with prices: {len(prices)}")
            # print(f"  Average price: €{sum(prices)/len(prices):.2f}")
            # print(f"  Price range: €{min(prices):.2f} - €{max(prices):.2f}")
        
        # Condition breakdown
        conditions = {}
        for product in all_products:
            condition = product.condition or "Unknown"
            conditions[condition] = conditions.get(condition, 0) + 1
        
        print(f"\nCondition Breakdown:")
        for condition, count in sorted(conditions.items()):
            print(f"  {condition}: {count}")
        
        return all_products
    else:
        print("\nNo products found!")
        return []

def main():
    """Main function - improved version of your requests.py"""
    print("Improved eBay Requests Scraper")
    print("Based on your original requests.py approach")
    print("="*60)
    
    # Keywords to search for
    keywords = [
        "xbox series x",
        "playstation 5",
        # "nintendo switch",
        "steam deck",
        "playstation 4",
    ]
    
    # Run the improved scraper
    products = improved_requests_scraper(keywords)
    
    print(f"\nScraping completed! Check the generated files:")
    # print("- ebay_response_*.html - Raw HTML files")
    print("- ebay_products_*.json - Structured product data")

if __name__ == "__main__":
    main()

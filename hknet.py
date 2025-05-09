import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
import os
import hashlib
from pathlib import Path
import json
import pytz
from dateutil import parser

HONG_KONG_TZ = pytz.timezone('Asia/Hong_Kong')

def get_thread_description(thread_url):
    """Fetch and preserve original formatted content from thread page."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(thread_url, headers=headers, timeout=10)
        response.raise_for_status()  # Raise an error for bad responses

        soup = BeautifulSoup(response.text, 'html.parser')
        container = soup.find('div', class_='article-detail-content-container')
        
        if not container:
            return None

        # Process images to ensure they have proper attributes
        for img in container.find_all('img'):
            img_src = img.get('data-src') or img.get('src')
            if img_src:
                img['src'] = img_src
                img['style'] = 'max-width:100%; height:auto;'
                img['alt'] = img.get('alt', '')  # Ensure there's an alt attribute
        
        # Remove unwanted elements
        for element in container.find_all(['script', 'style', 'iframe', 'noscript']):
            element.decompose()
        
        # Clean up empty paragraphs
        for p in container.find_all('p'):
            if not p.get_text(strip=True):
                p.decompose()
        
        # Convert content to string
        content_str = str(container)

        # Extract publication and update times from JSON-LD
        json_ld_script = soup.find('script', type='application/ld+json')
        publication_time = None
        updated_time = None

        if json_ld_script:
            json_data = json.loads(json_ld_script.string)
            publication_time = json_data.get('datePublished')
            updated_time = json_data.get('dateModified')

        # Add publication time to content if available
        if publication_time:
            content_str = f"<p>Published on: {publication_time} Updated on: {updated_time}</p>{content_str}"

        return content_str, publication_time, updated_time

    except requests.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except Exception as e:
        print(f"Couldn't fetch description from {thread_url}: {e}")

    return None

def get_existing_entries(atom_file):
    """Get existing entries from either gh-pages branch or local file"""
    existing_titles = set()
    
    # Check both possible locations (gh-pages branch and local file)
    possible_paths = [
        Path("gh-pages-deploy") / atom_file,  # From fetched gh-pages branch
        Path(atom_file)                       # Local file (if exists)
    ]
    
    for file_path in possible_paths:
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), 'xml')
                    for entry in soup.find_all('entry'):
                        if entry.title and entry.title.text:
                            normalized_title = entry.title.text.strip().lower()
                            existing_titles.add(normalized_title)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
    
    return existing_titles


def parse_time(time_element):
    """Parse time element with timezone"""
    try:
        if time_element and time_element.has_attr('title'):
            dt = datetime.strptime(time_element['title'], '%Y-%m-%d %H:%M')
            return HONG_KONG_TZ.localize(dt)  

    except Exception as e:
        print(f"Time parsing error: {e}")
    return datetime.now(HONG_KONG_TZ)


def fetch_feed(url, base_url, atom_file, title, subtitle, item_selector, link_selector, use_headers=True):

    fg = FeedGenerator()
    fg.id(url)
    fg.title(title)
    fg.link(href=url)
    fg.subtitle(subtitle)
    fg.updated(datetime.now(HONG_KONG_TZ))

    existing_titles = get_existing_entries(atom_file)
    new_entries = 0


    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' 
    }

    if use_headers:
        response = requests.get(url, headers=headers)
    else:
        response = requests.get(url)  # No headers

    if response.status_code != 200:
        print(f"Failed to retrieve {url}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')

    for thread in soup.select(item_selector):

        title_tag = thread.select_one(link_selector)
        if not title_tag:
            continue

        entry_title = title_tag.get_text(strip=True)
        if not entry_title:
            print("Skipping entry with empty title.")
            continue

        normalized_title = entry_title.strip().lower()
        if normalized_title in existing_titles:
            continue        

        thread_url = urljoin(url, title_tag['href'])

        # Initialize pub_date and updated_date with default values
        pub_date = datetime.now(HONG_KONG_TZ)  # Set to Hong Kong timezone
        updated_date = datetime.now(HONG_KONG_TZ)  # Set to Hong Kong timezone

        time_tag = thread.select_one('.listing-information .listing-date .font-en')

        if time_tag:
            time_str = time_tag.get_text(strip=True)  # Extract text from the tag
            try:
                now = datetime.now(HONG_KONG_TZ)
                time_obj = datetime.strptime(time_str, "%H:%M").time()  # Parse the time string
                pub_date = datetime.combine(now.date(), time_obj).astimezone(HONG_KONG_TZ)
                updated_date = pub_date
            except ValueError as e:
                print(f"Could not parse time '{time_str}': {e}")

        if not title or not time_tag:
            continue

        description = ''
        thread_desc = get_thread_description(thread_url)
        if thread_desc:
            content_str, publication_time_str, updated_time_str = thread_desc  
            description += f"\n\n{content_str}"  

        # Create feed entry
        entry = fg.add_entry()
        entry.id(thread_url)
        entry.title(entry_title)
        entry.link(href=thread_url)
        entry.published(pub_date)
        entry.updated(updated_date)
        entry.content(description, type='html')

        # Add author info
        if author := thread.select_one('td.author cite a'):
            entry.author({'name': author.get_text(strip=True)})

        # Check if any required field is missing
        if not entry_title or not thread_url or not pub_date:
            print("Error: Missing required fields for entry.")
            continue

        new_entries += 1
        existing_titles.add(normalized_title)

    if new_entries > 0:
        fg.atom_file(atom_file)
        print(f"Feed updated with {new_entries} new entries: {atom_file}")
    else:
        print(f"No new entries found. Feed not updated: {atom_file}")


fetch_feed(
    url='https://inews.hket.com/sran001/%E5%85%A8%E9%83%A8?mtc=20080',
    base_url='https://inews.hket.com/',
    atom_file='hknet.xml',
    title='HKET News Feed',
    subtitle='Latest news',
    item_selector='.template_item.hket-col-xs-60',
    link_selector='.listing-title a',
    use_headers=True  
)

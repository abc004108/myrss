from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import time
from bs4 import BeautifulSoup
from selenium.common.exceptions import NoSuchElementException

import pytz
from feedgen.feed import FeedGenerator
from urllib.parse import urljoin
from pathlib import Path

from datetime import datetime, timedelta
import re
HONG_KONG_TZ = pytz.timezone('Asia/Hong_Kong')

def convert_relative_time(relative_time):
    # Get the current time
    now = datetime.now()

    # Patterns for matching relative time
    patterns = {
        '秒前': (lambda x: now - timedelta(seconds=int(x))),
        '分鐘前': (lambda x: now - timedelta(minutes=int(x))),
        '小時前': (lambda x: now - timedelta(hours=int(x))),
        '天前': (lambda x: now - timedelta(days=int(x))),
        '個月前': (lambda x: now - timedelta(days=int(x) * 30)),  # Approximation
        '年前': (lambda x: now - timedelta(days=int(x) * 365))   # Approximation
    }

    # Match the relative time string
    for unit, func in patterns.items():
        match = re.match(r'(\d+)\s*' + unit, relative_time)
        if match:
            return func(match.group(1))

    return None  # Return None if no match found


def get_thread_description(thread_url):
    # Configure Selenium
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in background
    driver = webdriver.Chrome(options=chrome_options)

    try:
        # Load the page
        driver.get(thread_url)

        time.sleep(3)

        dropdown_element = driver.find_element(By.XPATH, "//select")  # Locate the dropdown
        dropdown = Select(dropdown_element)

        # Check if "最後回覆" option is available
        try:
            dropdown.select_by_visible_text("最後回覆")  # Select by visible text
        except Exception:
            print("Option '最後回覆' not found. Skipping...")
            return None  # Return None if the option is not available

        time.sleep(3)

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # Find all specific reply items
        reply_items = soup.find_all('div', class_='reply-item-wrapper')

        content_list = []

        # Extract the text and timestamp from each reply
        for reply in reply_items:
            try:
                reply_html = reply.find('div', class_='reply-view-root')
                if reply_html:
                    reply_content = str(reply_html)  # Keep the original HTML
                    timestamp = reply.find('span', class_='content-thread-create-time').get_text(strip=True)
                    content_list.append(f"<div><strong>{timestamp}:</strong> {reply_content}</div>")  # Append to list

            except AttributeError:  # Skip if any element is not found
                continue

        exact_time = None  # Initialize exact_time
        if timestamp:  # Ensure there's a timestamp to process
            exact_time = convert_relative_time(timestamp)
            if exact_time:
                print("Exact time:", exact_time.strftime('%Y-%m-%d %H:%M:%S'))

        if exact_time is not None and exact_time.tzinfo is None:
            exact_time = HONG_KONG_TZ.localize(exact_time)

        content_str = f"<p>Published on: {exact_time}</p><br>" + "<br>".join(reversed(content_list))
        
        return content_str, exact_time  # Return the accumulated content

    except NoSuchElementException:
        print("Error: Could not find the dropdown element. Skipping this site...")
        return None  # Return None if the dropdown is not found
    finally:
        driver.quit()  # Ensure the driver quits regardless of errors


def fetch_feed(url, base_url, atom_file, title, subtitle):

    fg = FeedGenerator()
    fg.id(url)
    fg.title(title)
    fg.link(href=url)
    fg.subtitle(subtitle)
    fg.updated(datetime.now(HONG_KONG_TZ))


    exclude_urls = [
        'https://www.hongkongcard.com/forum/show/47100',
        'https://www.hongkongcard.com/forum/show/49560',
        'https://www.hongkongcard.com/forum/show/5418'
    ]

    new_entries = 0

    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in background
    driver = webdriver.Chrome(options=chrome_options)

    # Load the page and wait for JavaScript to render
    driver.get(url)
    time.sleep(2)  # Wait for content to load (adjust as needed)

    html_content = driver.page_source
    driver.quit()

    soup = BeautifulSoup(html_content, 'html.parser')

    for thread in soup.select('.thread-container-parent'):

        if new_entries >= 15 :
            break

        thread_link = thread.find('a', class_='forum-thread-container')
        if not thread_link or 'href' not in thread_link.attrs:
            continue

        if 'forum' not in thread_link['href']:
            continue            

        thread_url = urljoin(base_url, thread_link['href'])
        if thread_url in exclude_urls:
            continue
        print(thread_url)


        title_span = thread.select_one('.thread-title-content')
        if not title_span:
            continue
        entry_title = title_span.get_text(strip=True)


        description = ''
        thread_desc = get_thread_description(thread_url)
        if thread_desc:
            content_str, pub_date = thread_desc  
            if content_str:
                description = f"\n{content_str}"
        
            entry_pub_date = pub_date if pub_date else datetime.now(HONG_KONG_TZ)
            print(entry_pub_date)
        


        entry = fg.add_entry()
        entry.id(f"{thread_url}#{int(time.time())}")  # Append a timestamp to make it unique
        entry.title(entry_title)
        entry.link(href=thread_url)
        entry.published(entry_pub_date)
        entry.updated(entry_pub_date)
        entry.content(description, type='html')

        new_entries += 1

    fg.atom_file(atom_file)
    print(f"Feed updated with {new_entries} new entries: {atom_file}")


fetch_feed(
    url='https://www.hongkongcard.com/forum',
    base_url='https://www.hongkongcard.com/forum',
    atom_file='hkcard.xml',
    title='Hong Kong Card Forum',
    subtitle='Latest discussions',
)

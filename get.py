import os
import re
import time
import logging
import argparse
from urllib.parse import urlparse
from curl_cffi import requests
from bs4 import BeautifulSoup

# --- Configuration ---
# The range of pages you want to scrape.
START_PAGE = 1
# The directory where raw HTML files will be stored.
DATA_DIR = "raw-paged-data"
# The file to store all the extracted permalinks.
PERMALINKS_FILE = "permalinks.txt"
# The file to log which pages have been successfully scanned, for resuming progress.
SCANNED_FILE = "scanned.txt"
# The delay in seconds to wait before retrying a failed request.
RETRY_DELAY = 30
# The browser profile to impersonate to avoid being blocked.
IMPERSONATE_BROWSER = "chrome110"

# --- Setup Logging ---
# Configures basic logging to print progress and error messages to the console.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def setup_environment():
    """
    Creates the necessary directory for storing raw HTML data if it doesn't already exist.
    """
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        logging.info(f"Created directory: {DATA_DIR}")

def get_already_scanned_pages():
    """
    Reads the scanned.txt file to build a set of page numbers that have already been
    processed. This allows the script to resume from where it left off.
    Returns:
        A set of integers representing the page numbers already scanned.
    """
    scanned_pages = set()
    if os.path.exists(SCANNED_FILE):
        with open(SCANNED_FILE, 'r') as f:
            for line in f:
                # Safely convert each line to an integer.
                try:
                    scanned_pages.add(int(line.strip()))
                except ValueError:
                    logging.warning(f"Could not parse line in {SCANNED_FILE}: {line.strip()}")
    return scanned_pages

def save_permalinks(links):
    """
    Appends a list of found permalinks to the permalinks.txt file.
    Args:
        links (list): A list of URL strings to save.
    """
    with open(PERMALINKS_FILE, 'a', encoding='utf-8') as f:
        for link in links:
            f.write(link + '\n')

def mark_page_as_scanned(page_number):
    """
    Appends a page number to the scanned.txt file to mark it as complete.
    Args:
        page_number (int): The page number that was successfully processed.
    """
    with open(SCANNED_FILE, 'a') as f:
        f.write(str(page_number) + '\n')

def extract_permalinks(html_content, permalink_prefix):
    """
    Uses BeautifulSoup to parse the HTML, find all links with the exact text "Permalink",
    and returns their href attributes if they match the blog's URL structure.
    Args:
        html_content (str): The raw HTML of a webpage.
        permalink_prefix (str): The base URL string that valid permalinks should start with.
    Returns:
        A set of unique permalink URLs found on the page.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    permalinks = set()
    
    # We now iterate through all links and check for the specific link text.
    for link in soup.find_all('a', href=True):
        # .get_text(strip=True) cleanly gets the text content of the tag.
        if link.get_text(strip=True) == 'Permalink':
            href = link['href']
            # We run a sanity check to ensure the link belongs to the target blog.
            if href.startswith(permalink_prefix):
                permalinks.add(href)
                
    return permalinks

def check_for_next_page(html_content, current_page_num):
    """
    Parses the HTML to find a valid 'Next' page link.
    A valid link is identified by being in the 'pager-right' section and
    containing either the text 'Next' or the '»' character. It must also
    point to the next sequential page.
    Args:
        html_content (str): The raw HTML of the current page.
        current_page_num (int): The number of the page just scraped.
    Returns:
        bool: True if a valid next page exists, False otherwise.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find the link on the right side of the pager.
    next_link = soup.select_one('div.pager-inner span.pager-right a')
    
    if not next_link:
        return False
        
    # Check for indicators of a "Next" link, like the text 'Next' or the '»' symbol.
    link_text = next_link.get_text(strip=True).lower()
    if 'next' not in link_text and '»' not in link_text:
        return False

    # Extract the URL and perform the sanity check.
    next_href = next_link.get('href')
    if not next_href:
        return False
    
    # Use a regular expression to find the page number in the URL.
    match = re.search(r'/page/(\d+)/?$', next_href)
    if not match:
        logging.warning(f"Found 'Next' link with an unexpected URL format: {next_href}")
        return False
        
    try:
        next_page_num = int(match.group(1))
        expected_next_page = current_page_num + 1
        
        if next_page_num == expected_next_page:
            return True
        else:
            logging.warning(
                f"Sanity check failed: Current page is {current_page_num}, but 'Next' link points to page {next_page_num}."
            )
            return False
    except (ValueError, IndexError):
        logging.warning(f"Could not parse page number from 'Next' link URL: {next_href}")
        return False

def main():
    """
    The main function to run the scraper.
    """
    parser = argparse.ArgumentParser(description="Scrape permalinks from a Typepad-style blog by iterating through its pages.")
    parser.add_argument("blog_url", help="The root URL of the blog (e.g., 'https://growabrain.typepad.com/growabrain/')")
    args = parser.parse_args()

    # --- Derive URLs from the input ---
    parsed_url = urlparse(args.blog_url)
    if not parsed_url.scheme or not parsed_url.netloc:
        logging.error("Invalid URL provided. Please include the scheme (e.g., 'https://').")
        return

    path_parts = [part for part in parsed_url.path.split('/') if part]
    blog_name = path_parts[0] if path_parts else parsed_url.netloc.split('.')[0]

    BASE_URL = f"{parsed_url.scheme}://{parsed_url.netloc}/{blog_name}/page/{{}}/"
    PERMALINK_PREFIX = f"{parsed_url.scheme}://{parsed_url.netloc}/{blog_name}/"
    
    logging.info(f"Using Base URL for pages: {BASE_URL.format('<num>')}")
    logging.info(f"Using Permalink Prefix: {PERMALINK_PREFIX}")

    setup_environment()
    scanned_pages = get_already_scanned_pages()
    logging.info(f"Found {len(scanned_pages)} already scanned pages. Resuming progress.")

    session = requests.Session()
    page_num = START_PAGE

    while True:
        if page_num in scanned_pages:
            logging.info(f"Page {page_num} already scanned. Skipping.")
            page_num += 1
            continue

        url = BASE_URL.format(page_num)
        logging.info(f"Scanning page {page_num}: {url}")

        retries = 0
        max_retries = 5
        response_content = None

        while retries < max_retries:
            try:
                response = session.get(url, impersonate=IMPERSONATE_BROWSER, timeout=20)

                if response.status_code == 200:
                    response_content = response.text
                    break
                elif response.status_code == 404:
                    logging.info(f"Page {page_num} not found (404). Assuming this is the end of the blog.")
                    response_content = "STOP"
                    break
                elif 500 <= response.status_code < 600:
                    logging.warning(f"Received server error (status {response.status_code}) for page {page_num}. Retrying in {RETRY_DELAY} seconds...")
                    time.sleep(RETRY_DELAY)
                    retries += 1
                else:
                    logging.error(f"Received unexpected status code {response.status_code} for page {page_num}. Skipping page.")
                    response_content = "SKIP"
                    break

            except Exception as e:
                logging.error(f"An exception occurred while fetching page {page_num}: {e}. Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
                retries += 1

        if response_content == "STOP":
            break
        if response_content == "SKIP" or response_content is None:
            if response_content is None:
                logging.error(f"Failed to fetch page {page_num} after {max_retries} retries. Moving to the next page.")
            page_num += 1
            continue

        # --- Process successful fetch ---
        file_path = os.path.join(DATA_DIR, f'page_{page_num}.html')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(response_content)

        permalinks = extract_permalinks(response_content, PERMALINK_PREFIX)
        if permalinks:
            save_permalinks(permalinks)
            logging.info(f"Found and saved {len(permalinks)} unique permalinks from page {page_num}")
        else:
            logging.info(f"No permalinks found on page {page_num}")

        mark_page_as_scanned(page_num)
        
        # Check if there's a next page to continue the loop
        if not check_for_next_page(response_content, page_num):
            logging.info(f"No valid 'Next' link found on page {page_num}. Concluding scrape.")
            break

        page_num += 1

    logging.info("Scraping process complete.")

if __name__ == "__main__":
    main()


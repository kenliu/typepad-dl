import os
import logging
import time
import sys
import threading
import concurrent.futures
import argparse
from urllib.parse import urljoin, urlparse
from curl_cffi import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# --- Configuration ---
# The file containing the list of post URLs to download.
PERMALINKS_FILE = "permalinks.txt"
# The file to log which posts have been successfully downloaded.
DOWNLOADED_LOG_FILE = "downloaded_permalinks.txt"
# The main directory where all downloaded posts and media will be stored.
POSTS_DIR = "posts"
# Number of concurrent download threads.
MAX_WORKERS = 8
# The browser profile to impersonate to avoid being blocked.
IMPERSONATE_BROWSER = "chrome110"
# A list of common media file extensions to look for.
MEDIA_EXTENSIONS = [
    '.pdf', '.jpg', '.jpeg', '.png', '.gif', 
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.mp3', '.wav', '.mp4', '.mov', '.zip', '.rar'
]


# --- Setup Logging ---
# Configures basic logging to print progress and error messages to the console.
# Set format to a simpler one to avoid clutter with the tqdm bar.
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def setup_environment():
    """
    Creates the main 'posts' directory if it doesn't already exist.
    """
    if not os.path.exists(POSTS_DIR):
        os.makedirs(POSTS_DIR)
        logging.info(f"Created main directory: {POSTS_DIR}")

def get_post_urls():
    """
    Reads the permalinks file and returns a list of URLs.
    Returns:
        A list of strings, where each string is a URL. Returns an empty list if the file doesn't exist.
    """
    if not os.path.exists(PERMALINKS_FILE):
        logging.error(f"Error: The file '{PERMALINKS_FILE}' was not found.")
        return []
    with open(PERMALINKS_FILE, 'r') as f:
        # Read all lines and strip any whitespace from them.
        urls = [line.strip() for line in f if line.strip()]
    return urls

def get_already_downloaded_urls():
    """
    Reads the log file to build a set of URLs that have already been downloaded.
    This allows the script to resume from where it left off.
    Returns:
        A set of strings representing the URLs already processed.
    """
    downloaded = set()
    if os.path.exists(DOWNLOADED_LOG_FILE):
        with open(DOWNLOADED_LOG_FILE, 'r') as f:
            for line in f:
                downloaded.add(line.strip())
    return downloaded

def log_url_as_downloaded(url, lock):
    """
    Appends a URL to the log file to mark it as complete in a thread-safe way.
    Args:
        url (str): The URL that was successfully processed.
        lock (threading.Lock): The lock to ensure safe file writing.
    """
    with lock:
        with open(DOWNLOADED_LOG_FILE, 'a') as f:
            f.write(url + '\n')

def generate_filename_from_url(url, blog_base_url):
    """
    Creates a clean base filename from a post URL.
    Example: 'https://.../blawg/2025/08/foo.html' -> '2025_08_foo.html'
    Args:
        url (str): The full URL of the blog post.
        blog_base_url (str): The base URL of the blog.
    Returns:
        A string representing the clean base filename.
    """
    if url.startswith(blog_base_url):
        # Remove the base part of the URL.
        short_path = url[len(blog_base_url):]
        # Replace slashes with underscores.
        return short_path.replace('/', '_')
    return os.path.basename(urlparse(url).path) # Fallback for unexpected URL formats

def download_file(session, url, save_path):
    """
    Downloads a file (HTML or media) from a URL and saves it to a specified path.
    Args:
        session: The requests session object.
        url (str): The URL of the file to download.
        save_path (str): The local path where the file should be saved.
    Returns:
        True if download was successful, False otherwise.
    """
    try:
        response = session.get(url, impersonate=IMPERSONATE_BROWSER, timeout=30)
        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
        else:
            # Using tqdm.write to prevent interfering with the progress bar
            tqdm.write(f"WARNING: Failed to download {url}. Status code: {response.status_code}")
            return False
    except Exception as e:
        tqdm.write(f"ERROR: An exception occurred while downloading {url}: {e}")
        return False

def process_url(url, blog_base_url, session, lock):
    """
    The core logic for processing a single URL. This function is executed by each thread.
    Args:
        url (str): The post URL to process.
        blog_base_url (str): The base URL of the blog.
        session: The shared requests session object.
        lock (threading.Lock): The lock for writing to the log file.
    """
    # 1. Generate the filename and paths for this post.
    base_filename = generate_filename_from_url(url, blog_base_url)
    html_filename = os.path.splitext(base_filename)[0] + ".html"
    html_save_path = os.path.join(POSTS_DIR, html_filename)

    # 2. Download the post's HTML content.
    try:
        response = session.get(url, impersonate=IMPERSONATE_BROWSER, timeout=20)
        if response.status_code != 200:
            tqdm.write(f"ERROR: Failed to fetch post HTML for {url}. Status: {response.status_code}")
            return
        html_content = response.text
    except Exception as e:
        tqdm.write(f"ERROR: An exception occurred fetching post HTML for {url}: {e}")
        return

    # 3. Save the HTML file.
    with open(html_save_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # 4. Parse the HTML to find and download media.
    soup = BeautifulSoup(html_content, 'html.parser')
    content_div = soup.find('div', class_='content')

    if content_div:
        media_links = []
        for link in content_div.find_all('a', href=True):
            href = link['href']
            path = urlparse(href).path
            is_media_link = any(path.lower().endswith(ext) for ext in MEDIA_EXTENSIONS)
            if '.typepad.com/' in href and is_media_link:
                media_links.append(urljoin(url, href))

        if media_links:
            media_dir_name = os.path.splitext(base_filename)[0]
            media_dir_path = os.path.join(POSTS_DIR, media_dir_name)
            if not os.path.exists(media_dir_path):
                os.makedirs(media_dir_path)

            for media_url in media_links:
                media_filename = os.path.basename(urlparse(media_url).path)
                media_save_path = os.path.join(media_dir_path, media_filename)
                if not os.path.exists(media_save_path):
                    download_file(session, media_url, media_save_path)
                    time.sleep(0.5) # A small polite delay
    
    # 5. Log this URL as successfully processed.
    log_url_as_downloaded(url, lock)


def main():
    """
    The main function to set up and run the concurrent downloader.
    """
    parser = argparse.ArgumentParser(description="Download all posts and their media from a Typepad-style blog.")
    parser.add_argument("blog_url", help="The root URL of the blog (e.g., 'https://growabrain.typepad.com/growabrain/')")
    args = parser.parse_args()

    # --- Derive URL from the input ---
    parsed_url = urlparse(args.blog_url)
    if not parsed_url.scheme or not parsed_url.netloc:
        logging.error("Invalid URL provided. Please include the scheme (e.g., 'https://').")
        return

    path_parts = [part for part in parsed_url.path.split('/') if part]
    blog_name = path_parts[0] if path_parts else parsed_url.netloc.split('.')[0]
    
    BLOG_BASE_URL = f"{parsed_url.scheme}://{parsed_url.netloc}/{blog_name}/"
    logging.info(f"Using Blog Base URL: {BLOG_BASE_URL}")

    setup_environment()
    all_post_urls = get_post_urls()
    downloaded_urls = get_already_downloaded_urls()

    urls_to_process = [url for url in all_post_urls if url not in downloaded_urls]
    
    if not urls_to_process:
        logging.info("All posts have already been downloaded. Exiting.")
        return

    logging.info(f"Found {len(all_post_urls)} total post URLs.")
    logging.info(f"{len(downloaded_urls)} posts already downloaded.")
    logging.info(f"Starting download of {len(urls_to_process)} new posts using {MAX_WORKERS} workers.")
    
    session = requests.Session()
    file_lock = threading.Lock()

    try:
        # Use ThreadPoolExecutor to manage a pool of threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Create a dictionary of futures
            future_to_url = {executor.submit(process_url, url, BLOG_BASE_URL, session, file_lock): url for url in urls_to_process}
            
            # Use tqdm to create a progress bar as futures complete
            for future in tqdm(concurrent.futures.as_completed(future_to_url), total=len(urls_to_process), desc="Downloading Posts"):
                try:
                    # Get the result of the future. This will also raise any exceptions that occurred.
                    future.result()
                except Exception as exc:
                    url = future_to_url[future]
                    tqdm.write(f"ERROR: {url} generated an exception: {exc}")
        
        logging.info("--- All posts processed successfully. ---")

    except KeyboardInterrupt:
        tqdm.write("\nProcess interrupted by user. Waiting for active downloads to finish before exiting.")
        # The 'with' statement for the executor handles graceful shutdown automatically.
        sys.exit(0)

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")

    finally:
        logging.info("--- Script finished. ---")


if __name__ == "__main__":
    main()

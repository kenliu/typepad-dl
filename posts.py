import os
import logging
import time
import sys
import threading
import concurrent.futures
import argparse
import re
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
# Retry logic for fetching posts
MAX_RETRIES = 3
RETRY_DELAY = 5 # seconds
# The browser profile to impersonate to avoid being blocked.
IMPERSONATE_BROWSER = "chrome110"

# Global debug flag
DEBUG_MODE = False

# --- Setup Logging ---
# Configures basic logging to print progress and error messages to the console.
# Set format to a simpler one to avoid clutter with the tqdm bar.
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def debug_print(message):
    """Print debug messages if debug mode is enabled"""
    if DEBUG_MODE:
        tqdm.write(f"DEBUG: {message}")

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

def get_file_extension_from_content_type(content_type):
    """
    Maps Content-Type headers to file extensions.
    """
    content_type_map = {
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg', 
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'image/svg+xml': '.svg',
        'image/bmp': '.bmp',
        'image/tiff': '.tiff',
        'application/pdf': '.pdf',
        'text/plain': '.txt',
        'application/msword': '.doc',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/zip': '.zip',
        'application/x-rar-compressed': '.rar',
        'video/mp4': '.mp4',
        'video/quicktime': '.mov',
        'audio/mpeg': '.mp3',
        'audio/wav': '.wav',
    }
    
    # Clean up content-type (remove charset and other parameters)
    if content_type:
        content_type = content_type.split(';')[0].strip().lower()
        return content_type_map.get(content_type)
    return None

def detect_file_extension_from_content(content):
    """
    Detects file type from the first few bytes (magic numbers).
    """
    if not content or len(content) < 8:
        return None
        
    # Check magic numbers for common file types
    if content.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    elif content.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    elif content.startswith(b'GIF87a') or content.startswith(b'GIF89a'):
        return '.gif'
    elif content.startswith(b'RIFF') and b'WEBP' in content[:12]:
        return '.webp'
    elif content.startswith(b'%PDF'):
        return '.pdf'
    elif content.startswith(b'BM'):
        return '.bmp'
    elif content.startswith(b'II*\x00') or content.startswith(b'MM\x00*'):
        return '.tiff'
    elif content.startswith(b'<svg') or content.startswith(b'<?xml'):
        return '.svg'
    
    return None

def download_file(session, url, save_path):
    """
    Downloads a file (HTML or media) from a URL and saves it to a specified path.
    Automatically detects and adds appropriate file extension if missing.
    Args:
        session: The requests session object.
        url (str): The URL of the file to download.
        save_path (str): The local path where the file should be saved.
    Returns:
        True if download was successful, False otherwise.
    """
    try:
        debug_print(f"Attempting to download: {url}")
        debug_print(f"Initial save path: {save_path}")
        
        # First try to get content type with a HEAD request (faster)
        extension = None
        try:
            head_response = session.head(url, impersonate=IMPERSONATE_BROWSER, timeout=10)
            if head_response.status_code == 200:
                content_type = head_response.headers.get('Content-Type', '')
                extension = get_file_extension_from_content_type(content_type)
                debug_print(f"Content-Type: {content_type} -> Extension: {extension}")
        except Exception as e:
            debug_print(f"HEAD request failed: {e}")
        
        # Download the actual file
        response = session.get(url, impersonate=IMPERSONATE_BROWSER, timeout=30)
        if response.status_code == 200:
            # If we didn't get extension from Content-Type, try to detect from content
            if not extension:
                extension = detect_file_extension_from_content(response.content)
                debug_print(f"Detected extension from content: {extension}")
            
            # Add extension to save path if we found one and it doesn't already have one
            final_save_path = save_path
            if extension:
                # Check if the save_path already has an extension
                current_ext = os.path.splitext(save_path)[1]
                if not current_ext:
                    final_save_path = save_path + extension
                    debug_print(f"Added extension: {final_save_path}")
                else:
                    debug_print(f"File already has extension: {current_ext}")
            else:
                debug_print("No extension detected, saving without extension")
            
            # Save the file
            with open(final_save_path, 'wb') as f:
                f.write(response.content)
            debug_print(f"Successfully downloaded: {url} ({len(response.content)} bytes) -> {final_save_path}")
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
    debug_print(f"\n--- Processing URL: {url} ---")
    
    # 1. Generate the filename and paths for this post.
    base_filename = generate_filename_from_url(url, blog_base_url)
    html_filename = os.path.splitext(base_filename)[0] + ".html"
    html_save_path = os.path.join(POSTS_DIR, html_filename)

    debug_print(f"Base filename: {base_filename}")
    debug_print(f"HTML save path: {html_save_path}")

    # 2. Download the post's HTML content with a retry loop.
    html_content = None
    for attempt in range(MAX_RETRIES):
        try:
            debug_print(f"Fetching HTML (attempt {attempt + 1}/{MAX_RETRIES})")
            response = session.get(url, impersonate=IMPERSONATE_BROWSER, timeout=20)
            if response.status_code == 200:
                html_content = response.text
                debug_print(f"Successfully fetched HTML ({len(html_content)} characters)")
                break  # Success, exit the retry loop
            elif response.status_code == 404:
                tqdm.write(f"WARNING: Post not found (404) at {url}. Skipping.")
                return # Permanent error, no need to retry or process further
            else:
                tqdm.write(f"WARNING: Got status {response.status_code} for {url} on attempt {attempt + 1}. Retrying...")
        except Exception as e:
            tqdm.write(f"WARNING: Exception for {url} on attempt {attempt + 1}: {e}. Retrying...")
        
        # Don't sleep on the last attempt
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAY)

    # If all retries failed, html_content will still be None
    if html_content is None:
        tqdm.write(f"ERROR: Failed to fetch post HTML for {url} after {MAX_RETRIES} attempts. Skipping post.")
        return

    # 3. Save the HTML file.
    with open(html_save_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    debug_print(f"Saved HTML to: {html_save_path}")

    # 4. Parse the HTML to find and download all media (images and linked files).
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Debug: Check what divs we can find
    all_divs = soup.find_all('div')
    debug_print(f"Found {len(all_divs)} total div elements")
    
    # Look for different possible content containers
    content_selectors = [
        ('div', {'class': 'content'}),
        ('div', {'class': 'entry-content'}),
        ('div', {'class': 'post-content'}),
        ('div', {'class': 'entry'}),
        ('article', {}),
        ('main', {}),
    ]
    
    content_div = None
    for tag, attrs in content_selectors:
        content_div = soup.find(tag, attrs)
        if content_div:
            debug_print(f"Found content container: {tag} with {attrs}")
            break
    
    if not content_div:
        debug_print("No content div found with standard selectors, using entire body")
        content_div = soup.find('body') or soup
    
    debug_print(f"Content container has {len(content_div.get_text())} characters of text")

    if content_div:
        # Use a set to automatically handle duplicate URLs
        media_urls = set()

        # Debug: Find all images first
        all_imgs = content_div.find_all('img')
        debug_print(f"Found {len(all_imgs)} img tags in content")
        
        # Find all images, clean their URLs to get full-size versions
        for i, img in enumerate(all_imgs):
            src = img.get('src', '')
            debug_print(f"Image {i+1}: src='{src}'")
            
            if src:
                # Check for different typepad patterns
                if '.typepad.com/' in src:
                    debug_print(f"  -> Found typepad image: {src}")
                    # Remove thumbnail suffixes like '-300wi' or '-120wi'
                    original_src = src
                    cleaned_src = re.sub(r'-\d+wi$', '', src)
                    debug_print(f"  -> Cleaned from '{original_src}' to '{cleaned_src}'")
                    # Ensure we have an absolute URL
                    full_url = urljoin(url, cleaned_src)
                    debug_print(f"  -> Full URL: {full_url}")
                    media_urls.add(full_url)
                else:
                    debug_print(f"  -> Not a typepad image, checking if should include anyway")
                    # Maybe include other image hosts too
                    full_url = urljoin(url, src)
                    debug_print(f"  -> Full URL: {full_url}")
                    media_urls.add(full_url)
            else:
                debug_print(f"  -> Image {i+1} has no src attribute")

        # Debug: Find all links
        all_links = content_div.find_all('a')
        debug_print(f"Found {len(all_links)} link tags in content")

        # Find all links that point to other Typepad assets (like PDFs, etc.)
        for i, link in enumerate(all_links):
            href = link.get('href', '')
            debug_print(f"Link {i+1}: href='{href}'")
            
            if href:
                # Check for typepad asset patterns
                if '.typepad.com/.a/' in href:
                    if not href.endswith('-popup'):
                        debug_print(f"  -> Found typepad asset link: {href}")
                        full_url = urljoin(url, href)
                        debug_print(f"  -> Full URL: {full_url}")
                        media_urls.add(full_url)
                    else:
                        debug_print(f"  -> Skipping popup link: {href}")
                else:
                    debug_print(f"  -> Not a typepad asset link")
            else:
                debug_print(f"  -> Link {i+1} has no href attribute")

        debug_print(f"Total unique media URLs found: {len(media_urls)}")
        for i, media_url in enumerate(sorted(media_urls), 1):
            debug_print(f"  Media {i}: {media_url}")

        if media_urls:
            media_dir_name = os.path.splitext(base_filename)[0]
            media_dir_path = os.path.join(POSTS_DIR, media_dir_name)
            debug_print(f"Creating media directory: {media_dir_path}")
            
            if not os.path.exists(media_dir_path):
                os.makedirs(media_dir_path)

            for media_url in media_urls:
                media_filename = os.path.basename(urlparse(media_url).path)
                if not media_filename:  # Handle URLs without clear filenames
                    media_filename = media_url.split('/')[-1]
                    if not media_filename:
                        media_filename = "unknown_media"
                
                media_save_path = os.path.join(media_dir_path, media_filename)
                debug_print(f"Processing media: {media_url}")
                debug_print(f"  -> Filename: {media_filename}")
                debug_print(f"  -> Save path: {media_save_path}")
                
                if not os.path.exists(media_save_path):
                    success = download_file(session, media_url, media_save_path)
                    if success:
                        debug_print(f"  -> Downloaded successfully")
                    else:
                        debug_print(f"  -> Download failed")
                    time.sleep(0.5) # A small polite delay
                else:
                    debug_print(f"  -> File already exists, skipping")
        else:
            debug_print("No media URLs found for this post")
    else:
        debug_print("No content container found, cannot extract media")
    
    # 5. Log this URL as successfully processed.
    log_url_as_downloaded(url, lock)
    debug_print(f"--- Finished processing URL: {url} ---\n")


def main():
    """
    The main function to set up and run the concurrent downloader.
    """
    global DEBUG_MODE
    
    parser = argparse.ArgumentParser(description="Download all posts and their media from a Typepad-style blog.")
    parser.add_argument("blog_url", help="The root URL of the blog (e.g., 'https://growabrain.typepad.com/growabrain/')")
    parser.add_argument("--debug", action="store_true", help="Enable debug output to help diagnose media finding issues")
    args = parser.parse_args()

    DEBUG_MODE = args.debug
    
    if DEBUG_MODE:
        print("DEBUG MODE ENABLED - Verbose output will be shown")

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
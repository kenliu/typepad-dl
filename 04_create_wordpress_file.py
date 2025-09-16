import os
import json
import logging
import math
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from tqdm import tqdm
from datetime import datetime
import argparse

# --- Configuration ---
# The directory where your downloaded Typepad posts are stored.
SOURCE_POSTS_DIR = "posts"
# The directory where the processed media map is located.
SOURCE_EXPORT_DIR = "wordpress_export"
# The path to the JSON file that maps old file paths to new filenames.
MAP_FILE = os.path.join(SOURCE_EXPORT_DIR, "file_map.json")
# The name of the final WordPress import file.
OUTPUT_WXR_FILE = os.path.join(SOURCE_EXPORT_DIR, "import.xml")
# The path where media will be located in WordPress.
WP_MEDIA_PATH = "/wp-content/uploads/typepad_media/"
# Default author name if one cannot be found in the HTML.
DEFAULT_AUTHOR = "admin"

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def parse_date(date_str):
    """
    Parses various date string formats found in Typepad blogs and returns
    a datetime object. This function is designed to be robust against extra
    text often found in the date line.
    """
    if not date_str:
        return None
    
    # --- Aggressive Cleanup Logic ---
    # 1. Take only the part before the first '|' to remove "Permalink", "Comments", etc.
    clean_str = date_str.split('|')[0]
    
    # 2. A common format is "... DATE in CATEGORY". Split by " in " to remove the category.
    clean_str = clean_str.split(' in ')[0]

    # 3. Another common format is "Posted by AUTHOR on DATE". We can find the last
    #    instance of " on " and take everything that follows it.
    if ' on ' in clean_str:
        # rsplit from the right once to correctly handle names like "Ron"
        clean_str = clean_str.rsplit(' on ', 1)[-1]
    
    # 4. Finally, remove the "at " that often precedes the time.
    clean_str = clean_str.replace("at ", "").strip()
    
    # A list of possible date formats to try.
    formats_to_try = [
        "%B %d, %Y %I:%M %p",    # July 09, 2022 10:55 PM
        "%B %d, %Y",            # October 14, 2015
        "%b %d, %Y %I:%M:%S %p", # Oct 21, 2015 12:17:25 AM
    ]
    for fmt in formats_to_try:
        try:
            # The final clean_str should now be just the date/time part.
            return datetime.strptime(clean_str.strip(), fmt)
        except ValueError:
            continue
            
    # Return None if no format matches after all cleanup attempts.
    return None

def rewrite_links(soup_content, file_map, original_post_url, scrub_popups=True):
    """
    Rewrites all media links in the post content to point to their new,
    local WordPress paths. Also scrubs Typepad's popup image links.
    """
    # --- Scrub Typepad's image popup links, leaving just the image ---
    if scrub_popups:
        # Find all links that point to Typepad's image popup viewer
        for a_tag in soup_content.find_all('a', href=True):
            if '.shared/image.html' in a_tag['href']:
                # Check if the link contains an image
                if a_tag.find('img'):
                    # This "unwraps" the image, removing the <a> tag
                    # but keeping the <img> tag inside it.
                    a_tag.unwrap()

    # Rewrite image links
    for img_tag in soup_content.find_all('img'):
        if not img_tag.get('src'):
            continue
        
        original_src = img_tag['src']
        # Construct the key to look for in the file_map.
        # This involves getting the filename from the URL and combining it with the post's folder.
        post_slug = os.path.splitext(os.path.basename(urlparse(original_post_url).path))[0]
        original_filename = os.path.basename(urlparse(original_src).path)
        
        # The key in our map is the original local file path.
        map_key = os.path.join(SOURCE_POSTS_DIR, post_slug, original_filename)
        
        if map_key in file_map:
            new_filename = file_map[map_key]
            img_tag['src'] = os.path.join(WP_MEDIA_PATH, new_filename)
        else:
            # Fallback for links that might not be in a post-specific folder
            # (e.g., shared images). We just try to find the filename.
            for key, value in file_map.items():
                if key.endswith(original_filename):
                    img_tag['src'] = os.path.join(WP_MEDIA_PATH, value)
                    break
    
    # Rewrite links to other media files (like PDFs)
    for a_tag in soup_content.find_all('a'):
        if not a_tag.get('href'):
            continue
        
        original_href = a_tag['href']
        # We only want to rewrite links to files, not to other web pages.
        if any(original_href.lower().endswith(ext) for ext in ['.pdf', '.zip', '.doc', '.docx', '.mp3']):
            post_slug = os.path.splitext(os.path.basename(urlparse(original_href).path))[0]
            original_filename = os.path.basename(urlparse(original_href).path)
            map_key = os.path.join(SOURCE_POSTS_DIR, post_slug, original_filename)
            
            if map_key in file_map:
                new_filename = file_map[map_key]
                a_tag['href'] = os.path.join(WP_MEDIA_PATH, new_filename)

    return soup_content

def main():
    """
    Main function to generate the WordPress WXR file from the
    archived HTML posts.
    """
    parser = argparse.ArgumentParser(description="Convert archived Typepad HTML files to a WordPress WXR import file.")
    parser.add_argument("--blog_title", help="The title of your blog (e.g., 'My Awesome Blog').", default="Archived Typepad Blog")
    parser.add_argument("--blog_url", help="The original root URL of the blog (e.g., 'https://myblog.typepad.com/blog/').", default="http://example.com/blog")
    parser.add_argument("--disable-popup-scrubbing", action="store_true", help="Disables the removal of Typepad's image popup links.")
    parser.add_argument("--max-posts-per-file", type=int, default=0, help="Split the output into multiple files with this many posts per file. Default is 0 (all in one file).")
    args = parser.parse_args()

    # --- 1. Load the File Map ---
    logging.info("Starting WXR creation script.")
    if not os.path.exists(MAP_FILE):
        logging.error(f"Map file not found at '{MAP_FILE}'. Please run the `process_media.py` script first.")
        return

    with open(MAP_FILE, 'r', encoding='utf-8') as f:
        file_map = json.load(f)
    logging.info(f"Loaded {len(file_map)} file mappings.")

    # --- 2. Find All HTML Post Files ---
    html_files = [os.path.join(SOURCE_POSTS_DIR, f) for f in os.listdir(SOURCE_POSTS_DIR) if f.lower().endswith(".html")]
    if not html_files:
        logging.error(f"No HTML files found in '{SOURCE_POSTS_DIR}'.")
        return
        
    logging.info(f"Found {len(html_files)} HTML post files to process.")

    # --- 3. Start Building the WXR File ---
    # This is the standard header for a WordPress WXR file.
    wxr_header = f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0"
    xmlns:excerpt="http://wordpress.org/export/1.2/excerpt/"
    xmlns:content="http://purl.org/rss/1.0/modules/content/"
    xmlns:wfw="http://wellformedweb.org/CommentAPI/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:wp="http://wordpress.org/export/1.2/"
>
<channel>
    <title>{args.blog_title}</title>
    <link>{args.blog_url}</link>
    <description>An archive of a Typepad blog.</description>
    <pubDate>{datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
    <language>en-US</language>
    <wp:wxr_version>1.2</wp:wxr_version>
"""
    
    all_wxr_items = []
    
    # --- 4. Process Each HTML File and Collect All Items ---
    for html_file in tqdm(html_files, desc="Converting Posts"):
        with open(html_file, 'r', encoding='utf-8') as f:
            try:
                soup = BeautifulSoup(f.read(), 'html.parser')
            except Exception as e:
                logging.warning(f"Could not parse {html_file}. Skipping. Error: {e}")
                continue

        # --- Extract Post Details ---
        title = soup.find('h3', class_='entry-header') or soup.find('h3')
        title_text = title.get_text(strip=True) if title else "Untitled Post"

        # Find the original URL of the post from the canonical link or permalink
        canonical_link = soup.find('link', rel='canonical')
        original_post_url = canonical_link['href'] if canonical_link else (soup.find('a', class_='permalink')['href'] if soup.find('a', class_='permalink') else None)
        if not original_post_url:
            post_slug = os.path.splitext(os.path.basename(html_file))[0]
            original_post_url = urljoin(args.blog_url, post_slug + ".html")

        post_name = urlparse(original_post_url).path.strip('/').split('/')[-1].replace('.html', '')

        # --- Find and parse the date with fallbacks ---
        publish_date = None
        date_text = ""
        
        # 1. Try to parse from the HTML content first (most accurate).
        date_tag = soup.find('p', class_='entry-footer-info') or soup.find('p', class_='posted') or soup.find('h2', class_='date-header')
        if date_tag:
            date_text = date_tag.get_text(strip=True)
            publish_date = parse_date(date_text)
        
        # 2. If parsing failed, fall back to the filename.
        if not publish_date:
            try:
                filename_parts = os.path.basename(html_file).split('_')
                if len(filename_parts) >= 2 and filename_parts[0].isdigit() and filename_parts[1].isdigit():
                    year = int(filename_parts[0])
                    month = int(filename_parts[1])
                    publish_date = datetime(year, month, 1) # Default to the 1st of the month
                    if date_text: # Only show warning if there was text we failed to parse
                        tqdm.write(f"WARNING: Could not parse date '{date_text}' in {os.path.basename(html_file)}. Using filename: {publish_date.strftime('%Y-%m')}")
            except (ValueError, IndexError):
                pass # Silently fail if filename format is unexpected.

        # 3. As a last resort, if both methods fail, use the current time.
        if not publish_date:
            tqdm.write(f"WARNING: Could not determine date for {os.path.basename(html_file)}. Using current time.")
            publish_date = datetime.now()
        
        # Find the author
        author_tag = soup.find('div', class_=lambda c: c and c.startswith('entry-author-'))
        author_name = author_tag['class'][0].replace('entry-author-', '') if author_tag else DEFAULT_AUTHOR

        # --- Extract and Clean Content ---
        content_div = soup.find('div', class_='entry-body') or soup.find('div', class_='entry-content')
        if not content_div:
            logging.warning(f"Could not find content body for {html_file}. Skipping.")
            continue
            
        # Pass the scrubbing flag to the rewrite function
        content_soup = rewrite_links(content_div, file_map, original_post_url, scrub_popups=not args.disable_popup_scrubbing)
        content_html = str(content_soup)

        # --- Assemble the WXR <item> for this post ---
        item = f"""
    <item>
        <title>{title_text}</title>
        <link>{original_post_url}</link>
        <pubDate>{publish_date.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>
        <dc:creator><![CDATA[{author_name}]]></dc:creator>
        <guid isPermaLink="false">{post_name}</guid>
        <description></description>
        <content:encoded><![CDATA[{content_html}]]></content:encoded>
        <excerpt:encoded><![CDATA[]]></excerpt:encoded>
        <wp:post_id>{len(all_wxr_items) + 1}</wp:post_id>
        <wp:post_date><![CDATA[{publish_date.strftime('%Y-%m-%d %H:%M:%S')}]]></wp:post_date>
        <wp:post_date_gmt><![CDATA[{publish_date.strftime('%Y-%m-%d %H:%M:%S')}]]></wp:post_date_gmt>
        <wp:comment_status><![CDATA[closed]]></wp:comment_status>
        <wp:ping_status><![CDATA[closed]]></wp:ping_status>
        <wp:post_name><![CDATA[{post_name}]]></wp:post_name>
        <wp:status><![CDATA[publish]]></wp:status>
        <wp:post_parent>0</wp:post_parent>
        <wp:menu_order>0</wp:menu_order>
        <wp:post_type><![CDATA[post]]></wp:post_type>
        <wp:post_password><![CDATA[]]></wp:post_password>
        <wp:is_sticky>0</wp:is_sticky>
    </item>
"""
        all_wxr_items.append(item)
        
    # --- 5. Finalize and Save the WXR File(s) ---
    wxr_footer = """
</channel>
</rss>
"""
    
    if args.max_posts_per_file <= 0:
        # Write everything to a single file
        with open(OUTPUT_WXR_FILE, 'w', encoding='utf-8') as f:
            f.write(wxr_header)
            for item in all_wxr_items:
                f.write(item)
            f.write(wxr_footer)
        logging.info(f"Successfully created single WordPress import file: {OUTPUT_WXR_FILE}")
    else:
        # Split the items into chunks and write multiple files
        chunk_size = args.max_posts_per_file
        num_chunks = math.ceil(len(all_wxr_items) / chunk_size)
        
        for i in range(num_chunks):
            output_filename = os.path.join(SOURCE_EXPORT_DIR, f"import-part-{i+1}.xml")
            
            start_index = i * chunk_size
            end_index = start_index + chunk_size
            chunk_items = all_wxr_items[start_index:end_index]
            
            with open(output_filename, 'w', encoding='utf-8') as f:
                f.write(wxr_header)
                for item in chunk_items:
                    f.write(item)
                f.write(wxr_footer)
        
        logging.info(f"Successfully created {num_chunks} WordPress import files in '{SOURCE_EXPORT_DIR}'.")

    logging.info("Process complete.")

if __name__ == "__main__":
    main()


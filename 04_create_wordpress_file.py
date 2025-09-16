import os
import json
import logging
import math
import re
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
# The relative path where media will be located in WordPress.
# Using ../ makes it relative to the post's URL (e.g., /my-post/).
WP_MEDIA_PATH = "../wp-content/uploads/typepad_media/"
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
    # First, get rid of extra text like "| Permalink" or "in [Category]"
    clean_str = date_str.split('|')[0]
    clean_str = clean_str.split(' in ')[0]
    # Next, find the date part, which usually comes after " on "
    if ' on ' in clean_str:
        clean_str = clean_str.rsplit(' on ', 1)[-1]
    
    # Normalize whitespace. This fixes issues with non-breaking spaces (\xa0)
    # and multiple spaces between date parts, making the string predictable.
    clean_str = clean_str.replace('\xa0', ' ')
    clean_str = re.sub(r'\s+', ' ', clean_str).strip()
    
    # Now that whitespace is clean, remove the "at " before the time.
    clean_str = clean_str.replace("at ", "")
    
    formats_to_try = [
        "%B %d, %Y %I:%M %p",    # July 09, 2022 10:55 PM
        "%B %d, %Y",            # October 14, 2015
        "%b %d, %Y %I:%M:%S %p", # Oct 21, 2015 12:17:25 AM
    ]
    for fmt in formats_to_try:
        try:
            return datetime.strptime(clean_str.strip(), fmt)
        except ValueError:
            continue
    return None

def find_file_in_map(original_url, local_file_slug, file_map):
    """
    Finds a file in the map using a more flexible matching logic
    that ignores file extensions.
    """
    original_filename_no_ext = os.path.splitext(os.path.basename(urlparse(original_url).path))[0]
    
    # Construct the ideal path stem we are looking for
    path_stem_to_find = os.path.join(SOURCE_POSTS_DIR, local_file_slug, original_filename_no_ext)
    
    # First, try to find a key in the map that matches this stem
    for key in file_map:
        key_stem = os.path.splitext(key)[0]
        if key_stem == path_stem_to_find:
            return file_map[key]
            
    # As a fallback, if not found, just check for the filename itself
    # This helps with shared images not in a post-specific folder
    for key in file_map:
        key_filename_no_ext = os.path.splitext(os.path.basename(key))[0]
        if key_filename_no_ext == original_filename_no_ext:
            return file_map[key]

    return None # Return None if no match is found

def process_content(soup_content, file_map, local_file_slug, blog_url, scrub_popups=True, remove_divs=True, remove_brs=True):
    """
    Cleans and rewrites the post content by processing all links and tags
    in a structured order.
    """
    # --- Step 1: Remove "Editor's Note" paragraphs ---
    editor_note_phrases = ["Back in March", "none of the images will work", "a lot of links are now broken"]
    for p_tag in soup_content.find_all('p'):
        p_text = p_tag.get_text()
        if all(phrase in p_text for phrase in editor_note_phrases):
            p_tag.decompose()

    # --- Step 2: Unwrap images from bare <td> tags ---
    for td_tag in soup_content.find_all('td'):
        if td_tag.parent.name != 'tr':
            td_tag.unwrap()
            
    # --- Step 3: Remove all div tags if enabled ---
    if remove_divs:
        for div_tag in soup_content.find_all('div'):
            div_tag.unwrap()
            
    # --- New Step 4: Remove <br> tags if enabled ---
    if remove_brs:
        for br_tag in soup_content.find_all('br'):
            br_tag.replace_with(' ') # Replace with a single space

    # --- Step 5: Process all links (<a> tags) in one go ---
    for a_tag in soup_content.find_all('a', href=True):
        if not a_tag.parent:
            continue

        original_href = a_tag.get('href', '')
        # Rule 1: Scrub JavaScript Popups
        if scrub_popups:
            onclick = a_tag.get('onclick', '')
            is_known_popup_url = '.shared/image.html' in original_href or original_href.endswith('-popup')
            is_generic_js_popup = 'typepad.com' in original_href and 'window.open' in onclick
            if is_known_popup_url or is_generic_js_popup:
                if a_tag.find('img'):
                    a_tag.unwrap()
                elif not a_tag.get_text(strip=True):
                    a_tag.decompose()
                continue
        
        # Rule 2: Rewrite internal links between blog posts
        if blog_url and original_href.startswith(blog_url):
            is_media = any(original_href.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.zip', '.doc', '.docx', '.mp3'])
            if not is_media:
                 path = urlparse(original_href).path
                 slug = os.path.splitext(os.path.basename(path))[0]
                 if slug:
                     a_tag['href'] = f"/{slug}/"
                     continue
        
        # Rule 3: Rewrite links to media files (including images wrapped in links)
        new_filename = find_file_in_map(original_href, local_file_slug, file_map)
        if new_filename:
            # If the link just wraps an image, unwrap it.
            if a_tag.find('img'):
                a_tag.unwrap()
            # Otherwise, it's a link to a file (like a PDF), so rewrite the href.
            else:
                a_tag['href'] = f"{WP_MEDIA_PATH}{new_filename}"

    # --- Step 6: Rewrite and clean all standalone <img> tags ---
    for img_tag in soup_content.find_all('img', src=True):
        new_filename = find_file_in_map(img_tag['src'], local_file_slug, file_map)
        if new_filename:
            img_tag['src'] = f"{WP_MEDIA_PATH}{new_filename}"
        
        # Convert inline float styles to WordPress alignment classes
        if img_tag.has_attr('style'):
            style = img_tag['style'].lower()
            new_classes = img_tag.get('class', [])
            if 'float: right' in style:
                new_classes.append('alignright')
            elif 'float: left' in style:
                new_classes.append('alignleft')
            if new_classes:
                img_tag['class'] = ' '.join(new_classes)
                del img_tag['style']

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
    parser.add_argument("--disable-div-rm", action="store_true", help="Disables the removal of all div tags from post content.")
    parser.add_argument("--disable-br-rm", action="store_true", help="Disables removing <br> tags and cleaning up whitespace.")
    parser.add_argument("--max-posts-per-file", type=int, default=0, help="Split the output into multiple files with this many posts per file. Default is 0 (all in one file).")
    args = parser.parse_args()
    
    # --- Add a warning if the blog URL is not provided ---
    blog_url_provided = args.blog_url != "http://example.com/blog"
    if not blog_url_provided:
        logging.warning("No --blog_url provided. Internal links to other posts will not be rewritten.")
        # Set to None so the script doesn't try to match against the default value.
        args.blog_url = None

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
    <link>{args.blog_url or 'http://example.com'}</link>
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
        local_file_slug = os.path.splitext(os.path.basename(html_file))[0]
        canonical_link = soup.find('link', rel='canonical')
        original_post_url = canonical_link['href'] if canonical_link else (soup.find('a', class_='permalink')['href'] if soup.find('a', class_='permalink') else None)
        if not original_post_url:
            original_post_url = urljoin(args.blog_url, local_file_slug + ".html")
        post_name = urlparse(original_post_url).path.strip('/').split('/')[-1].replace('.html', '')

        # --- Find and parse the date with fallbacks ---
        publish_date = None
        date_text = ""
        date_tag = soup.find('p', class_='entry-footer-info') or soup.find('p', class_='posted') or soup.find('h2', class_='date-header')
        if date_tag:
            # Use .strings to correctly get text pieces around HTML tags
            date_text = "".join(date_tag.strings)
            publish_date = parse_date(date_text)
        if not publish_date:
            try:
                filename_parts = local_file_slug.split('_')
                if len(filename_parts) >= 2 and filename_parts[0].isdigit() and filename_parts[1].isdigit():
                    year = int(filename_parts[0])
                    month = int(filename_parts[1])
                    publish_date = datetime(year, month, 1)
                    if date_text:
                        tqdm.write(f"WARNING: Could not parse date '{date_text.strip()}' in {os.path.basename(html_file)}. Using filename: {publish_date.strftime('%Y-%m')}")
            except (ValueError, IndexError):
                pass
        if not publish_date:
            tqdm.write(f"WARNING: Could not determine date for {os.path.basename(html_file)}. Using current time.")
            publish_date = datetime.now()
        
        author_tag = soup.find('div', class_=lambda c: c and c.startswith('entry-author-'))
        author_name = author_tag['class'][0].replace('entry-author-', '') if author_tag else DEFAULT_AUTHOR

        # --- Extract and Clean Content ---
        content_div = soup.find('div', class_='entry-body') or soup.find('div', class_='entry-content')
        if not content_div:
            content_div = soup.find('article') or soup.find('body')
            if not content_div:
                logging.warning(f"Could not find any content body for {html_file}. Skipping.")
                continue
            
        content_soup = process_content(
            content_div, 
            file_map, 
            local_file_slug,
            args.blog_url,
            scrub_popups=not args.disable_popup_scrubbing,
            remove_divs=not args.disable_div_rm,
            remove_brs=not args.disable_br_rm
        )
        content_html = "".join(str(c) for c in content_soup.contents)
        
        # New: Final whitespace cleanup, also conditional
        if not args.disable_br_rm:
            content_html = re.sub(r'\s+', ' ', content_html).strip()

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
        with open(OUTPUT_WXR_FILE, 'w', encoding='utf-8') as f:
            f.write(wxr_header)
            for item in all_wxr_items:
                f.write(item)
            f.write(wxr_footer)
        logging.info(f"Successfully created single WordPress import file: {OUTPUT_WXR_FILE}")
    else:
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
    
    # --- Final instructions for the user ---
    print("\n--- Next Steps ---")
    print("1. Upload the 'typepad_media' folder to your WordPress site's 'wp-content/uploads/' directory.")
    print("2. Go to your WordPress admin dashboard, navigate to Tools -> Import, and run the WordPress importer with your new .xml file(s).")
    if blog_url_provided:
        print("3. IMPORTANT: For internal links to work, go to Settings -> Permalinks and set the structure to 'Post name'.")
    print("------------------")

if __name__ == "__main__":
    main()
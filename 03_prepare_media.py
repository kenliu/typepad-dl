import os
import shutil
import json
import uuid
import logging
from PIL import Image
import imagehash
from tqdm import tqdm
import magic

# --- Configuration ---
# The directory where your downloaded Typepad posts are stored.
SOURCE_DIR = "posts"
# The main output directory for the WordPress-ready files.
OUTPUT_DIR = "wordpress_export"
# The sub-directory where all media files will be stored.
MEDIA_SUBDIR = "typepad_media"
# The name of the JSON file that will store the mapping of old files to new files.
MAP_FILE = "file_map.json"
# The perceptual hash difference threshold. Images with a difference score
# below this number will be considered duplicates. A low number like 1 or 2
# is good for finding near-identical images.
HASH_DIFFERENCE_THRESHOLD = 2

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def sanitize_filename(post_slug, original_filename):
    """
    Creates a safe and descriptive filename by combining the post's slug
    and the original filename.
    """
    # Remove file extension from post slug if it exists
    post_slug_base = os.path.splitext(post_slug)[0]
    
    # Combine them
    combined_name = f"{post_slug_base}_{original_filename}"
    
    # Replace any characters that are not safe for filenames
    safe_name = "".join(c if c.isalnum() or c in ('.', '_', '-') else '_' for c in combined_name)
    return safe_name

def main():
    """
    Main function to process media files, handle duplicates, and prepare
    them for WordPress import.
    """
    # --- 1. Setup Environment ---
    logging.info("Starting media processing script.")
    
    media_output_path = os.path.join(OUTPUT_DIR, MEDIA_SUBDIR)
    if not os.path.exists(media_output_path):
        os.makedirs(media_output_path)
        logging.info(f"Created output directory: {media_output_path}")

    if not os.path.exists(SOURCE_DIR):
        logging.error(f"Source directory '{SOURCE_DIR}' not found. Please run the download script first.")
        return

    # --- 2. Initialize Tracking ---
    processed_hashes = {}
    file_map = {}
    
    # --- 3. Scan for All Media Files ---
    files_to_process = []
    for root, _, files in os.walk(SOURCE_DIR):
        for filename in files:
            if not filename.lower().endswith(".html") and not filename.lower().endswith("-popup"):
                original_path = os.path.join(root, filename)
                files_to_process.append(original_path)
    
    logging.info(f"Found {len(files_to_process)} media files to process.")

    # --- 4. Process Each File ---
    mime = magic.Magic(mime=True)
    for original_path in tqdm(files_to_process, desc="Processing Media"):
        try:
            # Use python-magic to determine the true file type.
            file_type = mime.from_file(original_path)
            is_image = file_type.startswith('image/')
            
            # --- Handle Images with Perceptual Hashing ---
            if is_image:
                with Image.open(original_path) as img:
                    current_hash = imagehash.phash(img)
                
                best_match_hash = None
                lowest_diff = float('inf')

                for existing_hash, _ in processed_hashes.items():
                    diff = current_hash - existing_hash
                    if diff < lowest_diff:
                        lowest_diff = diff
                        best_match_hash = existing_hash
                
                if lowest_diff < HASH_DIFFERENCE_THRESHOLD:
                    new_filename = processed_hashes[best_match_hash]
                    file_map[original_path] = new_filename
                    continue

            # --- If it's a new image or not an image file, process it ---
            post_slug = os.path.basename(os.path.dirname(original_path))
            original_filename = os.path.basename(original_path)
            
            new_filename = sanitize_filename(post_slug, original_filename)
            destination_path = os.path.join(media_output_path, new_filename)
            
            if os.path.exists(destination_path):
                name_part, extension = os.path.splitext(new_filename)
                unique_id = str(uuid.uuid4())[:8]
                new_filename = f"{name_part}_{unique_id}{extension}"
                destination_path = os.path.join(media_output_path, new_filename)

            shutil.copy2(original_path, destination_path)
            
            file_map[original_path] = new_filename
            
            if is_image and 'current_hash' in locals():
                processed_hashes[current_hash] = new_filename

        except Exception as e:
            # Catch errors from python-magic or Pillow if a file is truly corrupt
            logging.warning(f"Could not process file {original_path}. It may be corrupt. Error: {e}")

    # --- 5. Save the Final Map ---
    map_file_path = os.path.join(OUTPUT_DIR, MAP_FILE)
    with open(map_file_path, 'w', encoding='utf-8') as f:
        json.dump(file_map, f, indent=4)
        
    logging.info(f"Successfully processed all media files.")
    logging.info(f"A map of old to new filenames has been saved to: {map_file_path}")
    logging.info(f"All unique media has been copied to: {media_output_path}")
    logging.info("You are now ready to run the `04_create_wordpress_file.py` script.")

if __name__ == "__main__":
    main()


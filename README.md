# Typepad Blog Archiver & WordPress Importer 📥

This is a simple, four-step tool to download a full archive of a Typepad blog and prepare it for import into WordPress. It's built to save your content and help you move to a new home on the web.

First, it finds every post on your blog. Then, it downloads each post and all its media. Finally, it organizes everything into a standard WordPress import file.

-----

## Features

  * **Complete Archiving**: Downloads all posts, associated media files, and site assets (CSS, JS).
  * **WordPress Export**: Creates a WordPress-compatible `.xml` file for easy importing.
  * **Smart Media Handling**: De-duplicates images and gives all files clean, web-safe names.
  * **Resume Support**: If a script stops, you can run it again and it will pick up where it left off.
  * **Fast Downloads**: Uses multiple threads to download posts and files quickly.

-----

## How to Use

Follow these four steps to archive your blog and prepare it for WordPress.

### Step 1: Get All Post Links

This step uses `01_get.py` to crawl your blog and create a list of every post's unique URL.

1.  **Open your terminal** or command prompt.
2.  **Run the script** with your blog's URL as the argument. Make sure to include the full path, including the last slash.
    ```bash
    python 01_get.py "https://blawg.typepad.com/blawg/"
    ```
3.  **Wait for it to finish.** The script will go through every page of your blog and find all the "Permalink" links.

This creates a file named `**permalinks.txt**` that contains the URL for every post on your blog.

### Step 2: Download All Posts and Media

This step uses `02_posts.py` to read the list of URLs and download everything.

1.  **Run the script** from your terminal. This also takes the URL as the argument.
    ```bash
    python 02_posts.py "https://blawg.typepad.com/blawg/"
    ```
    For more detailed output if you run into problems, you can use the `--debug` flag:
    ```bash
    python 02_posts.py "https://blawg.typepad.com/blawg/" --debug
    ```
2.  **A progress bar will appear.** The script will now download the HTML for every post and any media files (images, PDFs, etc.) it finds inside that post.

When it's done, you will have a `posts` folder with your full blog archive.

### Step 3: Prepare Media for WordPress

This step uses `03_prepare_media.py` to get all your downloaded files ready for WordPress.

1.  **Run the script** from your terminal. It doesn't need any arguments.
    ```bash
    python 03_prepare_media.py
    ```
2.  **The script will find all your media** (images, documents, etc.) from the `posts` folder. It gets rid of duplicates, gives them clean names, and copies them into a new folder called `wordpress_export/typepad_media`.

### Step 4: Create the WordPress Import File

This is the final step to create the `.xml` file for WordPress.

1.  **Run the script** with your blog's original URL and a title.
    ```bash
    python 04_create_wordpress_file.py --blog_url "https://blawg.typepad.com/blawg/" --blog_title "My Awesome Blog"
    ```
2.  **This script reads every post,** cleans up the HTML, and updates all the image links to work on your new WordPress site. It then creates a single `import.xml` file in the `wordpress_export` folder.

### Step 5: Import to WordPress\! 🎉

You're ready to move your content into WordPress.

1.  Using an FTP client or your web host's file manager, **upload the `typepad_media` folder** into your WordPress site's `wp-content/uploads/` directory.
2.  Log in to your WordPress admin dashboard. Go to **Tools -\> Import**.
3.  Find "WordPress" at the bottom and click **"Install Now"** if you haven't already, then **"Run Importer"**.
4.  Upload the `import.xml` file you created in Step 4.
5.  Follow the on-screen instructions. When you're done, go to **Settings -\> Permalinks** and choose the **"Post name"** option. This is important for your old links to work\!

-----

## Requirements ⚙️

You need Python 3 installed on your computer. You also need to install a few Python packages.

Run this command in your terminal to install them:

```bash
pip3 install curl_cffi beautifulsoup4 tqdm Pillow imagehash python-magic-bin
```

**Note for Windows users:** The `python-magic-bin` package is recommended because it includes files needed to run on Windows without extra setup.

-----

## What if the `pip` command fails? 🛠️

Sometimes, even if you have Python, the `pip` command isn't installed or your system can't find it. If you get an error like "command not found", here is how to install it.

### For Windows 🖥️

Modern Python installers for Windows should include `pip` automatically. The easiest fix is often to repair your Python installation.

1.  Find the original Python installer you downloaded. If you don't have it, download it again from the official Python website.
2.  Run the installer. Choose the **"Modify"** or **"Repair"** option.
3.  Make sure the checkbox for **"pip"** is selected.
4.  On the next step, make sure the checkbox for **"Add Python to environment variables"** or **"Add Python to PATH"** is selected. This is very important\!
5.  Finish the installation.

Alternatively, you can try to install it from the command prompt:

```bash
python -m ensurepip --upgrade
```

### For macOS 🍎

Python 3 on macOS should also come with `pip`. If it's missing, you can install it with this command in your terminal:

```bash
python3 -m ensurepip --upgrade
```

### For Linux (Ubuntu/Debian) 🐧

You can use the system's package manager, `apt`, to install `pip`. This is the most reliable method.

1.  First, update your package list:
    ```bash
    sudo apt update
    ```
2.  Then, install the package for `pip`:
    ```bash
    sudo apt install python3-pip
    ```

### Check if it Worked

After trying one of the steps above, close and reopen your terminal. Then, run this command to see if it was successful:

```bash
pip3 --version
```

If it shows you a version number, you're all set\!

## Troubleshooting & FAQ 🤔

Here are solutions to some common issues you might run into.

### Files are saving in the wrong place\!

This usually happens if you run the script from the wrong folder. You need to tell your terminal to navigate to the correct directory first.

  * **The Fix:** Use the `cd` (change directory) command to move into the folder where you saved the `.py` files.
    ```bash
    # Example: If your files are in a folder called "archive" on your Desktop
    cd Desktop/archive
    ```
    Once you are in the correct folder, you can run the `python` commands.

### The `python` command doesn't work.

On many systems, especially macOS and Linux, you need to be more specific.

  * **The Fix:** Try using `python3` and `pip3` in your commands instead. For example:
    ```bash
    python3 01_get.py "https://yourblog.typepad.com/blog/"

    pip3 install curl_cffi beautifulsoup4 tqdm
    ```

### My image links are broken in WordPress.

This can happen for two common reasons.

1.  **You didn't set the `--blog_url` flag.** When you run `04_create_wordpress_file.py`, you must provide your original blog URL. This helps the script know which links are internal and need to be rewritten.
2.  **You forgot to set your Permalinks.** In your WordPress dashboard, go to **Settings -\> Permalinks** and select **"Post name"**.

### The WordPress import is failing or timing out\!

If you have a very large blog with thousands of posts, the single `import.xml` file might be too big for your web host to handle. This can cause the import process to crash, time out, or fail without a clear error.

  * **The Fix:** You can split the export into multiple smaller files. The script has a built-in option for this. When you run step 4, add the `--max-posts-per-file` flag.
    ```bash
    python 04_create_wordpress_file.py --blog_url "..." --blog_title "..." --max-posts-per-file 100
    ```
    This will create several files (e.g., `import-part-1.xml`, `import-part-2.xml`, etc.), each containing a maximum of 100 posts. You can then upload these smaller files to the WordPress importer one at a time until your whole blog is imported. If it still fails, try a smaller number like `50`.

-----

## How It Works

The tool is split into four parts to be safe and reliable.

1.  `01_get.py`: This script acts like a search engine. It navigates your blog's "Next" page links and finds the direct URL for every single post. It saves these in `permalinks.txt`.

2.  `02_posts.py`: This script is the downloader. It reads each URL from `permalinks.txt` and downloads the post's HTML page, its media (images, PDFs), and any shared site assets (CSS, JS).

3.  `03_prepare_media.py`: This script is the organizer. It scans all the downloaded media, finds and removes duplicate images, gives every file a clean and safe name, and moves them to a single `typepad_media` folder. It creates a `file_map.json` to remember the old filename for each new one.

4.  `04_create_wordpress_file.py`: This is the builder. It reads each HTML post and the `file_map.json`. It cleans up the post content, fixes all the media links to point to their new location, and bundles everything into a single `import.xml` file that WordPress can read.

-----

## Final File Structure

After running all the scripts, your folder will look like this:

```
.
├── 01_get.py
├── 02_posts.py
├── 03_prepare_media.py
├── 04_create_wordpress_file.py
├── permalinks.txt            # <-- List of all your post URLs
├── downloaded_permalinks.txt   # <-- Log of downloaded posts
├── scanned.txt               # <-- Log of scanned blog pages
|
├── raw-paged-data/           # <-- Raw HTML of each blog index page
│   ├── page_1.html
│   └── ...
|
├── posts/                    # <-- YOUR RAW ARCHIVE
│   ├── assets/
│   ├── 2025_08_my-first-post.html
│   ├── 2025_08_my-first-post/
│   │   └── picture_of_dog.jpg
│   └── ...
|
└── wordpress_export/         # <-- YOUR WORDPRESS IMPORT FILES
    ├── file_map.json         # <-- Map of old to new media files
    ├── import.xml            # <-- The file you upload to WordPress
    └── typepad_media/        # <-- All your media, ready to upload
        ├── 2025_08_my-first-post_picture_of_dog.jpg
        └── ...
```
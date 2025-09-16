# Typepad Blog Archiver 📥

This is a simple, two-step tool to download a full archive of a Typepad blog. It's built to save your content before Typepad shuts down.

First, it finds every post on your blog. Then, it downloads each post as an HTML file and grabs all linked media (like images, CSS, and PDFs).

-----

## Features

  * **Complete Archiving**: Downloads all posts, associated media files, and site assets (CSS, JS).
  * **Resume Support**: If the script stops, you can run it again and it will pick up where it left off.
  * **Simple Structure**: Saves each post as a clean HTML file. Media for each post goes into a matching folder, and shared assets go into a common `assets` directory.
  * **Fast Downloads**: Uses multiple threads to download posts and files quickly.

-----

## How to Use

Follow these two steps to archive your blog.

### Step 1: Get All Post Links

This step uses `01_get.py` to crawl your blog and create a list of every post's unique URL.

1.  **Open your terminal** or command prompt.
2.  **Run the script** with your blog's URL as the argument. Make sure to include the full path, including the last slash.
    ```bash
    python 01_get.py "https://blawg.typepad.com/blawg/"
    ```
3.  **Wait for it to finish.** The script will go through every page of your blog (`/page/1/`, `/page/2/`, etc.) and find all the "Permalink" links.

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
2.  **A progress bar will appear.** The script will now download the HTML for every post and any media files or assets (CSS, JS, images) it finds inside that post.

When it's done, you will have a `posts` folder with your full blog archive.

-----

## Requirements ⚙️

You need Python 3 installed on your computer. You also need to install a few Python packages.

Run this command in your terminal to install them:

```bash
pip install curl_cffi beautifulsoup4 tqdm
```

-----

Of course\! That's a great question, as it's a common stumbling block.

You can add the following section to the `README.md` file, probably right after the "Requirements" section.

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

  * **The Fix:** Use the `cd` (change directory) command to move into the folder where you saved the `01_get.py` and `02_posts.py` files.
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

### `01_get.py` only finds a few posts and then stops.

This can happen if your blog theme is very old or broken and is missing a "Next" page link for the script to follow. While the script has been improved to handle this better, some themes might still fail.

  * **The Fix (Manual Workaround):** You can create the `permalinks.txt` file yourself.
    1.  Log into Typepad and use their built-in export tool. It will give you a single large `.txt` file.
    2.  Open that file in a text editor and search for all the URLs to your posts. They usually contain a keyword like `PERMALINK`.
    3.  Copy and paste all of those post URLs into a new file named `permalinks.txt`. Make sure there is only one URL per line.
    4.  Save the file. Now you can skip `01_get.py` and run `02_posts.py` directly.

### The scripts are not downloading my images.

This was a bug in an earlier version. If you are having this problem, please make sure you have the latest version of the `02_posts.py` script. The new version is much better at finding and downloading all linked media, including images inside links.

-----

## How It Works

The tool is split into two parts to be safe and reliable.

1.  `01_get.py`: This script acts like a search engine. It navigates your blog's "Next" page links over and over. On each page, it looks for links with the text "Permalink", which are the direct URLs to your posts.

      * It saves these URLs in `**permalinks.txt**`.
      * It saves the raw HTML of each index page in the `**raw-paged-data/**` folder.
      * It keeps track of which pages it has already processed in `**scanned.txt**` so it can resume if stopped.

2.  `02_posts.py`: This script is the downloader. It reads each URL from `permalinks.txt` and does the following:

      * Downloads the post's main HTML page.
      * Scans the HTML for shared assets like CSS, JavaScript, and icons, downloads them, and saves them to a central `**posts/assets/**` folder. It rewrites the HTML to point to these local files.
      * Creates a folder named after the post slug (e.g., `my-first-post/`).
      * Scans the post content for links to files (like `.jpg`, `.pdf`, `.zip`).
      * Downloads all those files into the folder it created.
      * Keeps track of finished posts in `**downloaded_permalinks.txt**` so it can resume if stopped.

-----

## Final File Structure

After running both scripts, your folder will look like this:

```
.
├── 01_get.py
├── 02_posts.py
├── permalinks.txt            # <-- List of all your post URLs
├── downloaded_permalinks.txt   # <-- Log of downloaded posts
├── scanned.txt               # <-- Log of scanned blog pages
|
├── raw-paged-data/           # <-- Raw HTML of each blog index page
│   ├── page_1.html
│   └── page_2.html
│
└── posts/                    # <-- YOUR FINAL ARCHIVE
    ├── assets/               # <-- Shared site assets
    │   ├── main_stylesheet.css
    │   ├── site_script.js
    │   └── favicon.ico
    │
    ├── 2025_08_my-first-post.html
    ├── 2025_08_my-first-post/
    │   ├── picture_of_dog.jpg
    │   └── important_document.pdf
    │
    ├── 2025_09_another-post.html
    └── ...and so on
```
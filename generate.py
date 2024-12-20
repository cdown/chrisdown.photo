#!/usr/bin/env python
import os
import re
import json
import yaml
import requests
import subprocess
from selectolax.parser import HTMLParser
from collections import namedtuple

FlickrImageData = namedtuple("FlickrImageData", ["url", "title"])
CACHE_FILE = "image_titles_cache.json"
IMG_DIR = "images"

# On desktop, the layout has a body width of 1400px with 10px border on each
# side, resulting in 1380px usable width. For a two-column layout, each column
# should be half of 1380px, which is 690px. Accounting for an 8px gap on each
# side of a column due to 16px column-gap, the required image width is 690 -
# 8 = 682px.
#
# For a single column layout (e.g., on mobile), the width requirement is 820px
# minus 10px padding either side, leading to a practical minimum width
# requirement of 800px to ensure quality display in all layouts.
IMG_WIDTH = 800


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as file:
            return json.load(file)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as file:
        json.dump(cache, file, indent=4)


def extract_photo_id(url):
    match = re.search(r"/photos/[^/]+/([^/]+)/?", url)
    if not match:
        raise ValueError(f"Invalid Flickr URL: {url}")
    return match.group(1)


def fetch_image_data(flickr_url):
    print(f"Fetching image data from {flickr_url}")
    response = requests.get(f"{flickr_url}/sizes/o/")
    html = HTMLParser(response.text)
    title = html.css_first('meta[name="title"]').attributes["content"]
    image_url = html.css_first(
        'div#allsizes-photo > img[src*="live.staticflickr.com"]'
    ).attributes["src"]
    return title, image_url


def download_image(image_url, temp_path):
    print(f"Downloading image from {image_url}")
    response = requests.get(image_url)
    with open(temp_path, "wb") as file:
        file.write(response.content)


def process_image(temp_path, output_path, danger_of_banding):
    print(f"Processing image and saving to {output_path}")
    quality = "100" if danger_of_banding else "90"

    # If there's a danger of banding we do two things to try to mitigate it,
    # since we can't use 16-bit AVIF due to 8-bit rendering pipeline in
    # browsers:
    #
    # 1. Bump the quality
    # 2. Add a little noise
    noise_args = (
        ["-attenuate", "0.04", "+noise", "Gaussian"] if danger_of_banding else []
    )
    resize_cmd = [
        "magick",
        temp_path,
        "-auto-orient",
        "-strip",
        "-colorspace",
        "sRGB",
        "-quality",
        quality,
        "-resize",
        str(IMG_WIDTH),
        "-unsharp",
        "0x0.5+0.5+0.008",
        *noise_args,
        output_path,
    ]
    subprocess.run(resize_cmd, check=True)
    os.remove(temp_path)


def get_flickr_image(flickr_url, danger_of_banding=False):
    photo_id = extract_photo_id(flickr_url)
    title_cache = load_cache()
    image_path = f"{IMG_DIR}/{photo_id}.avif"

    if photo_id in title_cache and os.path.exists(image_path):
        print(f"Using cached title and image for {flickr_url}")
        title = title_cache[photo_id]
    else:
        title, image_url = fetch_image_data(flickr_url)
        title_cache[photo_id] = title
        save_cache(title_cache)

        os.makedirs(IMG_DIR, exist_ok=True)
        if not os.path.exists(image_path):
            temp_path = f"{IMG_DIR}/{photo_id}_temp.jpg"
            download_image(image_url, temp_path)
            process_image(temp_path, image_path, danger_of_banding)

    print(f"Completed processing for {flickr_url}")
    return FlickrImageData(url=image_path, title=title_cache[photo_id])


def generate_gallery_html(content):
    html = ""
    for item in content["items"]:
        if "flickr" in item:
            print(f"Processing gallery item: {item['flickr']}")
            image_data = get_flickr_image(
                item["flickr"], item.get("danger_of_banding", False)
            )
            html += (
                f'<div class="gallery-item">'
                f'<a href="{item["flickr"]}">'
                f'<img src="{image_data.url}" alt="{image_data.title}" class="gallery-image">'
                "</a></div>"
            )
        if "text" in item:
            text_html = "</p><p class='gallery-text'>".join(item["text"])
            html += f'<div class="gallery-item"><p class="gallery-text">{text_html}</p></div>'
    return html


def render_html(template_path, content_html, output_path):
    with open(template_path) as template, open(output_path, "w") as output:
        output.write(template.read().replace("{{ gallery_items }}", content_html))


def main():
    with open("content.yaml") as content_file:
        content = yaml.safe_load(content_file)
    gallery_html = generate_gallery_html(content)
    render_html("template.html", gallery_html, "output.html")
    print("Webpage generation complete. Output saved to output.html.")


if __name__ == "__main__":
    main()

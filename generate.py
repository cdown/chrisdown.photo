#!/usr/bin/env python
import os
import re
import json
import yaml
import requests
import subprocess
from selectolax.parser import HTMLParser
from collections import namedtuple

FlickrImageData = namedtuple("FlickrImageData", ["title", "sizes"])
CACHE_FILE = "image_titles_cache.json"
IMG_DIR = "images"

IMG_HEIGHTS = [1080, 1440, 2160]


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


def process_image_for_height(temp_path, output_path, height, danger_of_banding):
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
        f"x{height}",
        "-unsharp",
        "0x0.5+0.5+0.008",
        *noise_args,
        output_path,
    ]
    subprocess.run(resize_cmd, check=True)


def get_flickr_image(flickr_url, danger_of_banding=False):
    photo_id = extract_photo_id(flickr_url)
    title_cache = load_cache()
    image_title = title_cache.get(photo_id, None)
    sizes = {}

    # We store references to e.g. images/<photo_id>_1080.avif, etc.
    # If not all sizes exist, fetch image and create them
    # Otherwise, if they're on disk, just skip re-download
    missing_sizes = []
    for h in IMG_HEIGHTS:
        path_for_height = f"{IMG_DIR}/{photo_id}_{h}.avif"
        sizes[str(h)] = path_for_height
        if not os.path.exists(path_for_height):
            missing_sizes.append(h)

    if missing_sizes or image_title is None:
        # Need to either fetch or generate images
        if image_title is None:
            fetched_title, image_url = fetch_image_data(flickr_url)
            title_cache[photo_id] = fetched_title
            save_cache(title_cache)
        else:
            # We already have the title, but we still need the URL for re-downloading
            _, image_url = fetch_image_data(flickr_url)

        image_title = title_cache[photo_id]
        os.makedirs(IMG_DIR, exist_ok=True)

        temp_path = f"{IMG_DIR}/{photo_id}_temp.jpg"
        download_image(image_url, temp_path)

        for h in missing_sizes:
            avif_path = f"{IMG_DIR}/{photo_id}_{h}.avif"
            process_image_for_height(temp_path, avif_path, h, danger_of_banding)

        os.remove(temp_path)

    print(f"Completed processing for {flickr_url}")
    return FlickrImageData(title=image_title, sizes=sizes)


def generate_gallery_html(content):
    html = ""
    for item in content["items"]:
        if "flickr" in item:
            print(f"Processing gallery item: {item['flickr']}")
            image_data = get_flickr_image(
                item["flickr"], item.get("danger_of_banding", False)
            )
            data_attrs = []
            for h in IMG_HEIGHTS:
                data_attrs.append(f'data-{h}="{image_data.sizes[str(h)]}"')
            data_attrs_str = " ".join(data_attrs)
            html += (
                f'<div class="gallery-item">'
                f'<img src="" {data_attrs_str} alt="{image_data.title}" class="gallery-image">'
                "</div>"
            )
        if "text" in item:
            text_html = "</p><p class='gallery-text'>".join(item["text"])
            html += f'<div class="gallery-item"><p class="gallery-text">{text_html}</p></div>'
    return html


def generate_about(content):
    html = f"""
    <div class="about-content">
        <img class="about-image" src="{content["about"]["image"]}">
        <div class="about-text">
            {''.join(f"<p>{item}</p>" for item in content["about"]["text"])}
        </div>
    </div>
    """
    return html

def render_html(template_path, content, output_path):
    with open(template_path) as template, open(output_path, "w") as output:
        output.write(
            template.read()
            .replace("{{ gallery_items }}", generate_gallery_html(content))
            .replace("{{ about }}", generate_about(content))
        )


def main():
    with open("content.yaml") as content_file:
        content = yaml.safe_load(content_file)
    render_html("template.html", content, "output.html")
    print("Webpage generation complete. Output saved to output.html.")


if __name__ == "__main__":
    main()

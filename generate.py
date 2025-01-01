#!/usr/bin/env python
import os
import re
import json
import yaml
import requests
import subprocess
from selectolax.parser import HTMLParser
from collections import namedtuple

FlickrImageData = namedtuple("FlickrImageData", ["title", "sizes", "width", "height"])
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


def get_local_image_dimensions(image_path):
    try:
        result = subprocess.run(
            ["identify", "-format", "%w %h", image_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        width_str, height_str = result.stdout.strip().split()
        width, height = int(width_str), int(height_str)
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid dimensions for {image_path}")
        return width, height
    except Exception as e:
        raise ValueError(f"Could not determine image dimensions from {image_path}") from e


def process_image_for_height(temp_path, output_path, height, danger_of_banding):
    quality = "95" if danger_of_banding else "85"

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
    cache = load_cache()
    image_info = cache.get(photo_id, {})
    image_title = image_info.get("title")
    image_width = image_info.get("width")
    image_height = image_info.get("height")

    sizes = {}
    missing_sizes = []
    for h in IMG_HEIGHTS:
        path_for_height = f"{IMG_DIR}/{photo_id}_{h}.avif"
        sizes[str(h)] = path_for_height
        if not os.path.exists(path_for_height):
            missing_sizes.append(h)

    # We need to download if missing sizes OR we don't have dimension/title yet
    if missing_sizes or image_title is None or image_width is None or image_height is None:
        fetched_title, image_url = fetch_image_data(flickr_url)

        # Download the original image so we can find out its dimensions
        os.makedirs(IMG_DIR, exist_ok=True)
        temp_path = f"{IMG_DIR}/{photo_id}_temp.jpg"
        download_image(image_url, temp_path)
        width, height = get_local_image_dimensions(temp_path)

        # Update in-memory cache
        image_info["title"] = fetched_title
        image_info["width"] = width
        image_info["height"] = height
        cache[photo_id] = image_info
        save_cache(cache)

        # For newly missing sizes, do the conversion
        for h_val in missing_sizes:
            avif_path = f"{IMG_DIR}/{photo_id}_{h_val}.avif"
            process_image_for_height(temp_path, avif_path, h_val, danger_of_banding)

        os.remove(temp_path)
    else:
        # Use cached values
        fetched_title = image_info["title"]
        width = image_info["width"]
        height = image_info["height"]

    print(f"Completed processing for {flickr_url}")
    return FlickrImageData(
        title=fetched_title,
        sizes=sizes,
        width=width,
        height=height
    )


def generate_gallery_html(content):
    html = ""
    for index, item in enumerate(content["items"]):
        if "flickr" in item:
            print(f"Processing gallery item: {item['flickr']}")
            image_data = get_flickr_image(
                item["flickr"], item.get("danger_of_banding", False)
            )
            data_attrs = []
            for h in IMG_HEIGHTS:
                data_attrs.append(f'data-{h}="{image_data.sizes[str(h)]}"')
            data_attrs_str = " ".join(data_attrs)
            aspect_ratio = f"{image_data.width}/{image_data.height}"

            html += (
                f'<div class="gallery-item" data-index="{index}">'
                f'<img src="" style="aspect-ratio: {aspect_ratio};" {data_attrs_str} alt="{image_data.title}" class="gallery-image">'
                f"</div>"
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

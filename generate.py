#!/usr/bin/env python

import yaml
import requests
from selectolax.parser import HTMLParser
import json
import os


def load_cache(file_path):
    try:
        with open(file_path, "r") as cache_file:
            return json.load(cache_file)
    except FileNotFoundError:
        return {}


def save_cache(cache, file_path):
    with open(file_path, "w") as cache_file:
        json.dump(cache, cache_file, indent=4)


def get_flickr_image_url(flickr_url, size):
    print(f"Fetching image URL for {flickr_url} size {size}")
    response = requests.get(f"{flickr_url}/sizes/{size}/")
    html = HTMLParser(response.text)
    img_tag = html.css_first('div#allsizes-photo > img[src*="live.staticflickr.com"]')

    if img_tag:
        return img_tag.attributes["src"]

    return None


def find_large_enough_flickr_image_url(flickr_url, flickr_cache):
    if flickr_url in flickr_cache:
        print(f"Using cached URL for {flickr_url}")
        return flickr_cache[flickr_url]

    # Smallest to largest that may give >= min_width.
    sizes = ["l", "h", "k", "o"]

    # On desjtop, the layout has a body width of 1400px with 10px border on
    # each side, resulting in 1380px usable width. For a two-column layout,
    # each column should be half of 1380px, which is 690px. Accounting for an
    # 8px gap on each side of a column due to 16px column-gap, the required
    # image width is # 690 - 8 = 682px.
    #
    # For a single column layout (e.g., on mobile), the width requirement is
    # 900px minus some padding and scrollbar, leading to a practical minimum
    # width requirement of 880px to ensure quality display in all layouts.
    min_width = 880

    for size in sizes:
        img_url = get_flickr_image_url(flickr_url, size)
        if img_url:
            response = requests.head(img_url)
            if "imagewidth" in response.headers:
                width = int(response.headers["imagewidth"])
                if width >= min_width:
                    flickr_cache[flickr_url] = img_url
                    return img_url

    raise ValueError("No images are big enough on Flickr")


def generate_gallery_items_html(content, flickr_cache):
    gallery_items_html = ""
    for item in content["items"]:
        if "flickr" in item:
            img_url = find_large_enough_flickr_image_url(item["flickr"], flickr_cache)
            gallery_items_html += (
                '<div class="gallery-item">'
                f'<a href="{item["flickr"]}">'
                f'<img src="{img_url}" alt="" class="gallery-image">'
                "</a>"
                "</div>"
            )
        if "text" in item:
            text_html = "</p><p class='gallery-text'>".join(item["text"])
            gallery_items_html += (
                '<div class="gallery-item">'
                f"<p class='gallery-text'>{text_html}</p>"
                "</div>"
            )
    return gallery_items_html


def render_html(template_file, gallery_items_html, output_path):
    with open(output_path, "w") as output_file:
        for line in template_file:
            output_file.write(line.replace("{{ gallery_items }}", gallery_items_html))


def main():
    with open("content.yaml", "r") as content_file:
        content = yaml.safe_load(content_file)

    with open("template.html", "r") as template_file:
        flickr_cache = load_cache("flickr_cache.json")

        gallery_items_html = generate_gallery_items_html(content, flickr_cache)
        render_html(template_file, gallery_items_html, "output.html")

        save_cache(flickr_cache, "flickr_cache.json")
        print("Webpage generation complete. Output saved to output.html.")
        print("Cache saved to flickr_cache.json.")


if __name__ == "__main__":
    main()

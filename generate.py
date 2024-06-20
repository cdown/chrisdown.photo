#!/usr/bin/env python

import yaml
import requests
from selectolax.parser import HTMLParser
import json
import os
from collections import namedtuple

FlickrImageData = namedtuple("FlickrImageData", ["url", "title"])


def load_cache(file_path):
    try:
        with open(file_path, "r") as cache_file:
            return json.load(cache_file)
    except FileNotFoundError:
        return {}


def save_cache(cache, file_path):
    with open(file_path, "w") as cache_file:
        json.dump(cache, cache_file, indent=4)


def get_flickr_image_data(flickr_url, size):
    print(f"Fetching image data for {flickr_url} size {size}")
    response = requests.get(f"{flickr_url}/sizes/{size}/")
    html = HTMLParser(response.text)
    img_tag = html.css_first('div#allsizes-photo > img[src*="live.staticflickr.com"]')
    meta_title_tag = html.css_first('meta[name="title"]')

    if not img_tag:
        raise ValueError(f"Image tag not found for {flickr_url} size {size}")

    if not meta_title_tag:
        raise ValueError(f"Meta title tag not found for {flickr_url}")

    return FlickrImageData(
        url=img_tag.attributes["src"], title=meta_title_tag.attributes["content"]
    )


def find_large_enough_flickr_image_data(flickr_url, flickr_cache):
    if flickr_url in flickr_cache:
        print(f"Using cached data for {flickr_url}")
        return FlickrImageData(
            url=flickr_cache[flickr_url]["url"], title=flickr_cache[flickr_url]["title"]
        )

    # Smallest to largest that may give >= min_width.
    sizes = ["c", "l", "h", "k", "o"]

    # On desjtop, the layout has a body width of 1400px with 10px border on
    # each side, resulting in 1380px usable width. For a two-column layout,
    # each column should be half of 1380px, which is 690px. Accounting for an
    # 8px gap on each side of a column due to 16px column-gap, the required
    # image width is # 690 - 8 = 682px.
    #
    # For a single column layout (e.g., on mobile), the width requirement is
    # 820px minus 10px padding either side, leading to a practical minimum
    # width requirement of 800px to ensure quality display in all layouts.
    min_width = 800

    for size in sizes:
        image_data = get_flickr_image_data(flickr_url, size)
        response = requests.head(image_data.url)
        if "imagewidth" in response.headers:
            width = int(response.headers["imagewidth"])
            if width >= min_width:
                flickr_cache[flickr_url] = {
                    "url": image_data.url,
                    "title": image_data.title,
                }
                return image_data

    raise ValueError("No images are big enough on Flickr")


def generate_gallery_items_html(content, flickr_cache):
    gallery_items_html = ""
    for item in content["items"]:
        if "flickr" in item:
            image_data = find_large_enough_flickr_image_data(
                item["flickr"], flickr_cache
            )
            gallery_items_html += (
                '<div class="gallery-item">'
                f'<a href="{item["flickr"]}">'
                f'<img src="{image_data.url}" alt="{image_data.title}" class="gallery-image">'
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

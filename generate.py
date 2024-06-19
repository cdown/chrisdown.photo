#!/usr/bin/env python

import yaml
import requests
from bs4 import BeautifulSoup
from jinja2 import Template
import json
import os


def load_yaml(file_path):
    with open(file_path, "r") as file:
        return yaml.safe_load(file)


def load_template(file_path):
    with open(file_path, "r") as file:
        return Template(file.read())


def load_cache(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as cache_file:
            return json.load(cache_file)
    return {}


def save_cache(cache, file_path):
    with open(file_path, "w") as cache_file:
        json.dump(cache, cache_file, indent=4)


def get_flickr_image_url(flickr_url, size):
    print(f"Fetching image URL for {flickr_url} size {size}")
    response = requests.get(f"{flickr_url}/sizes/{size}/")
    soup = BeautifulSoup(response.text, "html.parser")
    img_tag = soup.find("img", {"src": lambda x: x and "live.staticflickr.com" in x})

    if img_tag:
        return img_tag["src"]

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
            if 'imagewidth' in response.headers:
                width = int(response.headers['imagewidth'])
                if width >= min_width:
                    flickr_cache[flickr_url] = img_url
                    return img_url

    raise ValueError("No images are big enough on Flickr")


def generate_gallery_items_html(content, flickr_cache):
    gallery_items_html = ""
    for item in content["items"]:
        if "flickr" in item:
            img_url = find_large_enough_flickr_image_url(item["flickr"], flickr_cache)
            gallery_items_html += f"""
            <div class="gallery-item">
                <a href="{item['flickr']}">
                    <img src="{img_url}" alt="" class="gallery-image">
                </a>
            </div>
            """
        if "text" in item:
            gallery_items_html += f"""
            <div class="gallery-item">
                {"<p class='gallery-text'>" + "</p><p class='gallery-text'>".join(item['text']) + "</p>"}
            </div>
            """
    return gallery_items_html


def render_html(template, gallery_items_html, output_path):
    html_output = template.render(gallery_items=gallery_items_html)
    with open(output_path, "w") as file:
        file.write(html_output)


def main():
    content = load_yaml("content.yaml")
    template = load_template("template.html")
    flickr_cache = load_cache("flickr_cache.json")

    gallery_items_html = generate_gallery_items_html(content, flickr_cache)
    render_html(template, gallery_items_html, "output.html")

    save_cache(flickr_cache, "flickr_cache.json")
    print("Webpage generation complete. Output saved to output.html.")
    print("Cache saved to flickr_cache.json.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python

import os
import re
import json
import yaml
import requests
import subprocess
from selectolax.parser import HTMLParser
from collections import namedtuple

CACHE_FILE = "image_titles_cache.json"
IMG_DIR = "images"
IMG_WIDTHS = [800, 1400, 2000, 3000]

FlickrImageData = namedtuple("FlickrImageData", ["title"])


def _load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as fh:
            return json.load(fh)
    return {}


def _save_cache(cache):
    with open(CACHE_FILE, "w") as fh:
        json.dump(cache, fh, indent=2)


def _photo_id(url):
    m = re.search(r"/photos/[^/]+/(\d+)", url)
    if not m:
        raise ValueError(f"Bad Flickr URL: {url}")
    return m.group(1)


def _fetch_image_page(url):
    r = requests.get(f"{url}/sizes/o/")
    r.raise_for_status()
    doc = HTMLParser(r.text)
    title = doc.css_first('meta[name="title"]').attributes["content"]
    img = doc.css_first(
        'div#allsizes-photo img[src*="live.staticflickr.com"]'
    ).attributes["src"]
    return title, img


def _download(url, dest):
    r = requests.get(url)
    r.raise_for_status()
    with open(dest, "wb") as fh:
        fh.write(r.content)


def _dimensions(path):
    res = subprocess.run(
        ["identify", "-format", "%w %h", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    w, h = map(int, res.stdout.strip().split())
    return w, h


def _resize(src, dest, width, danger_of_banding=False):
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

    cmd = [
        "magick",
        src,
        "-auto-orient",
        "-strip",
        "-colorspace",
        "sRGB",
        "-quality",
        quality,
        "-resize",
        str(width),
    ]

    if noise_args:
        cmd.extend(noise_args)

    cmd.append(dest)

    subprocess.run(cmd, check=True)


def get_flickr_image(url, danger_of_banding=False):
    pid = _photo_id(url)
    cache = _load_cache()
    meta = cache.get(pid, {})

    sizes = {str(w): f"{IMG_DIR}/{pid}_{w}.avif" for w in IMG_WIDTHS}
    missing = [w for w in IMG_WIDTHS if not os.path.exists(sizes[str(w)])]

    if missing or not {"title", "width", "height"} <= meta.keys():
        title, big = _fetch_image_page(url)
        os.makedirs(IMG_DIR, exist_ok=True)
        tmp = f"{IMG_DIR}/{pid}_src.jpg"
        _download(big, tmp)
        w, h = _dimensions(tmp)
        meta.update({"title": title, "width": w, "height": h})
        cache[pid] = meta
        _save_cache(cache)
        for w_out in missing:
            _resize(tmp, sizes[str(w_out)], w_out, danger_of_banding)
        os.remove(tmp)

    return FlickrImageData(
        title=meta["title"],
    )


def _generate_image_data(item):
    """Generate structured data for a single image"""
    danger_of_banding = item.get("danger_of_banding", False)
    data = get_flickr_image(item["flickr"], danger_of_banding)
    pid = _photo_id(item["flickr"])

    return {
        "id": pid,
        "title": data.title,
        "sizes": IMG_WIDTHS,
    }


def build_gallery(content):
    """Generate a JSON data structure for all images"""
    images = []

    for item in content["items"]:
        image_data = _generate_image_data(item)
        images.append(image_data)

    js_content = f"""
<div id="gallery-one-col" class="gallery layout-one-col">
  <div class="column" id="one-col-container"></div>
</div>

<div id="gallery-two-col" class="gallery layout-two-col">
  <div class="column" id="two-col-1"></div>
  <div class="column" id="two-col-2"></div>
</div>

<div id="gallery-three-col" class="gallery layout-three-col">
  <div class="column" id="three-col-1"></div>
  <div class="column" id="three-col-2"></div>
  <div class="column" id="three-col-3"></div>
</div>

<script>
const GALLERY_IMAGES = {json.dumps(images)};

const LAYOUT_CONFIG = {{
  one_col: {{
    images: {json.dumps([_photo_id(item["flickr"]) for item in content["layouts"]["one_col"]])}
  }},
  two_col: {{
    col1: {json.dumps([_photo_id(item["flickr"]) for item in content["layouts"]["two_col"]["col1"]])},
    col2: {json.dumps([_photo_id(item["flickr"]) for item in content["layouts"]["two_col"]["col2"]])}
  }},
  three_col: {{
    col1: {json.dumps([_photo_id(item["flickr"]) for item in content["layouts"]["three_col"]["col1"]])},
    col2: {json.dumps([_photo_id(item["flickr"]) for item in content["layouts"]["three_col"]["col2"]])},
    col3: {json.dumps([_photo_id(item["flickr"]) for item in content["layouts"]["three_col"]["col3"]])}
  }}
}};
</script>
"""
    return js_content


def build_about(about_block):
    paras = "".join(f"<p>{p}</p>" for p in about_block["text"])
    img = about_block["image"]
    return (
        '<div class="about-content">'
        f'<img class="about-image" src="{img}" alt="Chris Down portrait">'
        f'<div class="about-text">{paras}</div>'
        "</div>"
    )


def render(template_path, content, output_path):
    tpl = open(template_path).read()
    html = tpl.replace("{{ gallery }}", build_gallery(content))
    html = html.replace("{{ about }}", build_about(content["about"]))
    with open(output_path, "w") as fh:
        fh.write(html)


def main():
    raw = open("content.yaml").read()
    content = yaml.safe_load(raw)
    render("template.html", content, "output.html")
    print("Generated output.html")


if __name__ == "__main__":
    main()

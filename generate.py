#!/usr/bin/env python

import os
import re
import json
import yaml
import requests
import subprocess
from selectolax.parser import HTMLParser
from collections import namedtuple
from multiprocessing import Pool, cpu_count

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
    quality = "90" if danger_of_banding else "85"

    tmp_png = dest.replace(".avif", "_tmp.png")
    cmd = [
        "magick",
        src,
        "-auto-orient",
        "-strip",
        "-colorspace",
        "sRGB",
        "-resize",
        str(width),
    ]

    cmd.append(tmp_png)
    subprocess.run(cmd, check=True)

    # Generate AVIF using cavif with RGB encoding
    subprocess.run(
        [
            "cavif",
            "--quality",
            quality,
            "--speed",
            "1",
            "--depth",
            "8",
            "--color",
            "rgb",
            "--overwrite",
            tmp_png,
            "--output",
            dest,
        ],
        check=True,
    )

    # Generate JPEG fallback for Firefox due to colour management issues with
    # AVIF. Sigh...
    jpeg_dest = dest.replace(".avif", ".jpg")
    jpeg_quality = "95" if danger_of_banding else "90"
    subprocess.run(
        [
            "magick",
            tmp_png,
            "-quality",
            jpeg_quality,
            jpeg_dest,
        ],
        check=True,
    )

    os.remove(tmp_png)


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

        # Return resize jobs for later parallel processing
        return (
            FlickrImageData(title=meta["title"]),
            tmp,
            sizes,
            missing,
            danger_of_banding,
        )

    return (FlickrImageData(title=meta["title"]), None, None, None, None)


def _generate_image_data(item):
    """Generate structured data for a single image"""
    danger_of_banding = item.get("danger_of_banding", False)
    result = get_flickr_image(item["flickr"], danger_of_banding)
    data, tmp, sizes, missing, danger = result
    pid = _photo_id(item["flickr"])
    cache = _load_cache()
    meta = cache.get(pid, {})

    return {
        "id": pid,
        "title": data.title,
        "sizes": IMG_WIDTHS,
        "width": meta.get("width"),
        "height": meta.get("height"),
        "resize_job": (tmp, sizes, missing, danger) if tmp else None,
    }


def _build_image_html(pid, meta, index):
    """Generate HTML for a single image element"""
    aspect_ratio = f"{meta['width']} / {meta['height']}"
    return f"""<img class="gallery-image"
         data-image-id="{pid}"
         alt="{meta['title']}"
         width="{meta['width']}"
         height="{meta['height']}"
         style="aspect-ratio:{aspect_ratio}"
         src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==">"""


def _build_column_html(image_ids, cache, column_id):
    """Generate HTML for a column of images"""
    images_html = []
    for index, item in enumerate(image_ids):
        pid = _photo_id(item["flickr"])
        if pid not in cache:
            continue
        meta = cache[pid]
        images_html.append(_build_image_html(pid, meta, index))

    return f'<div class="column" id="{column_id}">{"".join(images_html)}</div>'


def build_gallery(content):
    """Generate server-rendered HTML gallery with all images"""
    images = []
    resize_jobs = []

    # First pass: download and prepare all images
    for item in content["items"]:
        image_data = _generate_image_data(item)
        if image_data["resize_job"]:
            tmp, sizes, missing, danger = image_data["resize_job"]
            for w_out in missing:
                resize_jobs.append((tmp, sizes[str(w_out)], w_out, danger))
        del image_data["resize_job"]
        images.append(image_data)

    # Second pass: resize all in parallel
    if resize_jobs:
        print(f"Processing {len(resize_jobs)} resize jobs in parallel...")
        with Pool(cpu_count()) as pool:
            pool.starmap(_resize, resize_jobs)

        # Clean up source files
        source_files = set(job[0] for job in resize_jobs)
        for src_file in source_files:
            if os.path.exists(src_file):
                os.remove(src_file)

    cache = _load_cache()

    one_col_html = _build_column_html(
        content["layouts"]["one_col"], cache, "one-col-container"
    )

    two_col_html = _build_column_html(
        content["layouts"]["two_col"]["col1"], cache, "two-col-1"
    ) + _build_column_html(content["layouts"]["two_col"]["col2"], cache, "two-col-2")

    three_col_html = (
        _build_column_html(
            content["layouts"]["three_col"]["col1"], cache, "three-col-1"
        )
        + _build_column_html(
            content["layouts"]["three_col"]["col2"], cache, "three-col-2"
        )
        + _build_column_html(
            content["layouts"]["three_col"]["col3"], cache, "three-col-3"
        )
    )

    gallery_html = f"""
<div id="gallery-one-col" class="gallery layout-one-col">
  {one_col_html}
</div>

<div id="gallery-two-col" class="gallery layout-two-col">
  {two_col_html}
</div>

<div id="gallery-three-col" class="gallery layout-three-col">
  {three_col_html}
</div>

<script>
const IMAGE_SIZES = {json.dumps(IMG_WIDTHS)};
</script>
"""
    return gallery_html


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

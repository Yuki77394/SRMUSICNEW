import os
import re
import aiofiles
import aiohttp
from io import BytesIO
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from py_yt import VideosSearch
from config import YOUTUBE_IMG_URL

# Constants
CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

PANEL_W, PANEL_H = 763, 545
PANEL_X = (1280 - PANEL_W) // 2
PANEL_Y = 88
TRANSPARENCY = 170
INNER_OFFSET = 36

THUMB_W, THUMB_H = 542, 273
THUMB_X = PANEL_X + (PANEL_W - THUMB_W) // 2
THUMB_Y = PANEL_Y + INNER_OFFSET

TITLE_X = 377
META_X = 377
TITLE_Y = THUMB_Y + THUMB_H + 10
META_Y = TITLE_Y + 45

BAR_X, BAR_Y = 388, META_Y + 45
BAR_RED_LEN = 280
BAR_TOTAL_LEN = 480

ICONS_W, ICONS_H = 415, 45
ICONS_X = PANEL_X + (PANEL_W - ICONS_W) // 2
ICONS_Y = BAR_Y + 48

MAX_TITLE_WIDTH = 580

def trim_to_width(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    ellipsis = "…"
    if font.getlength(text) <= max_w:
        return text
    for i in range(len(text) - 1, 0, -1):
        if font.getlength(text[:i] + ellipsis) <= max_w:
            return text[:i] + ellipsis
    return ellipsis


# ---------------------------------------------------------------------------
# Local image validation helpers
#
# These guarantee that any local path returned by get_thumb() points to a
# real, PIL-readable image file. They do NOT change the existing thumbnail
# design — they only validate / regenerate the SAME design.
# ---------------------------------------------------------------------------

def _is_valid_local_image(path: str) -> bool:
    """Return True only if *path* exists, has non-zero size, and can be
    opened + verified by PIL as a real image in a Telegram-compatible mode.

    Telegram Bot API rejects photos with an alpha channel (RGBA/P/LA modes)
    with DOCUMENT_INVALID, so we only accept RGB images here. This forces
    cached RGBA PNGs (from before this fix) to be regenerated as RGB.
    """
    try:
        if not path or not isinstance(path, str):
            return False
        if not os.path.exists(path):
            return False
        if os.path.getsize(path) <= 0:
            return False
        with Image.open(path) as im:
            im.verify()  # raises if file is not a valid image
        # Re-open to check mode (verify() invalidates the image object)
        with Image.open(path) as im:
            mode = im.mode
            # Telegram Bot API requires RGB — reject anything with alpha
            if mode != "RGB":
                return False
        return True
    except Exception:
        return False


def _remove_file(path: str) -> None:
    """Best-effort delete of a cache file."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


async def _download_and_validate_image(url: str) -> bytes:
    """Download *url* and validate the response bytes as a real image
    using PIL.Image.verify().

    Returns the raw image bytes if validation succeeds, otherwise None.

    This prevents HTML error pages (e.g. catbox 404), empty responses,
    truncated downloads, and non-image content from ever being written to
    the cache directory.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return None
                raw = await resp.read()
                if not raw or len(raw) == 0:
                    return None
                # Validate with PIL before accepting the bytes
                try:
                    buf = BytesIO(raw)
                    with Image.open(buf) as im:
                        im.verify()
                    return raw
                except Exception:
                    return None
    except Exception:
        return None


async def _download_fallback_image(url: str, dest_path: str) -> str:
    """Download a fallback URL, validate it with PIL, and save it locally
    as a real image file. Returns dest_path if successful, None otherwise."""
    raw = await _download_and_validate_image(url)
    if raw is None:
        return None
    try:
        # Re-open the validated bytes and re-save as PNG to ensure a clean
        # local copy that Telegram can always read.
        buf = BytesIO(raw)
        with Image.open(buf) as im:
            im.convert("RGB").save(dest_path, "PNG")
        if _is_valid_local_image(dest_path):
            return dest_path
        return None
    except Exception:
        _remove_file(dest_path)
        return None


async def get_thumb(videoid: str):
    """Generate (or return cached) thumbnail for *videoid*.

    Guarantees:
      - Returns a local file path that points to a real, PIL-verified image.
      - Returns None if thumbnail generation completely fails.

    NEVER returns a remote URL or an unverified file path.
    """
    cache_path = os.path.join(CACHE_DIR, f"{videoid}_v4.png")

    # ------------------------------------------------------------------
    # Cache validation — never blindly return a corrupted cache file
    # ------------------------------------------------------------------
    if os.path.exists(cache_path):
        if _is_valid_local_image(cache_path):
            return cache_path
        # Corrupted cache → delete and regenerate
        _remove_file(cache_path)

    # ------------------------------------------------------------------
    # YouTube video data fetch
    # ------------------------------------------------------------------
    results = VideosSearch(f"https://www.youtube.com/watch?v={videoid}", limit=1)
    try:
        results_data = await results.next()
        result_items = results_data.get("result", [])
        if not result_items:
            raise ValueError("No results found.")
        data = result_items[0]
        title = re.sub(r"\W+", " ", data.get("title", "Unsupported Title")).title()
        thumbnail = data.get("thumbnails", [{}])[0].get("url", YOUTUBE_IMG_URL)
        duration = data.get("duration")
        views = data.get("viewCount", {}).get("short", "Unknown Views")
    except Exception:
        title, thumbnail, duration, views = "Unsupported Title", YOUTUBE_IMG_URL, None, "Unknown Views"

    is_live = not duration or str(duration).strip().lower() in {"", "live", "live now"}
    duration_text = "Live" if is_live else duration or "Unknown Mins"

    # ------------------------------------------------------------------
    # Download thumbnail bytes + validate with PIL BEFORE writing to disk
    # ------------------------------------------------------------------
    thumb_path = os.path.join(CACHE_DIR, f"thumb{videoid}.png")
    raw_bytes = await _download_and_validate_image(thumbnail)

    if raw_bytes is None:
        # Fallback: try to download YOUTUBE_IMG_URL as a last resort and
        # validate it locally. If that also fails, return None so the
        # caller uses a text-only panel.
        fallback_path = os.path.join(CACHE_DIR, f"thumb{videoid}_fb.png")
        fb = await _download_fallback_image(YOUTUBE_IMG_URL, fallback_path)
        if fb is None:
            return None
        # Use the validated fallback as the source for the base image
        thumb_path = fb
    else:
        # Write validated bytes to disk for the existing design pipeline
        try:
            async with aiofiles.open(thumb_path, "wb") as f:
                await f.write(raw_bytes)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Build the existing thumbnail design (UNCHANGED — same visuals)
    # ------------------------------------------------------------------
    try:
        base = Image.open(thumb_path).resize((1280, 720)).convert("RGBA")
        bg = ImageEnhance.Brightness(base.filter(ImageFilter.BoxBlur(10))).enhance(0.6)

        # Frosted glass panel
        panel_area = bg.crop((PANEL_X, PANEL_Y, PANEL_X + PANEL_W, PANEL_Y + PANEL_H))
        overlay = Image.new("RGBA", (PANEL_W, PANEL_H), (255, 255, 255, TRANSPARENCY))
        frosted = Image.alpha_composite(panel_area, overlay)
        mask = Image.new("L", (PANEL_W, PANEL_H), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, PANEL_W, PANEL_H), 50, fill=255)
        bg.paste(frosted, (PANEL_X, PANEL_Y), mask)

        # Draw details
        draw = ImageDraw.Draw(bg)
        try:
            title_font = ImageFont.truetype("SWAGGYMUSIC/assets/font2.ttf", 32)
            regular_font = ImageFont.truetype("SWAGGYMUSIC/assets/font.ttf", 18)
        except OSError:
            title_font = regular_font = ImageFont.load_default()

        thumb = base.resize((THUMB_W, THUMB_H))
        tmask = Image.new("L", thumb.size, 0)
        ImageDraw.Draw(tmask).rounded_rectangle((0, 0, THUMB_W, THUMB_H), 20, fill=255)
        bg.paste(thumb, (THUMB_X, THUMB_Y), tmask)

        draw.text((TITLE_X, TITLE_Y), trim_to_width(title, title_font, MAX_TITLE_WIDTH), fill="black", font=title_font)
        draw.text((META_X, META_Y), f"YouTube | {views}", fill="black", font=regular_font)

        # Progress bar
        draw.line([(BAR_X, BAR_Y), (BAR_X + BAR_RED_LEN, BAR_Y)], fill="red", width=6)
        draw.line([(BAR_X + BAR_RED_LEN, BAR_Y), (BAR_X + BAR_TOTAL_LEN, BAR_Y)], fill="gray", width=5)
        draw.ellipse([(BAR_X + BAR_RED_LEN - 7, BAR_Y - 7), (BAR_X + BAR_RED_LEN + 7, BAR_Y + 7)], fill="red")

        draw.text((BAR_X, BAR_Y + 15), "00:00", fill="black", font=regular_font)
        end_text = "Live" if is_live else duration_text
        draw.text((BAR_X + BAR_TOTAL_LEN - (90 if is_live else 60), BAR_Y + 15), end_text, fill="red" if is_live else "black", font=regular_font)

        # Icons
        icons_path = "SWAGGYMUSIC/assets/play_icons.png"
        if os.path.isfile(icons_path):
            ic = Image.open(icons_path).resize((ICONS_W, ICONS_H)).convert("RGBA")
            r, g, b, a = ic.split()
            black_ic = Image.merge("RGBA", (r.point(lambda *_: 0), g.point(lambda *_: 0), b.point(lambda *_: 0), a))
            bg.paste(black_ic, (ICONS_X, ICONS_Y), black_ic)

        # Save final composite
        # Flatten RGBA → RGB before saving so Telegram's Bot API accepts the
        # photo. Telegram rejects photos that contain an alpha channel with
        # DOCUMENT_INVALID, even when the alpha is mostly opaque (the frosted
        # glass panel produces alpha values 191-255). We composite onto a
        # white background which preserves the exact visual appearance of the
        # existing design (the blurred thumbnail + frosted panel is already
        # fully opaque visually — the alpha channel is just an artifact of the
        # RGBA compositing pipeline).
        try:
            flat = Image.new("RGB", bg.size, (255, 255, 255))
            flat.paste(bg, mask=bg.getchannel("A"))
            flat.save(cache_path)
        except Exception:
            _remove_file(cache_path)
            return None
    except Exception:
        # Generation failed — make sure we don't leave a partial cache file
        _remove_file(cache_path)
        return None
    finally:
        # Always clean up the intermediate downloaded thumbnail
        _remove_file(thumb_path)

    # ------------------------------------------------------------------
    # Final guarantee: only return the cache path if it's a valid image
    # ------------------------------------------------------------------
    if _is_valid_local_image(cache_path):
        return cache_path
    return None

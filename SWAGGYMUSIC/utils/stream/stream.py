#
# Copyright (C) 2021-2022 by TheAloneteam@Github, < https://github.com/TheAloneTeam >.
#
# This file is part of < https://github.com/TheAloneTeam/SWAGGYMUSIC > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/TheAloneTeam/SWAGGYMUSIC/blob/master/LICENSE >
#
# All rights reserved.

import os
from random import randint
from typing import Union

from PIL import Image as PILImage
from pyrogram.errors import (DocumentInvalid, ExternalUrlInvalid, MediaEmpty,
                             MediaInvalid, MessageIdInvalid, MessageNotModified,
                             PhotoInvalid, PhotoInvalidDimensions,
                             PhotoSaveFileInvalid, SendMessageMediaInvalid,
                             WebpageCurlFailed, WebpageMediaEmpty,
                             WebpageNotFound, WebpageUrlInvalid)
from pyrogram.types import InlineKeyboardMarkup, InputMediaPhoto

import config
from SWAGGYMUSIC import LOGGER, Carbon, YouTube, app
from SWAGGYMUSIC.core.call import Alone
from SWAGGYMUSIC.misc import db
from SWAGGYMUSIC.utils.database import (add_active_video_chat, get_filter,
                                       is_active_chat, is_autoplay_on,
                                       is_thumb_on)
from SWAGGYMUSIC.utils.exceptions import AssistantErr
from SWAGGYMUSIC.utils.inline import aq_markup, close_markup, stream_markup
from SWAGGYMUSIC.utils.pastebin import AloneBin
from SWAGGYMUSIC.utils.stream.queue import put_queue, put_queue_index
from SWAGGYMUSIC.utils.thumbnails import get_thumb


# ---------------------------------------------------------------------------
# Thumbnail validation / recovery helpers
#
# These helpers wrap the existing get_thumb() so that update_stream_ui never
# passes an invalid image to Telegram's send_photo. They do NOT modify
# thumbnails.py — the existing thumbnail design is preserved exactly.
# ---------------------------------------------------------------------------


def _extract_vidid_from_path(img: Union[str, None]) -> Union[str, None]:
    """Extract the YouTube video id from a local cache path produced by
    thumbnails.get_thumb (pattern: cache/{vidid}_v4.png)."""
    if not img or not isinstance(img, str):
        return None
    if img.startswith(("http://", "https://")):
        return None
    basename = os.path.basename(img)
    if basename.endswith("_v4.png"):
        return basename[: -len("_v4.png")]
    return None


async def _validate_thumbnail(img: Union[str, None]) -> tuple:
    """Validate that *img* is a usable thumbnail for Telegram send_photo.

    Returns ``(is_valid: bool, validated_path: str|None, info: str)``.

    For URLs we cannot pre-validate cheaply (Telegram fetches them server-side),
    so we accept them but the caller must still handle DocumentInvalid at send
    time. For local files we verify existence, size > 0, and PIL readability.
    """
    if not img or not isinstance(img, str):
        return (False, None, f"empty/non-string img: {type(img).__name__}")

    # URL — assume valid (let Telegram try); recovery happens at send time
    if img.startswith(("http://", "https://")):
        return (True, img, f"URL (not pre-validated): {img}")

    # Local file
    if not os.path.exists(img):
        return (False, None, f"local file does not exist: {img}")

    size = os.path.getsize(img)
    if size == 0:
        return (False, None, f"local file is empty (0 bytes): {img}")

    try:
        with PILImage.open(img) as im:
            im.verify()  # raises if the file is not a valid image
        # verify() closes the file; reopen to read format/mode
        with PILImage.open(img) as im:
            fmt = im.format
            mode = im.mode
        return (
            True,
            img,
            f"local file OK: format={fmt} mode={mode} size={size} bytes path={img}",
        )
    except Exception as e:
        return (False, None, f"PIL verification failed for {img}: {e}")


async def _regenerate_thumbnail(vidid: str, original_img: Union[str, None]) -> Union[str, None]:
    """Delete the corrupted cache file (if any) and re-call get_thumb(vidid)
    so thumbnails.py regenerates the SAME existing design from scratch."""
    if not vidid:
        return None

    if original_img and isinstance(original_img, str) and not original_img.startswith(("http://", "https://")):
        try:
            if os.path.exists(original_img):
                os.remove(original_img)
                LOGGER(__name__).warning(
                    f"Thumbnail regeneration: removed corrupted cache file {original_img}"
                )
        except Exception as e:
            LOGGER(__name__).error(
                f"Thumbnail regeneration: failed to remove {original_img}: {e}"
            )

    try:
        new_img = await get_thumb(vidid)
        LOGGER(__name__).info(
            f"Thumbnail regeneration: get_thumb({vidid}) returned {new_img}"
        )
        return new_img
    except Exception as e:
        LOGGER(__name__).error(
            f"Thumbnail regeneration: get_thumb({vidid}) raised: {e}"
        )
        return None


async def _safe_reencode_thumbnail(img: Union[str, None]) -> Union[str, None]:
    """Re-encode the existing image as a clean JPEG without changing its
    visual design. Useful when the original PNG is somehow rejected by
    Telegram (e.g. unusual ICC profile, exotic compression)."""
    if not img or not isinstance(img, str):
        return None
    if img.startswith(("http://", "https://")):
        return None  # cannot re-encode a URL

    try:
        with PILImage.open(img) as im:
            rgb = im.convert("RGB")
            temp_path = img + ".reencoded.jpg"
            rgb.save(temp_path, "JPEG", quality=95)
        LOGGER(__name__).info(
            f"Thumbnail re-encode: saved JPEG copy to {temp_path}"
        )
        return temp_path
    except Exception as e:
        LOGGER(__name__).error(
            f"Thumbnail re-encode failed for {img}: {e}"
        )
        return None


async def _prepare_thumbnail(img: Union[str, None]) -> Union[str, None]:
    """Validate the thumbnail returned by get_thumb() and attempt recovery
    (regeneration + JPEG re-encode) if it is invalid.

    Returns a validated local file path / URL that is safe to pass to
    send_photo, or ``None`` if all recovery attempts failed (caller should
    fall back to a text-only panel).
    """
    is_valid, validated, info = await _validate_thumbnail(img)
    LOGGER(__name__).info(f"Thumbnail prepare: initial validation → {info}")

    if is_valid:
        return validated

    # Attempt 1: regenerate via get_thumb (extract vidid from cache path)
    vidid = _extract_vidid_from_path(img)
    if vidid:
        LOGGER(__name__).warning(
            f"Thumbnail prepare: attempting regeneration for vidid={vidid}"
        )
        regenerated = await _regenerate_thumbnail(vidid, img)
        if regenerated:
            is_valid, validated, info = await _validate_thumbnail(regenerated)
            LOGGER(__name__).info(
                f"Thumbnail prepare: post-regeneration validation → {info}"
            )
            if is_valid:
                return validated
            # Attempt 2: re-encode the regenerated file as JPEG
            reencoded = await _safe_reencode_thumbnail(regenerated)
            if reencoded:
                is_valid, validated, info = await _validate_thumbnail(reencoded)
                if is_valid:
                    LOGGER(__name__).info(
                        f"Thumbnail prepare: JPEG re-encode after regeneration OK"
                    )
                    return validated
    else:
        # No vidid available (e.g. static config URL that is dead) — try to
        # re-encode if it happens to be a local file
        if img and isinstance(img, str) and not img.startswith(("http://", "https://")):
            reencoded = await _safe_reencode_thumbnail(img)
            if reencoded:
                is_valid, validated, info = await _validate_thumbnail(reencoded)
                if is_valid:
                    LOGGER(__name__).info(
                        f"Thumbnail prepare: JPEG re-encode OK"
                    )
                    return validated

    LOGGER(__name__).error(
        f"Thumbnail prepare: all recovery attempts failed for img={img}"
    )
    return None


# ---------------------------------------------------------------------------
# Panel update / creation
# ---------------------------------------------------------------------------

async def update_stream_ui(
    chat_id,
    original_chat_id,
    mystic,
    img,
    caption,
    button,
):
    # Errors that indicate the panel message reference itself is no longer
    # usable (deleted, in another chat, too old to edit, etc.).
    _INVALID_MSG_REFS = (
        MessageIdInvalid,
        MessageNotModified,
    )

    # Errors that indicate the photo/media payload is unusable.
    _INVALID_PHOTO_ERRORS = (
        DocumentInvalid,
        MediaInvalid,
        MediaEmpty,
        PhotoInvalid,
        PhotoInvalidDimensions,
        PhotoSaveFileInvalid,
        SendMessageMediaInvalid,
        ExternalUrlInvalid,
        WebpageCurlFailed,
        WebpageMediaEmpty,
        WebpageNotFound,
        WebpageUrlInvalid,
    )

    markup = InlineKeyboardMarkup(button)

    # ------------------------------------------------------------------
    # THUMBNAIL ON path
    # ------------------------------------------------------------------
    if await is_thumb_on(chat_id):
        # Validate + attempt regeneration / re-encode BEFORE calling send_photo
        prepared_img = await _prepare_thumbnail(img)

        if prepared_img is not None:
            # We have a validated image → try edit_media first (in-place),
            # then send_photo. mystic is only deleted AFTER a replacement
            # message has been successfully created.
            if mystic:
                try:
                    return await mystic.edit_media(
                        media=InputMediaPhoto(prepared_img, caption=caption, has_spoiler=True),
                        reply_markup=markup,
                    )
                except _INVALID_MSG_REFS as edit_err:
                    LOGGER(__name__).warning(
                        f"update_stream_ui: edit_media failed for chat={chat_id} "
                        f"(mystic id={getattr(mystic, 'id', None)}): {edit_err}. "
                        f"Will send a fresh photo panel."
                    )
                except Exception as edit_err:
                    LOGGER(__name__).error(
                        f"update_stream_ui: unexpected edit_media error for "
                        f"chat={chat_id}: {edit_err}. Will send a fresh photo panel."
                    )

            # Send a fresh photo message FIRST, then delete the old mystic
            try:
                new_msg = await app.send_photo(
                    original_chat_id,
                    photo=prepared_img,
                    has_spoiler=True,
                    caption=caption,
                    reply_markup=markup,
                )
                # Replacement succeeded — now safe to delete old mystic
                if mystic:
                    try:
                        await mystic.delete()
                    except Exception:
                        pass
                return new_msg
            except _INVALID_PHOTO_ERRORS as photo_err:
                LOGGER(__name__).error(
                    f"update_stream_ui: send_photo failed for chat={original_chat_id} "
                    f"({photo_err}). Falling back to text-only playback panel."
                )
            except Exception as photo_err:
                LOGGER(__name__).error(
                    f"update_stream_ui: send_photo raised unexpected error for "
                    f"chat={original_chat_id}: {photo_err}. Falling back to text-only."
                )
        else:
            LOGGER(__name__).error(
                f"update_stream_ui: thumbnail could not be validated/regenerated "
                f"for chat={chat_id}. Skipping send_photo, using text-only panel."
            )

        # ----- text-only fallback (thumbnail invalid OR send_photo failed) -----
        if mystic:
            try:
                return await mystic.edit_text(text=caption, reply_markup=markup)
            except _INVALID_MSG_REFS as edit_err:
                LOGGER(__name__).warning(
                    f"update_stream_ui: edit_text (text fallback) failed for "
                    f"chat={chat_id}: {edit_err}. Will send a fresh text panel."
                )
            except Exception as edit_err:
                # Maybe mystic was a photo message → try edit_caption
                try:
                    await mystic.edit_caption(caption=caption, reply_markup=markup)
                    return mystic
                except Exception:
                    LOGGER(__name__).error(
                        f"update_stream_ui: edit_text/edit_caption both failed "
                        f"for chat={chat_id}: {edit_err}. Sending fresh text panel."
                    )

        try:
            new_msg = await app.send_message(
                original_chat_id,
                text=caption,
                reply_markup=markup,
            )
            # Replacement succeeded — now safe to delete old mystic
            if mystic:
                try:
                    await mystic.delete()
                except Exception:
                    pass
            return new_msg
        except Exception as msg_err:
            LOGGER(__name__).error(
                f"update_stream_ui: text-only send_message also failed for "
                f"chat={original_chat_id}: {msg_err}"
            )
            raise

    # ------------------------------------------------------------------
    # THUMBNAIL OFF path (text-only)
    # ------------------------------------------------------------------
    else:
        if mystic:
            try:
                return await mystic.edit_text(
                    text=caption,
                    reply_markup=markup,
                )
            except _INVALID_MSG_REFS as edit_err:
                LOGGER(__name__).warning(
                    f"update_stream_ui: edit_text failed for chat={chat_id} "
                    f"(mystic id={getattr(mystic, 'id', None)}): {edit_err}. "
                    f"Will send a fresh text panel."
                )
            except Exception as edit_err:
                try:
                    await mystic.edit_caption(caption=caption, reply_markup=markup)
                    return mystic
                except Exception:
                    LOGGER(__name__).error(
                        f"update_stream_ui: edit_text/edit_caption both failed "
                        f"for chat={chat_id}: {edit_err}. Sending fresh text panel."
                    )

        try:
            new_msg = await app.send_message(
                original_chat_id,
                text=caption,
                reply_markup=markup,
            )
            if mystic:
                try:
                    await mystic.delete()
                except Exception:
                    pass
            return new_msg
        except Exception as msg_err:
            LOGGER(__name__).error(
                f"update_stream_ui: send_message failed for "
                f"chat={original_chat_id}: {msg_err}"
            )
            raise


async def update_queue_ui(
    chat_id,
    original_chat_id,
    mystic,
    caption,
    button,
):
    if mystic:
        if await is_thumb_on(chat_id):
            try:
                await mystic.edit_caption(
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(button),
                )
            except Exception:
                try:
                    await mystic.edit_text(
                        text=caption,
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                except Exception:
                    pass
        else:
            try:
                await mystic.edit_text(
                    text=caption,
                    reply_markup=InlineKeyboardMarkup(button),
                )
            except Exception:
                try:
                    await mystic.edit_caption(
                        caption=caption,
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                except Exception:
                    pass
    else:
        await app.send_message(
            chat_id=original_chat_id,
            text=caption,
            reply_markup=InlineKeyboardMarkup(button),
        )


async def stream(
    _,
    mystic,
    user_id,
    result,
    chat_id,
    user_name,
    original_chat_id,
    video: Union[bool, str] = None,
    streamtype: Union[bool, str] = None,
    spotify: Union[bool, str] = None,
    forceplay: Union[bool, str] = None,
):
    if not result:
        return
    if forceplay:
        await Alone.force_stop_stream(chat_id)
    if streamtype == "playlist":
        msg = f"{_['play_19']}\n\n"
        count = 0
        for search in result:
            if int(count) == config.PLAYLIST_FETCH_LIMIT:
                continue
            try:
                (
                    title,
                    duration_min,
                    duration_sec,
                    thumbnail,
                    vidid,
                ) = await YouTube.details(search, False if spotify else True)
            except:
                continue
            if str(duration_min) == "None":
                continue
            if duration_sec > config.DURATION_LIMIT:
                continue
            if await is_active_chat(chat_id):
                await put_queue(
                    chat_id,
                    original_chat_id,
                    f"vid_{vidid}",
                    title,
                    duration_min,
                    user_name,
                    vidid,
                    user_id,
                    "video" if video else "audio",
                    mystic=mystic,
                )
                position = len(db.get(chat_id)) - 1
                count += 1
                msg += f"{count}. {title[:70]}\n"
                msg += f"{_['play_20']} {position}\n\n"
            else:
                if not forceplay:
                    db[chat_id] = []
                status = True if video else None
                try:
                    file_path, direct = await YouTube.download(
                        vidid, mystic, video=status, videoid=True
                    )
                except:
                    raise AssistantErr(_["play_14"])
                await Alone.join_call(
                    chat_id,
                    original_chat_id,
                    file_path,
                    title,
                    video=status,
                    image=thumbnail,
                )
                await put_queue(
                    chat_id,
                    original_chat_id,
                    file_path if direct else f"vid_{vidid}",
                    title,
                    duration_min,
                    user_name,
                    vidid,
                    user_id,
                    "video" if video else "audio",
                    forceplay=forceplay,
                    mystic=mystic,
                )
                img = await get_thumb(vidid)
                button = stream_markup(
                    _, chat_id, await is_autoplay_on(chat_id), await is_thumb_on(chat_id), await get_filter(chat_id)
                )
                caption = _["stream_1"].format(
                    f"https://t.me/{app.username}?start=info_{vidid}",
                    title[:23],
                    duration_min,
                    user_name,
                )
                run = await update_stream_ui(chat_id, original_chat_id, mystic, img, caption, button)
                db[chat_id][0]["mystic"] = run
                db[chat_id][0]["markup"] = "stream"
                db[chat_id][0]["file"] = file_path
        if count == 0:
            return
        else:
            link = await AloneBin(msg)
            lines = msg.count("\n")
            if lines >= 17:
                car = os.linesep.join(msg.split(os.linesep)[:17])
            else:
                car = msg
            carbon = await Carbon.generate(car, randint(100, 10000000))
            upl = close_markup(_)
            return await app.send_photo(
                original_chat_id,
                has_spoiler=True,
                photo=carbon,
                caption=_["play_21"].format(position, link),
                reply_markup=upl,
            )
    elif streamtype == "youtube":
        link = result["link"]
        vidid = result["vidid"]
        title = (result["title"]).title()
        duration_min = result["duration_min"]
        thumbnail = result["thumb"]
        status = True if video else None
        try:
            file_path, direct = await YouTube.download(
                vidid, mystic, videoid=True, video=status
            )
        except Exception as ex:
            print(ex)
            raise AssistantErr(_["play_14"])
        if await is_active_chat(chat_id):
            await put_queue(
                chat_id,
                original_chat_id,
                file_path if direct else f"vid_{vidid}",
                title,
                duration_min,
                user_name,
                vidid,
                user_id,
                "video" if video else "audio",
                mystic=mystic,
            )
            position = len(db.get(chat_id)) - 1
            button = aq_markup(_, chat_id)
            caption = _["queue_4"].format(position, title[:27], duration_min, user_name)
            await update_queue_ui(chat_id, original_chat_id, mystic, caption, button)
        else:
            if not forceplay:
                db[chat_id] = []
            await Alone.join_call(
                chat_id,
                original_chat_id,
                file_path,
                title,
                video=status,
                image=thumbnail,
            )
            await put_queue(
                chat_id,
                original_chat_id,
                file_path if direct else f"vid_{vidid}",
                title,
                duration_min,
                user_name,
                vidid,
                user_id,
                "video" if video else "audio",
                forceplay=forceplay,
                mystic=mystic,
            )
            img = await get_thumb(vidid)
            button = stream_markup(
                _, chat_id, await is_autoplay_on(chat_id), await is_thumb_on(chat_id), await get_filter(chat_id)
            )
            caption = _["stream_1"].format(
                f"https://t.me/{app.username}?start=info_{vidid}",
                title[:23],
                duration_min,
                user_name,
            )
            run = await update_stream_ui(chat_id, original_chat_id, mystic, img, caption, button)
            db[chat_id][0]["mystic"] = run
            db[chat_id][0]["markup"] = "stream"
            db[chat_id][0]["file"] = file_path
    elif streamtype == "soundcloud":
        file_path = result["filepath"]
        title = result["title"]
        duration_min = result["duration_min"]
        if await is_active_chat(chat_id):
            await put_queue(
                chat_id,
                original_chat_id,
                file_path,
                title,
                duration_min,
                user_name,
                streamtype,
                user_id,
                "audio",
                mystic=mystic,
            )
            position = len(db.get(chat_id)) - 1
            button = aq_markup(_, chat_id)
            caption = _["queue_4"].format(position, title[:27], duration_min, user_name)
            await update_queue_ui(chat_id, original_chat_id, mystic, caption, button)
        else:
            if not forceplay:
                db[chat_id] = []
            await Alone.join_call(chat_id, original_chat_id, file_path, title, video=None)
            await put_queue(
                chat_id,
                original_chat_id,
                file_path,
                title,
                duration_min,
                user_name,
                streamtype,
                user_id,
                "audio",
                forceplay=forceplay,
                mystic=mystic,
            )
            button = stream_markup(
                _, chat_id, await is_autoplay_on(chat_id), await is_thumb_on(chat_id), await get_filter(chat_id)
            )
            caption = _["stream_1"].format(
                config.SUPPORT_CHAT, title[:23], duration_min, user_name
            )
            run = await update_stream_ui(chat_id, original_chat_id, mystic, config.SOUNCLOUD_IMG_URL, caption, button)
            db[chat_id][0]["mystic"] = run
            db[chat_id][0]["markup"] = "tg"
            db[chat_id][0]["file"] = file_path
    elif streamtype == "telegram":
        file_path = result["path"]
        link = result["link"]
        title = (result["title"]).title()
        duration_min = result["dur"]
        status = True if video else None
        if await is_active_chat(chat_id):
            await put_queue(
                chat_id,
                original_chat_id,
                file_path,
                title,
                duration_min,
                user_name,
                streamtype,
                user_id,
                "video" if video else "audio",
                mystic=mystic,
            )
            position = len(db.get(chat_id)) - 1
            button = aq_markup(_, chat_id)
            caption = _["queue_4"].format(position, title[:27], duration_min, user_name)
            await update_queue_ui(chat_id, original_chat_id, mystic, caption, button)
        else:
            if not forceplay:
                db[chat_id] = []
            await Alone.join_call(chat_id, original_chat_id, file_path, title, video=status)
            await put_queue(
                chat_id,
                original_chat_id,
                file_path,
                title,
                duration_min,
                user_name,
                streamtype,
                user_id,
                "video" if video else "audio",
                forceplay=forceplay,
                mystic=mystic,
            )
            if video:
                await add_active_video_chat(chat_id)
            button = stream_markup(
                _, chat_id, await is_autoplay_on(chat_id), await is_thumb_on(chat_id), await get_filter(chat_id)
            )
            img = config.TELEGRAM_VIDEO_URL if video else config.TELEGRAM_AUDIO_URL
            caption = _["stream_1"].format(link, title[:23], duration_min, user_name)
            run = await update_stream_ui(chat_id, original_chat_id, mystic, img, caption, button)
            db[chat_id][0]["mystic"] = run
            db[chat_id][0]["markup"] = "tg"
            db[chat_id][0]["file"] = file_path
    elif streamtype == "live":
        link = result["link"]
        vidid = result["vidid"]
        title = (result["title"]).title()
        thumbnail = result["thumb"]
        duration_min = "Live Track"
        status = True if video else None
        if await is_active_chat(chat_id):
            await put_queue(
                chat_id,
                original_chat_id,
                f"live_{vidid}",
                title,
                duration_min,
                user_name,
                vidid,
                user_id,
                "video" if video else "audio",
                mystic=mystic,
            )
            position = len(db.get(chat_id)) - 1
            button = aq_markup(_, chat_id)
            caption = _["queue_4"].format(position, title[:27], duration_min, user_name)
            await update_queue_ui(chat_id, original_chat_id, mystic, caption, button)
        else:
            if not forceplay:
                db[chat_id] = []
            n, file_path = await YouTube.video(link)
            if n == 0:
                raise AssistantErr(_["str_3"])
            await Alone.join_call(
                chat_id,
                original_chat_id,
                file_path,
                title,
                video=status,
                image=thumbnail if thumbnail else None,
            )
            await put_queue(
                chat_id,
                original_chat_id,
                f"live_{vidid}",
                title,
                duration_min,
                user_name,
                vidid,
                user_id,
                "video" if video else "audio",
                forceplay=forceplay,
                mystic=mystic,
            )
            img = await get_thumb(vidid)
            button = stream_markup(
                _, chat_id, await is_autoplay_on(chat_id), await is_thumb_on(chat_id), await get_filter(chat_id)
            )
            caption = _["stream_1"].format(
                f"https://t.me/{app.username}?start=info_{vidid}",
                title[:23],
                duration_min,
                user_name,
            )
            run = await update_stream_ui(chat_id, original_chat_id, mystic, img, caption, button)
            db[chat_id][0]["mystic"] = run
            db[chat_id][0]["markup"] = "tg"
    elif streamtype == "index":
        link = result
        title = "ɪɴᴅᴇx ᴏʀ ᴍ3ᴜ8 ʟɪɴᴋ"
        duration_min = "00:00"
        if await is_active_chat(chat_id):
            await put_queue_index(
                chat_id,
                original_chat_id,
                "index_url",
                title,
                duration_min,
                user_name,
                link,
                "video" if video else "audio",
                mystic=mystic,
            )
            position = len(db.get(chat_id)) - 1
            button = aq_markup(_, chat_id)
            caption = _["queue_4"].format(position, title[:27], duration_min, user_name)
            await update_queue_ui(chat_id, original_chat_id, mystic, caption, button)
        else:
            if not forceplay:
                db[chat_id] = []
            await Alone.join_call(
                chat_id,
                original_chat_id,
                link,
                title,
                video=True if video else None,
            )
            await put_queue_index(
                chat_id,
                original_chat_id,
                "index_url",
                title,
                duration_min,
                user_name,
                link,
                "video" if video else "audio",
                forceplay=forceplay,
                mystic=mystic,
            )
            button = stream_markup(
                _, chat_id, await is_autoplay_on(chat_id), await is_thumb_on(chat_id), await get_filter(chat_id)
            )
            caption = _["stream_2"].format(user_name)
            run = await update_stream_ui(chat_id, original_chat_id, mystic, config.STREAM_IMG_URL, caption, button)
            db[chat_id][0]["mystic"] = run
            db[chat_id][0]["markup"] = "tg"
            db[chat_id][0]["file"] = link

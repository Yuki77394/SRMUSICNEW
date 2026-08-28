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
# Thumbnail validation helper
#
# After fixing thumbnails.py, get_thumb() is guaranteed to return either:
#   - a local file path that points to a real, PIL-verified image
#   - None
#
# So this helper only needs to validate LOCAL files. URLs are NEVER accepted
# as valid images — they are the source of DOCUMENT_INVALID in production.
# ---------------------------------------------------------------------------

def _validate_local_thumbnail(img: Union[str, None]) -> bool:
    """Return True only if *img* is a non-empty string pointing to an
    existing local file with non-zero size that PIL can verify as a real
    image. URLs and None are rejected."""
    try:
        if not img or not isinstance(img, str):
            return False
        # Reject URLs — only local file paths are valid after thumbnails.py fix
        if img.startswith(("http://", "https://")):
            return False
        if not os.path.exists(img):
            return False
        if os.path.getsize(img) <= 0:
            return False
        from PIL import Image as PILImage
        with PILImage.open(img) as im:
            im.verify()
        return True
    except Exception:
        return False


async def _send_text_panel(original_chat_id, caption, markup, mystic=None):
    """Best-effort text-only panel creation.

    Order:
      1. If mystic exists, try edit_text (in-place)
      2. If that fails (or no mystic), send a fresh message
      3. Only AFTER the fresh message is created, delete the old mystic
      4. Return the new (or edited) Message object

    This prevents MESSAGE_ID_INVALID by never deleting the old mystic
    before a replacement exists.
    """
    # Errors that mean the panel message reference itself is no longer usable
    _INVALID_MSG_REFS = (MessageIdInvalid, MessageNotModified)

    if mystic:
        try:
            return await mystic.edit_text(text=caption, reply_markup=markup)
        except _INVALID_MSG_REFS as edit_err:
            LOGGER(__name__).warning(
                f"update_stream_ui: edit_text failed for chat={original_chat_id} "
                f"(mystic id={getattr(mystic, 'id', None)}): {edit_err}. "
                f"Will send a fresh text panel."
            )
        except Exception as edit_err:
            # Maybe mystic is a photo message → try edit_caption as last resort
            try:
                await mystic.edit_caption(caption=caption, reply_markup=markup)
                return mystic
            except Exception:
                LOGGER(__name__).error(
                    f"update_stream_ui: edit_text/edit_caption both failed "
                    f"for chat={original_chat_id}: {edit_err}. Sending fresh text panel."
                )

    # Send a fresh text message FIRST, then delete old mystic AFTER success
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
            f"update_stream_ui: text-only send_message also failed for "
            f"chat={original_chat_id}: {msg_err}"
        )
        raise


async def update_stream_ui(
    chat_id,
    original_chat_id,
    mystic,
    img,
    caption,
    button,
):
    """Update or create the playback panel.

    Thumbnail ON  → use img (validated local file) for a photo panel;
                    if img is None/invalid, fall back to text-only.
    Thumbnail OFF → always use text-only panel.

    Safety guarantees:
      - mystic is NEVER deleted before a replacement panel exists
      - edit_media is only attempted when mystic actually contains a photo
      - URLs are NEVER passed to send_photo (thumbnails.py no longer returns
        URLs, but this is a defensive check)
    """
    _INVALID_MSG_REFS = (MessageIdInvalid, MessageNotModified)
    _INVALID_PHOTO_ERRORS = (
        DocumentInvalid, MediaInvalid, MediaEmpty, PhotoInvalid,
        PhotoInvalidDimensions, PhotoSaveFileInvalid, SendMessageMediaInvalid,
        ExternalUrlInvalid, WebpageCurlFailed, WebpageMediaEmpty,
        WebpageNotFound, WebpageUrlInvalid,
    )

    markup = InlineKeyboardMarkup(button)

    # ------------------------------------------------------------------
    # THUMBNAIL ON path
    # ------------------------------------------------------------------
    if await is_thumb_on(chat_id):
        # Validate the thumbnail — only accept real local image files
        if _validate_local_thumbnail(img):
            # We have a valid local image → try to use it
            #
            # Determine whether mystic is a PHOTO message (can edit_media)
            # or a TEXT message (must send a fresh photo panel).
            is_photo_msg = bool(getattr(mystic, "photo", None)) if mystic else False

            if mystic and is_photo_msg:
                try:
                    return await mystic.edit_media(
                        media=InputMediaPhoto(img, caption=caption, has_spoiler=True),
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
                # If we reach here, edit_media failed → fall through to send_photo

            # Send a fresh photo message FIRST, then delete old mystic AFTER
            try:
                new_msg = await app.send_photo(
                    original_chat_id,
                    photo=img,
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
                # Fall through to text-only fallback below
            except Exception as photo_err:
                LOGGER(__name__).error(
                    f"update_stream_ui: send_photo raised unexpected error for "
                    f"chat={original_chat_id}: {photo_err}. Falling back to text-only."
                )
                # Fall through to text-only fallback below
        else:
            LOGGER(__name__).error(
                f"update_stream_ui: thumbnail is invalid/None for chat={chat_id} "
                f"(img={img}). Using text-only panel fallback."
            )

        # ----- text-only fallback (thumbnail invalid OR send_photo failed) -----
        return await _send_text_panel(original_chat_id, caption, markup, mystic)

    # ------------------------------------------------------------------
    # THUMBNAIL OFF path (text-only)
    # ------------------------------------------------------------------
    else:
        return await _send_text_panel(original_chat_id, caption, markup, mystic)


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

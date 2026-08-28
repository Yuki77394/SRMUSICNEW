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


async def update_stream_ui(
    chat_id,
    original_chat_id,
    mystic,
    img,
    caption,
    button,
):
    # Errors that indicate the panel message reference itself is no longer
    # usable (deleted, in another chat, too old to edit, etc.). When any of
    # these is raised we must drop the stored mystic and create a fresh panel.
    _INVALID_MSG_REFS = (
        MessageIdInvalid,
        MessageNotModified,
    )

    # Errors that indicate the photo/media payload is unusable. When any of
    # these is raised by send_photo we fall back to a text-only panel so the
    # user is never left without playback controls.
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

    if await is_thumb_on(chat_id):
        if mystic:
            try:
                # If it's already a photo message, edit it in place
                return await mystic.edit_media(
                    media=InputMediaPhoto(img, caption=caption, has_spoiler=True),
                    reply_markup=markup,
                )
            except _INVALID_MSG_REFS as edit_err:
                # mystic is no longer editable (deleted / wrong type / etc.).
                # Try to delete the stale reference, then fall through to send_photo.
                LOGGER(__name__).warning(
                    f"update_stream_ui: edit_media failed for chat={chat_id} "
                    f"(mystic id={getattr(mystic, 'id', None)}): {edit_err}. "
                    f"Will send a fresh photo panel."
                )
                try:
                    await mystic.delete()
                except Exception:
                    pass
            except Exception as edit_err:
                # Unexpected error from edit_media — log it and try the fresh
                # photo path so playback is not interrupted.
                LOGGER(__name__).error(
                    f"update_stream_ui: unexpected edit_media error for "
                    f"chat={chat_id}: {edit_err}. Falling back to send_photo."
                )
                try:
                    await mystic.delete()
                except Exception:
                    pass
        # Send a fresh photo panel (fallback when mystic could not be edited
        # or when there was no mystic to begin with, e.g. autoplay next-song
        # path in call.py).
        try:
            return await app.send_photo(
                original_chat_id,
                photo=img,
                has_spoiler=True,
                caption=caption,
                reply_markup=markup,
            )
        except _INVALID_PHOTO_ERRORS as photo_err:
            # The thumbnail image is unusable (DocumentInvalid, bad URL,
            # corrupted cache file, etc.). Recover by sending a text-only
            # panel with the same caption + buttons so the user always has
            # working playback controls.
            LOGGER(__name__).error(
                f"update_stream_ui: send_photo failed for chat={original_chat_id} "
                f"({photo_err}). Falling back to text-only playback panel."
            )
            try:
                return await app.send_message(
                    original_chat_id,
                    text=caption,
                    reply_markup=markup,
                )
            except Exception as msg_err:
                LOGGER(__name__).error(
                    f"update_stream_ui: text-only fallback also failed for "
                    f"chat={original_chat_id}: {msg_err}"
                )
                raise
        except Exception as photo_err:
            # Any other send_photo error — also fall back to text-only panel
            # so a single bad thumbnail never breaks the whole play flow.
            LOGGER(__name__).error(
                f"update_stream_ui: send_photo raised unexpected error for "
                f"chat={original_chat_id}: {photo_err}. Falling back to text-only."
            )
            try:
                return await app.send_message(
                    original_chat_id,
                    text=caption,
                    reply_markup=markup,
                )
            except Exception as msg_err:
                LOGGER(__name__).error(
                    f"update_stream_ui: text-only fallback also failed for "
                    f"chat={original_chat_id}: {msg_err}"
                )
                raise
    else:
        if mystic:
            try:
                # If it's a text message, edit it
                return await mystic.edit_text(
                    text=caption,
                    reply_markup=markup,
                )
            except _INVALID_MSG_REFS as edit_err:
                # mystic is no longer editable. Drop the stale reference and
                # fall through to send_message.
                LOGGER(__name__).warning(
                    f"update_stream_ui: edit_text failed for chat={chat_id} "
                    f"(mystic id={getattr(mystic, 'id', None)}): {edit_err}. "
                    f"Will send a fresh text panel."
                )
                try:
                    await mystic.delete()
                except Exception:
                    pass
            except Exception as edit_err:
                # If it was a photo message or edit_text failed for another
                # reason, try edit_caption as a last in-place attempt.
                try:
                    await mystic.edit_caption(
                        caption=caption,
                        reply_markup=markup,
                    )
                    return mystic
                except Exception:
                    try:
                        await mystic.delete()
                    except Exception:
                        pass
                    LOGGER(__name__).error(
                        f"update_stream_ui: edit_text/edit_caption both failed "
                        f"for chat={chat_id}: {edit_err}. Sending fresh text panel."
                    )
        try:
            return await app.send_message(
                original_chat_id,
                text=caption,
                reply_markup=markup,
            )
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

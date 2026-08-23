#
# Copyright (C) 2021-2022 by TheAloneteam@Github, < https://github.com/TheAloneTeam >.
#
# This file is part of < https://github.com/TheAloneTeam/AloneMusic > project,
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/TheAloneTeam/AloneMusic/blob/master/LICENSE >
#
# All rights reserved.

import asyncio
import os
import random
import re
import urllib.parse
from typing import Union

import httpx
import yt_dlp
from py_yt import VideosSearch
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

from AloneMusic import LOGGER
from AloneMusic.utils.formatters import time_to_seconds
import config


# ============================================================
# API CONFIG
# ============================================================

API_URL = os.getenv(
    "API_URL",
    "https://api.riteshyt.in",
).rstrip("/")

API_KEY = os.getenv(
    "API_KEY",
    "riteshfree576fd88ed84a3f46c84fd556",
).strip()


# ============================================================
# DOWNLOAD HELPERS
# ============================================================

async def download_assistant(
    query: str,
    dl_type: str,
) -> str:
    """
    Generate API download URL.
    """

    safe_query = urllib.parse.quote(
        str(query),
        safe="",
    )

    ext = (
        "mp3"
        if dl_type == "audio"
        else "mp4"
    )

    if API_KEY:
        return (
            f"{API_URL}/downloads/"
            f"{API_KEY}/{safe_query}.{ext}"
        )

    return (
        f"{API_URL}/downloads/stream"
        f"?query={safe_query}"
        f"&dl_type={dl_type}"
    )


async def download_song(
    link: str,
) -> str:
    return await download_assistant(
        link,
        "audio",
    )


async def download_video(
    link: str,
) -> str:
    return await download_assistant(
        link,
        "video",
    )


# ============================================================
# YOUTUBE API
# ============================================================

class YouTubeAPI:

    def __init__(self):
        self.base = (
            "https://www.youtube.com/watch?v="
        )

        self.regex = (
            r"(?:youtube\.com|youtu\.be)"
        )

        self.status = (
            "https://www.youtube.com/oembed?url="
        )

        self.listbase = (
            "https://youtube.com/playlist?list="
        )

        self.reg = re.compile(
            r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
        )

        self._client = None

        self.cache_dir = os.path.join(
            os.getcwd(),
            "cache",
            "youtube",
        )

        os.makedirs(
            self.cache_dir,
            exist_ok=True,
        )

    # ========================================================
    # HTTP CLIENT
    # ========================================================

    async def get_client(self):
        if (
            self._client is None
            or self._client.is_closed
        ):
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    600.0,
                    connect=15.0,
                ),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 "
                        "(X11; Linux x86_64) "
                        "AppleWebKit/537.36 "
                        "Chrome/120 Safari/537.36"
                    )
                },
            )

        return self._client

    # ========================================================
    # BASIC YOUTUBE CHECK
    # ========================================================

    async def exists(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link

        return bool(
            re.search(
                self.regex,
                link,
            )
        )

    # ========================================================
    # URL FROM TELEGRAM MESSAGE
    # ========================================================

    async def url(
        self,
        message_1: Message,
    ) -> Union[str, None]:

        messages = [message_1]

        if message_1.reply_to_message:
            messages.append(
                message_1.reply_to_message
            )

        for message in messages:

            if message.entities:

                for entity in message.entities:

                    if (
                        entity.type
                        == MessageEntityType.URL
                    ):
                        text = (
                            message.text
                            or message.caption
                        )

                        if text:
                            return text[
                                entity.offset:
                                entity.offset
                                + entity.length
                            ]

            elif message.caption_entities:

                for entity in (
                    message.caption_entities
                ):

                    if (
                        entity.type
                        == MessageEntityType.TEXT_LINK
                    ):
                        return entity.url

        return None

    # ========================================================
    # CLEAN URL
    # ========================================================

    def _clean_link(
        self,
        link: str,
    ):
        if not link:
            return ""

        link = str(link).strip()

        if "&" in link:
            link = link.split("&")[0]

        if "?si=" in link:
            link = link.split("?si=")[0]

        elif "&si=" in link:
            link = link.split("&si=")[0]

        return link

    # ========================================================
    # EXTRACT VIDEO ID
    # ========================================================

    def _extract_video_id(
        self,
        link: str,
    ):
        regex = (
            r"(?:youtube\.com\/"
            r"(?:[^\/]+\/.+\/|"
            r"(?:v|e(?:mbed)?)\/|"
            r".*[?&]v=)|"
            r"youtu\.be\/)"
            r"([^\"&?\/\s]{11})"
        )

        match = re.search(
            regex,
            link,
        )

        if match:
            return match.group(1)

        return None

    # ========================================================
    # FETCH DETAILS
    # ========================================================

    async def _fetch_details(
        self,
        link: str,
    ):
        link = self._clean_link(link)

        client = await self.get_client()

        params = {
            "link": link,
        }

        if API_KEY:
            params["api_key"] = API_KEY

        try:

            response = await client.get(
                f"{API_URL}/details",
                params=params,
            )

            if response.status_code == 200:
                return response.json()

            LOGGER(__name__).error(
                "API Error "
                f"({response.status_code}): "
                f"{response.text[:500]}"
            )

        except Exception as e:

            LOGGER(__name__).error(
                f"Error fetching details: {e}"
            )

        return None

    # ========================================================
    # DETAILS
    # ========================================================

    async def details(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link

        data = await self._fetch_details(
            link
        )

        if data:
            return (
                data.get("title"),
                data.get("duration_min"),
                data.get("duration_sec"),
                data.get("thumbnail"),
                data.get("vidid"),
            )

        return (
            None,
            None,
            0,
            None,
            None,
        )

    # ========================================================
    # TITLE
    # ========================================================

    async def title(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link

        data = await self._fetch_details(
            link
        )

        return (
            data.get("title")
            if data
            else None
        )

    # ========================================================
    # DURATION
    # ========================================================

    async def duration(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link

        data = await self._fetch_details(
            link
        )

        return (
            data.get("duration_min")
            if data
            else None
        )

    # ========================================================
    # THUMBNAIL
    # ========================================================

    async def thumbnail(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.base + link

        data = await self._fetch_details(
            link
        )

        return (
            data.get("thumbnail")
            if data
            else None
        )

    # ========================================================
    # VALIDATE REMOTE AUDIO/VIDEO
    # ========================================================

    async def _check_stream_url(
        self,
        url: str,
        media_type: str = "audio",
    ) -> bool:
        """
        Check whether API returned a usable media source.

        Important:
        Some servers return HTML/JSON with HTTP 200.
        PyTgCalls then reports NoAudioSourceFound.
        """

        if not url:
            return False

        if not (
            str(url).startswith("http://")
            or str(url).startswith("https://")
        ):
            return False

        client = await self.get_client()

        for attempt in range(3):

            try:

                response = await client.get(
                    url,
                    headers={
                        "Range": "bytes=0-4095",
                        "User-Agent": (
                            "Mozilla/5.0"
                        ),
                    },
                    follow_redirects=True,
                )

                if response.status_code not in (
                    200,
                    206,
                ):
                    LOGGER(__name__).warning(
                        "Media source returned "
                        f"HTTP {response.status_code}"
                    )

                    await asyncio.sleep(
                        2 + attempt
                    )

                    continue

                content_type = (
                    response.headers.get(
                        "content-type",
                        "",
                    )
                    .lower()
                )

                data = response.content

                if not data:
                    await asyncio.sleep(
                        2 + attempt
                    )
                    continue

                # Reject HTML/JSON error pages.
                if (
                    "text/html"
                    in content_type
                ):
                    await asyncio.sleep(
                        2 + attempt
                    )
                    continue

                if (
                    "application/json"
                    in content_type
                ):
                    await asyncio.sleep(
                        2 + attempt
                    )
                    continue

                # Audio validation.
                if media_type == "audio":

                    audio_types = (
                        "audio/",
                        "application/octet-stream",
                    )

                    if not any(
                        x in content_type
                        for x in audio_types
                    ):
                        # MP3 magic bytes.
                        if not (
                            data[:3] == b"ID3"
                            or data[:2]
                            in (
                                b"\xff\xfb",
                                b"\xff\xf3",
                                b"\xff\xf2",
                            )
                        ):
                            await asyncio.sleep(
                                2 + attempt
                            )
                            continue

                return True

            except Exception as e:

                LOGGER(__name__).warning(
                    "Stream check failed "
                    f"(attempt {attempt + 1}): {e}"
                )

                await asyncio.sleep(
                    2 + attempt
                )

        return False

    # ========================================================
    # API DOWNLOAD URL
    # ========================================================

    async def _api_download_url(
        self,
        link: str,
        dl_type: str,
    ):
        link = self._clean_link(link)

        vidid = self._extract_video_id(
            link
        )

        if vidid:

            ext = (
                "mp4"
                if dl_type == "video"
                else "mp3"
            )

            if API_KEY:
                return (
                    f"{API_URL}/downloads/"
                    f"{API_KEY}/youtube.com/"
                    f"{vidid}.{ext}"
                )

            return (
                f"{API_URL}/downloads/"
                f"youtube.com/{vidid}.{ext}"
            )

        return await download_assistant(
            link,
            dl_type,
        )

    # ========================================================
    # YOUTUBE VIDEO
    # ========================================================

    async def video(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):

        if videoid:
            link = self.base + link

        link = self._clean_link(link)

        try:

            await self.prefetch(
                link,
                video=True,
            )

            stream_url = (
                await self._api_download_url(
                    link,
                    "video",
                )
            )

            valid = await self._check_stream_url(
                stream_url,
                "video",
            )

            if valid:
                return (
                    1,
                    stream_url,
                )

            LOGGER(__name__).warning(
                "API video source invalid. "
                "Trying yt-dlp fallback."
            )

            fallback = (
                await self._ytdlp_download(
                    link,
                    video=True,
                )
            )

            if fallback:
                return (
                    1,
                    fallback,
                )

            return (
                0,
                "Video source unavailable",
            )

        except Exception as e:

            LOGGER(__name__).error(
                f"Video source error: {e}"
            )

            try:

                fallback = (
                    await self._ytdlp_download(
                        link,
                        video=True,
                    )
                )

                if fallback:
                    return (
                        1,
                        fallback,
                    )

            except Exception:
                pass

            return (
                0,
                "Video source unavailable",
            )

    # ========================================================
    # PLAYLIST
    # ========================================================

    async def playlist(
        self,
        link,
        limit,
        user_id,
        videoid: Union[bool, str] = None,
    ):

        if videoid:
            link = self.listbase + link

        link = self._clean_link(link)

        client = await self.get_client()

        params = {
            "link": link,
            "limit": limit,
        }

        if API_KEY:
            params["api_key"] = API_KEY

        try:

            response = await client.get(
                f"{API_URL}/playlist",
                params=params,
            )

            if response.status_code == 200:

                data = response.json()

                return data.get(
                    "videos"
                )

            LOGGER(__name__).error(
                "API Playlist Error "
                f"({response.status_code}): "
                f"{response.text[:500]}"
            )

        except Exception as e:

            LOGGER(__name__).error(
                f"Playlist API error: {e}"
            )

        return None

    # ========================================================
    # RELATED VIDEOS / AUTOPLAY
    # ========================================================

    async def get_related_videos(
        self,
        vidid: str,
    ):

        autoplay_limit = min(
            config.DURATION_LIMIT,
            600,
        )

        # ----------------------------------------------------
        # Priority 1: YouTube Radio Mix
        # ----------------------------------------------------

        url = (
            f"https://www.youtube.com/watch?v="
            f"{vidid}&list=RD{vidid}"
        )

        ydl_opts = {
            "quiet": True,
            "extract_flat": "in_playlist",
            "playlist_items": "2-20",
            "skip_download": True,
            "ignoreerrors": True,
        }

        try:

            with yt_dlp.YoutubeDL(
                ydl_opts
            ) as ydl:

                loop = (
                    asyncio.get_event_loop()
                )

                info = await loop.run_in_executor(
                    None,
                    lambda: ydl.extract_info(
                        url,
                        download=False,
                    ),
                )

                if (
                    info
                    and "entries" in info
                ):

                    ids = []

                    for entry in (
                        info["entries"]
                    ):

                        if not entry:
                            continue

                        entry_id = entry.get(
                            "id"
                        )

                        if (
                            not entry_id
                            or entry_id == vidid
                        ):
                            continue

                        duration = entry.get(
                            "duration"
                        )

                        if (
                            duration
                            and duration
                            > autoplay_limit
                        ):
                            continue

                        ids.append(
                            entry_id
                        )

                    if ids:
                        return ids

        except Exception as e:

            LOGGER(__name__).warning(
                f"Radio Mix failed: {e}"
            )

        # ----------------------------------------------------
        # Priority 2: Search by title
        # ----------------------------------------------------

        title = await self.title(
            vidid,
            True,
        )

        if title:

            try:

                results = VideosSearch(
                    f"{title} related songs",
                    limit=10,
                )

                related = []

                result_data = (
                    await results.next()
                )

                for result in result_data.get(
                    "result",
                    [],
                ):

                    duration_str = result.get(
                        "duration"
                    )

                    if duration_str:

                        try:

                            seconds = (
                                time_to_seconds(
                                    duration_str
                                )
                            )

                            if (
                                seconds
                                > autoplay_limit
                            ):
                                continue

                        except Exception:
                            pass

                    if (
                        result.get("id")
                        != vidid
                    ):
                        related.append(
                            result["id"]
                        )

                if related:
                    return related

            except Exception as e:

                LOGGER(__name__).warning(
                    f"Related search failed: {e}"
                )

        # ----------------------------------------------------
        # Priority 3: Broad fallback
        # ----------------------------------------------------

        categories = [
            "Latest Hindi Songs",
            "Top Bollywood Hits",
            "Indian Pop Songs",
            "New English Songs",
            "Trending Music India",
        ]

        try:

            query = random.choice(
                categories
            )

            results = VideosSearch(
                query,
                limit=20,
            )

            related = []

            result_data = (
                await results.next()
            )

            for result in result_data.get(
                "result",
                [],
            ):

                duration_str = result.get(
                    "duration"
                )

                if duration_str:

                    try:

                        seconds = (
                            time_to_seconds(
                                duration_str
                            )
                        )

                        if (
                            seconds
                            > autoplay_limit
                        ):
                            continue

                    except Exception:
                        pass

                if (
                    result.get("id")
                    != vidid
                ):
                    related.append(
                        result["id"]
                    )

            if related:
                return related

        except Exception as e:

            LOGGER(__name__).warning(
                f"Broad autoplay search failed: {e}"
            )

        return []

    # ========================================================
    # TRACK
    # ========================================================

    async def track(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):

        if videoid:
            link = self.base + link

        data = await self._fetch_details(
            link
        )

        if data:

            track_details = {
                "title": data.get(
                    "title"
                ),
                "link": data.get(
                    "link"
                ),
                "vidid": data.get(
                    "vidid"
                ),
                "duration_min": data.get(
                    "duration_min"
                ),
                "thumb": data.get(
                    "thumbnail"
                ),
            }

            return (
                track_details,
                data.get("vidid"),
            )

        return (
            None,
            None,
        )

    # ========================================================
    # SEARCH / SLIDER
    # ========================================================

    async def slider(
        self,
        link: str,
        query_type: int,
        videoid: Union[bool, str] = None,
    ):

        if videoid:
            link = self.base + link

        link = self._clean_link(link)

        client = await self.get_client()

        params = {
            "query": link,
            "limit": 10,
        }

        if API_KEY:
            params["api_key"] = API_KEY

        try:

            response = await client.get(
                f"{API_URL}/search",
                params=params,
            )

            if response.status_code == 200:

                result_data = response.json()

                result = result_data.get(
                    "result"
                )

                if (
                    result
                    and len(result)
                    > query_type
                ):

                    res = result[
                        query_type
                    ]

                    thumbnails = res.get(
                        "thumbnails",
                        [],
                    )

                    thumb = (
                        thumbnails[0]["url"]
                        .split("?")[0]
                        if thumbnails
                        else None
                    )

                    return (
                        res.get("title"),
                        res.get("duration"),
                        thumb,
                        res.get("id"),
                    )

            else:

                LOGGER(__name__).error(
                    "API Search Error "
                    f"({response.status_code}): "
                    f"{response.text[:500]}"
                )

        except Exception as e:

            LOGGER(__name__).error(
                f"Search API error: {e}"
            )

        return (
            None,
            None,
            None,
            None,
        )

    # ========================================================
    # YT-DLP FALLBACK
    # ========================================================

    async def _ytdlp_download(
        self,
        link: str,
        video: bool = False,
    ):
        """
        Fallback downloader.

        This is used only when the API source is
        unavailable/invalid.
        """

        link = self._clean_link(link)

        loop = asyncio.get_event_loop()

        safe_id = (
            self._extract_video_id(link)
            or str(
                abs(
                    hash(link)
                )
            )
        )

        output_template = os.path.join(
            self.cache_dir,
            f"{safe_id}.%(ext)s",
        )

        if video:

            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "format": (
                    "best[ext=mp4]/"
                    "bestvideo+bestaudio/"
                    "best"
                ),
                "outtmpl": output_template,
                "merge_output_format": "mp4",
                "retries": 3,
                "fragment_retries": 3,
                "socket_timeout": 30,
                "overwrites": False,
            }

        else:

            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "format": (
                    "bestaudio/best"
                ),
                "outtmpl": output_template,
                "retries": 3,
                "fragment_retries": 3,
                "socket_timeout": 30,
                "postprocessors": [
                    {
                        "key": (
                            "FFmpegExtractAudio"
                        ),
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }

        def _download():

            with yt_dlp.YoutubeDL(
                ydl_opts
            ) as ydl:

                info = ydl.extract_info(
                    link,
                    download=True,
                )

                if not info:
                    return None

                prepared = (
                    ydl.prepare_filename(info)
                )

                if video:
                    candidates = [
                        prepared,
                        os.path.splitext(
                            prepared
                        )[0]
                        + ".mp4",
                    ]

                else:
                    candidates = [
                        os.path.splitext(
                            prepared
                        )[0]
                        + ".mp3",
                        prepared,
                    ]

                for path in candidates:

                    if (
                        path
                        and os.path.isfile(path)
                        and os.path.getsize(
                            path
                        ) > 1024
                    ):
                        return path

                return None

        try:

            result = await loop.run_in_executor(
                None,
                _download,
            )

            if result:
                LOGGER(__name__).info(
                    "yt-dlp fallback succeeded: "
                    f"{result}"
                )

                return result

        except Exception as e:

            LOGGER(__name__).error(
                f"yt-dlp fallback failed: {e}"
            )

        return None

    # ========================================================
    # DOWNLOAD
    # ========================================================

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> tuple:

        if videoid:
            link = self.base + link

        dl_type = (
            "video"
            if (
                video
                or songvideo
            )
            else "audio"
        )

        link = self._clean_link(
            link
        )

        # ----------------------------------------------------
        # API PREFETCH
        # ----------------------------------------------------

        try:

            await self.prefetch(
                link,
                video=(
                    dl_type == "video"
                ),
            )

        except Exception as e:

            LOGGER(__name__).warning(
                f"Prefetch warning: {e}"
            )

        # ----------------------------------------------------
        # GENERATE API SOURCE
        # ----------------------------------------------------

        try:

            stream_url = (
                await self._api_download_url(
                    link,
                    dl_type,
                )
            )

            # Give the API some time to finish generating
            # the file.
            for attempt in range(5):

                valid = (
                    await self._check_stream_url(
                        stream_url,
                        dl_type,
                    )
                )

                if valid:

                    LOGGER(__name__).info(
                        "API media source ready."
                    )

                    return (
                        stream_url,
                        True,
                    )

                LOGGER(__name__).warning(
                    "API media source not ready "
                    f"(attempt {attempt + 1}/5)"
                )

                await asyncio.sleep(
                    2 + attempt
                )

        except Exception as e:

            LOGGER(__name__).error(
                f"API download failed: {e}"
            )

        # ----------------------------------------------------
        # FALLBACK
        # ----------------------------------------------------

        LOGGER(__name__).warning(
            "API source unavailable. "
            "Trying yt-dlp fallback."
        )

        fallback = await self._ytdlp_download(
            link,
            video=(
                dl_type == "video"
            ),
        )

        if fallback:

            return (
                fallback,
                True,
            )

        # ----------------------------------------------------
        # COMPLETE FAILURE
        # ----------------------------------------------------

        raise RuntimeError(
            "Unable to obtain a valid "
            f"YouTube {dl_type} source."
        )

    # ========================================================
    # PREFETCH
    # ========================================================

    async def prefetch(
        self,
        link: str,
        video: bool = False,
    ):

        dl_type = (
            "video"
            if video
            else "audio"
        )

        link = self._clean_link(
            link
        )

        client = await self.get_client()

        params = {
            "query": link,
            "dl_type": dl_type,
            "prefetch": "true",
        }

        if API_KEY:
            params["api_key"] = API_KEY

        try:

            response = await client.get(
                f"{API_URL}/download",
                params=params,
            )

            if response.status_code in (
                200,
                202,
            ):
                return True

            LOGGER(__name__).warning(
                "Prefetch returned "
                f"HTTP {response.status_code}"
            )

        except Exception as e:

            LOGGER(__name__).error(
                f"Prefetch failed for {link}: {e}"
            )

        return False

    # ========================================================
    # FORMATS
    # ========================================================

    async def formats(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):

        if videoid:
            link = self.base + link

        link = self._clean_link(
            link
        )

        client = await self.get_client()

        params = {
            "link": link,
        }

        if API_KEY:
            params["api_key"] = API_KEY

        try:

            response = await client.get(
                f"{API_URL}/formats",
                params=params,
            )

            if response.status_code == 200:

                data = response.json()

                formats = data.get(
                    "formats",
                    [],
                )

                for fmt in formats:
                    fmt["yturl"] = link

                return (
                    formats,
                    link,
                )

            LOGGER(__name__).error(
                "API Formats Error "
                f"({response.status_code}): "
                f"{response.text[:500]}"
            )

        except Exception as e:

            LOGGER(__name__).error(
                f"Formats API error: {e}"
            )

        return (
            [],
            link,
        )

    # ========================================================
    # CLOSE CLIENT
    # ========================================================

    async def close(self):

        if (
            self._client
            and not self._client.is_closed
        ):
            await self._client.aclose()

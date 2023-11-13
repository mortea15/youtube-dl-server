import sys
import subprocess
from pathlib import Path

import taglib

from starlette.status import HTTP_303_SEE_OTHER
from starlette.applications import Starlette
from starlette.config import Config
from starlette.staticfiles import StaticFiles
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.templating import Jinja2Templates
from starlette.background import BackgroundTask

from yt_dlp import YoutubeDL, version
from yt_dlp.postprocessor.ffmpeg import ACODECS

templates = Jinja2Templates(directory="templates")
config = Config(".env")

_default_output_directory = config("DEFAULT_OUTPUT_DIRECTORY", cast=str, default="/music")
_default_output_filename = config("DEFAULT_OUTPUT_FILENAME", cast=str, default="%(title).200s")

app_defaults = {
    "YDL_FORMAT": config("YDL_FORMAT", cast=str, default="bestvideo+bestaudio/best"),
    "YDL_EXTRACT_AUDIO_FORMAT": config("YDL_EXTRACT_AUDIO_FORMAT", default=None),
    "YDL_EXTRACT_AUDIO_QUALITY": config("YDL_EXTRACT_AUDIO_QUALITY", cast=str, default="192"),
    "YDL_OUTPUT_TEMPLATE": config("YDL_OUTPUT_TEMPLATE", cast=str, default=f"{_default_output_directory}/{_default_output_filename}.%(ext)s"),
    "YDL_ARCHIVE_FILE": config("YDL_ARCHIVE_FILE", default=None),
    "YDL_UPDATE_TIME": config("YDL_UPDATE_TIME", cast=bool, default=True),
}


def __parse_file_meta(form):
    filename = form.get("output_filename")
    if not filename or filename == "":
        filename = _default_output_filename
    output_dir = form.get("output_subdir", "")
    artists, title, album = form.get("artists"), form.get("title"), form.get("album")
    
    output_dir = Path(_default_output_directory).joinpath(output_dir)
    if not output_dir.exists():
        output_dir.mkdir()
    
    try:
        _artists = artists.split(";")
    except:
        _artists = [artists]

    meta = {
        "artists": _artists,
        "title": title,
        "album": album,
    }

    return f"{output_dir}/{filename}.%(ext)s", meta


def __tag(
        filepath: Path,
        _id: str | None = None,
        artists: list[str] | None = None,
        title: str | None = None,
        album: str | None = None
    ):
    try:
        print(f"INFO: Tagging '{filepath}'")
        song = taglib.File(filepath)
        if _id:
            song.tags["VIDEO_ID"] = _id
        if artists:
            song.tags["ARTIST"] = artists
        if title:
            song.tags["TITLE"] = [title]
        if album:
            song.tags["ALBUM"] = [album]
        song.save()
    except Exception as error:
        print(f"ERROR: Exception while tagging '{filepath}'")
        print(error)


async def dl_queue_list(request):
    return templates.TemplateResponse("index.html", {"request": request, "ytdlp_version": version.__version__})


async def redirect(request):
    return RedirectResponse(url="/youtube-dl")


async def q_put(request):
    form = await request.form()
    url = form.get("url").strip()
    ui = form.get("ui")
    output_filepath, audio_meta = __parse_file_meta(form)
    options = {
        "format": form.get("format"),
        "filepath": output_filepath,
        "meta": audio_meta,
    }

    if not url:
        return JSONResponse(
            {"success": False, "error": "/q called without a 'url' in form data"}
        )

    task = BackgroundTask(download, url, options)

    print("Added url " + url + " to the download queue")

    if not ui:
        return JSONResponse(
            {"success": True, "url": url, "options": options}, background=task
        )
    return RedirectResponse(
        url="/youtube-dl?added=" + url, status_code=HTTP_303_SEE_OTHER, background=task
    )


async def update_route(scope, receive, send):
    task = BackgroundTask(update)

    return JSONResponse({"output": "Initiated package update"}, background=task)


def update():
    try:
        output = subprocess.check_output(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"]
        )

        print(output.decode("utf-8"))
    except subprocess.CalledProcessError as e:
        print(e.output)


def get_ydl_options(request_options):
    request_vars = {
        "YDL_EXTRACT_AUDIO_FORMAT": None,
    }

    requested_format = request_options.get("format", "bestaudio")

    if requested_format in ["aac", "flac", "mp3", "m4a", "opus", "vorbis", "wav"]:
        request_vars["YDL_EXTRACT_AUDIO_FORMAT"] = requested_format
    elif requested_format == "bestaudio":
        request_vars["YDL_EXTRACT_AUDIO_FORMAT"] = "best"

    ydl_vars = app_defaults | request_vars

    postprocessors = []

    if ydl_vars["YDL_EXTRACT_AUDIO_FORMAT"]:
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": ydl_vars["YDL_EXTRACT_AUDIO_FORMAT"],
                "preferredquality": ydl_vars["YDL_EXTRACT_AUDIO_QUALITY"],
            }
        )

    return {
        "format": ydl_vars["YDL_FORMAT"],
        "postprocessors": postprocessors,
        "outtmpl": request_options["filepath"],
        "download_archive": ydl_vars["YDL_ARCHIVE_FILE"],
        "updatetime": ydl_vars["YDL_UPDATE_TIME"] == "True",
    }


def download(url, request_options):
    meta = request_options.pop("meta")
    with YoutubeDL(get_ydl_options(request_options)) as ydl:
        _info = ydl.extract_info(url, download=True)
        if isinstance(_info, dict):
            for req_dl in _info.get("requested_downloads", []):
                output_filepath = Path(req_dl["filepath"])
                if output_filepath.is_file() and output_filepath.suffix.strip(".") in tuple(ACODECS.keys()):
                    __tag(
                        output_filepath,
                        _id=_info.get("id"),
                        artists=meta.get("artists"),
                        title=meta.get("title"),
                        album=meta.get("album"),
                    )


routes = [
    Route("/", endpoint=redirect),
    Route("/youtube-dl", endpoint=dl_queue_list),
    Route("/youtube-dl/q", endpoint=q_put, methods=["POST"]),
    Route("/youtube-dl/update", endpoint=update_route, methods=["PUT"]),
]

app = Starlette(debug=True, routes=routes)

print("Updating youtube-dl to the newest version")
update()

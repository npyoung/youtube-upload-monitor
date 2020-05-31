#!/usr/bin/env python
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload
from tqdm import tqdm
from retrying import retry

import argparse as ap
from fnmatch import fnmatch
import httplib2
import os
from pathlib import Path
import time


SCOPES = ['https://www.googleapis.com/auth/youtube.upload'] # OAuth 2.0 access scope
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
CHUNKSIZE = 32 * 1024**2 # 32MB
FS_POLLING_INTERVAL = 10
patterns = ['*.mp4', '*.mkv']


def is_upload_retryable(e):
    retryable = False
    if isinstance(e, HttpError):
        if e.resp.status in [500, 502, 503, 504]:
            retryable = True
    else:
        for etype in (httplib2.HttpLib2Error, IOError):
            if isinstance(e, etype):
                retryable = True
                break
    return retryable


def authenticate(client_secrets_file):
    # Get credentials and create an API client
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
    credentials = flow.run_console()
    youtube = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
    return youtube


@retry(retry_on_exception=is_upload_retryable, wait_exponential_multiplier=1e3, wait_exponential_max=1e6)
def make_request(request):
    return request.next_chunk()


@retry(retry_on_exception=lambda e: isinstance(e, OSError), wait_exponential_multiplier=10e3, wait_exponential_max=30*60*1e3)
def do_upload(youtube, fname):
    # Figure out file size for progress later
    fsize = Path(fname).stat().st_size

    # Use video name to come up with default title
    title = Path(fname).stem

    request = youtube.videos().insert(
        part="snippet,status",
        body={
          "snippet": {
            "categoryId": "22",
            "description": "",
            "title": title
          },
          "status": {
            "privacyStatus": "private"
          }
        },

        media_body=MediaFileUpload(fname, chunksize=CHUNKSIZE, resumable=True)
    )

    response = None
    with tqdm(total=fsize) as progress:
        progress.write("Uploading...")
        while response is None:
            status, response = make_request(request)
            if response is not None:
                if 'id' in response:
                    progress.write("Video id {} was successfully uploaded.".format(response['id']))
                else:
                    exit("The upload failed with an unexpected response: {}".format(response))
            else:
                progress.update(CHUNKSIZE)


def main(dir, client_secrets_file):
    youtube = authenticate(client_secrets_file)
    contents = set(os.listdir(dir))

    httplib2.RETRIES = 1 # we are handling retry logic ourselves.

    # Run until ctrl-c
    try:
        while True:
            print("Waiting for new files")
            time.sleep(FS_POLLING_INTERVAL)
            new_contents = set(os.listdir(dir))
            added = new_contents - contents
            contents = new_contents
            for fname in added:
                for pattern in patterns:
                    if fnmatch(fname, pattern):
                        do_upload(youtube, os.path.join(dir, fname))
    except KeyboardInterrupt:
        print("Quitting gracefully")


if __name__ == '__main__':
    parser = ap.ArgumentParser()
    parser.add_argument('dir', type=str, default='.', help="Folder to watch")
    parser.add_argument('-s', '--client-secrets-file', dest='client_secrets_file', type=str,
                        default=Path.home() / "google_api_client_secret.json",
                        help="Path to the Google API client secrets file for this service")
    args = parser.parse_args()
    main(args.dir, str(args.client_secrets_file))

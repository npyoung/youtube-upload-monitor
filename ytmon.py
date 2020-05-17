#!python3

# Sample Python code for youtube.videos.insert
# NOTES:
# 1. This sample code uploads a file and can't be executed via this interface.
#    To test this code, you must run it locally using your own API credentials.
#    See: https://developers.google.com/explorer-help/guides/code_samples#python
# 2. This example makes a simple upload request. We recommend that you consider
#    using resumable uploads instead, particularly if you are transferring large
#    files or there's a high likelihood of a network interruption or other
#    transmission failure. To learn more about resumable uploads, see:
#    https://developers.google.com/api-client-library/python/guide/media_upload

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload
from tqdm import tqdm
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

import argparse as ap
import httplib2
import os
from pathlib import Path
import time

# Explicitly tell the underlying HTTP transport library not to retry, since
# we are handling retry logic ourselves.
httplib2.RETRIES = 1

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError)

# Always retry when an apiclient.errors.HttpError with one of these status
# codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

# This OAuth 2.0 access scope allows an application to upload files to the
# authenticated user's YouTube channel, but doesn't allow other types of access.
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

# The CLIENT_SECRETS_FILE variable specifies the name of a file that contains
# the OAuth 2.0 information for this application, including its client_id and
# client_secret. You can acquire an OAuth 2.0 client ID and client secret from
# the {{ Google Cloud Console }} at
# {{ https://cloud.google.com/console }}.
# Please ensure that you have enabled the YouTube Data API for your project.
# For more information about using OAuth2 to access the YouTube Data API, see:
#   https://developers.google.com/youtube/v3/guides/authentication
# For more information about the client_secrets.json file format, see:
#   https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
client_secrets_file = Path.home() / "google_api_client_secret.json"

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
VALID_PRIVACY_STATUSES = ('public', 'private', 'unlisted')
CHUNKSIZE = 64 * 1024**2

patterns = ['*.mp4', '*.mkv']


def on_created(event):
    fname = event.src_path
    print("File added: {}".format(fname))
    try:
        do_upload(fname)
    except HttpError as e:
        print('An HTTP error {} occurred:\n{}'.format(e.resp.status, e.content))


def do_upload(fname):
    # Disable OAuthlib's HTTPS verification when running locally.
    # *DO NOT* leave this option enabled in production.
    #os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    # Figure out file size for progress later
    fsize = Path(fname).stat().st_size

    # Get credentials and create an API client
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
    credentials = flow.run_console()
    youtube = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

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

    resumable_upload(request, fsize)


# This method implements an exponential backoff strategy to resume a
# failed upload.
def resumable_upload(request, fsize):
    response = None
    error = None
    retry = 0
    with tqdm(total=fsize) as progress:
        while response is None:
            try:
                print("Uploading...")
                status, response = request.next_chunk()
                if response is not None:
                    if 'id' in response:
                        print("Video id {} was successfully uploaded.".format(response['id']))
                    else:
                        exit("The upload failed with an unexpected response: {}".format(response))
                else:
                    progress.update(CHUNKSIZE)

            except HttpError as e:
                if e.resp.status in RETRIABLE_STATUS_CODES:
                    error = 'A retriable HTTP error %d occurred:\n%s' % (e.resp.status, e.content)
                else:
                    raise
            except RETRIABLE_EXCEPTIONS as e:
                error = "A retriable error occurred: {}".format(e)

            if error is not None:
                print(error)
                retry += 1
                if retry > MAX_RETRIES:
                    exit('No longer attempting to retry.')

                max_sleep = 2 ** retry
                sleep_seconds = max_sleep
                print("Sleeping {:d} seconds and then retrying...".format(sleep_seconds))
                time.sleep(sleep_seconds)


def main(dir):
    # Set up watchdog
    handler = PatternMatchingEventHandler(patterns, ignore_directories=True)
    handler.on_created = on_created
    observer = Observer()
    observer.schedule(handler, dir, recursive=True)
    observer.start()
    print("Watching...")

    # Run until ctrl-c
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        observer.join()
        print("Quitting gracefully")


if __name__ == '__main__':
    parser = ap.ArgumentParser()
    parser.add_argument('dir', type=str, default='.', help="Folder to watch")
    args = parser.parse_args()
    main(args.dir)

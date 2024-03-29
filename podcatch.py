#!/usr/bin/python3

# This file is part of podcatch, a simple command line podcast catcher.
# podcatch is subject to the GNU General Public License, version 2 or above.
# See the file COPYING for full license agreement.
#
# (c) 2015 Dominik Riebeling

from __future__ import print_function
from xml.etree import ElementTree as ET
from urllib.request import Request, urlopen
import urllib.parse as urlparse
from urllib.error import HTTPError, URLError
import email.utils
import os
import sys
import time
import argparse

USERAGENT = 'podcatch/1.0'

def catch(feed, outfolder, verbose=False, quiet=False):
    '''Podcatch the episodes of feed.
    '''
    try:
        print("=" * 20)
        if verbose:
            print("Retrieving RSS %s" % feed['url'])
        req = Request(
            feed['url'],
            headers={'User-Agent': USERAGENT})
        remote = urlopen(req)
        content = remote.read()
        remote.close()
    except (IOError, HTTPError) as error:
        print("Error retrieving RSS feed %s: %s" % (feed['name'], error))
        return

    try:
        rss = ET.fromstring(content)
    except ET.ParseError:
        print("XML parse error! Invalid feed %s?" % feed['name'])
        return

    version = None
    if 'version' in rss.attrib:
        version = rss.attrib['version']
    if version is None or not version == "2.0":  # only 2.0 for now
        print("Unsupported RSS version: '%s'" % version)
        return

    channel = None
    if len(list(rss)) == 1 and rss[0].tag == 'channel':
        channel = rss[0]
    else:
        # invalid RSS (single channel on top level required)
        print("Invalid number of channel elements.")
        return

    print("Channel: %s" % channel.find('title').text)

    # check for update?
    builddate = channel.find('lastBuildDate')
    if builddate is not None:
        print("Build Date: %s" % time.asctime(date_to_local(builddate.text)))
    feedfolder = os.path.join(outfolder, feed['name'])

    if not os.path.exists(feedfolder):
        os.makedirs(feedfolder)

    # channel image
    image = channel.find('image/url')
    if image is not None:
        _, fileext = os.path.splitext(urlparse.urlparse(image.text).path)
        imgfile = os.path.join(feedfolder, "folder%s" % fileext)
        if not os.path.exists(imgfile):
            try:
                download(image.text, imgfile)
            except HTTPError as error:
                print("HTTP error %i: %s, skipping" % (error.code, imgfile))

    items = channel.findall('item')
    num = len(items)
    if verbose:
        print("Found %i items in channel" % num)
        print("=" * 20)
    # check if the enclosures use different filenames. If not clashes will
    # happen during download. In this case set a flag so we don't use the
    # server filename, instead we use the title.
    encurls = [x for x in
               [os.path.basename(urlparse.urlparse(x.attrib['url']).path)
                for x in [x.find('enclosure') for x in items]
                if x is not None] if len(x) > 0]
    rename = len(encurls) != len(set(encurls))

    # get all items
    for index, item in enumerate(items):
        enclosure = item.find('enclosure')
        if enclosure is None:
            print("ERROR: no enclosure in channel item, skipping")
            continue
        if 'url' not in enclosure.attrib:
            print("ERROR: no URL in enclosure, skipping")
            continue

        title = item.find('title').text.strip()
        # on Python2 the element can be str or unicode. Convert to unicode.
        if not isinstance(title, str):
            title = title.encode("utf-8")
        # check for update?
        pubdate = item.find('pubDate')
        if pubdate is not None:
            pub = time.asctime(date_to_local(pubdate.text))
        if not quiet:
            print("%s/%s, %s: Episode '%s'" % (index + 1, num, pub, title))

        itemurl = enclosure.attrib['url']
        if not itemurl:
            print("ERROR: URL is empty, skipping")
            continue
        if not rename:
            basefn = os.path.basename(urlparse.urlparse(itemurl).path)
        else:
            invalidchars = ('<', '>', ':', '"', '/', '\\', '|', '?', '*')
            basefn = "%s%s" % (
                "".join([x if x not in invalidchars else '_' for x in title]),
                os.path.splitext(urlparse.urlparse(itemurl).path)[1])
        outfn = os.path.join(feedfolder, basefn)
        # FIXME: use local file timestamp for modification check
        if not os.path.exists(outfn):
            # some broken feeds omit the length attribute
            if 'length' in enclosure.attrib and 'type' in enclosure.attrib:
                print("Getting '%s' (%s, %s bytes)" % (
                    basefn, enclosure.attrib['type'],
                    enclosure.attrib['length']))
            else:
                print("Getting %s" % basefn)
            try:
                download(itemurl, outfn, quiet)
            except HTTPError as error:
                print("HTTP error %i: %s, skipping" % (error.code, itemurl))
                continue
            except URLError as error:
                print("URL error: %s: %s, skipping" % (error.reason, itemurl))
                continue
        elif verbose:
            print("Already have %s" % basefn)

        if not os.path.exists(outfn + ".txt"):
            outtxt = open(outfn + ".txt", "w")
            outtxt.write(title)
            outtxt.write("\n\n")
            description = item.find('description')
            if description is not None:
                txt = description.text
                if not isinstance(txt, str):
                    outtxt.write(txt.encode("utf-8"))
                else:
                    outtxt.write(txt)
                outtxt.write("\n")
            else:
                print("No description found.")
            outtxt.close()


def download(url, dest, quiet=False):
    '''Download url and store file as dest.

    If the web server returns a Last-Modified header for the file set the
    timestamp of dest to use the retrieved date.
    Uses a temporary filename by adding the extension ".temp" during download,
    to avoid broken downloads resulting in a file present at dest.'''
    tmpfile = dest + ".temp"
    request = Request(url, headers={'User-Agent': USERAGENT})
    resume = 0
    if os.path.exists(tmpfile):
        resume = os.path.getsize(tmpfile)
        request.add_header("Range", "bytes=%s-" % resume)
    try:
        hdl = urlopen(request)
    except HTTPError as error:
        if error.code == 416:  # Requested Range Not Satisfiable
            # If this happens the range does not exist. This usually means that
            # the file has already been downloaded completely, thus the
            # "remaining" range does not exist.
            # If the server doesn't support the Range header it will ignore it
            # and respond with 200 (see RFC2616).

            # FIXME: retrieve server timestamp here as well.
            os.rename(tmpfile, dest)
            return
        raise

    mode = "wb"
    if hdl.getcode() == 206:  # Partial Content
        mode = "ab"
    outhdl = open(tmpfile, mode)
    total = int(hdl.info()['Content-Length']) + resume
    length = resume
    while True:
        data = hdl.read(0x2000)
        outhdl.write(data)
        length += 0x2000
        if sys.stdout.isatty() is True and not quiet:
            print("%i / %i (%.1f%%)\r"
                  % (length, total, 100. * length / total), end="")
        if data is None or not data:
            break

    outhdl.close()
    os.rename(tmpfile, dest)
    # Python2 and Python3 use different casing for headers dictionary.
    # Create lower-case keys dictionary to use.
    headers = {k.lower(): v for k, v in dict(hdl.info()).items()}
    if "last-modified" in headers:
        lastmod = headers["last-modified"]
        lastmodified = email.utils.mktime_tz(email.utils.parsedate_tz(lastmod))
        os.utime(dest, (lastmodified, lastmodified))
    hdl.close()


def date_to_local(date):
    '''Convert date string (RFC2822 format) to local time tuple.

    The resulting tuple can be passed directly to time functions.'''
    parsed = email.utils.parsedate_tz(date)
    if parsed is not None:
        return time.localtime(email.utils.mktime_tz(parsed))
    print("WARNING: Invalid date string '%s', could not parse" % date)
    return time.localtime(0)


def read_serverlist(filename):
    '''Read feed configuration from serverlist file filename.

    The serverlist file uses the same format as podget.sh, hence the same
    name for the input file is used here.'''
    servers = list()

    with open(filename, "r") as fin:
        rss = fin.readlines()
        for line in rss:
            if line.startswith("#"):
                continue
            try:
                url, category, name = line.split(' ', 2)
                servers.append({'url': url, 'category': category,
                                'name': name.strip()})
            except ValueError:
                # invalid line, ignore
                pass
    return servers


def podcatch():
    '''Run podcatch.
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    parser.add_argument('-s', '--serverlist',
                        help='Specify serverlist file')
    parser.add_argument('-o', '--outfolder',
                        help='Specify output folder')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Less output')
    args = parser.parse_args()
    serverlist = "serverlist"
    if args.outfolder is None:
        outfolder = os.getcwd()
    else:
        outfolder = args.outfolder
    if args.serverlist is not None:
        serverlist = args.serverlist
    for server in read_serverlist(serverlist):
        catch(server, outfolder, args.verbose, args.quiet)


if __name__ == "__main__":
    podcatch()

#!/usr/bin/python

# This file is part of podcatch, a simple command line podcast catcher.
# podcatch is subject to the GNU General Public License, version 2 or above.
# See the file COPYING for full license agreement.
#
# (c) 2015 Dominik Riebeling

from xml.etree import ElementTree as ET
import urllib
import urlparse
import email.utils
import os
import time
import argparse


def catch(feed, verbose=False):
    '''Podcatch the episodes of feed.
    '''
    try:
        print("=" * 20)
        if verbose:
            print("Retrieving RSS %s" % feed['url'])
        remote = urllib.urlopen(feed['url'])
        encoding = remote.headers.getparam("charset")
        if encoding is not None:
            content = remote.read().decode(encoding).encode("UTF-8")
        else:
            content = remote.read()
        remote.close()
    except IOError:
        print("Error retrieving RSS feed.")
        return

    try:
        rss = ET.fromstring(content)
    except ET.ParseError:
        print("XML parse error! Invalid feed?")
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

    if not os.path.exists(feed['name']):
        os.makedirs(feed['name'])

    # channel image
    image = channel.find('image/url')
    if image is not None:
        imgfile = os.path.join(feed['name'], "folder.jpg")
        urllib.urlretrieve(image.text, imgfile)

    items = channel.findall('item')
    num = len(items)
    if verbose:
        print("Found %i items in channel" % num)
        print("=" * 20)
    # get all items
    for index, item in enumerate(items):
        enclosure = item.find('enclosure')
        if enclosure is None:
            continue

        title = item.find('title').text.encode('UTF-8')
        # check for update?
        pubdate = item.find('pubDate')
        if pubdate is not None:
            pub = time.asctime(date_to_local(pubdate.text))
        print("%s/%s, %s: Episode '%s'" % (index + 1, num, pub, title))

        itemurl = enclosure.attrib['url']
        basefn = os.path.basename(urlparse.urlparse(itemurl).path)
        outfn = os.path.join(feed['name'], basefn)
        # FIXME: check for partial downloads (and resume if possible)
        # FIXME: use local file timestamp for modification check
        if not os.path.exists(outfn):
            print("Getting %s (%s, %s bytes)" % (
                basefn, enclosure.attrib['type'],
                enclosure.attrib['length']))
            download(itemurl, outfn)
        elif verbose:
            print("Already have %s" % basefn)

        if not os.path.exists(outfn + ".txt"):
            outtxt = open(outfn + ".txt", "w")
            outtxt.write(title)
            outtxt.write("\n\n")
            outtxt.write(item.find('description').text.encode('UTF-8'))
            outtxt.write("\n")
            outtxt.close()


def download(url, dest):
    '''Download url and store file as dest.

    If the web server returns a LastModified header for the file set the
    timestamp of dest to use the retrieved date.
    Uses a temporary filename by adding the extension ".temp" during download,
    to avoid broken downloads resulting in a file present at dest.'''
    hdr = urllib.urlretrieve(url, dest + ".temp")[1]
    os.rename(dest + ".temp", dest)
    if 'last-modified' in hdr:
        lastmodified = email.utils.mktime_tz(
            email.utils.parsedate_tz(hdr['last-modified']))
        os.utime(dest, (lastmodified, lastmodified))


def date_to_local(date):
    '''Convert date string (RFC2822 format) to local time tuple.

    The resulting tuple can be passed directly to time functions.'''
    timestamp = email.utils.mktime_tz(email.utils.parsedate_tz(date))
    return time.localtime(timestamp)


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
    args = parser.parse_args()
    serverlist = "serverlist"
    if args.serverlist is not None:
        serverlist = args.serverlist
    for server in read_serverlist(serverlist):
        catch(server, args.verbose)


if __name__ == "__main__":
    podcatch()

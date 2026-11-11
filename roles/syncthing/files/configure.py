#!/usr/bin/env python3
"""Configure a named Obsidian share via the local authenticated REST API."""
import json
from pathlib import Path
import sys
import urllib.request
import xml.etree.ElementTree as ET


def main():
    args = sys.argv[1:]
    if len(args) == 3:
        # Backwards-compatible command line for an existing Lion-only setup.
        home, folder, peer_json = args
        folder_id, label = 'lion-obsidian', 'Lion — Obsidian'
    elif len(args) == 5:
        home, folder, peer_json, folder_id, label = args
    else:
        raise SystemExit('usage: configure-obsidian-sync HOME PATH PEERS [FOLDER_ID LABEL]')
    key = ET.parse(Path(home) / 'config.xml').findtext('gui/apikey')
    def api(path, body=None, method=None):
        request = urllib.request.Request(
            'http://127.0.0.1:8384/rest/' + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={'X-API-Key': key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read()
            return json.loads(text) if text else None
    config = api('config')
    before = json.dumps(config, sort_keys=True)
    identity = api('system/status')['myID']
    peers = json.loads(peer_json)
    for peer in peers:
        if not any(d['deviceID'] == peer['deviceID'] for d in config['devices']):
            device = api('config/defaults/device')
            device.update(peer)
            config['devices'].append(device)
    share = next((f for f in config['folders'] if f['id'] == folder_id), None)
    if share is None:
        share = api('config/defaults/folder')
        share.update(id=folder_id, label=label, path=folder,
                     type='sendreceive', fsWatcherEnabled=True, rescanIntervalS=3600)
        share['versioning'] = {'type': 'staggered', 'params': {'maxAge': '2592000', 'cleanInterval': '3600'}}
        config['folders'].append(share)
    # This is the dedicated managed share. Its folder ID remains stable during a
    # local vault rename, so updating only the path preserves its peer/database.
    if share['path'] != folder:
        share['path'] = folder
    share['label'] = label
    # Obsidian needs ordinary Markdown files on every peer. Receive-encrypted
    # shares cannot be opened as a vault and are not supported for this folder.
    share['type'] = 'sendreceive'
    for device_id in [identity] + [p['deviceID'] for p in peers]:
        if not any(d['deviceID'] == device_id for d in share['devices']):
            share['devices'].append({'deviceID': device_id})
    for device in share['devices']:
        device['encryptionPassword'] = ''
    if json.dumps(config, sort_keys=True) != before:
        api('config', config, method='PUT')
        print('CHANGED')
    # Merge ignore rules; don't overwrite user rules. Settings/bookmarks/CSS
    # sync, while each device retains its own window layout and caches.
    rules = ['/.obsidian/workspace*.json', '/.obsidian/cache', '/.trash', '/.git', '*.refresh-part']
    existing = api('db/ignores?folder=' + urllib.parse.quote(folder_id, safe='')).get('ignore') or []
    wanted = existing + [r for r in rules if r not in existing]
    if wanted != existing:
        api('db/ignores?folder=' + urllib.parse.quote(folder_id, safe=''), {'ignore': wanted})
        print('CHANGED')
    print(identity)


if __name__ == '__main__':
    main()

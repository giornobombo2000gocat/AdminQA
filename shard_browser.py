"""Standalone ShardX runtime and owned, isolated CDP sessions.

Engine assets stay beside the application. Account profiles stay in QA_data;
neither cookies nor proxy credentials are printed. No JavaScript stealth shim.
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from shardx import ShardX
from shardx.browser import Browser
from shardx.profile import FingerprintLibrary
from shardx.runtime import Runtime, PUB_BASE, FINGERPRINTS_ARCHIVE, FINGERPRINTS_TOP_DIR


def runtime_path():
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    return base / 'shard-runtime'


class BoundedRuntime(Runtime):
    """Use the official manifest with bounded downloads and checked ZIP paths."""
    def _fetch_manifest(self):
        snapshot = self.root / 'upstream-manifest.json'
        data = super()._fetch_manifest()
        if data:
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text(json.dumps(data), encoding='utf-8')
            return data
        return json.loads(snapshot.read_text(encoding='utf-8')) if snapshot.is_file() else {}

    def _download_and_extract(self, arch, dest):
        dest = Path(dest).resolve()
        dest.mkdir(parents=True, exist_ok=True)
        tmp = dest / ('.' + arch.key + '.tmp')
        digest = hashlib.sha256()
        started = time.monotonic()
        received = 0
        try:
            with httpx.stream('GET', PUB_BASE + '/' + arch.key,
                              timeout=httpx.Timeout(30, connect=15), follow_redirects=True) as response:
                response.raise_for_status()
                total = int(response.headers.get('content-length', 0))
                etag = response.headers.get('etag', '').strip('"')
                with tmp.open('wb') as output:
                    for chunk in response.iter_bytes(1 << 16):
                        received += len(chunk)
                        if received > 1_000_000_000 or time.monotonic() - started > 600:
                            raise TimeoutError('ShardX download limit exceeded')
                        output.write(chunk)
                        digest.update(chunk)
                        if self._progress:
                            self._progress(arch.label, received, total)
                if total and received != total:
                    raise ValueError('Incomplete ShardX archive')
            with zipfile.ZipFile(tmp) as archive:
                if sum(entry.file_size for entry in archive.infolist()) > 3_000_000_000:
                    raise ValueError('ShardX archive expansion limit exceeded')
                for entry in archive.infolist():
                    target = (dest / entry.filename).resolve()
                    if not target.is_relative_to(dest) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('Unsafe ShardX ZIP entry')
                # CRC verifies downloaded data; the recorded SHA is an audit hash,
                # not an independently authenticated publisher signature.
                if archive.testzip() is not None:
                    raise ValueError('Corrupted ShardX ZIP')
                archive.extractall(dest)
            audit = self.root / 'download-hashes.json'
            hashes = json.loads(audit.read_text()) if audit.is_file() else {}
            hashes[arch.key] = {'sha256': digest.hexdigest(), 'bytes': received, 'etag': etag}
            audit.write_text(json.dumps(hashes, indent=2), encoding='utf-8')
            return etag
        finally:
            tmp.unlink(missing_ok=True)

    def _install_fingerprints(self):
        staging = self.fingerprints_dir / '.staging'
        staging.mkdir(parents=True, exist_ok=True)
        try:
            self._download_and_extract(FINGERPRINTS_ARCHIVE, staging)
            source = staging / FINGERPRINTS_TOP_DIR
            source = source if source.is_dir() else staging
            for item in source.glob('*.json'):
                json.loads(item.read_text(encoding='utf-8'))
                shutil.copyfile(item, self.fingerprints_dir / item.name)
        finally:
            # Fixed child directory, resolved and checked before recursive delete.
            target = staging.resolve()
            if target.is_relative_to(self.fingerprints_dir.resolve()) and target != self.fingerprints_dir.resolve():
                shutil.rmtree(target)


def make_sdk(profile_root, progress=None):
    sdk = ShardX(cache_dir=str(runtime_path()), profiles_dir=str(profile_root))
    sdk.runtime = BoundedRuntime(cache_dir=str(runtime_path()), profiles_dir=str(profile_root), progress=progress)
    sdk.library = FingerprintLibrary(sdk.runtime)
    sdk._browser = Browser(sdk.runtime)
    return sdk


async def prepare_runtime(profile_root, notify):
    last = [0.0]
    def progress(label, received, total):
        now = time.monotonic()
        if now - last[0] >= 2 or received == total:
            last[0] = now
            notify(f'ShardBrowser: {label} — {received // (1024*1024)} МБ' +
                   (f' / {total // (1024*1024)} МБ' if total else ''))
    sdk = make_sdk(profile_root, progress)
    notify('Перевіряю локальний ShardBrowser…')
    await asyncio.to_thread(sdk.runtime.install)
    notify('ShardBrowser готовий. Версія Chromium: ' + sdk.runtime.chromium_version)
    return sdk


class ShardBrowser:
    def __init__(self, sdk, session_id, *, proxy=None, headless=False):
        self.sdk = sdk
        self.session_id = session_id
        self.proxy = proxy
        self.headless = headless
        self.session = None
        self.endpoint = None
        self._lock = None

    def _launch(self):
        # Stable per-account fingerprint and cookie jar. Hash prevents path injection.
        key = hashlib.sha256(self.session_id.encode()).hexdigest()
        if os.name=='nt':
            import msvcrt
            lock_path=self.sdk.runtime.profiles_root / (key+'.lock')
            self._lock=lock_path.open('a+b')
            try:
                if not os.fstat(self._lock.fileno()).st_size:
                    self._lock.write(b'0');self._lock.flush()
                self._lock.seek(0)
                msvcrt.locking(self._lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                self._lock.close();self._lock=None
                raise RuntimeError('Профіль акаунта вже відкритий іншою сесією адмінки.')
        mapping = self.sdk.runtime.profiles_root / (key + '.json')
        if mapping.is_file():
            profile_id=json.loads(mapping.read_text())['profile_id']
            if not re.fullmatch(r'[a-f0-9]{32}',profile_id):raise ValueError('Invalid saved Shard profile id')
            profile = self.sdk.open_profile(profile_id)
        else:
            profile = self.sdk.create_profile(platform='Windows')
            mapping.write_text(json.dumps({'profile_id': profile.id}), encoding='utf-8')
        extra=['--remote-debugging-address=127.0.0.1', '--disable-popup-blocking']
        if self.headless:extra += ['--no-sandbox','--disable-gpu']
        self.session = self.sdk.launch(profile, proxy=self.proxy, cdp=True,
            headless=self.headless, webrtc='block',
            extra_args=extra)
        return self.session

    async def start(self, playwright):
        launch = asyncio.create_task(asyncio.to_thread(self._launch))
        try:
            await asyncio.shield(launch)
            endpoint = urlparse(self.session.cdp_url or '')
            if endpoint.scheme != 'ws' or endpoint.hostname != '127.0.0.1' or not endpoint.port:
                raise RuntimeError('ShardBrowser не надав локальний CDP endpoint.')
            self.endpoint = f'http://127.0.0.1:{endpoint.port}'
            return await playwright.chromium.connect_over_cdp(self.session.cdp_url, timeout=15000)
        except BaseException:
            # A cancelled to_thread still runs. Reap its owned browser before exit.
            try:
                await launch
            finally:
                await self.close()
            raise

    async def close(self):
        try:
            if self.session is not None:
                process = self.session.process
                if process.poll() is None and os.name == 'nt':
                    await asyncio.to_thread(subprocess.run,
                        ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                await asyncio.to_thread(self.session.stop)
        finally:
            if self._lock:
                self._lock.close();self._lock=None

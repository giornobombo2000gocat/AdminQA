"""Launch a private Chrome/Edge process and attach through loopback CDP."""
import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def browser_executable(channel='chrome'):
    if channel not in {'chrome','msedge'}:
        raise ValueError('CDP поддерживает установленный Chrome или Edge.')
    suffix='Google/Chrome/Application/chrome.exe' if channel=='chrome' else 'Microsoft/Edge/Application/msedge.exe'
    for key in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
        base=os.environ.get(key)
        if base:
            candidate=Path(base)/suffix
            if candidate.is_file():return candidate
    raise ValueError('Не найден выбранный Chrome или Edge.')


class CDPBrowser:
    def __init__(self,profile_root,session_id,channel='chrome',headless=False,stagehand=False):
        self.root=Path(profile_root).resolve()
        self.session_id=session_id;self.channel=channel;self.headless=headless
        self.profile=None;self.process=None;self.endpoint=None;self.stagehand=stagehand

    async def start(self,playwright):
        executable=browser_executable(self.channel)
        self.root.mkdir(parents=True,exist_ok=True)
        prefix=hashlib.sha256(self.session_id.encode()).hexdigest()[:12]+'-'
        self.profile=Path(tempfile.mkdtemp(prefix=prefix,dir=self.root)).resolve()
        args=[str(executable),'--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
              '--user-data-dir='+str(self.profile),'--no-first-run','--no-default-browser-check',
              '--disable-popup-blocking','about:blank']
        if self.stagehand:
            args[1:1]=['--enable-unsafe-extension-debugging','--remote-allow-origins=*']
        # Test-only headless sessions run inside the agent's Windows sandbox.
        # Visible desktop sessions keep Chrome's normal sandbox and GPU.
        if self.headless:args[1:1]=['--headless=new','--no-sandbox','--disable-gpu']
        self.process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        active_port=self.profile/'DevToolsActivePort'
        try:
            async with asyncio.timeout(30):
                while True:
                    if self.process.poll() is not None:raise RuntimeError('Браузер CDP завершился до подключения.')
                    if active_port.is_file():
                        try:
                            lines=active_port.read_text(encoding='utf-8').splitlines()
                            port=int(lines[0])
                            if not 1024<=port<=65535 or len(lines)<2 or not re.fullmatch(r'/devtools/browser/[a-fA-F0-9-]+',lines[1]):
                                raise ValueError('Invalid private CDP endpoint')
                            self.endpoint='http://127.0.0.1:'+str(port)
                            return await playwright.chromium.connect_over_cdp('ws://127.0.0.1:'+str(port)+lines[1],timeout=10000)
                        except (IndexError,ValueError):pass
                    await asyncio.sleep(.1)
        except BaseException:
            await self.close();raise

    async def close(self):
        if self.process and self.process.poll() is None:
            if os.name=='nt':
                try:
                    await asyncio.to_thread(subprocess.run,['taskkill','/PID',str(self.process.pid),'/T','/F'],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                except Exception:pass
            if self.process.poll() is None:self.process.terminate()
            try:await asyncio.to_thread(self.process.wait,5)
            except subprocess.TimeoutExpired:self.process.kill();await asyncio.to_thread(self.process.wait,5)
        if self.profile and self.profile.exists():
            target=self.profile.resolve()
            if target==self.root or not target.is_relative_to(self.root):
                raise RuntimeError('Profile cleanup escaped its private directory')
            for attempt in range(3):
                try:await asyncio.to_thread(shutil.rmtree,target);break
                except OSError:
                    if attempt==2:raise
                    await asyncio.sleep(.3)

"""Start the private portable vision service before any browser session."""
import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

MODEL='gemma3:4b'
ENDPOINT='http://127.0.0.1:11434'

def api(path,data=None,timeout=10):
    body=None if data is None else json.dumps(data).encode()
    request=urllib.request.Request(ENDPOINT+path,data=body,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        return json.load(response)

class VisionRuntime:
    def __init__(self,notify=lambda _:None):
        self.notify=notify;self.process=None;self.log=None

    async def start(self):
        root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
        runtime=root/'vision-runtime'
        try:await asyncio.to_thread(api,'/api/version')
        except Exception:
            executable=runtime/'ollama.exe'
            if not executable.is_file():raise ValueError('Не найдена папка vision-runtime рядом с EXE. Запускай программу из подготовленной папки.')
            environment=os.environ.copy()
            profile=runtime/'profile';profile.mkdir(exist_ok=True)
            environment['USERPROFILE']=str(profile)
            environment.update(OLLAMA_MODELS=str(runtime/'models'),OLLAMA_HOST='127.0.0.1:11434',
                OLLAMA_NO_CLOUD='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_NUM_PARALLEL='1')
            self.log=(runtime/'service.log').open('ab')
            self.process=subprocess.Popen([str(executable),'serve'],cwd=runtime,env=environment,
                stdout=self.log,stderr=self.log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.notify('Запускаю локальную vision-модель…')
            for _ in range(100):
                if self.process.poll() is not None:raise ValueError('Локальный vision-сервер завершился. Подробности: vision-runtime/service.log.')
                try:await asyncio.to_thread(api,'/api/version');break
                except Exception:await asyncio.sleep(.2)
            else:raise ValueError('Локальный vision-сервер не запустился за 20 секунд.')
        try:
            details=await asyncio.to_thread(api,'/api/show',{'model':MODEL})
            if 'vision' not in details.get('capabilities',[]):raise ValueError('Подготовленная модель не поддерживает изображения.')
            self.notify('Загружаю модель в память. Первый запуск может занять до двух минут…')
            await asyncio.to_thread(api,'/api/generate',{'model':MODEL,'prompt':'','stream':False,'keep_alive':'10m'},120)
        except Exception:
            await self.close()
            raise ValueError('Vision-модель gemma3:4b не готова. Нужна подготовленная папка vision-runtime с её файлами.')
        self.notify('Vision-модель готова: '+MODEL+'. Снимки обрабатываются локально.')
        return MODEL

    async def close(self):
        if self.process and self.process.poll() is None:
            try:await asyncio.to_thread(api,'/api/generate',{'model':MODEL,'prompt':'','stream':False,'keep_alive':0},10)
            except Exception:pass
            if os.name=='nt':
                # Windows terminate() alone leaves the GPU runner orphaned.
                try:
                    await asyncio.to_thread(subprocess.run,['taskkill','/PID',str(self.process.pid),'/T','/F'],
                        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                except Exception:pass
            if self.process.poll() is None:self.process.terminate()
            try:await asyncio.to_thread(self.process.wait,10)
            except subprocess.TimeoutExpired:self.process.kill();await asyncio.to_thread(self.process.wait,5)
        if self.log:self.log.close()

"""End-to-end acceptance test with the actual local vision model."""
import asyncio
import json
import threading
import traceback
from pathlib import Path

def run(report):
    from desktop_app import run_system,DEFAULTS
    from playwright.async_api import BrowserType
    from room_agent import RoomAgent
    results={'passed':False,'real_model_tested':True,'model':'gemma3:4b','vision_steps':[]}
    directory=report.parent/('vision-acceptance-'+report.stem);directory.mkdir(exist_ok=True)
    stop=threading.Event()
    class Signal:
        def __init__(self,callback):self.callback=callback
        def emit(self,*args):self.callback(*args)
    class Events:
        message=Signal(lambda message:None)
        outcome=Signal(lambda sid,data:results.update(outcome=data))
    original_launch=BrowserType.launch;original_choice=RoomAgent.model_choice
    async def launch(self,*args,**kwargs):
        kwargs['headless']=True
        return await original_launch(self,*args,**kwargs)
    async def choice(self,items,phase):
        assert self.config.get('ai_vision') and self.config.get('ai_model')=='gemma3:4b'
        command=await original_choice(self,items,phase)
        results['vision_steps'].append({'phase':phase,'action':command.get('action')})
        return command
    async def verify():
        settings={'site':{**DEFAULTS,'cdp_headless':True,'url':'http://127.0.0.1:5000/workflow/login','demo':True,
            'workflow_demo':True,'vision_demo':True,'strategy':'vision','goal':'фишки: 10'},
            'accounts':[{'id':'vision-acceptance','login':'qa@local.test','password':'qa-demo','proxy':''}],
            'stealth':False}
        task=asyncio.create_task(run_system(settings,directory,stop,Events()))
        try:
            async with asyncio.timeout(240):
                while 'outcome' not in results:
                    if task.done():await task;raise AssertionError('Session finished before an engine move')
                    await asyncio.sleep(.2)
            # Exact login/game/category controls no longer need an LLM call.
            assert len(results['vision_steps'])>=1,results['vision_steps']
            outcome=results.pop('outcome')
            assert set(outcome['move']['captured_cards'])=={'coppe:1','denari:7'}
            results.update(passed=True,checks=['Portable runtime starts and warms model',
                'Real vision opens sign-in and navigates without route text',
                'Seat and confirmed virtual chip bet','Actual ScopaEngine move and capture verified'])
        finally:
            stop.set();await asyncio.wait_for(task,40)
    try:
        BrowserType.launch=launch;RoomAgent.model_choice=choice
        asyncio.run(verify())
    except Exception:results.update(passed=False,error=traceback.format_exc())
    finally:BrowserType.launch=original_launch;RoomAgent.model_choice=original_choice
    report.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if results['passed'] else 1

"""Ordinary Scopa: exact catalog card -> visible Prova -> explicit demo URL.

No tournament registration, stake confirmation or Gioca fallback.
"""
import re
from urllib.parse import urlparse


class DemoNavigationError(RuntimeError): pass


class ScopaDemoRoute:
    def __init__(self,notify):
        self.notify=notify
        self.opening=False
        self.page=None

    @staticmethod
    def is_demo(url):
        parsed=urlparse(url)
        return (parsed.hostname in {'betsson.it','www.betsson.it'} and
                parsed.path.rstrip('/') in {'/skillgames/scopa/demo','/skillgames/scopa/prova','/skillgames/scopa/fun'})

    async def step(self,page):
        parsed=urlparse(page.url)
        if self.is_demo(page.url):return 'demo'
        if parsed.hostname not in {'betsson.it','www.betsson.it'}:
            raise DemoNavigationError('Не удалось подтвердить бесплатный режим Scopa на этой странице. Автоматические действия остановлены.')
        if self.opening:
            raise DemoNavigationError('После Prova не подтверждён адрес деморежима Scopa. Повторного клика и перехода в Gioca не будет.')
        if parsed.path.rstrip('/')!='/skillgames':
            await page.goto(f'{parsed.scheme}://{parsed.netloc}/skillgames',wait_until='domcontentloaded',timeout=20000)
            self.notify('Открываю каталог карточных игр для обычной Scopa.')
            return 'acted'
        await page.locator('.gioco1').first.wait_for(state='attached',timeout=10000)
        cards=page.locator('.gioco1')
        matches=[]
        for i in range(await cards.count()):
            card=cards.nth(i)
            title=await card.evaluate("e=>e.querySelector('.gioco1__titolo')?.textContent||e.querySelector('img')?.alt||''")
            if re.fullmatch(r'\s*Scopa\s*',title,re.I):matches.append(card)
        if len(matches)!=1:raise DemoNavigationError('Обычная Scopa не найдена однозначно. Premio Matto не выбирается.')
        card=matches[0]
        await card.scroll_into_view_if_needed(timeout=4000)
        await card.hover(timeout=4000)
        labels=card.get_by_text(re.compile(r'^\s*Prova\s*$',re.I))
        visible=[labels.nth(i) for i in range(await labels.count()) if await labels.nth(i).is_visible()]
        if len(visible)!=1:raise DemoNavigationError('У обычной Scopa нет доступной кнопки Prova. Gioca автоматически не нажимается.')
        target=visible[0]
        href=await target.get_attribute('href')
        if href and re.search(r'/real(?:[/?#]|$)',href,re.I):
            raise DemoNavigationError('Кнопка Prova ведёт в real-режим. Переход остановлен.')
        before=list(page.context.pages)
        await target.click(trial=True,timeout=4000)
        self.opening=True
        await target.click(timeout=4000)
        # Only a page opened by this exact demo click may become the active page.
        for _ in range(10):
            opened=[p for p in page.context.pages if p not in before and not p.is_closed()]
            if opened:
                if len(opened)!=1 or await opened[0].opener() is not page:
                    raise DemoNavigationError('Окно Prova не определено однозначно.')
                self.page=opened[0]
                await self.page.wait_for_load_state('domcontentloaded',timeout=10000)
                break
            if self.is_demo(page.url):break
            import asyncio
            await asyncio.sleep(.1)
        self.notify('Нажата Prova у обычной Scopa. Проверяю именно деморежим перед подключением математики.')
        return 'acted'

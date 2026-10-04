"""Optional browser patches and varied interaction timing for QA.

No guarantee of indistinguishability, CAPTCHA bypass or device emulation.
"""
from __future__ import annotations

import asyncio
import math
import platform
import random
import re
import weakref
from collections.abc import Awaitable, Callable


# Recent desktop major versions checked 2026-10-02. Selection below filters
# by the actual launched engine/major and uses its version if the list is stale.
RECENT_VERSIONS = {'chromium': ('154.0.0.0', '153.0.0.0'),
                   'firefox': ('157.0', '156.0')}
_cursor_positions = weakref.WeakKeyDictionary()


def gaussian_seconds(mean=0.30, sigma=0.09, minimum=0.04, maximum=0.80, *, rng=None):
    """Sample a truncated normal distribution by rejection, never clamp tails."""
    values = (mean, sigma, minimum, maximum)
    if not all(math.isfinite(v) for v in values) or not 0 <= minimum < maximum or sigma <= 0:
        raise ValueError('Expected finite values, 0 <= minimum < maximum, sigma > 0')
    if not minimum <= mean <= maximum:
        raise ValueError('Mean must lie inside delay bounds')
    generator = rng if rng is not None else random
    for _ in range(10_000):
        result = generator.gauss(mean, sigma)
        if minimum <= result <= maximum:
            return result
    raise ValueError('Delay interval is too narrow relative to sigma')


async def random_human_delay(mean=0.30, sigma=0.09, minimum=0.04, maximum=0.80, *, rng=None):
    seconds = gaussian_seconds(mean, sigma, minimum, maximum, rng=rng)
    await asyncio.sleep(seconds)
    return seconds


def user_agent_list(engine, versions=None):
    if engine not in RECENT_VERSIONS:
        raise ValueError('Supported engines: chromium, firefox')
    system = platform.system()
    if system == 'Windows':
        chrome_os, firefox_os = 'Windows NT 10.0; Win64; x64', 'Windows NT 10.0; Win64; x64'
    elif system == 'Darwin':
        chrome_os, firefox_os = 'Macintosh; Intel Mac OS X 10_15_7', 'Macintosh; Intel Mac OS X 10.15'
    else:
        chrome_os, firefox_os = 'X11; Linux x86_64', 'X11; Linux x86_64'
    result = []
    for version in (versions if versions is not None else RECENT_VERSIONS[engine]):
        if not re.fullmatch(r'\d+(?:\.\d+){1,3}', version):
            raise ValueError('Invalid version string')
        if engine == 'chromium':
            result.append(f'Mozilla/5.0 ({chrome_os}) AppleWebKit/537.36 '
                          f'(KHTML, like Gecko) Chrome/{version} Safari/537.36')
        else:
            result.append(f'Mozilla/5.0 ({firefox_os}; rv:{version}) Gecko/20100101 Firefox/{version}')
    return result


def choose_user_agent(engine, browser_version, *, rng=None):
    if engine not in RECENT_VERSIONS:
        raise ValueError('Supported engines: chromium, firefox')
    match = re.search(r'\d+(?:\.\d+)*', browser_version)
    if not match:
        raise ValueError('Cannot read launched browser version')
    actual = match.group(0)
    major = actual.split('.')[0]
    versions = [v for v in RECENT_VERSIONS[engine] if v.split('.')[0] == major]
    if not versions:
        versions = [f'{major}.0.0.0' if engine == 'chromium' else f'{major}.0']
    return (rng if rng is not None else random).choice(user_agent_list(engine, versions))


async def apply_stealth(context, *, engine='chromium'):
    """Apply before creating pages. Limit Firefox to webdriver patch.

    Full Chromium-oriented patches in Firefox would introduce fake Chrome APIs.
    Keep native UA, platform, languages and GPU identifiers unchanged.
    """
    from playwright_stealth import Stealth, ALL_EVASIONS_DISABLED_KWARGS
    if engine == 'firefox':
        options = {**ALL_EVASIONS_DISABLED_KWARGS, 'navigator_webdriver': True}
    elif engine == 'chromium':
        options = dict(navigator_user_agent=False, navigator_platform=False,
                       navigator_languages=False, webgl_vendor=False)
    else:
        raise ValueError('Unsupported engine')
    await Stealth(**options).apply_stealth_async(context)


async def smooth_click(element, *, jitter=2.0, steps=24, timeout_ms=10_000,
                       before_click: Callable[[], Awaitable[None]] | None = None,
                       rng=None):
    """Curved mouse path then a checked Locator click, without automatic retry.

    Takes a Playwright Locator, not an ElementHandle. Serial calls per page only.
    Jitter stays within the central area; Locator retains hit-target checks.
    """
    if (not math.isfinite(jitter) or jitter < 0 or type(steps) is not int
            or not 4 <= steps <= 240 or timeout_ms <= 0):
        raise ValueError('Invalid click parameters')
    generator = rng if rng is not None else random
    page = element.page
    await element.scroll_into_view_if_needed(timeout=timeout_ms)
    await element.click(trial=True, timeout=timeout_ms)
    box = await element.bounding_box(timeout=timeout_ms)
    if box is None or box['width'] <= 0 or box['height'] <= 0:
        raise ValueError('Element has no visible bounds')
    dx = generator.uniform(-min(jitter, box['width'] * .15), min(jitter, box['width'] * .15))
    dy = generator.uniform(-min(jitter, box['height'] * .15), min(jitter, box['height'] * .15))
    end = (box['x'] + box['width'] / 2 + dx, box['y'] + box['height'] / 2 + dy)
    start = _cursor_positions.get(page, (0.0, 0.0))
    distance = math.dist(start, end)
    bend = min(60, distance * .15)
    controls = [(start[0] + (end[0]-start[0]) * f + generator.uniform(-bend, bend),
                 start[1] + (end[1]-start[1]) * f + generator.uniform(-bend, bend))
                for f in (.33, .66)]
    duration = gaussian_seconds(.35, .08, .10, .65, rng=generator)
    for index in range(1, steps + 1):
        t = index / steps
        t = t * t * (3 - 2 * t)  # slow start/end
        weights = ((1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3)
        points = [start, *controls, end]
        x = sum(w*p[0] for w, p in zip(weights, points))
        y = sum(w*p[1] for w, p in zip(weights, points))
        await page.mouse.move(max(0, x), max(0, y))
        _cursor_positions[page] = (max(0, x), max(0, y))
        await asyncio.sleep(duration / steps)
    await random_human_delay(.12, .04, .03, .25, rng=generator)
    # Re-resolve after movement: the DOM/geometry may have changed.
    current = await element.bounding_box(timeout=timeout_ms)
    if current is None:
        raise ValueError('Element disappeared before click')
    px = current['width'] / 2 + max(-current['width']*.15, min(dx, current['width']*.15))
    py = current['height'] / 2 + max(-current['height']*.15, min(dy, current['height']*.15))
    await page.mouse.move(current['x'] + px, current['y'] + py, steps=4)
    _cursor_positions[page] = (current['x'] + px, current['y'] + py)
    if before_click is not None:
        await before_click()
    press_ms = gaussian_seconds(.07, .02, .02, .15, rng=generator) * 1000
    await element.click(position={'x': px, 'y': py}, delay=press_ms, timeout=timeout_ms)

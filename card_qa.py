"""Async DOM card adapter for Playwright QA. Python 3.10+."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Frame, expect


class StaleSnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    card_selector: str = ".card"
    value_selector: str = ".card-value"
    suit_selector: str = ".card-suit"
    id_attribute: str = "data-card-id"
    api_url: str = "http://127.0.0.1:8000/analyze"
    response_id_field: str = "element_id"
    timeout_ms: int = 10_000
    mouse_steps: int = 12
    mode: str = 'cards'
    state_selector: str = '#game-state'
    hand_selector: str = '#player-hand .card'
    table_selector: str = '#table-cards .card'
    confirm_selector: str = '#confirm-move'
    selected_attribute: str = 'aria-pressed'


class CardQA:
    """Use one instance per page/frame and serialize its QA cycles.

    IDs must be unique, stable across renders, and identify the same logical
    card. The API returns {"element_id": "..."}; it cannot supply selectors.
    """

    def __init__(self, page: Page, config: Config = Config(), *,
                 frame: Frame | None = None, request_context: Any = None,
                 click_handler: Any = None):
        self.page = page
        self.root = frame if frame is not None else page
        self.config = config
        self._request_context = request_context
        self._click_handler = click_handler
        self._snapshot: dict[str, Any] | None = None
        self._authorized_id: str | None = None
        url = urlparse(config.api_url)
        if (url.scheme not in {"http", "https"}
                or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username or url.password):
            raise ValueError("api_url must be a loopback HTTP(S) endpoint")
        if config.timeout_ms <= 0 or config.mouse_steps < 1:
            raise ValueError("Invalid timeout or mouse_steps")

    async def _read_cards(self) -> list[dict[str, str]]:
        c = self.config
        # All fields are read in a single synchronous browser evaluation.
        # CSS selectors here must be standard DOM selectors.
        cards = await self.root.locator(c.card_selector).evaluate_all(
            """(nodes, c) => nodes.map(node => {
                const text = selector => {
                    const matches = node.querySelectorAll(selector);
                    if (matches.length !== 1)
                        throw new Error('Expected one child for ' + selector);
                    return matches[0].textContent.trim().replace(/\\s+/g, ' ');
                };
                return {element_id: node.getAttribute(c.id),
                        value: text(c.value), suit: text(c.suit)};
            })""",
            {"id": c.id_attribute, "value": c.value_selector,
             "suit": c.suit_selector},
        )
        ids = [card["element_id"] for card in cards]
        if any(not isinstance(i, str) or not i.strip() for i in ids):
            raise ValueError(f"Each card requires {c.id_attribute}")
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate card IDs")
        if any(not card["value"] or not card["suit"] for card in cards):
            raise ValueError("Empty value/suit")
        return cards

    async def extract_data(self) -> dict[str, Any]:
        self._authorized_id = None
        self._snapshot = None
        await self.root.locator(self.config.card_selector).first.wait_for(
            state="attached", timeout=self.config.timeout_ms)
        payload = {"schema_version": 1, "cards": await self._read_cards()}
        # Keep an independent copy: caller modifications cannot alter the baseline.
        self._snapshot = json.loads(json.dumps(payload))
        return payload

    async def sync_data(self, payload: dict[str, Any]) -> str:
        self._authorized_id = None
        if self._snapshot is None or payload != self._snapshot:
            raise StaleSnapshotError("Call extract_data() before sync_data()")
        if self._request_context is not None:
            result = await self._post_payload(self._request_context, payload)
        else:
            result = await self._temporary_request(payload)
        if not isinstance(result, dict):
            raise ValueError("API response must be a JSON object")
        element_id = result.get(self.config.response_id_field)
        if element_id is None and "move_index" in result:
            index = result["move_index"]
            cards = self._snapshot["cards"]
            if type(index) is not int or not 0 <= index < len(cards):
                raise ValueError("API returned an invalid move_index")
            element_id = cards[index]["element_id"]
        ids = {card["element_id"] for card in self._snapshot["cards"]}
        if not isinstance(element_id, str) or element_id not in ids:
            raise ValueError("API returned an unknown element_id")
        self._authorized_id = element_id
        return element_id

    async def _post_payload(self, request, payload):
        response = await request.post(
            self.config.api_url, data=payload,
            timeout=self.config.timeout_ms, max_redirects=0)
        try:
            if not response.ok:
                raise RuntimeError(f"Analysis API returned HTTP {response.status}")
            return await response.json()
        finally:
            await response.dispose()

    async def _temporary_request(self, payload):
        # A standalone request context avoids sharing browser cookies with API.
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            request = await p.request.new_context()
            try:
                return await self._post_payload(request, payload)
            finally:
                await request.dispose()

    async def execute_action(self, element_id: str) -> None:
        if self._snapshot is None or element_id != self._authorized_id:
            raise ValueError("Action must come from the latest successful sync_data")
        # Consume once; retrying an uncertain click could perform it twice.
        self._authorized_id = None
        c = self.config
        # CSS escaping is performed by the browser, never by the API.
        selector = await self.root.evaluate(
            "([attr, id]) => '[' + CSS.escape(attr) + '=' + CSS.escape(id) + ']'",
            [c.id_attribute, element_id])
        target = self.root.locator(c.card_selector).and_(self.root.locator(selector))
        await expect(target).to_have_count(1, timeout=c.timeout_ms)
        await target.scroll_into_view_if_needed(timeout=c.timeout_ms)
        await target.click(trial=True, timeout=c.timeout_ms)
        if self._click_handler is not None:
            async def verify_snapshot():
                if await self._read_cards() != self._snapshot["cards"]:
                    raise StaleSnapshotError("DOM cards changed; extract and analyze again")
            await self._click_handler(target, timeout_ms=c.timeout_ms,
                                      before_click=verify_snapshot)
            return
        box = await target.bounding_box(timeout=c.timeout_ms)
        if box is None:
            raise StaleSnapshotError("Card has no visible bounding box")
        await self.page.mouse.move(box["x"] + box["width"] / 2,
                                   box["y"] + box["height"] / 2,
                                   steps=c.mouse_steps)
        if await self._read_cards() != self._snapshot["cards"]:
            raise StaleSnapshotError("DOM cards changed; extract and analyze again")
        # Locator resolves the current node and checks visibility, stability,
        # enabled state and hit target before dispatching a normal click.
        await target.click(timeout=c.timeout_ms)


async def qa_cycle(page: Page) -> None:
    adapter = CardQA(page)
    payload = await adapter.extract_data()
    element_id = await adapter.sync_data(payload)
    await adapter.execute_action(element_id)

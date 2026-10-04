"""Scopa adapter: explicit full-state JSON, legal actions and confirmed captures.

The site bridge must render a JSON envelope {revision, state, search?} in
state_selector. Hidden opponent identities remain unknown, never fabricated.
"""
import asyncio
import copy
import json
from playwright.async_api import expect
from card_qa import CardQA, StaleSnapshotError
from backend.app.schemas.games import GameStateSchema
from backend.app.services.serialization import state_from_schema, state_to_wire
from engine.rules import RulesEngine


class WaitingForTurn(Exception):
    pass


class TableChangedError(RuntimeError):
    """A pinned document/table changed; never carry a move to another table."""


class PartialActionError(RuntimeError):
    """Some selection clicks may have happened; never automatically replay."""


class ScopaQA(CardQA):
    async def read(self):
        c = self.config
        raw=await self.root.evaluate('''c => {
            const nodes=document.querySelectorAll(c.state);
            if(nodes.length!==1) throw Error('Expected one full-state JSON element');
            if(!window.__qaTableDocumentV1)window.__qaTableDocumentV1=crypto.randomUUID();
            return {document_id:window.__qaTableDocumentV1,envelope:JSON.parse(nodes[0].textContent),
              hand:Array.from(document.querySelectorAll(c.hand),e=>e.getAttribute(c.id)),
              table:Array.from(document.querySelectorAll(c.table),e=>e.getAttribute(c.id))};
        }''', {'state':c.state_selector,'hand':c.hand_selector,
               'table':c.table_selector,'id':c.id_attribute})
        identity=(self.root.url,raw['document_id'],copy.deepcopy(raw['envelope'].get('room')))
        if hasattr(self,'_table_identity') and identity!=self._table_identity:
            raise TableChangedError('Стіл або документ змінився. Поточний хід скасовано; для нового столу перезапусти сесію.')
        return raw

    async def extract_data(self):
        await self.root.locator(self.config.state_selector).wait_for(state='attached')
        raw = await self.read()
        envelope = raw['envelope']
        data = envelope['state']
        # Require every field, including zero/empty values. Schema defaults must
        # not silently turn missing observations into a fictional game state.
        missing = set(GameStateSchema.model_fields) - set(data)
        if missing:
            raise ValueError('Missing full-state fields: '+', '.join(sorted(missing)))
        if type(envelope.get('revision')) is not int or envelope['revision'] < 1:
            raise ValueError('A positive integer state revision is required')
        state = state_from_schema(GameStateSchema.model_validate(data))
        for zone, ids in [('hand', data['player_hand']), ('table', data['table_cards'])]:
            if len(raw[zone]) != len(set(raw[zone])) or set(raw[zone]) != set(ids):
                raise ValueError('Rendered cards and full game state disagree: '+zone)
        if not hasattr(self,'_table_identity'):
            self._table_identity=(self.root.url,raw['document_id'],copy.deepcopy(envelope.get('room')))
        if data['current_player'] != 'player' or not data['player_hand']:
            raise WaitingForTurn()
        self._moves = list(RulesEngine().get_legal_moves(state))
        if not self._moves:
            raise WaitingForTurn()
        self._raw = copy.deepcopy(raw)
        self._snapshot = {'schema_version':2, 'revision':envelope['revision'],
            'state':copy.deepcopy(data), 'search':envelope.get('search',{'max_depth':2}),
            'legal_moves':[{'played_card':m.played_card.id,
                'captured_cards':[c.id for c in m.captured_cards]} for m in self._moves]}
        self._command = None
        return copy.deepcopy(self._snapshot)

    async def sync_data(self, payload):
        if payload != self._snapshot:
            raise ValueError('Payload is not the current snapshot')
        result = (await self._post_payload(self._request_context, payload) if self._request_context
                  else await self._temporary_request(payload))
        if not isinstance(result,dict): raise ValueError('Engine response must be an object')
        if result.get('fallback'):
            raise RuntimeError('Engine timeout: do not execute a random move in Scopa QA')
        i = result.get('move_index')
        if type(i) is not int or not 0 <= i < len(self._moves):
            raise ValueError('Invalid engine action index')
        move = self._snapshot['legal_moves'][i]
        if ('played_card' in result and result['played_card'] != move['played_card']) or (
                'captured_cards' in result and sorted(result['captured_cards']) != sorted(move['captured_cards'])):
            raise ValueError('Engine index and capture command disagree')
        self._command = i
        self.analysis = result
        # Optional local demo presentation hook; never accepts remote selectors.
        await self.page.evaluate('(r)=>{if(typeof window.showAnalysis==="function") window.showAnalysis(r)}',result)
        return i

    async def unchanged(self):
        if await self.read() != self._raw:
            raise StaleSnapshotError('Game changed since analysis')

    async def target(self, zone, card_id):
        escaped = await self.page.evaluate('(x)=>CSS.escape(x)',card_id)
        attr = await self.page.evaluate('(x)=>CSS.escape(x)',self.config.id_attribute)
        loc = self.root.locator(zone).and_(self.root.locator(f'[{attr}="{escaped}"]'))
        await expect(loc).to_have_count(1, timeout=self.config.timeout_ms)
        return loc

    async def click(self, target):
        await target.scroll_into_view_if_needed()
        await target.click(trial=True)
        await self.unchanged()
        if self._click_handler:
            await self._click_handler(target,timeout_ms=self.config.timeout_ms,before_click=self.unchanged)
        else:
            box=await target.bounding_box()
            if not box: raise ValueError('Card is not visible')
            await self.page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2,steps=self.config.mouse_steps)
            await self.unchanged()
            await target.click()

    async def execute_action(self, index):
        if type(index) is not int or index != self._command:
            raise ValueError('Action has not been authorized for this snapshot')
        self._command = None  # Single-use command, including failures.
        await self.unchanged()
        move=self._moves[index]
        targets=[await self.target(self.config.hand_selector,move.played_card.id)]
        targets += [await self.target(self.config.table_selector,c.id) for c in move.captured_cards]
        confirm=self.root.locator(self.config.confirm_selector)
        await expect(confirm).to_have_count(1)
        # No existing selection may accidentally contaminate a new action.
        selected=self.config.selected_attribute
        if await self.root.locator(self.config.hand_selector+', '+self.config.table_selector).evaluate_all(
                '(nodes,a)=>nodes.some(n=>n.getAttribute(a)==="true")',selected):
            raise ValueError('Clear existing card selection before automation')
        started=False
        try:
            for target in targets:
                started=True
                await self.click(target)
                await expect(target).to_have_attribute(selected,'true',timeout=self.config.timeout_ms)
                await asyncio.sleep(.25)
            expected_ids={move.played_card.id,*(c.id for c in move.captured_cards)}
            actual=await self.root.locator(self.config.hand_selector+', '+self.config.table_selector).evaluate_all(
                '(nodes,c)=>nodes.filter(n=>n.getAttribute(c.a)==="true").map(n=>n.getAttribute(c.id))',
                {'a':selected,'id':self.config.id_attribute})
            if set(actual)!=expected_ids or len(actual)!=len(expected_ids):
                raise ValueError('Unexpected cards selected')
            await self.click(confirm)
            await self.root.wait_for_function('''c=>JSON.parse(document.querySelector(c.selector).textContent).revision!==c.revision''',
                arg={'selector':self.config.state_selector,'revision':self._snapshot['revision']},timeout=self.config.timeout_ms)
            after=await self.read()
            expected=state_to_wire(move.resulting_state)
            if after['envelope']['state']!=expected:
                raise ValueError('Confirmed state differs from the legal move result')
            self.outcome={'before':self._snapshot['state'],'after':expected,
                          'move':self._snapshot['legal_moves'][index],'analysis':self.analysis}
        except Exception as exc:
            if started: raise PartialActionError('Selection/confirmation outcome must be reviewed') from exc
            raise

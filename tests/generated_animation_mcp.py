"""Generated-motion MCP schemas and real STDIO-to-HTTP routing against a mock API.

No Studio service, account, saved model, runtime or inference is started or changed.
Run with .mcp-venv/Scripts/python.exe tests/generated_animation_mcp.py.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import asyncio
import json
import os
import sys

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
MOTION_ID = 'a' * 32
MODEL_ID = 'b' * 32
OPERATION_ID = 'c' * 32
TEST_TOKEN = 'generated-motion-fixture-key'
TOOL_NAMES = {
    'list_generated_animations', 'get_generated_animation', 'generate_animation',
    'cancel_animation_generation', 'add_generated_animation',
}


class MockAPI(BaseHTTPRequestHandler):
    calls = []
    next_error = None
    server_mode = True

    def log_message(self, *_):
        pass

    def respond(self, status, value):
        body = json.dumps(value).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_request(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        body = json.loads(raw) if raw else None
        self.calls.append({'method': self.command, 'path': self.path, 'body': body,
                           'authorized': self.headers.get('Authorization') == 'Bearer ' + TEST_TOKEN})
        if not self.calls[-1]['authorized']:
            self.respond(401, {'detail': 'Fixture authorization required.'})
            return
        if type(self).next_error:
            status, value = type(self).next_error
            type(self).next_error = None
            self.respond(status, value)
            return
        prefix = '/api/v1/my-animations'
        motion = {'id': MOTION_ID, 'name': 'Walk and stop', 'prompt': 'Walk forward then stop',
                  'state': 'done', 'stage': 'Saved', 'progress': 100, 'duration': 5, 'fps': 30,
                  'frames': 150, 'seed': 42, 'created': 1, 'provenance': {'runtime': 'fixture'},
                  'clip_name': 'Generated_fixture', 'preview_root': 'pelvis',
                  'preview_url': prefix + '/' + MOTION_ID + '/files/preview.glb',
                  'files': {'motion.npz': prefix + '/' + MOTION_ID + '/files/motion.npz'}}
        if self.command == 'GET' and self.path == prefix:
            self.respond(200, {'animations': [motion], 'engine': {'ready': True, 'label': 'Fixture',
                         'backend': 'CPU', 'experimental': True, 'message': 'Mock API only.'},
                         'min_duration': 2, 'max_duration': 10, 'step': .5})
        elif self.command == 'GET' and self.path == prefix + '/' + MOTION_ID:
            self.respond(200, motion)
        elif self.command == 'POST' and self.path == prefix:
            self.respond(202, {'id': MOTION_ID, 'state': 'queued',
                              'status_url': prefix + '/' + MOTION_ID})
        elif self.command == 'POST' and self.path == prefix + '/' + MOTION_ID + '/cancel':
            self.respond(200, {'ok': True})
        elif self.command == 'POST' and self.path == '/api/v1/models/' + MODEL_ID + '/my-animations':
            update = {'id': MODEL_ID, 'state': 'queued', 'status_url': '/api/v1/jobs/' + MODEL_ID}
            if self.server_mode:
                update.update(operation_id=OPERATION_ID,
                              status_url='/api/v1/animation-operations/' + OPERATION_ID)
            self.respond(202, update)
        elif self.command == 'GET' and self.path in (
                '/api/v1/animation-operations/' + OPERATION_ID, '/api/v1/jobs/' + MODEL_ID):
            self.respond(200, {'id': OPERATION_ID if '/animation-operations/' in self.path else MODEL_ID,
                              'model_id': MODEL_ID, 'state': 'done', 'stage': 'Animations saved to model'})
        else:
            self.respond(404, {'detail': 'Unexpected fixture route.'})

    do_GET = handle_request
    do_POST = handle_request


async def run():
    MockAPI.calls = []
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)
        print('PASS', name, flush=True)

    server = ThreadingHTTPServer(('127.0.0.1', 0), MockAPI)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {**os.environ, 'TRELLIS_API_URL': f'http://127.0.0.1:{server.server_port}',
           'TRELLIS_API_TOKEN': TEST_TOKEN, 'PYTHONUTF8': '1'}
    env.pop('TRELLIS_API_CA_BUNDLE', None)
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'trellis_mcp.py')],
                                  cwd=ROOT, env=env)
    try:
        async with Client(params) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            check('Five generated-motion tools discovered', TOOL_NAMES <= tools.keys())
            check('Standard animation tools preserved', {'list_animations', 'add_animation', 'add_animations'} <= tools.keys())
            check('Read, write and cancellation annotations',
                  tools['list_generated_animations'].annotations.read_only_hint
                  and tools['get_generated_animation'].annotations.read_only_hint
                  and not tools['generate_animation'].annotations.read_only_hint
                  and not tools['add_generated_animation'].annotations.destructive_hint
                  and tools['cancel_animation_generation'].annotations.destructive_hint)

            schema = tools['generate_animation'].input_schema
            recipe = schema.get('$defs', {}).get('GeneratedAnimationCreate') or schema['properties']['recipe']
            fields = recipe['properties']
            check('Typed generation limits and defaults',
                  recipe.get('additionalProperties') is False
                  and fields['prompt']['minLength'] == 3 and fields['prompt']['maxLength'] == 1000
                  and fields['name']['maxLength'] == 80
                  and fields['duration']['minimum'] == 2 and fields['duration']['maximum'] == 10
                  and fields['duration']['multipleOf'] == .5 and fields['duration']['default'] == 5
                  and fields['seed']['maximum'] == 2147483647 and fields['seed']['default'] == 42)
            apply_schema = tools['add_generated_animation'].input_schema
            selection = apply_schema.get('$defs', {}).get('GeneratedAnimationApply') or apply_schema['properties']['selection']
            check('Typed application preserves the root-travel option',
                  selection['properties']['in_place']['default'] is False
                  and 'root travel' in selection['properties']['in_place']['description'].lower()
                  and 'new linked model copy' not in selection['properties']['in_place']['description'].lower())

            listing = await client.call_tool('list_generated_animations')
            check('List reads private library through versioned HTTP',
                  not listing.is_error and listing.structured_content['engine']['ready']
                  and MockAPI.calls[-1]['path'] == '/api/v1/my-animations')
            result = await client.call_tool('get_generated_animation', {'animation_id': MOTION_ID})
            check('Get preserves preview and source URLs', not result.is_error
                  and result.structured_content['clip_name'] == 'Generated_fixture'
                  and result.structured_content['files']['motion.npz'].startswith('/api/v1/my-animations/'))
            result = await client.call_tool('generate_animation', {'recipe': {'prompt': 'Walk\nforward\tthen stop'}})
            check('Generate normalizes prompt and forwards typed defaults once', not result.is_error
                  and result.structured_content['state'] == 'queued'
                  and MockAPI.calls[-1] == {'method': 'POST', 'path': '/api/v1/my-animations',
                      'body': {'name': 'New animation', 'prompt': 'Walk forward then stop', 'duration': 5.0, 'seed': 42},
                      'authorized': True})

            before = len(MockAPI.calls)
            for arguments in ({'recipe': {'prompt': 'Walk forward', 'duration': 5.1}},
                              {'recipe': {'prompt': 'Walk forward', 'seed': True}},
                              {'recipe': {'prompt': 'Walk forward', 'unexpected': 'field'}},
                              {'recipe': {'prompt': '  '}}):
                rejected = await client.call_tool('generate_animation', arguments)
                assert rejected.is_error, arguments
            rejected = await client.call_tool('get_generated_animation', {'animation_id': '../../shutdown'})
            check('Invalid recipes and identifiers never reach HTTP', rejected.is_error and len(MockAPI.calls) == before)

            result = await client.call_tool('cancel_animation_generation', {'animation_id': MOTION_ID})
            check('Cancellation is scoped to the requested motion', not result.is_error
                  and MockAPI.calls[-1]['method'] == 'POST'
                  and MockAPI.calls[-1]['path'] == '/api/v1/my-animations/' + MOTION_ID + '/cancel')
            generation_count = sum(c['method'] == 'POST' and c['path'] == '/api/v1/my-animations' for c in MockAPI.calls)
            for server_mode in (False, True):
                MockAPI.server_mode = server_mode
                for in_place in (False, True):
                    args = {'model_id': MODEL_ID, 'selection': {'animation_id': MOTION_ID}}
                    if in_place:
                        args['selection']['in_place'] = True
                    result = await client.call_tool('add_generated_animation', args)
                    assert not result.is_error and result.structured_content['id'] == MODEL_ID
                    assert MockAPI.calls[-1]['path'] == '/api/v1/models/' + MODEL_ID + '/my-animations'
                    assert MockAPI.calls[-1]['body'] == {'animation_id': MOTION_ID, 'in_place': in_place}
                    update = result.structured_content
                    assert update.get('operation_id') == (OPERATION_ID if server_mode else None)
                    polled = await client.call_tool('get_animation_update', {'status_url': update['status_url']})
                    assert not polled.is_error and polled.structured_content['state'] == 'done'
                    assert MockAPI.calls[-1]['method'] == 'GET'
                    assert MockAPI.calls[-1]['path'] == update['status_url']
            check('Both editions keep model ID and poll their returned update URL', True)
            check('Apply forwards root-travel mode and never regenerates',
                  sum(c['method'] == 'POST' and c['path'] == '/api/v1/my-animations' for c in MockAPI.calls) == generation_count)
            before = len(MockAPI.calls)
            rejected = await client.call_tool('get_animation_update',
                                             {'status_url': 'https://example.invalid/api/v1/jobs/' + MODEL_ID})
            check('Animation status polling rejects external URLs before HTTP',
                  rejected.is_error and len(MockAPI.calls) == before)
            MockAPI.next_error = (200, {'id': MODEL_ID, 'state': 'done',
                                       'operation_error': 'Fixture transfer failed; previous model preserved.'})
            result = await client.call_tool('get_animation_update', {'status_url': '/api/v1/jobs/' + MODEL_ID})
            check('Desktop preserved-model status retains the animation failure',
                  not result.is_error and result.structured_content['state'] == 'done'
                  and result.structured_content['operation_error'].startswith('Fixture transfer failed'))
            MockAPI.next_error = (503, {'detail': 'Fixture unavailable: ' + TEST_TOKEN})
            result = await client.call_tool('list_generated_animations')
            check('HTTP failures become tool errors with credentials redacted',
                  result.is_error and '503' in str(result) and TEST_TOKEN not in str(result))
            check('All mock requests use the configured account token', all(c['authorized'] for c in MockAPI.calls))
            guide = await client.read_resource('trellis://guide')
            api_guide = await client.read_resource('trellis://api')
            check('MCP resources expose the new English documentation',
                  'add_generated_animation' in str(guide) and '/my-animations' in str(api_guide))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    print(json.dumps({'passed': len(checks), 'isolated_mock_http': True,
                      'inference_run': False, 'live_service_modified': False}, indent=2))


if __name__ == '__main__':
    asyncio.run(run())

import asyncio
import json
import os
import threading
import time
import wave
from pathlib import Path
from queue import Queue, Empty

import numpy as np
import speech_recognition as sr
from aiohttp import web, WSMsgType
from openai import OpenAI
import requests

BASE = Path(__file__).resolve().parent
SAMPLE_RATE = 16000
FRAME_MS = 100
SILENCE_SECONDS = 0.9
MIN_SPEECH_SECONDS = 0.35
MAX_UTTERANCE_SECONDS = 15
RMS_THRESHOLD = float(os.getenv('RMS_THRESHOLD', '0.018'))
MODEL = os.getenv('OPENAI_MODEL', 'gpt-4')
PORT = int(os.getenv('PORT', '8443'))

client = OpenAI()
recognizer = sr.Recognizer()
chunks = Queue(maxsize=400)
chat_lock = threading.Lock()

SYSTEM_PROMPT = ('You are a friendly social robot speaking through a Peerbots face. '
                 'Answer questions briefly, conversationally, and in plain spoken text. '
                 'Do not include animation commands, markup, or stage directions.')


def initialize_files():
    (BASE / 'history.txt').write_text(json.dumps([{'role': 'system', 'content': SYSTEM_PROMPT}]))
    (BASE / 'listen.txt').write_text('no')


def peerbots_say(speech):
    """Use the official Peerbots send-message endpoint to speak through the face."""
    key = os.environ['PEERBOTS_API_KEY']
    username = os.environ['PEERBOTS_USERNAME']
    response = requests.post(
        f'https://api.peerbots.org/v1/send-message/{requests.utils.quote(username, safe="")}',
        headers={'Accept': 'application/json', 'X-API-KEY': key},
        json={'title': 'Robot response', 'speech': speech},
        timeout=20,
    )
    response.raise_for_status()
    print('Sent speech to Peerbots:', response.status_code, flush=True)


def process_utterance(pcm):
    try:
        audio = sr.AudioData(pcm, SAMPLE_RATE, 2)
        text = recognizer.recognize_google(audio)
        print('Phone microphone / Human said:', text, flush=True)
        with chat_lock:
            history_file = BASE / 'history.txt'
            history = json.loads(history_file.read_text())
            history.append({'role': 'user', 'content': text})
            completion = client.chat.completions.create(model=MODEL, messages=history)
            response = completion.choices[0].message.content or ''
            print('Assistant:', response, flush=True)
            history.append({'role': 'assistant', 'content': response})
            history_file.write_text(json.dumps(history, indent=2))
            (BASE / 'response.txt').write_text(response)
            # No NAO animation or listen.txt polling: Peerbots handles speech.
            peerbots_say(response)
    except sr.UnknownValueError:
        print('Could not understand speech', flush=True)
    except sr.RequestError as exc:
        print('Google speech recognition error:', exc, flush=True)
    except Exception as exc:
        print('Processing error:', repr(exc), flush=True)


def speech_worker():
    frame_samples = int(SAMPLE_RATE * FRAME_MS / 1000)
    pending = np.empty(0, dtype=np.int16)
    speaking = False
    utterance = []
    speech_frames = 0
    silent_frames = 0
    pre_roll = []
    while True:
        try:
            data = chunks.get(timeout=1)
        except Empty:
            continue
        pending = np.concatenate((pending, np.frombuffer(data, dtype='<i2')))
        while len(pending) >= frame_samples:
            frame, pending = pending[:frame_samples], pending[frame_samples:]
            rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768) ** 2)))
            voiced = rms >= RMS_THRESHOLD
            if not speaking:
                pre_roll.append(frame.copy())
                pre_roll = pre_roll[-3:]
                if voiced:
                    speaking = True
                    utterance = pre_roll.copy()
                    speech_frames = 1
                    silent_frames = 0
                    pre_roll = []
                    print('Speech detected...', flush=True)
            else:
                utterance.append(frame.copy())
                if voiced:
                    speech_frames += 1
                    silent_frames = 0
                else:
                    silent_frames += 1
                if silent_frames * FRAME_MS / 1000 >= SILENCE_SECONDS or len(utterance) * FRAME_MS / 1000 >= MAX_UTTERANCE_SECONDS:
                    if speech_frames * FRAME_MS / 1000 >= MIN_SPEECH_SECONDS:
                        process_utterance(np.concatenate(utterance).astype('<i2').tobytes())
                    speaking = False
                    utterance = []
                    pre_roll = []
                    speech_frames = 0
                    silent_frames = 0


async def index(request):
    if request.query.get('token') != os.getenv('PEERBOTS_TOKEN', '') or not os.getenv('PEERBOTS_TOKEN'):
        raise web.HTTPForbidden(text='Invalid access token')
    return web.FileResponse(BASE / 'face.html')


async def websocket_handler(request):
    if request.query.get('token') != os.getenv('PEERBOTS_TOKEN', '') or not os.getenv('PEERBOTS_TOKEN'):
        raise web.HTTPForbidden(text='Invalid access token')
    ws = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=30)
    await ws.prepare(request)
    print('Phone microphone connected', flush=True)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                try:
                    chunks.put_nowait(msg.data)
                except Exception:
                    pass
            elif msg.type == WSMsgType.ERROR:
                print('WebSocket error:', ws.exception(), flush=True)
    finally:
        print('Phone microphone disconnected', flush=True)
    return ws


def main():
    for name in ('OPENAI_API_KEY', 'PEERBOTS_API_KEY', 'PEERBOTS_USERNAME'):
        if not os.environ.get(name):
            raise RuntimeError(f'Missing required setting: {name}')
    initialize_files()
    threading.Thread(target=speech_worker, daemon=True).start()
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/audio', websocket_handler)
    ssl_context = None
    cert = BASE / 'cert.pem'
    key = BASE / 'key.pem'
    if cert.exists() and key.exists():
        import ssl
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(str(cert), str(key))
    else:
        print('WARNING: No cert.pem/key.pem. HTTP works for laptop testing only; phone microphone requires trusted HTTPS.')
    web.run_app(app, host='127.0.0.1', port=PORT, ssl_context=ssl_context)


if __name__ == '__main__':
    main()

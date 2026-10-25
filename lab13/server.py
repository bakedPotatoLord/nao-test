import asyncio
import glob
import json
import os
import threading
import time
from pathlib import Path
from queue import Queue, Empty

import numpy as np
import requests
import speech_recognition as sr
from aiohttp import web, WSMsgType
from openai import OpenAI

from gaze import Gaze

try:
    import serial  # pyserial, for the Arduino head controller
except ImportError:
    serial = None


# ---------------- Settings ----------------

BASE = Path(__file__).resolve().parent
SAMPLE_RATE = 16000
FRAME_MS = 100
SILENCE_SECONDS = 0.9
MIN_SPEECH_SECONDS = 0.35
MAX_UTTERANCE_SECONDS = 15
RMS_THRESHOLD = float(os.getenv('RMS_THRESHOLD', '0.018'))
MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')  # needs JSON mode support
PORT = int(os.getenv('PORT', '8443'))

# Roughly how fast the face speaks, used to mute the mic while it talks.
SPEECH_WORDS_PER_SECOND = 2.5
SPEECH_START_DELAY = 1.5

client = OpenAI()
recognizer = sr.Recognizer()
chunks = Queue(maxsize=400)
chat_lock = threading.Lock()
mute_until = 0
phone_sockets = set()  # open connections from the phone page
loop = None


# ---------------- Head motion (Arduino) ----------------

GESTURES = ('look_user', 'look_screen', 'nod', 'shake', 'none')

arduino = None
arduino_lock = threading.Lock()


def send_head_command(command):
    if arduino is None:
        return
    with arduino_lock:
        arduino.write((command + '\n').encode())


gaze = Gaze(send=send_head_command)


def connect_arduino():
    """Open the Arduino's serial port. The robot still talks if no Arduino is plugged in."""
    global arduino
    ports = sorted(glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*'))
    if serial is None or not ports:
        print('No Arduino found, head will not move', flush=True)
        return
    arduino = serial.Serial(ports[0], 9600, timeout=1)
    print('Arduino connected on', ports[0], flush=True)
    threading.Thread(target=read_arduino, daemon=True).start()


def read_arduino():
    """Print status messages from the Arduino, such as when homing is complete."""
    while True:
        line = arduino.readline().decode(errors='replace').strip()
        if line:
            print('Arduino:', line, flush=True)


# ---------------- Robot personality and dialogue ----------------

SYSTEM_PROMPT = """You are a small desk robot that works as an IT help-desk assistant at a college.
You have a hexagonal head on a half torso and a phone screen for a face. Your eyes have cameras so you
can look at the user's computer screen, and your neck can turn toward the user or their computer.
You help students, faculty and staff with everyday tech problems so the IT staff have less work.
Personality: friendly, calm, patient and approachable. Use plain, simple words and a normal voice.

Follow this conversation structure, one step at a time:
1. Greet the user once: "Hello, how can I help you?"
2. If they have no information about the problem, say you will try to diagnose it.
   If they have some information, ask them to tell you a little more about the issue.
3. Ask once: "Can you grant me access?" This is just a permission question. Do not explain how to
   give access. Any answer except a clear no counts as yes, so move on to step 4 right away.
4. Decide if you can fix it.
   - Easy problems (wifi, printer, sound, frozen app, slow computer): give one simple fix to try.
   - Hard problems (blue screen, won't turn on, broken hardware, lost data): say it is too difficult
     to solve on your own and ask "Can I help you create a ticket?" If yes, say you created a ticket.
5. End with "Glad to be of assistance."

Keep every reply to 1-2 short spoken sentences, with no lists or markdown.

Turn taking: the user can only talk after you finish, so make it obvious when it is their turn.
End every reply with a question or a clear request (for example "What happens when you try?"),
except the final "Glad to be of assistance." Never ask two questions in one reply.

Reply with ONLY a JSON object in this format:
{"title": "<2-4 word summary>", "speech": "<what you say>", "emotion": "<emotion>", "color": "<color>", "gesture": "<gesture>"}
emotion must be one of: Neutral, Surprised, Happy, Sad, Concerned, Sleepy
color must be one of: Light Blue, Blue, Green, Red, Purple, Pink, Yellow, Orange, Grey, Black, White
Use Happy + Light Blue normally, Surprised + Yellow when asking for access,
Concerned + Purple when the problem is too difficult, and Happy + Pink when saying goodbye.
gesture must be one of: look_user, look_screen, nod, shake, none
Your head already looks at the user while they talk, looks away while you think, and looks back
at the user when you finish talking, so you do not need to ask for that. The gesture only adds
meaning to what you say:
- look_screen: your sentence is about their computer screen or you ask for access. Your head
  turns to their computer while you speak and back to them for your last words.
- nod: you agree, confirm a fix worked, or say goodbye.
- shake: the problem is too difficult for you to fix.
- look_user or none: everything else."""


def initialize_history():
    (BASE / 'history.txt').write_text(json.dumps([{'role': 'system', 'content': SYSTEM_PROMPT}]))


# ---------------- Peerbots face ----------------

def face_channels():
    """PEERBOTS_USERNAME can list several accounts, separated by commas."""
    return [name.strip() for name in os.environ['PEERBOTS_USERNAME'].split(',') if name.strip()]


def peerbots_say(message):
    """Send a message (title, speech, emotion, color) to every listed Peerbots face."""
    global mute_until
    for channel in face_channels():
        try:
            response = requests.post(
                'https://api.peerbots.org/v1/publish',
                headers={'Accept': 'application/json', 'X-API-KEY': os.environ['PEERBOTS_API_KEY']},
                json={'channel': channel, 'message': {'type': 'message', **message}},
                timeout=20,
            )
            print(f'Sent to Peerbots ({channel}):', response.status_code, flush=True)
        except requests.RequestException as exc:
            print(f'Could not reach Peerbots ({channel}):', exc, flush=True)
    # Ignore the mic until the face has finished speaking.
    words = len(message['speech'].split())
    talk_time = SPEECH_START_DELAY + words / SPEECH_WORDS_PER_SECOND
    mute_until = time.time() + talk_time
    # When the face should be done talking, tell the phone to turn its mic back on.
    threading.Timer(talk_time, tell_phone, args=('listen',)).start()
    return talk_time


def tell_phone(text):
    """Send a short text message to every connected phone page."""
    if loop is None:
        return
    for ws in list(phone_sockets):
        asyncio.run_coroutine_threadsafe(ws.send_str(text), loop)

# ---------------- Speech handling ----------------

def process_utterance(pcm):
    """Transcribe what the user said, get the robot's reply, and act it out."""
    try:
        audio = sr.AudioData(pcm, SAMPLE_RATE, 2)
        text = recognizer.recognize_google(audio)
        print('Human said:', text, flush=True)
        with chat_lock:
            history_file = BASE / 'history.txt'
            history = json.loads(history_file.read_text())
            history.append({'role': 'user', 'content': text})
            completion = client.chat.completions.create(
                model=MODEL, messages=history, response_format={'type': 'json_object'})
            reply = completion.choices[0].message.content or ''
            print('Robot:', reply, flush=True)
            history.append({'role': 'assistant', 'content': reply})
            history_file.write_text(json.dumps(history, indent=2))
            try:
                message = json.loads(reply)
            except json.JSONDecodeError:
                message = {'title': 'Robot response', 'speech': reply,
                           'emotion': 'Neutral', 'color': 'Light Blue'}
            gesture = message.pop('gesture', 'none')
            if gesture not in GESTURES:
                gesture = 'none'
            message.setdefault('speech', '')
            talk_time = peerbots_say(message)
            gaze.robot_replies(message['speech'], gesture, talk_time, SPEECH_START_DELAY)
    except sr.UnknownValueError:
        print('Could not understand speech', flush=True)
        gaze.not_understood()
    except sr.RequestError as exc:
        print('Google speech recognition error:', exc, flush=True)
        gaze.not_understood()
    except Exception as exc:
        print('Processing error:', repr(exc), flush=True)
        gaze.not_understood()


def speech_worker():
    """Split the phone's audio stream into utterances using volume and pauses."""
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
        if time.time() < mute_until:
            pending, speaking, utterance, pre_roll = np.empty(0, dtype=np.int16), False, [], []
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
                    gaze.user_started_talking()
            else:
                utterance.append(frame.copy())
                if voiced:
                    speech_frames += 1
                    silent_frames = 0
                else:
                    silent_frames += 1
                if (silent_frames * FRAME_MS / 1000 >= SILENCE_SECONDS
                        or len(utterance) * FRAME_MS / 1000 >= MAX_UTTERANCE_SECONDS):
                    if speech_frames * FRAME_MS / 1000 >= MIN_SPEECH_SECONDS:
                        gaze.user_stopped_talking()
                        process_utterance(np.concatenate(utterance).astype('<i2').tobytes())
                    speaking = False
                    utterance = []
                    pre_roll = []
                    speech_frames = 0
                    silent_frames = 0


# ---------------- Web server for the phone ----------------

def valid_token(request):
    token = os.getenv('PEERBOTS_TOKEN')
    return bool(token) and request.query.get('token') == token


async def index(request):
    if not valid_token(request):
        raise web.HTTPForbidden(text='Invalid access token')
    return web.FileResponse(BASE / 'face.html')


async def websocket_handler(request):
    if not valid_token(request):
        raise web.HTTPForbidden(text='Invalid access token')
    ws = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=30)
    await ws.prepare(request)
    print('Phone microphone connected', flush=True)
    phone_sockets.add(ws)
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
        phone_sockets.discard(ws)
        print('Phone microphone disconnected', flush=True)
    return ws


async def remember_loop(app):
    global loop
    loop = asyncio.get_running_loop()


def main():
    for name in ('OPENAI_API_KEY', 'PEERBOTS_API_KEY', 'PEERBOTS_USERNAME'):
        if not os.environ.get(name):
            raise RuntimeError(f'Missing required setting: {name}')
    initialize_history()
    connect_arduino()
    gaze.now('attend', 'robot starts up', 'face the user')
    gaze.start_idle_glances()
    threading.Thread(target=speech_worker, daemon=True).start()
    app = web.Application()
    app.on_startup.append(remember_loop)
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
        print('No cert.pem/key.pem found, serving HTTP behind the tunnel')
    web.run_app(app, host='127.0.0.1', port=PORT, ssl_context=ssl_context)


if __name__ == '__main__':
    main()

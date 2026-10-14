# Peerbots Phone Microphone + GPT Robot Speech

Run on macOS, Windows or Linux. The phone only needs a modern browser; the Peerbots face remains full-screen. The browser captures microphone audio, sends it through a Cloudflare HTTPS tunnel to Python on the laptop, and Google speech recognition transcribes it. GPT generates a short spoken response and the **Peerbots API speaks it on the face**.

## Student setup

1. Obtain an OpenAI API key, a Peerbots API key (see https://api.peerbots.org/docs), and the Peerbots face username/email. Open the face and sign in to the matching Peerbots account as required.
2. On macOS, double-click `setup_and_run.command`; on Windows, double-click `setup_and_run.bat`; on Linux, run `bash setup_and_run.sh`.
3. Enter the keys and username when prompted. They are passed to the server as environment variables, not saved in the project files.
4. Open the displayed HTTPS URL on the phone, grant microphone access, and use the embedded Peerbots face.
5. Keep the laptop terminal running. Ctrl+C stops the session.

Python 3.9+ is required. The launcher creates a virtual environment, installs dependencies, downloads Cloudflare Tunnel, and starts the server. Installing Python itself may require a separate step if missing.

## What changed

- No NAO API or `^start(...)` animation tags.
- `server.py` posts `{'title': 'Robot response', 'speech': response}` to `https://api.peerbots.org/v1/send-message/{username}` with `X-API-KEY`, following Peerbots' official Python sample.
- `history.txt` and `response.txt` remain available; `listen.txt` is initialized for compatibility but no longer polled. Peerbots handles output directly.
- Google `speech_recognition.Recognizer().recognize_google()` is unchanged.

## Caveats

- The wrapper iframe was manually confirmed to display the face, but API delivery, browser audio capture, and complete installers still need testing with a real face and phone.
- The audio stream passes through Cloudflare Tunnel; Google and OpenAI also receive data as part of transcription and generation.
- Phone speakers may be picked up by the microphone, causing feedback/repeated robot speech. Reduce volume, use headphones for testing, or add microphone muting while the robot speaks.
- Keep the generated URL and API keys private. Free quick tunnels can be restricted by campus networks.
- If the face is not logged in to the account addressed by `PEERBOTS_USERNAME`, messages may not arrive.
- The browser must allow microphone access and the face iframe; behavior may vary by browser.

## Manual run

Set `OPENAI_API_KEY`, `PEERBOTS_API_KEY`, `PEERBOTS_USERNAME`, and `PEERBOTS_TOKEN` environment variables, install `requirements.txt`, then run `python server.py`. Serve it via a browser-trusted HTTPS tunnel.

Official sample: https://github.com/PEERbots/api-samples/blob/main/send_message.py

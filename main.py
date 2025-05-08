import os
import json
import base64
import asyncio
import datetime
import logging
from websockets.client import connect
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect as TwilioConnect
from dotenv import load_dotenv
from google.cloud import storage

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load env variables
load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME')
PORT = int(os.getenv('PORT', 5050))

# Goodbye detection keywords
BYE_KEYWORDS = ["bye", "goodbye", "see you", "talk to you later", "bye for now", "take care"]

# Assistant system config
SYSTEM_MESSAGE = (
    "You are a helpful and bubbly AI assistant who answers any questions I ask. "
    "Your answers should be brief, to the point, and avoid repeating what the user has already said."
)
VOICE = 'alloy'
LOG_EVENT_TYPES = [
    'response.content.done',
    'response.done',
    'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped',
    'input_audio_buffer.speech_started',
    'response.create',
    'session.created',
    'rate_limits.updated',
]

# FastAPI app and transcript state
app = FastAPI()
transcript_log = []

def timestamped_line(role, text):
    now = datetime.datetime.utcnow().strftime("%H:%M:%S")
    return f"[{now}] {role.upper()}: {text.strip()}"

def upload_transcript_to_gcs(text_lines):
    if not GCS_BUCKET_NAME:
        logger.warning("GCS_BUCKET_NAME is not configured.")
        return
    if not text_lines:
        logger.warning("Transcript is empty, skipping upload.")
        return
    timestamp = datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    file_name = f"recordings/conversation-{timestamp}.txt"
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(file_name)
    blob.upload_from_string('\n'.join(text_lines))
    logger.info(f"Transcript uploaded to GCS at gs://{GCS_BUCKET_NAME}/{file_name}")

@app.get("/", response_class=HTMLResponse)
async def index_page():
    return "<html><body><h1>Twilio Media Stream Server is running!</h1></body></html>"

# This endpoint handles incoming calls from Twilio. 
# When Twilio dials the number and your app is set as the webhook, it sends a request to this /incoming-call route. 
# The function responds with instructions on how Twilio should handle the call.
@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    logger.info("Received incoming call request from: %s", request.client.host)
    response = VoiceResponse()
    host = request.url.hostname
    connect = TwilioConnect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    await websocket.accept()  # Accept the WebSocket connection at the start
    logger.info("✅ WebSocket connection accepted")

    global transcript_log
    transcript_log = []

    async with connect(
        'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
    ) as openai_ws:
        await send_session_update(openai_ws)

        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None

        async def receive_from_twilio():
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media' and openai_ws.open:
                        latest_media_timestamp = int(data['media']['timestamp'])
                        await openai_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                    elif data['event'] == 'mark':
                        if mark_queue:
                            mark_queue.pop(0)
                    elif data['event'] == 'stop':
                        logger.info("📞 Call ended. Uploading transcript...")
                        upload_transcript_to_gcs(transcript_log)
                        if openai_ws.open:
                            await openai_ws.close()
                        return
            except WebSocketDisconnect:
                if openai_ws.open:
                    await openai_ws.close()
            except Exception as e:
                logger.error(f"Error in receive_from_twilio: {e}")

        async def send_to_twilio():
            user_speech_buffer = []
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)

                    if response['type'] in LOG_EVENT_TYPES:
                        print(f"🔹 {response['type']}", response)

                    if response.get('type') == 'response.audio.delta' and 'delta' in response:
                        try:
                            audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                            await websocket.send_json({
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": audio_payload}
                            })
                        except Exception as e:
                            logger.warning(f"Failed to send audio payload: {e}")

                        if response_start_timestamp_twilio is None:
                            response_start_timestamp_twilio = latest_media_timestamp
                        if response.get('item_id'):
                            last_assistant_item = response['item_id']
                        await send_mark(websocket, stream_sid)

                    if response.get('type') == 'response.done':
                        outputs = response.get('response', {}).get('output', [])
                        for item in outputs:
                            role = item.get('role', 'assistant')
                            for content_piece in item.get('content', []):
                                if content_piece.get('type') == 'audio' and content_piece.get('transcript'):
                                    transcript_text = content_piece['transcript']
                                    transcript_log.append(timestamped_line(role, transcript_text))

                                    # Goodbye detection
                                    if any(bye in transcript_text.lower() for bye in BYE_KEYWORDS):
                                        print("Goodbye detected. Ending call...")
                                        await websocket.send_json({
                                            "event": "media",
                                            "streamSid": stream_sid,
                                            "media": {"payload": "Goodbye, call me back if you need help."}
                                        })
                                        await websocket.send_json({
                                            "event": "stop", 
                                            "streamSid": stream_sid
                                        })
                                        upload_transcript_to_gcs(transcript_log)  # Upload the transcript
                                        await openai_ws.close()  # Close OpenAI WebSocket
                                        await websocket.close()  # Close Twilio WebSocket
                                        return  # End the call

                        user_input = response.get('input', {})
                        if user_input.get('transcript'):
                            print("Inferred user said:", user_input['transcript'])
                            transcript_log.append(timestamped_line("user", user_input['transcript']))

                    if response.get('type') == 'input.audio.text':
                        user_text = response.get('text')
                        if user_text:
                            user_speech_buffer.append(user_text.strip())

                    if response.get('type') == 'input_audio_buffer.speech_stopped':
                        if user_speech_buffer:
                            full_user_speech = ' '.join(user_speech_buffer)
                            print("Final user speech:", full_user_speech)
                            transcript_log.append(timestamped_line("user", full_user_speech))
                            user_speech_buffer.clear()

                    if response.get('type') == 'input_audio_buffer.committed':
                        transcript_log.append(timestamped_line("user", "[Speech committed]"))

                    if response.get('type') == 'input_audio_buffer.speech_started':
                        if last_assistant_item:
                            await handle_speech_started_event()
            except Exception as e:
                logger.error(f"Error in send_to_twilio: {e}")

        async def handle_speech_started_event():
            nonlocal response_start_timestamp_twilio, last_assistant_item
            if mark_queue and response_start_timestamp_twilio is not None:
                elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                if last_assistant_item:
                    await openai_ws.send(json.dumps({
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed_time
                    }))
                await websocket.send_json({"event": "clear", "streamSid": stream_sid})
                mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, stream_sid):
            if stream_sid:
                await connection.send_json({
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "responsePart"}
                })
                mark_queue.append('responsePart')

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def send_initial_conversation_item(openai_ws):
    await openai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Greet the user with 'Hello!, how are you doing today?'"}]
        }
    }))
    await openai_ws.send(json.dumps({"type": "response.create"}))


async def send_session_update(openai_ws):
    await openai_ws.send(json.dumps({
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad", "threshold": 0.3, "silence_duration_ms": 400},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": SYSTEM_MESSAGE,
            "modalities": ["text", "audio"],
            "temperature": 0.8
        }
    }))
    await send_initial_conversation_item(openai_ws)


if __name__ == "__main__":
    import uvicorn
    print(f"\n🚀 Server running on http://localhost:{PORT}")
    print(f"⚠️  Make sure to run ngrok:   ngrok http {PORT}\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT)

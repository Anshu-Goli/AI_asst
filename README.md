
# Voice AI Assistant

This project builds a **Voice AI Assistant** that processes incoming voice calls using **Twilio**, performs real-time speech-to-text and conversation via **OpenAI GPT-4**, and saves conversation transcripts to **Google Cloud Storage (GCS)**. It also includes functionality to detect goodbye phrases and gracefully end the call.

## Project Overview

- **Twilio** is used for handling incoming calls and streaming audio.
- **OpenAI's GPT-4** (Real-time API) is used for processing the conversation, generating responses, and transcribing speech.
- **Google Cloud Storage** (GCS) is used to save conversation transcripts after the call ends.
- The **FastAPI** framework is used to build the backend API and WebSocket connections.
- **Goodbye detection** is implemented to hang up the call when the user says goodbye.

---

## Prerequisites

Before running this project, make sure you have the following installed:

1. **Python 3.x**: Install from [here](https://www.python.org/downloads/).
2. **Google Cloud SDK**: Follow instructions to install [Google Cloud SDK](https://cloud.google.com/sdk/docs/install).
3. **ngrok**: Used to expose your local server to the internet. Install it from [here](https://ngrok.com/download).
4. **Twilio Account**: Sign up for a [Twilio account](https://www.twilio.com/), get a phone number, and obtain the Twilio Account SID and Auth Token.
5. **OpenAI API Key**: Create an account on [OpenAI](https://platform.openai.com/signup) and get your API key.

---

## Setup

### 1. Install Dependencies

Clone this repository and install the required packages.

```bash
git clone https://github.com/repo-name/project_name.git
cd project_name
pip install -r requirements.txt
```

### 2. Set up Environment Variables

Create a `.env` file in the root directory and add the following environment variables:

```plaintext
OPENAI_API_KEY=your-openai-api-key
GCS_BUCKET_NAME=your-gcs-bucket-name
PORT=5050
TWILIO_ACCOUNT_SID=your-twilio-account-sid
TWILIO_AUTH_TOKEN=your-twilio-auth-token
TWILIO_PHONE_NUMBER=your-twilio-phone-number
```

- **OPENAI_API_KEY**: Your OpenAI API key for accessing GPT-4.
- **GCS_BUCKET_NAME**: The name of your Google Cloud Storage bucket for storing transcripts.
- **PORT**: The port number for the FastAPI server.
- **TWILIO_ACCOUNT_SID** and **TWILIO_AUTH_TOKEN**: These are your Twilio credentials.
- **TWILIO_PHONE_NUMBER**: The Twilio phone number you’ll use to handle incoming calls.

### 3. Configure Google Cloud Storage

Ensure that your **Google Cloud Storage** bucket is set up and that the service account JSON key is correctly configured for access. You may need to authenticate using the `google-cloud` SDK by running:

```bash
gcloud auth activate-service-account --key-file=path-to-your-service-account-key.json
```

---

## Running the Application

### 1. Start the Application

Run the FastAPI application locally with `uvicorn`.

```bash
python main.py
```

Alternatively, you can run the following command to run the app directly with **Uvicorn**:

```bash
uvicorn main:app --host 0.0.0.0 --port 5050 --loop asyncio
```

### 2. Expose Your Local Server with ngrok

Since this project handles Twilio requests that need to hit your local server, you’ll need to expose your local server to the internet using **ngrok**.

Start an ngrok tunnel for the port you're running on (default is 5050):

```bash
ngrok http 5050
```

ngrok will give you a public URL that you will use to configure Twilio.

### 3. Configure Twilio Webhook

Go to your **Twilio Console**, and in the **Phone Numbers** section, find your phone number. Under the **Voice & Fax** section, set the **A Call Comes In** webhook to the following URL:

```
http://<ngrok-url>/incoming-call
```

This URL should point to the `/incoming-call` route in your FastAPI app.

---

## How It Works

### 1. **Incoming Call Handling**

When someone calls your Twilio phone number, Twilio sends a request to the `/incoming-call` route of your FastAPI server. The server generates a `VoiceResponse` object and connects to the **media stream** (real-time audio) from the Twilio API using WebSockets.

### 2. **Real-Time Audio Streaming**

The audio from the call is streamed via WebSockets to the OpenAI real-time API. The audio is transcribed using OpenAI’s **Whisper** model for speech-to-text and processed by **GPT-4** to generate a response.

- The audio is sent to OpenAI.
- OpenAI processes the text and generates a response.
- The response is converted into audio and sent back to Twilio.

### 3. **Goodbye Detection and Call Hang-up**

The application listens for specific goodbye phrases like "bye", "goodbye", etc., from the user. If one of these phrases is detected, the application sends a message to Twilio to gracefully end the call, saying "Goodbye, call me back if you need help."

### 4. **Transcript Logging**

Every time a new message is transcribed or an assistant response is generated, the system logs the text into the `transcript_log` list. When the call ends, the transcript is uploaded to Google Cloud Storage.

---

## Handling Errors and Logs

- **Logs**: The application uses Python's logging module to log various events, including errors, information about the call, and the detected goodbye phrases.
- **WebSocket Errors**: If there are issues with the WebSocket connection, errors will be logged, and the system will attempt to recover.

---

## Troubleshooting

1. **GCS Bucket Issues**:
   - Ensure your **Google Cloud Storage** bucket is correctly set up.
   - Make sure that the **service account** has the correct permissions (e.g., `storage.objects.create`).
   - Verify that the environment variable `GCS_BUCKET_NAME` is set correctly in your `.env` file.

2. **Twilio Webhook Issues**:
   - Double-check that ngrok is running and the URL is correctly set in the Twilio Console.
   - Make sure that your FastAPI app is running and accessible from the internet via the ngrok URL.

---

## Conclusion

This project sets up a simple yet powerful **Voice AI Assistant** capable of handling incoming calls, processing audio in real-time, generating responses using OpenAI's GPT-4, and logging the conversation to Google Cloud Storage. You can extend this to integrate with other services or add more sophisticated features like authentication or user-specific dialogues.

Let me know if you need further assistance!

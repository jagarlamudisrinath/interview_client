import queue
import re
import sys
import time
import requests
from google.oauth2 import service_account
from google.cloud import speech
import pyaudio
import urllib.parse

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms
STREAM_DURATION_LIMIT = 300  # Limit stream duration to 300 seconds (5 minutes)

class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(self: object, rate: int = RATE, chunk: int = CHUNK) -> None:
        """Initialize parameters and buffers."""
        self._rate = rate
        self._chunk = chunk
        self._buff = queue.Queue()
        self.closed = True
        self.start_time = None

    def __enter__(self: object) -> object:
        """Open the audio stream."""
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )
        self.start_time = time.time()
        self.closed = False
        return self

    def __exit__(self: object, type: object, value: object, traceback: object) -> None:
        """Close the audio stream."""
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self: object, in_data: object, frame_count: int, time_info: object, status_flags: object) -> object:
        """Collect data from the audio stream."""
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self: object) -> object:
        """Generate audio chunks from the stream."""
        while not self.closed:
            if time.time() - self.start_time > STREAM_DURATION_LIMIT:
                return  # Restart the stream if the duration limit is exceeded
            
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break

            yield b"".join(data)

def send_text_to_backend(transcript: str):
    """Send transcribed text to backend API and handle streaming response."""
    api_url = "http://localhost:8000/api/v1/interviews/1/start"
    headers = {'Content-Type': 'application/json'}
    payload = {'Question': transcript}  # Include the transcript in the payload

    try:
        if transcript != "":
            print("Sending text to backend: ", transcript)
            
            # Send a POST request with stream=True to handle streaming responses
            response = requests.post(api_url, headers=headers, json=payload, stream=True)
            response.raise_for_status()  # Raise an exception for HTTP errors
            
            # Process the streaming response
            current_text = ""
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    # Decode the chunk and append to current text
                    decoded_chunk = chunk.decode('utf-8')
                    current_text += decoded_chunk
                    # Print the updated text on the same line
                    sys.stdout.flush()
                    sys.stdout.write(f"\r{current_text}")
                      # Ensure the output is written to the terminal

    except requests.RequestException as e:
        print(f"Error sending request to backend: {e}")


def listen_print_loop(responses: object) -> str:
    """Process server responses and print them."""
    num_chars_printed = 0
    for response in responses:
        if not response.results:
            continue

        result = response.results[0]
        if not result.alternatives:
            continue

        transcript = result.alternatives[0].transcript
        overwrite_chars = " " * (num_chars_printed - len(transcript))

        if not result.is_final:
            sys.stdout.write(transcript + overwrite_chars + "\r")
            sys.stdout.flush()
            num_chars_printed = len(transcript)

        else:
            sys.stdout.write(transcript + overwrite_chars + "\n")
            sys.stdout.flush()

            # Call the API with the transcribed text
            send_text_to_backend(transcript)

            if re.search(r"\b(exit|quit)\b", transcript, re.I):
                print("Exiting..")
                break

            num_chars_printed = 0
    return transcript

def main() -> None:
    """Transcribe speech from audio and send to backend."""
    language_code = "en-US"
    client_file = '/Users/srinathjagarlamudi/PycharmProjects/ai-interviewee/xenon-poet-422719-t4-a4b630469f42.json'
    credentials = service_account.Credentials.from_service_account_file(client_file)

    client = speech.SpeechClient(credentials=credentials)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code=language_code,
    )

    streaming_config = speech.StreamingRecognitionConfig(
        config=config, interim_results=True
    )

    while True:
        with MicrophoneStream(RATE, CHUNK) as stream:
            audio_generator = stream.generator()
            requests = (
                speech.StreamingRecognizeRequest(audio_content=content)
                for content in audio_generator
            )

            responses = client.streaming_recognize(streaming_config, requests)

            listen_print_loop(responses)

if __name__ == "__main__":
    main()

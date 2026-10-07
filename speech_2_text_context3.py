from mistralai.client import Mistral
from mistralai.client.models import (
    AudioFormat,
    RealtimeTranscriptionError,
    RealtimeTranscriptionSessionCreated,
    TranscriptionStreamDone,
    TranscriptionStreamTextDelta,
    File,
)
#from mistralai.models.chat_completion import ChatMessage

from pydub import AudioSegment
import wave
import os
import asyncio
import sys
from typing import AsyncIterator
import io
import datetime
import pyaudio
import numpy as np

from typing import List, Dict, Optional

# Configuration
api_key = "--------------------------"
client = Mistral(api_key=api_key)
audio_format = AudioFormat(encoding="pcm_s16le", sample_rate=16000)

# Vocabulaire personnalisé
custom_vocabulary = [
    "AIForMe",
    "Lhospitalier",
    "acronyme",
    "Marthuret"
]

def find_domain(phrase: str) -> str:
    global client
# Configuration des messages
    messages = [
        {
            "role":"system",
            "content":"Tu es un expert en classification de textes. Ton rôle est de déterminer à quel domaine appartient une phrase parmi les suivants : pastoral, théologique, automatisation de la maison, astronomie, informatique, médecine, droit, économie, littérature, histoire, géographie, biologie, physique, chimie, arts, musique, sport, politique, philosophie, psychologie, sociologie. Réponds uniquement avec les 3 nom de domaine les plus pertinents, sans explication."
        },
        {
            "role":"user",
            "content":f"À quel domaine appartient la phrase suivante : '{phrase}' ?"
        }
    ]

    # Appel à l'API
    response = client.chat.complete(
        model="mistral-tiny",
        messages=messages,
        temperature=0.0,  # Réponse déterministe
        max_tokens=20
    )
    # Affichage du domaine
    domaine = response.choices[0].message.content.strip()
    print(f"Domaine de la phrase : {domaine}")
    return domaine

# Buffer pour stocker les chunks audio
current_phrase_audio = io.BytesIO()
phrase = ""
output_dir = "recorded_phrases"
os.makedirs(output_dir, exist_ok=True)

async def iter_microphone(*, sample_rate: int, chunk_duration_ms: int) -> AsyncIterator[bytes]:
    """Yield microphone PCM chunks using PyAudio (16-bit mono)."""
    p = pyaudio.PyAudio()
    chunk_samples = int(sample_rate * chunk_duration_ms / 1000)

    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=sample_rate,
        input=True,
        frames_per_buffer=chunk_samples,
    )

    loop = asyncio.get_running_loop()
    try:
        while True:
            data = await loop.run_in_executor(None, stream.read, chunk_samples, False)
            yield data
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

def save_phrase_to_mp3_and_get_wav(audio_buffer: io.BytesIO, phrase_text: str) -> tuple[str, bytes]:
    """
    Sauvegarde en MP3 ET retourne les données au format WAV pour l'API.
    """
    audio_buffer.seek(0)
    pcm_data = audio_buffer.read()

    # Sauvegarder en MP3 (pour usage local)
    audio_segment = AudioSegment(
        data=pcm_data,
        sample_width=2,  # 16 bits
        frame_rate=16000,
        channels=1,
    )
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_phrase = "".join(c if c.isalnum() else "_" for c in phrase_text[:20])
    mp3_filename = f"{timestamp}_{safe_phrase}.mp3"
    mp3_path = os.path.join(output_dir, mp3_filename)
    print(mp3_path)
    audio_segment.export(mp3_path, format="mp3", bitrate="64k")

    # Créer un fichier WAV en mémoire pour l'API
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16 bits
        wav_file.setframerate(16000)
        wav_file.writeframes(pcm_data)
    wav_data = wav_buffer.getvalue()
    print("Returning wav")
    return mp3_path, wav_data

async def transcribe_batch(wav_data: bytes) -> str:
    """Transcription batch avec vocabulaire personnalisé."""
    try:
        audio_file = File(
            content=wav_data,
            file_name="temp_audio.wav"  # Format WAV pour l'API
        )
        print("Calling batch transcription")
        response = client.audio.transcriptions.complete(
            model="voxtral-mini-latest",
            file=audio_file,
            context_bias=custom_vocabulary,
            language="fr",
        )
        return response.text
    except Exception as e:
        print(f"\nErreur transcription batch: {e}")
        return ""

async def process_audio_stream():
    global phrase, current_phrase_audio

    async def audio_with_buffer():
        global current_phrase_audio
        async for chunk in iter_microphone(
            sample_rate=audio_format.sample_rate, chunk_duration_ms=480
        ):
            current_phrase_audio.write(chunk)
            yield chunk

    try:
        async for event in client.audio.realtime.transcribe_stream(
            audio_stream=audio_with_buffer(),
            model="voxtral-mini-transcribe-realtime-2602",
            audio_format=audio_format,
        ):
            if isinstance(event, RealtimeTranscriptionSessionCreated):
                print("Session created.")
            elif isinstance(event, TranscriptionStreamTextDelta):
                if event.text in ['.', '!', '?']:
                    print()
                    full_phrase = phrase + event.text
                    print(f"Phrase complète (temps réel): {full_phrase}")

                    if current_phrase_audio.tell() > 0:
                        # Sauvegarder en MP3 et obtenir les données WAV
                        mp3_path, wav_data = save_phrase_to_mp3_and_get_wav(
                            current_phrase_audio, full_phrase
                        )
                        print(f"🎵 Fichier MP3 enregistré : {mp3_path}")
                        print("Recherche du domaine")
                        result = find_domain(phrase)
                        print(f"Domaine détecté: {result}")

                        # Transcription batch avec les données WAV
                        print("\n[Transcription batch en cours...]")
                        batch_result = await transcribe_batch(wav_data)
                        print(f"[Transcription batch]: {batch_result}\n")

                    if phrase.lower() in ["arrêt", "stop"]:
                        sys.exit(0)

                    phrase = ""
                    current_phrase_audio = io.BytesIO()
                else:
                    phrase += str(event.text)
                    print(str(event.text), end="", flush=True)
            elif isinstance(event, TranscriptionStreamDone):
                print("Transcription done.")
            elif isinstance(event, RealtimeTranscriptionError):
                print(f"Error: {event}")
    except KeyboardInterrupt:
        print("\nStopping...")

async def main():
    await process_audio_stream()

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))




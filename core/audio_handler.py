"""
Audio Handler for Dual-Pass AI Agent
Handles Text-to-Speech (TTS) via edge-tts and Speech-to-Text (STT) via SpeechRecognition
"""
import os
import pygame
import speech_recognition as sr
from langdetect import detect
from edge_tts import Communicate
import asyncio
import tempfile

class AudioHandler:
    def __init__(self):
        # Initialize pygame mixer for audio playback
        pygame.mixer.init()
        self.recognizer = sr.Recognizer()

    def speak(self, text: str):
        """
        Detects language and speaks the text using edge-tts.
        Blocks until audio finishes playing.
        """
        if not text.strip():
            return

        try:
            # Clean text to remove any thinking tags or markdown before speaking
            import re
            clean_text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
            clean_text = re.sub(r'\[THINK\].*?\[/THINK\]', '', clean_text, flags=re.DOTALL)
            clean_text = re.sub(r'[*_`]', '', clean_text)
            clean_text = clean_text.strip()
            
            if not clean_text:
                return

            lang = detect(clean_text)
            # Default to English Aria if not Turkish
            voice = "tr-TR-EmelNeural" if lang == 'tr' else "en-US-AriaNeural"
            
            print(f"[AUDIO] Speaking {len(clean_text)} chars in {voice}...")
            
            # Run Edge TTS asynchronously to generate audio file
            temp_file = os.path.join(tempfile.gettempdir(), "agent_response.mp3")
            asyncio.run(self._generate_audio(clean_text, voice, temp_file))
            
            # Play the audio file
            pygame.mixer.music.load(temp_file)
            pygame.mixer.music.play()
            
            # Wait for audio to finish
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
                
            pygame.mixer.music.unload()
            try:
                os.remove(temp_file)
            except Exception:
                pass
                
        except Exception as e:
            print(f"[AUDIO ERROR] TTS failed: {e}")

    async def _generate_audio(self, text, voice, output_file):
        communicate = Communicate(text, voice)
        await communicate.save(output_file)

    def listen(self) -> str:
        """
        Listens to the microphone and converts speech to text.
        Returns the recognized text or empty string on failure.
        """
        with sr.Microphone() as source:
            print("\n[AUDIO] Adjusting for ambient noise... Please wait.")
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
            print("[AUDIO] Listening... (Speak now)")
            
            try:
                # Listen for speech
                audio = self.recognizer.listen(source, timeout=10, phrase_time_limit=15)
                print("[AUDIO] Processing speech...")
                
                # Recognize speech using Google Speech Recognition
                # We can't auto-detect language reliably from raw audio without an API,
                # so we try to recognize in both languages or fallback to English config
                # Actually, trying Turkish first since the user prefers it, 
                # but let's just stick to default or a configured language.
                # It accepts tr-TR and en-US. We will try Google's auto/default.
                text = self.recognizer.recognize_google(audio, language="tr-TR")
                
                print(f"[AUDIO] Recognized: {text}")
                return text
                
            except sr.WaitTimeoutError:
                print("[AUDIO ERROR] No speech detected.")
                return ""
            except sr.UnknownValueError:
                print("[AUDIO ERROR] Could not understand audio.")
                return ""
            except sr.RequestError as e:
                print(f"[AUDIO ERROR] Could not request results; {e}")
                return ""
            except Exception as e:
                print(f"[AUDIO ERROR] Unexpected error: {e}")
                return ""

# Global instance
handler = AudioHandler()

def speak(text: str):
    handler.speak(text)

def listen() -> str:
    return handler.listen()

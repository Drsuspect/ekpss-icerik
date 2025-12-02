import asyncio
import edge_tts

# Replace with simple Turkish text. If this works, test with different texts.
text = "Merhaba, bu bir test konuşmasıdır."
voice = "tr-TR-AhmetNeural"

async def generate_audio():
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save("output_test.mp3")
    print("Audio saved as output_test.mp3")

if __name__ == "__main__":
    try:
        asyncio.run(generate_audio())
    except Exception as e:
        print("Ses oluşturma hatası:", e)
"""Quick mic test - record 2 seconds and check signal."""
import sounddevice as sd
import numpy as np

print("Recording 2 seconds... speak now!")
audio = sd.rec(int(2 * 16000), samplerate=16000, channels=1, dtype="int16")
sd.wait()
rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
maxamp = int(np.max(np.abs(audio)))
dev = sd.query_devices(sd.default.device[0])
print(f"Device: {dev['name']}")
print(f"RMS: {rms:.1f}, Max amplitude: {maxamp}")
if rms < 10:
    print("WARNING: Microphone appears SILENT -- OS-level issue")
elif rms < 200:
    print(f"Mic works but quiet (RMS={rms:.0f}). MIN_ENERGY_RMS is 200.")
else:
    print("Microphone is working fine!")

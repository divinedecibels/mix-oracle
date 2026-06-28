from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from pymongo import MongoClient
import uvicorn
import librosa
import pyloudnorm as pyln
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly
import time
import uuid
import os
import secrets
import bcrypt
import json
import asyncio
from dotenv import load_dotenv, find_dotenv
from google import genai
from google.oauth2 import id_token
from google.auth.transport import requests

# Load environment variables
load_dotenv(find_dotenv())

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

client_db = MongoClient(os.getenv("MONGO_URI")) 
db = client_db["mix_oracle"]
users_collection = db["users"]

def load_users():
    # Returns a dictionary for easy login checking
    return {u["email"]: u for u in users_collection.find()}

def save_users(users):
    # This logic changes slightly; instead of a full save, 
    # we just insert a new user document
    pass # You will now use users_collection.insert_one() in register()

# Email Configuration
conf = ConnectionConfig(
    MAIL_USERNAME = "divinedecibels@gmail.com",
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD"),
    MAIL_FROM = "divinedecibels@gmail.com",
    MAIL_PORT = 587,
    MAIL_SERVER = "smtp.gmail.com",
    MAIL_STARTTLS = True,
    MAIL_SSL_TLS = False,
    USE_CREDENTIALS = True,
    VALIDATE_CERTS = True
)

os.makedirs("temp_uploads", exist_ok=True)
app = FastAPI(title="Mix Oracle API")

# Rate Limiting Setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Secure CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",           # Local development
        "https://mixoracle.com",          # Replace with your actual production domain
        "https://www.mixoracle.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Auth & Lead Generation ---
class AuthUser(BaseModel):
    email: str
    password: str
    name: str = ""
    code: str = ""

class OTPRequest(BaseModel):
    email: str

LEADS_FILE = "leads.json"
OTP_STORE: dict = {} # { email: (code, expiry_timestamp) }

def load_users():
    if not os.path.exists(LEADS_FILE):
        return {}
    with open(LEADS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(LEADS_FILE, "w") as f:
        json.dump(users, f, indent=4)

@app.post("/auth/send-code")
async def send_verification_code(req: OTPRequest):
    users = load_users()
    if req.email in users:
        raise HTTPException(status_code=400, detail="Email already registered. Please log in.")
        
    code = str(secrets.randbelow(900000) + 100000)
    OTP_STORE[req.email] = (code, time.time() + 600) # 10 minute expiry
    
    try:
        msg = MessageSchema(
            subject="Your Mix Oracle Verification Code",
            recipients=[req.email],
            body=f"Your verification code is: {code}\n\nWelcome to Mix Oracle by Divine Decibels!",
            subtype="plain"
        )
        fm = FastMail(conf)
        await fm.send_message(msg)
        return {"status": "success", "message": "Code sent!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to send email.")

@app.post("/auth/register")
async def register(user: AuthUser):
    users = load_users()
    if user.email in users:
        raise HTTPException(status_code=400, detail="Email already registered.")
        
    if user.email not in OTP_STORE:
        raise HTTPException(status_code=400, detail="No code sent. Request a new one.")
        
    stored_code, expiry = OTP_STORE[user.email]
    
    if time.time() > expiry:
        del OTP_STORE[user.email]
        raise HTTPException(status_code=400, detail="Code expired. Request a new one.")
        
    if stored_code != user.code:
        raise HTTPException(status_code=400, detail="Invalid verification code.")
        
    hashed = bcrypt.hashpw(user.password.encode("utf-8"), bcrypt.gensalt())
    users[user.email] = {"password": hashed.decode("utf-8"), "name": user.name}
    save_users(users)
    del OTP_STORE[user.email]
    
    return {"status": "success", "message": "Account created!"}

@app.post("/auth/login")
async def login(user: AuthUser):
    users = load_users()
    if user.email not in users:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    stored_hash = users[user.email]["password"].encode("utf-8")
    if not bcrypt.checkpw(user.password.encode("utf-8"), stored_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    return {"status": "success"}

# --- Google OAuth ---
class GoogleAuthRequest(BaseModel):
    token: str

def verify_google_token(token: str):
    if not GOOGLE_CLIENT_ID:
        return None
    try:
        id_info = id_token.verify_oauth2_token(token, requests.Request(), GOOGLE_CLIENT_ID)
        return id_info
    except ValueError:
        return None

@app.post("/auth/google")
async def auth_google(payload: GoogleAuthRequest):
    token = payload.token
    user_info = verify_google_token(token)
    
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    
    users = load_users()
    email = user_info['email']
    name = user_info.get('name', email.split('@')[0])
    
    if email not in users:
        users[email] = {"password": "", "name": name}
        save_users(users)
    
    return {"status": "success", "email": email, "name": name}

# --- Endpoints ---
@app.post("/request-service")
async def request_service(name: str = Form(...), email: str = Form(...), message: str = Form(...)):
    try:
        msg = MessageSchema(
            subject="New Mix & Master Request from Mix Oracle",
            recipients=["divinedecibels@gmail.com"],
            body=f"From: {name} ({email})\n\nMessage:\n{message}",
            subtype="plain"
        )
        fm = FastMail(conf)
        await fm.send_message(msg)
        return {"status": "success"}
    except Exception as e:
        error_msg = f"Error sending email: {str(e)}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/upload")
@limiter.limit("10/minute")
async def upload_file(request: Request, file: UploadFile = File(...)):
    MAX_SIZE = 100 * 1024 * 1024 # 100MB Limit
    content = await file.read()
    
    if len(content) > MAX_SIZE:
        raise HTTPException(400, detail="File too large. Maximum size is 100MB.")
        
    file_id = str(uuid.uuid4())
    file_path = os.path.join("temp_uploads", f"{file_id}_{file.filename}")
    
    with open(file_path, "wb") as buffer:
        buffer.write(content)
        
    return {"file_id": file_id, "filename": file.filename}

# --- DSP Math Helpers ---
def calculate_true_correlation(L, R):
    mid = L + R
    side = L - R
    rms_mid = np.sqrt(np.mean(mid**2) + 1e-10)
    rms_side = np.sqrt(np.mean(side**2) + 1e-10)
    if (rms_mid + rms_side) == 0: return 1.0
    return float((rms_mid - rms_side) / (rms_mid + rms_side))

def get_band_correlation(y_stereo, sr, lowcut, highcut):
    nyq = 0.5 * sr
    if lowcut == 0:
        sos = butter(4, highcut / nyq, btype='low', output='sos')
    elif highcut >= nyq:
        sos = butter(4, lowcut / nyq, btype='high', output='sos')
    else:
        sos = butter(4, [lowcut / nyq, highcut / nyq], btype='band', output='sos')
    
    l_filt = sosfilt(sos, y_stereo[0])
    r_filt = sosfilt(sos, y_stereo[1])
    return calculate_true_correlation(l_filt, r_filt)

def fast_true_peak(y_flat: np.ndarray, sr: int) -> float:
    chunk = int(sr * 2)
    if len(y_flat) <= chunk * 3:
        ovs = resample_poly(y_flat, 4, 1)
        return round(20 * np.log10(np.max(np.abs(ovs)) + 1e-12), 1)

    n = len(y_flat) // chunk
    ranked = sorted([(np.max(np.abs(y_flat[i * chunk:(i + 1) * chunk])), i) for i in range(n)], reverse=True)

    max_tp = -100.0
    for _, i in ranked[:3]:
        seg = y_flat[i * chunk:(i + 1) * chunk]
        ovs = resample_poly(seg, 4, 1)
        tp  = 20 * np.log10(np.max(np.abs(ovs)) + 1e-12)
        max_tp = max(max_tp, tp)

    return round(max_tp, 1)

# --- Core Analyzer ---
def analyze_audio(y: np.ndarray, sr: int):
    is_stereo = y.ndim == 2
    if is_stereo:
        if y.shape[0] != 2:
            y = y.T
        is_stereo = y.shape[0] == 2
    
    y_stereo = y if is_stereo else np.vstack((y, y))
    y_mono = librosa.to_mono(y_stereo)

    meter = pyln.Meter(sr) 
    y_transposed = y_stereo.T 
    lufs = meter.integrated_loudness(y_transposed)
    true_peak_db = fast_true_peak(y_transposed.flatten(), sr)
    plr = true_peak_db - lufs
    dc_offset = float(np.mean(y_mono))
    
    if is_stereo:
        rms_l = 20 * np.log10(np.sqrt(np.mean(y_stereo[0]**2)) + 1e-10)
        rms_r = 20 * np.log10(np.sqrt(np.mean(y_stereo[1]**2)) + 1e-10)
        lr_balance_diff = round(abs(rms_l - rms_r), 2)
    else:
        lr_balance_diff = 0.0

    n_blocks = len(y_mono) // sr
    if n_blocks > 0:
        blocks = np.array_split(y_mono[:n_blocks*sr], n_blocks)
        block_rms = [np.sqrt(np.mean(b**2)) for b in blocks]
        block_db = [20 * np.log10(rms + 1e-10) for rms in block_rms]
        macro_dynamics = np.percentile(block_db, 95) - np.percentile(block_db, 5)
    else:
        macro_dynamics = 0.0

    overall_corr = calculate_true_correlation(y_stereo[0], y_stereo[1])
    low_corr = get_band_correlation(y_stereo, sr, 0, 150)
    high_corr = get_band_correlation(y_stereo, sr, 5000, sr/2)

    D = np.abs(librosa.stft(y_mono, n_fft=4096))
    magnitudes = librosa.amplitude_to_db(np.mean(D, axis=1), ref=np.max)
    frequencies = librosa.fft_frequencies(sr=sr, n_fft=4096)
    
    valid_idx = np.where((frequencies >= 20) & (frequencies <= 20000))
    freqs_filtered = frequencies[valid_idx]
    mags_filtered = magnitudes[valid_idx]
    
    target_freqs = np.geomspace(20, 20000, num=100)
    indices = [np.argmin(np.abs(freqs_filtered - f)) for f in target_freqs]

    mono_signal = (y_stereo[0] + y_stereo[1]) / 2.0
    rms_l = np.sqrt(np.mean(y_stereo[0]**2) + 1e-12)
    rms_r = np.sqrt(np.mean(y_stereo[1]**2) + 1e-12)
    rms_stereo = np.sqrt((rms_l**2 + rms_r**2) / 2.0)
    rms_mono = np.sqrt(np.mean(mono_signal**2) + 1e-12)
    mono_compatibility = round(20 * np.log10(rms_mono / rms_stereo), 1)

    block_size = 4 * sr
    n_timeline_blocks = len(y_mono) // block_size
    loudness_timeline = []
    
    if n_timeline_blocks > 0:
        blocks = np.array_split(y_mono[:n_timeline_blocks*block_size], n_timeline_blocks)
        for i, b in enumerate(blocks):
            rms = np.sqrt(np.mean(b**2) + 1e-12)
            db = 20 * np.log10(rms)
            loudness_timeline.append(round(db, 1))

    dr_block_size = 3 * sr
    n_dr_blocks = len(y_mono) // dr_block_size
    dr = 0.0
    if n_dr_blocks > 0:
        dr_blocks = np.array_split(y_mono[:n_dr_blocks*dr_block_size], n_dr_blocks)
        dr_block_peaks = []
        for b in dr_blocks:
            block_rms = np.sqrt(np.mean(b**2))
            dr_block_peaks.append(20 * np.log10(block_rms + 1e-12))
        if len(dr_block_peaks) >= 5:
            top_blocks = sorted(dr_block_peaks, reverse=True)[:max(1, len(dr_block_peaks) // 5)]
            dr = round(np.percentile(top_blocks, 50) - np.percentile(dr_block_peaks, 50), 1)

    return {
        "metrics": {
            "lufs": round(lufs, 1),
            "true_peak": round(true_peak_db, 1),
            "correlation": round(overall_corr, 2),
            "plr": round(plr, 1),
            "dr": dr,
            "low_correlation": round(low_corr, 2),
            "high_correlation": round(high_corr, 2),
            "dc_offset": dc_offset,
            "lr_balance": round(lr_balance_diff, 2),
            "macro_dynamics": round(macro_dynamics, 1),
            "mono_compatibility": round(mono_compatibility, 1),
            "loudness_timeline": loudness_timeline
        },
        "spectrum": {"frequencies": freqs_filtered[indices].tolist(), "magnitudes": mags_filtered[indices].tolist()},
        "raw_mags": mags_filtered, "raw_freqs": freqs_filtered
    }

def generate_diagnostics(metrics, raw_mags, raw_freqs, genre):
    issues = []
    
    def get_band_energy(low_f, high_f):
        idx = np.where((raw_freqs >= low_f) & (raw_freqs <= high_f))
        if len(idx[0]) == 0: return -100.0
        linear_amps = 10 ** (raw_mags[idx] / 20)
        mean_power  = np.mean(linear_amps ** 2)
        return 10 * np.log10(mean_power + 1e-12)

    sub = get_band_energy(20, 60)
    bass = get_band_energy(60, 250)
    mud = get_band_energy(250, 500)
    mid = get_band_energy(500, 2000)
    harsh = get_band_energy(2000, 5000)
    high_mids = get_band_energy(10000, 15000)
    ultra_highs = get_band_energy(16000, 20000)

    dyn_crushed_limit = 5.0 if genre == "EDM / Hip-Hop" else 8.0 if genre == "Acoustic / Jazz" else 7.0
    sub_allowance = 6.0 if genre == "EDM / Hip-Hop" else 3.0

    if abs(metrics["dc_offset"]) > 0.005: issues.append({"id": "dc_offset", "priority": "FIX NOW", "title": "DC Offset Detected", "body": "Waveform is not centered at zero. This causes asymmetrical limiting.", "action": "Apply a high-pass filter at 10Hz to your master bus."})
    if metrics["lr_balance"] > 1.5: issues.append({"id": "lr_imbalance", "priority": "REVIEW", "title": "Lopsided Mix", "body": f"One channel is {metrics['lr_balance']}dB louder than the other.", "action": "Check your hard-panned elements and balance them."})
    if metrics["macro_dynamics"] < 2.0 and metrics["lufs"] < -8.0 and genre != "EDM / Hip-Hop": issues.append({"id": "flat_macro_dynamics", "priority": "REVIEW", "title": "Flat Song Journey", "body": "Verses are just as loud as choruses, lacking emotional impact.", "action": "Automate mix bus volume up by 1dB during the chorus."})
    if (high_mids - ultra_highs) > 35.0: issues.append({"id": "fake_lossless", "priority": "FIX NOW", "title": "Fake Lossless File", "body": "Unnatural drop-off above 16kHz. Usually means an MP3 was rendered as a WAV.", "action": "Re-bounce the original project as a true WAV."})
    if metrics["true_peak"] > 0.5: issues.append({"id": "severe_clipping", "priority": "FIX NOW", "title": "Severe Clipping", "body": f"Peaks hitting {metrics['true_peak']} dBTP. This causes distortion.", "action": "Lower final limiter output ceiling to -1.0 dB."})
    elif metrics["plr"] < dyn_crushed_limit: issues.append({"id": "over_compressed", "priority": "FIX NOW", "title": "Crushed Dynamics", "body": f"Peak-to-Loudness (PLR) is only {metrics['plr']}dB. Transients are flat.", "action": "Back off mix bus compression."})
    if mud > bass - 3: issues.append({"id": "mud_overpower", "priority": "FIX NOW", "title": "Low-Mid Mud", "body": "250-500Hz range is clouding your mix.", "action": "Apply a wide cut around 350Hz on muddy instruments."})
    if harsh > mid - 1: issues.append({"id": "harshness_spike", "priority": "FIX NOW", "title": "Presence Harshness", "body": "Aggressive energy in the ear-fatiguing 2k-5kHz range.", "action": "Use a dynamic EQ on lead vocals around 3.5kHz."})
    if sub > bass + sub_allowance: issues.append({"id": "sub_blowout", "priority": "REVIEW", "title": "Sub-Bass Overload", "body": "Sub frequencies are significantly louder than bass punch.", "action": "Reduce sub-bass volume or high-pass at 25Hz."})
    if metrics["low_correlation"] < 0.4: issues.append({"id": "wide_bass", "priority": "FIX NOW", "title": "Unfocused Low End", "body": f"Bass (<150Hz) has wide stereo spread ({metrics['low_correlation']}).", "action": "Sum frequencies below 120Hz to mono."})
    elif metrics["correlation"] < 0.1: issues.append({"id": "phase_cancellation", "priority": "FIX NOW", "title": "Phase Cancellation", "body": "Stereo correlation is dangerously low.", "action": "Check stereo imagers."})

    return issues

def generate_ai_summary(metrics, issues, genre):
    if not client: return "AI analysis skipped: Please add your Gemini API key to the backend."
    
    issue_titles = [i['title'] for i in issues] if issues else ["None, the mix is perfectly healthy!"]
    
    prompt = f"""
    You are a veteran, empathetic mastering engineer. You are reviewing a diagnostic report for an unmastered '{genre}' track submitted by an independent producer.
    
    Track Metrics:
    - Loudness: {metrics['lufs']} LUFS
    - PLR (Peak-to-Loudness Ratio): {metrics['plr']} dB
    - True Peak: {metrics['true_peak']} dBTP
    - Core Issues Detected: {', '.join(issue_titles)}
    
    Write a concise, 3-sentence summary addressed directly to the producer. 
    Sentence 1: Validate the track's current state.
    Sentence 2: Gently but professionally point out the most critical issue holding it back.
    Sentence 3: Encourage them to fix it before mastering.
    
    Do NOT use bullet points. Speak like a friendly human expert.
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model='gemini-2.5-flash-lite', contents=prompt)
            return response.text.strip()
        except Exception as e:
            error_msg = str(e)
            if "503" in error_msg or "UNAVAILABLE" in error_msg or "429" in error_msg:
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
            return "Our AI assistant is currently taking a quick break, but your raw diagnostic data is ready below!"

@app.get("/analyze_stream/{file_id}")
async def analyze_stream(file_id: str, genre: str = "Pop / Standard"):
    async def event_generator():
        file_path = None
        try:
            for f in os.listdir("temp_uploads"):
                if f.startswith(file_id):
                    file_path = os.path.join("temp_uploads", f)
                    break
                    
            if not file_path:
                yield f"data: {json.dumps({'error': 'File not found on server'})}\n\n"
                return

            yield f"data: {json.dumps({'progress': 10, 'message': 'Decoding high-res audio matrix (30s sample)...'})}\n\n"
            await asyncio.sleep(0.1)
            
            # 1. Peek at the file to get the sample rate without loading the audio
            info = sf.info(file_path)
            
            # 2. Calculate exactly how many "frames" make up 30 seconds
            max_frames = int(info.samplerate * 30)
            
            # 3. Only load those 30 seconds into the server's memory
            audio_data, samplerate = sf.read(file_path, frames=max_frames)
            
            if audio_data.ndim > 1: 
                audio_data = audio_data.T

            yield f"data: {json.dumps({'progress': 40, 'message': 'Calculating phase correlation & dynamics...'})}\n\n"
            await asyncio.sleep(0.1)
            analysis = analyze_audio(audio_data, samplerate)

            yield f"data: {json.dumps({'progress': 70, 'message': 'Generating DSP diagnostic report...'})}\n\n"
            await asyncio.sleep(0.1)
            issues = generate_diagnostics(analysis["metrics"], analysis["raw_mags"], analysis["raw_freqs"], genre)

            yield f"data: {json.dumps({'progress': 85, 'message': 'Consulting AI Mastering Engineer...'})}\n\n"
            await asyncio.sleep(0.1)
            ai_summary = generate_ai_summary(analysis["metrics"], issues, genre)

            final_payload = {
                "status": "complete",
                "metrics": analysis["metrics"],
                "issues": issues,
                "spectrum": analysis["spectrum"],
                "ai_summary": ai_summary,
                "genre": genre
            }
            yield f"data: {json.dumps(final_payload)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
               
    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
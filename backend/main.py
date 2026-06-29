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
import shutil
from dotenv import load_dotenv, find_dotenv
from google import genai
from google.oauth2 import id_token
from google.auth.transport import requests
import certifi

# Load environment variables
load_dotenv(find_dotenv())

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

client_db = MongoClient(os.getenv("MONGO_URI"), tlsCAFile=certifi.where())
db = client_db["mix_oracle"]
users_collection = db["users"]


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

# --- MongoDB Auth ---
class AuthUser(BaseModel):
    email: str
    password: str
    name: str = ""
    code: str = ""

class OTPRequest(BaseModel):
    email: str

class GoogleAuthRequest(BaseModel):
    token: str

def verify_google_token(token: str):
    try:
        # Verify the token with Google
        idinfo = id_token.verify_oauth2_token(
            token, 
            requests.Request(), 
            GOOGLE_CLIENT_ID
        )
        return idinfo
    except ValueError:
        # Invalid token
        return None

# Unique index — prevents duplicate emails at the database level
users_collection.create_index("email", unique=True)

OTP_STORE: dict = {}  # { email: (code, expiry_timestamp) }


@app.post("/auth/send-code")
async def send_verification_code(req: OTPRequest):
    existing = users_collection.find_one({"email": req.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered. Please log in.")

    code = str(secrets.randbelow(900000) + 100000)
    OTP_STORE[req.email] = (code, time.time() + 600)  # 10-minute expiry

    try:
        msg = MessageSchema(
            subject="Your Mix Oracle Verification Code",
            recipients=[req.email],
            body=f"Your verification code is: {code}\n\nWelcome to Mix Oracle by Divine Decibels!",
            subtype="plain"
        )
        await FastMail(conf).send_message(msg)
        return {"status": "success", "message": "Code sent!"}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to send email.")


@app.post("/auth/register")
async def register(user: AuthUser):
    if users_collection.find_one({"email": user.email}):
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
    users_collection.insert_one({
        "email":         user.email,
        "password":      hashed.decode("utf-8"),
        "name":          user.name,
        "created_at":    time.time(),
        "auth_provider": "email"
    })
    del OTP_STORE[user.email]
    return {"status": "success", "message": "Account created!"}


@app.post("/auth/login")
async def login(user: AuthUser):
    existing = users_collection.find_one({"email": user.email})
    if not existing:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Catch Google-only accounts trying to use password login
    if existing.get("auth_provider") == "google" and not existing.get("password"):
        raise HTTPException(status_code=401, detail="This account uses Google Sign-In. Please continue with Google.")

    stored_hash = existing["password"].encode("utf-8")
    if not bcrypt.checkpw(user.password.encode("utf-8"), stored_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    return {"status": "success", "name": existing.get("name", "")}


@app.post("/auth/google")
async def auth_google(payload: GoogleAuthRequest):
    user_info = verify_google_token(payload.token)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid Google token.")

    email = user_info["email"]
    name  = user_info.get("name", email.split("@"))

    existing = users_collection.find_one({"email": email})
    if not existing:
        users_collection.insert_one({
            "email":         email,
            "password":      "",
            "name":          name,
            "created_at":    time.time(),
            "auth_provider": "google"
        })

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
    file_id = str(uuid.uuid4())
    file_path = os.path.join("temp_uploads", f"{file_id}_{file.filename}")
    
    # Async chunked streaming: strictly limits RAM to 1MB and never freezes the server
    with open(file_path, "wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)  # Read exactly 1MB at a time
            if not chunk:
                break
            buffer.write(chunk)
            
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
    
    l_filt = sosfilt(sos, y_stereo)
    r_filt = sosfilt(sos, y_stereo)
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


def load_audio_smart(file_path: str, max_duration_s: int = 60):
    """
    Loads a fixed window starting at 20% into the track.
    Deterministic — same file always gives same diagnostic window.
    Skips intros, reliably hits verse+chorus content.
    """
    info = sf.info(file_path)
    sr           = info.samplerate
    total_frames = info.frames
    window_frames = int(sr * max_duration_s)

    # Short file — load everything
    if total_frames <= window_frames:
        with sf.SoundFile(file_path) as f:
            data = f.read(dtype='float32', always_2d=True)
        y = data.T
    else:
        # Start at 20% — skips intro, lands on body of the track
        start_frame = min(
            int(total_frames * 0.20),
            total_frames - window_frames   # don't run off the end
        )
        with sf.SoundFile(file_path) as f:
            f.seek(start_frame)
            data = f.read(window_frames, dtype='float32', always_2d=True)
        y = data.T

    # Normalise channel count to exactly 2
    if y.ndim == 1 or y.shape[0] == 1:
        y = np.vstack((y.flatten(), y.flatten()))
    elif y.shape[0] > 2:
        y = y[:2]

    return y, sr


def get_full_timeline(file_path: str, block_s: int = 4) -> list:
    """
    Generates full-track loudness timeline without loading the whole file.
    Reads one 4-second block at a time — never more than ~1.5MB in RAM.
    """
    info = sf.info(file_path)
    sr = info.samplerate
    block_frames = int(sr * block_s)
    timeline = []

    with sf.SoundFile(file_path) as f:
        while True:
            chunk = f.read(block_frames, dtype='float32', always_2d=True)
            if len(chunk) == 0:
                break
            mono = np.mean(chunk, axis=1)
            rms = np.sqrt(np.mean(mono ** 2) + 1e-12)
            timeline.append(round(float(20 * np.log10(rms)), 1))

    return timeline
    
# --- Core Analyzer ---
def analyze_audio(y: np.ndarray, sr: int) -> dict:
    y = np.asarray(y, dtype=np.float32)

    if y.ndim == 1:
        y = np.vstack((y, y))

    y_stereo = y
    y_mono = np.mean(y_stereo, axis=0).astype(np.float32)

    
    meter = pyln.Meter(sr) 
    y_transposed = y_stereo.T 
    lufs = meter.integrated_loudness(y_transposed)
    true_peak_db = fast_true_peak(y_transposed.flatten(), sr)
    plr = true_peak_db - lufs
    dc_offset = float(np.mean(y_mono))
    
    # RESTORED: and for Left/Right RMS
    rms_l = 20 * np.log10(np.sqrt(np.mean(y_stereo**2)) + 1e-10)
    rms_r = 20 * np.log10(np.sqrt(np.mean(y_stereo**2)) + 1e-10)
    lr_balance_diff = round(abs(rms_l - rms_r), 2)

    n_blocks = len(y_mono) // sr
    if n_blocks > 0:
        blocks = np.array_split(y_mono[:n_blocks*sr], n_blocks)
        block_rms = [np.sqrt(np.mean(b**2)) for b in blocks]
        block_db = [20 * np.log10(rms + 1e-10) for rms in block_rms]
        macro_dynamics = np.percentile(block_db, 95) - np.percentile(block_db, 5)
    else:
        macro_dynamics = 0.0

    # RESTORED: and for Correlation
    overall_corr = calculate_true_correlation(y_stereo, y_stereo)
    low_corr = get_band_correlation(y_stereo, sr, 0, 150)
    high_corr = get_band_correlation(y_stereo, sr, 5000, sr/2)

    n_fft      = 2048
    hop_length = n_fft // 4
    win        = np.hanning(n_fft).astype(np.float32)
    frames = [
    np.abs(np.fft.rfft(y_mono[s:s + n_fft] * win))
    for s in range(0, len(y_mono) - n_fft, hop_length)
    ]
    avg_mag    = np.mean(frames, axis=0) if frames else np.abs(np.fft.rfft(y_mono[:n_fft]))
    ref_val    = np.max(avg_mag) + 1e-12
    magnitudes = (20 * np.log10(avg_mag / ref_val + 1e-12)).astype(np.float32)
    frequencies = np.fft.rfftfreq(n_fft, 1.0 / sr).astype(np.float32)
    
    valid_idx = np.where((frequencies >= 20) & (frequencies <= 20000))
    freqs_filtered = frequencies[valid_idx]
    mags_filtered = magnitudes[valid_idx]
    
    target_freqs = np.geomspace(20, 20000, num=100)
    indices = [np.argmin(np.abs(freqs_filtered - f)) for f in target_freqs]

    # RESTORED: and for Mono Compatibility
    mono_signal = (y_stereo + y_stereo) / 2.0
    rms_l_mono = np.sqrt(np.mean(y_stereo**2) + 1e-12)
    rms_r_mono = np.sqrt(np.mean(y_stereo**2) + 1e-12)
    rms_stereo = np.sqrt((rms_l_mono**2 + rms_r_mono**2) / 2.0)
    rms_mono_calc = np.sqrt(np.mean(mono_signal**2) + 1e-12)
    mono_compatibility = round(20 * np.log10(rms_mono_calc / rms_stereo), 1)

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
            "lufs": float(round(lufs, 1)),
            "true_peak": float(round(true_peak_db, 1)),
            "correlation": float(round(overall_corr, 2)),
            "plr": float(round(plr, 1)),
            "dr":         float(f"{dr:.1f}"),
            "low_correlation": float(round(low_corr, 2)),
            "high_correlation": float(round(high_corr, 2)),
            "dc_offset": float(f"{dc_offset:.4f}"),
            "lr_balance": float(f"{lr_balance_diff:.2f}"),
            "macro_dynamics": float(round(macro_dynamics, 1)),
            "mono_compatibility": float(round(mono_compatibility, 1)),
            "loudness_timeline": [round(float(val), 1) for val in loudness_timeline]
        },
        "spectrum": {
            "frequencies": [round(float(val), 1) for val in freqs_filtered[indices].tolist()], 
            "magnitudes": [round(float(val), 1) for val in mags_filtered[indices].tolist()]
        },
        "raw_mags": mags_filtered, 
        "raw_freqs": freqs_filtered
    }


def generate_diagnostics(metrics, raw_mags, raw_freqs, genre):
    issues = []
    
    def get_band_energy(low_f, high_f):
        idx = np.where((raw_freqs >= low_f) & (raw_freqs <= high_f))
        if len(idx) == 0: return -100.0
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
    if metrics["lr_balance"] > 1.5: issues.append({"id": "lr_imbalance", "priority": "REVIEW", "title": "Lopsided Mix", "body": f"One channel is {metrics['lr_balance']:.1f} dB louder than the other.", "action": "Check your hard-panned elements and balance them."})
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
            # UPDATED: Switched model string to a more stable endpoint
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            return response.text.strip()
        except Exception as e:
            error_msg = str(e)
            print(f"Gemini API Error (Attempt {attempt+1}): {error_msg}") # Added for debugging in Render
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
            # Locate the uploaded file
            for f in os.listdir("temp_uploads"):
                if f.startswith(file_id):
                    file_path = os.path.join("temp_uploads", f)
                    break

            if not file_path:
                yield f"data: {json.dumps({'error': 'File not found on server'})}\n\n"
                return

            # Step 1: Full-track timeline — lightweight scan, ~1.5MB RAM
            yield f"data: {json.dumps({'progress': 15, 'message': 'Mapping song energy journey...'})}\n\n"
            await asyncio.sleep(0.05)
            full_timeline = get_full_timeline(file_path)

            # Compute DR from full-track timeline (far more accurate than 30s window)
            full_dr = 0.0
            if len(full_timeline) >= 5:
                sorted_tl = sorted(full_timeline, reverse=True)
                top_20pct = sorted_tl[:max(1, len(sorted_tl) // 5)]
                full_dr = round(
                    float(np.percentile(top_20pct, 50)) - float(np.percentile(full_timeline, 50)),
                    1
                )

            # Step 2: Smart load — only the loudest 60s for DSP analysis
            yield f"data: {json.dumps({'progress': 30, 'message': 'Loading analysis window...'})}\n\n"
            await asyncio.sleep(0.05)
            audio_data, samplerate = load_audio_smart(file_path, max_duration_s=60)

            # Step 3: Core DSP analysis
            yield f"data: {json.dumps({'progress': 50, 'message': 'Calculating phase correlation & dynamics...'})}\n\n"
            await asyncio.sleep(0.1)
            analysis = analyze_audio(audio_data, samplerate)

            # Step 4: Diagnostic rules engine
            yield f"data: {json.dumps({'progress': 70, 'message': 'Generating DSP diagnostic report...'})}\n\n"
            await asyncio.sleep(0.1)
            issues = generate_diagnostics(
                analysis["metrics"], analysis["raw_mags"], analysis["raw_freqs"], genre
            )

            # Step 5: AI summary
            yield f"data: {json.dumps({'progress': 85, 'message': 'Consulting AI Mastering Engineer...'})}\n\n"
            await asyncio.sleep(0.1)
            ai_summary = generate_ai_summary(analysis["metrics"], issues, genre)

            # Final payload — inject full-track timeline over the 60s window version
            final_payload = {
                "status": "complete",
                "metrics": {
                    **analysis["metrics"],
                    "loudness_timeline": full_timeline,
                    "dr": full_dr,
                },
                "issues": issues,
                "spectrum": analysis["spectrum"],
                "ai_summary": ai_summary,
                "genre": genre,
            }
            yield f"data: {json.dumps(final_payload)}\n\n"

        except ValueError as e:
            yield f"data: {json.dumps({'error': f'Audio format issue: {str(e)}. Try exporting as WAV or AIFF instead of MP3.'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        finally:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
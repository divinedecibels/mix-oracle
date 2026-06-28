import librosa
import numpy as np
import soundfile as sf
from pyloudnorm import Meter
import json
import sys
import os

class MixDoctorAnalyzer:
    """
    Core analysis engine for Mix Doctor.
    Calculates LUFS, True Peak, Frequency Balance, Dynamic Range, and Stereo Correlation.
    """
    
    def __init__(self, sr=44100):
        self.sr = sr
        self.meter = Meter(sr)
        
    def load_audio(self, file_path):
        """Loads audio file and ensures it's in the correct format for processing."""
        # Load as stereo (mono=False)
        y, sr = librosa.load(file_path, sr=self.sr, mono=False)
        
        # Ensure 2D array (channels, samples)
        if y.ndim == 1:
            y = np.vstack([y, y])
            
        return y, sr

    def get_lufs(self, y):
        """Calculates Integrated LUFS (ITU-R BS.1770-4)."""
        # pyloudnorm expects (samples, channels)
        return self.meter.integrated_loudness(y.T)

    def get_true_peak(self, y):
        """Calculates True Peak in dBFS."""
        # Simple peak for now, could use oversampling for more accuracy
        peak = np.max(np.abs(y))
        return 20 * np.log10(peak) if peak > 0 else -100.0

    def get_spectrum_data(self, y_mono):
        """Generates frequency spectrum data for the UI problem map."""
        # Use a large FFT for good frequency resolution
        n_fft = 4096
        stft = np.abs(librosa.stft(y_mono, n_fft=n_fft))
        avg_stft = np.mean(stft, axis=1)
        freqs = librosa.fft_frequencies(sr=self.sr, n_fft=n_fft)
        
        # Filter to audible range (20Hz - 20kHz) and downsample for JSON
        mask = (freqs >= 20) & (freqs <= 20000)
        filtered_freqs = freqs[mask]
        filtered_mag = avg_stft[mask]
        
        # Logarithmic downsampling for UI curve (more points in lows, fewer in highs)
        indices = np.unique(np.logspace(0, np.log10(len(filtered_freqs)-1), num=200).astype(int))
        
        return {
            "frequencies": filtered_freqs[indices].tolist(),
            "magnitudes": (20 * np.log10(filtered_mag[indices] + 1e-9)).tolist()
        }

    def get_stereo_correlation(self, y):
        """Calculates stereo correlation coefficient (-1 to 1)."""
        if y.shape[0] < 2:
            return 1.0
        return np.corrcoef(y[0], y[1])[0, 1]

    def get_dynamic_range(self, y_mono):
        """Calculates Peak-to-RMS ratio (Crest Factor) as a proxy for dynamic range."""
        rms = librosa.feature.rms(y=y_mono)[0]
        peak = np.max(np.abs(y_mono))
        # Use mean RMS to avoid being skewed by silent sections
        avg_rms = np.mean(rms[rms > 1e-4]) if np.any(rms > 1e-4) else 1e-4
        crest_factor = peak / avg_rms
        return 20 * np.log10(crest_factor)

    def diagnose_issues(self, y, lufs, peak, correlation, spectrum):
        """Heuristic-based issue detection."""
        issues = []
        
        # 1. Low-end conflict (80-160Hz)
        freqs = np.array(spectrum["frequencies"])
        mags = np.array(spectrum["magnitudes"])
        low_mid_mask = (freqs >= 80) & (freqs <= 160)
        if np.any(low_mid_mask):
            avg_low_mid = np.mean(mags[low_mid_mask])
            # Simple thresholding relative to overall average
            if avg_low_mid > np.mean(mags) + 15:
                issues.append({
                    "id": "low_mid_buildup",
                    "priority": "FIX NOW",
                    "title": "Low-Mid Build-up",
                    "body": "Excessive energy detected in the 80-160Hz range, likely a kick/bass conflict.",
                    "action": "Cut 3-4dB at 110Hz on your bass or use sidechain compression."
                })

        # 2. Sibilance (7kHz - 8kHz)
        sibilance_mask = (freqs >= 7000) & (freqs <= 8000)
        if np.any(sibilance_mask):
            peak_sibilance = np.max(mags[sibilance_mask])
            if peak_sibilance > np.mean(mags) + 20:
                issues.append({
                    "id": "sibilance_spike",
                    "priority": "REVIEW",
                    "title": "Sibilance Spike",
                    "body": "Harsh frequencies detected around 7.2kHz.",
                    "action": "Apply a de-esser or a narrow notch filter at 7.2kHz."
                })

        # 3. Phase issues
        if correlation < 0.1:
            issues.append({
                "id": "phase_conflict",
                "priority": "FIX NOW",
                "title": "Phase Conflict",
                "body": "Extremely low stereo correlation. Your mix will collapse in mono.",
                "action": "Check for phase-inverted tracks or reduce excessive stereo widening."
            })

        return issues

    def analyze(self, file_path):
        """Runs the full analysis pipeline."""
        try:
            y, sr = self.load_audio(file_path)
            y_mono = librosa.to_mono(y)
            
            lufs = self.get_lufs(y)
            peak = self.get_true_peak(y)
            correlation = self.get_stereo_correlation(y)
            dynamic_range = self.get_dynamic_range(y_mono)
            spectrum = self.get_spectrum_data(y_mono)
            
            issues = self.diagnose_issues(y, lufs, peak, correlation, spectrum)
            
            return {
                "status": "success",
                "metrics": {
                    "lufs": round(float(lufs), 1),
                    "true_peak": round(float(peak), 1),
                    "correlation": round(float(correlation), 2),
                    "dynamic_range": round(float(dynamic_range), 1)
                },
                "issues": issues,
                "spectrum": spectrum
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "message": "No file path provided"}))
        sys.exit(1)
        
    analyzer = MixDoctorAnalyzer()
    results = analyzer.analyze(sys.argv[1])
    print(json.dumps(results))

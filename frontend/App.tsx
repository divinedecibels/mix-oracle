import { useState, useRef, useEffect } from 'react';
import { ArrowRight, RefreshCw, Play, Pause, X } from 'lucide-react';
import { GoogleLogin } from '@react-oauth/google';

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

// --- Types ---
type AppState = 'upload' | 'analyzing' | 'report';

interface DiagnosticIssue {
  id: string;
  priority: 'FIX NOW' | 'REVIEW' | 'PASSED';
  title: string;
  body: string;
  action: string;
}

interface AnalysisResults {
  metrics: {
    lufs: number;
    true_peak: number;
    correlation: number;
    plr: number;
    mono_compatibility: number;
    loudness_timeline: number[];
    dr: number;
  };
  issues: DiagnosticIssue[];
  spectrum: {
    frequencies: number[];
    magnitudes: number[];
  };
  ai_summary: string;
  genre: string;
}

interface AnalyzingViewProps {
  progress: number;
  statusMessage: string;
}

// --- Icons ---
const WaveformIcon = ({ className = "w-10 h-10" }) => (
  <svg viewBox="0 0 24 24" fill="currentColor" className={className} xmlns="http://www.w3.org/2000/svg">
    <rect x="3" y="10" width="2" height="4" rx="1" />
    <rect x="7" y="7" width="2" height="10" rx="1" />
    <rect x="11" y="4" width="2" height="16" rx="1" />
    <rect x="15" y="7" width="2" height="10" rx="1" />
    <rect x="19" y="10" width="2" height="4" rx="1" />
  </svg>
);

const EyeIcon = ({ className = "w-5 h-5" }) => (
  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className={className}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
  </svg>
);

// --- Components ---
const AnalyzingView = ({ progress, statusMessage }: AnalyzingViewProps) => {
  return (
    <div className="w-full max-w-2xl flex flex-col items-center">
      <div className="flex items-center gap-3 mb-12">
        <div className="bg-[#F59E0B] p-1.5 rounded-lg animate-pulse">
          <WaveformIcon className="w-6 h-6 text-black" />
        </div>
        <div className="flex flex-col">
          <span className="text-2xl font-bold tracking-tight leading-none">Mix Oracle</span>
          <span className="text-[10px] text-[#6B7280] font-bold uppercase tracking-widest mt-1">By Divine Decibels</span>
        </div>
      </div>

      <div className="w-full bg-[#111116] border border-[#26262C] rounded-[24px] p-16 flex flex-col items-center justify-center mb-6 shadow-xl">
        <style>{`
          @keyframes bounce-eq {
            0%, 100% { height: 30%; }
            50% { height: 100%; }
          }
        `}</style>
        <div className="flex items-end gap-1 mb-8 h-16">
          {[...Array(12)].map((_, i) => (
            <div 
              key={i} 
              className="w-2 bg-[#F59E0B] rounded-full" 
              style={{ 
                animation: `bounce-eq 0.6s ease-in-out infinite`,
                animationDelay: `${i * 0.1}s`,
                height: '50%'
              }} 
            />
          ))}
        </div>
  
        <h2 className="text-xl font-semibold mb-4 text-center">Diagnosing your mix...</h2>
        <div className="w-full bg-[#1A1A20] h-2 rounded-full overflow-hidden mb-4">
          <div 
            className="bg-[#F59E0B] h-full transition-all duration-300 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        <p className="text-[#F59E0B] text-sm font-bold tracking-wide animate-pulse">
          {statusMessage}
        </p>
      </div>
    </div>
  );
};

// --- Global Audio Engine ---
const mixPlayer = new Audio();

// --- Custom Audio Player ---
const CustomAudioPlayer = ({ src }: { src: string }) => {
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [time, setTime] = useState("0:00");
  const [formatError, setFormatError] = useState(false);

  useEffect(() => {
    mixPlayer.src = src;
    mixPlayer.load();

    const updateTime = () => {
      const current = mixPlayer.currentTime;
      const duration = mixPlayer.duration || 1; 
      setProgress((current / duration) * 100);

      const mins = Math.floor(current / 60);
      const secs = Math.floor(current % 60).toString().padStart(2, '0');
      setTime(`${mins}:${secs}`);
    };

    const onEnded = () => setIsPlaying(false);

    mixPlayer.addEventListener('timeupdate', updateTime);
    mixPlayer.addEventListener('ended', onEnded);

    return () => {
      mixPlayer.pause();
      mixPlayer.removeEventListener('timeupdate', updateTime);
      mixPlayer.removeEventListener('ended', onEnded);
    };
  }, [src]);

  const togglePlay = () => {
    if (isPlaying) {
      mixPlayer.pause();
      setIsPlaying(false);
    } else {
      setFormatError(false);
      mixPlayer.play()
        .then(() => setIsPlaying(true))
        .catch((err) => {
          console.error("Playback error:", err);
          setIsPlaying(false);
          if (err.name === "NotSupportedError") {
            setFormatError(true);
          }
        });
    }
  };

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!formatError && mixPlayer.duration && !isNaN(mixPlayer.duration)) {
      const bounds = e.currentTarget.getBoundingClientRect();
      const percent = (e.clientX - bounds.left) / bounds.width;
      mixPlayer.currentTime = percent * mixPlayer.duration;
      if (!isPlaying) {
        togglePlay();
      }
    }
  };

  return (
    <div className="w-full bg-[#111116] border border-[#26262C] rounded-[24px] p-6 mb-8 flex items-center gap-6 shadow-xl relative overflow-hidden">
      <div className="absolute top-0 left-0 w-1 h-full bg-[#3F3F46]"></div>
      
      <button 
        onClick={togglePlay} 
        disabled={formatError}
        className={`w-14 h-14 rounded-full flex items-center justify-center transition-all shadow-lg flex-shrink-0
          ${formatError ? 'bg-[#3F3F46] cursor-not-allowed opacity-50' : 'bg-[#F59E0B] text-black hover:scale-105 active:scale-95 shadow-[#F59E0B]/20'}
        `}
      >
        {isPlaying ? <Pause className="w-6 h-6 fill-black" /> : <Play className={`w-6 h-6 ${formatError ? 'fill-[#6B7280]' : 'fill-black'} translate-x-0.5`} />}
      </button>

      <div className="flex-1 flex flex-col gap-3">
        <div className="flex justify-between items-end">
          <span className="text-[11px] text-[#6B7280] font-black tracking-widest uppercase">
            {formatError ? <span className="text-red-400">Browser cannot play this format (e.g. AIFF)</span> : "Original Mix Playback"}
          </span>
          <span className="text-xs font-bold text-[#D1D5DB] font-mono">{time}</span>
        </div>

        <div 
          className={`h-2 w-full rounded-full overflow-hidden group ${formatError ? 'bg-red-900/20' : 'bg-[#1A1A20] cursor-pointer'}`}
          onClick={handleSeek}
        >
          <div 
            className={`h-full transition-all duration-75 relative ${formatError ? 'bg-red-500/50' : 'bg-[#F59E0B]'}`} 
            style={{ width: `${formatError ? 100 : progress}%` }} 
          />
        </div>
      </div>
    </div>
  );
};

const ReportView = ({ results, audioUrl, onReset }: { results: AnalysisResults, audioUrl: string | null, onReset: () => void }) => {
  const { metrics, issues, spectrum } = results;
  const [showForm, setShowForm] = useState(false);
  const [formStatus, setFormStatus] = useState<'idle' | 'sending' | 'success' | 'error'>('idle');
  
  const minFreq = 20;
  const maxFreq = 20000;
  const svgWidth = 1000;
  const svgHeight = 200;
  
  const freqToX = (freq: number) => {
    const logMin = Math.log10(minFreq);
    const logMax = Math.log10(maxFreq);
    const logFreq = Math.log10(Math.max(minFreq, Math.min(maxFreq, freq)));
    return ((logFreq - logMin) / (logMax - logMin)) * svgWidth;
  };
  
  const getSpectrumPath = (freqs: number[], mags: number[]) => {
    if (!freqs.length) return "";
    const minDb = -80;
    const maxDb = 0;
    return mags.map((mag, i) => {
      const x = freqToX(freqs[i]);
      const y = svgHeight - ((mag - minDb) / (maxDb - minDb)) * svgHeight;
      return `${i === 0 ? 'M' : 'L'}${x},${y}`;
    }).join(' ');
  };

  const getTimelinePath = (timeline: number[]) => {
    if (!timeline || !timeline.length) return "";
    const width = 1000;
    const height = 100;
    
    const maxDb = Math.max(...timeline);
    const minDb = Math.min(...timeline) - 5; 
    const range = maxDb - minDb || 1;

    return timeline.map((db, i) => {
      const x = (i / (timeline.length - 1)) * width;
      const y = height - ((db - minDb) / range) * height;
      return `${i === 0 ? 'M' : 'L'}${x},${y}`;
    }).join(' ');
  };

  return (
    <div className="w-full max-w-4xl py-12 px-6 animate-in fade-in duration-700">
      <div className="flex items-center justify-between mb-12">
        <div className="flex items-center gap-3">
          <div className="bg-[#F59E0B] p-1.5 rounded-lg">
            <WaveformIcon className="w-6 h-6 text-black" />
          </div>
          <span className="text-2xl font-bold tracking-tight">Health Report</span>
        </div>
     
        <button 
          onClick={onReset}
          className="flex items-center gap-2 text-sm text-[#6B7280] hover:text-white transition-colors"
        >
          <RefreshCw className="w-4 h-4" /> Analyze another track
        </button>
      </div>

      {audioUrl && <CustomAudioPlayer src={audioUrl} />}

      {/* AI Engineer Summary */}
      <div className="bg-[#111116] border border-[#F59E0B]/30 rounded-[24px] p-8 mb-12 relative overflow-hidden shadow-lg shadow-[#F59E0B]/5">
        <div className="absolute top-0 left-0 w-1 h-full bg-[#F59E0B]"></div>
        <div className="flex items-center gap-2 mb-4">
          <span className="text-xs font-bold uppercase text-[#F59E0B] tracking-wider">AI Engineer Notes</span>
          <span className="px-2 py-0.5 rounded-full bg-[#26262C] text-[10px] text-[#6B7280]">Genre: {results.genre}</span>
        </div>
        <p className="text-[#D1D5DB] text-[17px] leading-relaxed font-medium">
          {results.ai_summary}
        </p>
      </div>

      {/* Spectrum Problem Map */}
      <div className="bg-[#111116] border border-[#26262C] rounded-[24px] p-8 mb-12 relative overflow-hidden">
        <div className="flex items-center justify-between mb-8">
          <h3 className="text-lg font-bold">Frequency Diagnostic Map</h3>
          <div className="flex gap-4 text-xs">
            <div className="flex items-center gap-2 text-[#F59E0B]"><span className="w-3 h-0.5 bg-[#F59E0B]"></span> Your Mix</div>
            <div className="flex items-center gap-2 text-[#6B7280]"><span className="w-3 h-0.5 border-t border-dashed border-[#6B7280]"></span> Target</div>
          </div>
        </div>
        
        <div className="relative h-64 w-full">
          <svg className="w-full h-full overflow-visible" viewBox="0 0 1000 200" preserveAspectRatio="none">
            {[-80, -60, -40, -20, 0].map(db => (
              <line 
                key={db} 
                x1="0" 
                y1={svgHeight - ((db - (-80)) / (0 - (-80))) * svgHeight} 
                x2="1000" 
                y2={svgHeight - ((db - (-80)) / (0 - (-80))) * svgHeight} 
                stroke="#1A1A20" 
                strokeWidth="1" 
              />
            ))}
            
           {[20, 100, 1000, 10000, 20000].map(freq => (
              <line 
                key={freq} 
                x1={freqToX(freq)} 
                y1="0" 
                x2={freqToX(freq)} 
                y2="200" 
                stroke="#1A1A20" 
                strokeWidth="1" 
              />
            ))}
            
            <path 
              d="M0,120 C100,110 200,130 300,125 S500,115 700,120 S900,130 1000,125" 
              fill="none" stroke="#26262C" strokeWidth="2" strokeDasharray="4 4" 
            />
            
            <path 
              d={getSpectrumPath(spectrum.frequencies, spectrum.magnitudes)} 
              fill="none" stroke="#F59E0B" strokeWidth="2" className="transition-all duration-1000"
            />

            {issues.map((issue) => {
               let freq = 0;
               if (issue.id === 'mud_overpower') freq = 350;
               if (issue.id === 'harshness_spike') freq = 4000; 
               if (issue.id === 'phase_cancellation') freq = 1000; 
               if (issue.id === 'fake_lossless') freq = 18000; 
               if (freq === 0) return null;
               
               const x = freqToX(freq);
               
               return (
                 <g key={issue.id}>
                    <circle cx={x} cy="60" r="4" fill={issue.priority === 'FIX NOW' ? '#EF4444' : '#F59E0B'} />
                    <line x1={x} y1="60" x2={x} y2="30" stroke={issue.priority === 'FIX NOW' ? '#EF4444' : '#F59E0B'} strokeWidth="1" />
                    <foreignObject x={x - 60} y="0" width="120" height="30">
                      <div className={`text-center text-[8px] font-bold px-1 py-0.5 rounded text-white ${issue.priority === 'FIX NOW' ? 'bg-[#EF4444]' : 'bg-[#F59E0B] text-black'}`}>
                        {issue.title.toUpperCase()}
                      </div>
                    </foreignObject>
                 </g>
               );
            })}
          </svg>

          <div className="flex justify-between mt-4 text-[10px] text-[#3F3F46] font-bold">
            <span>20Hz</span><span>100Hz</span><span>1kHz</span><span>10kHz</span><span>20kHz</span>
          </div>
        </div>
      </div>

      {/* Section-Level Dynamics (Timeline) */}
      {metrics.loudness_timeline && metrics.loudness_timeline.length > 0 && (
        <div className="bg-[#111116] border border-[#26262C] rounded-[24px] p-8 mb-12 relative overflow-hidden">
          <div className="flex items-center justify-between mb-8">
            <h3 className="text-lg font-bold">Song Energy Journey (4s Blocks)</h3>
            <span className="text-xs font-bold text-[#6B7280] uppercase tracking-wider">
              {metrics.loudness_timeline.length * 4} Seconds Analyzed
            </span>
          </div>
          
          <div className="relative h-32 w-full">
            <svg className="w-full h-full overflow-visible" viewBox="0 0 1000 100" preserveAspectRatio="none">
              <path 
                d={getTimelinePath(metrics.loudness_timeline)} 
                fill="none" stroke="#F59E0B" strokeWidth="3" className="transition-all duration-1000 drop-shadow-md"
                strokeLinecap="round" strokeLinejoin="round"
              />
              <path 
                d={`${getTimelinePath(metrics.loudness_timeline)} L1000,100 L0,100 Z`} 
                fill="url(#timeline-gradient)" opacity="0.1" 
              />
              <defs>
                <linearGradient id="timeline-gradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#F59E0B" stopOpacity="1" />
                  <stop offset="100%" stopColor="#F59E0B" stopOpacity="0" />
                </linearGradient>
              </defs>
            </svg>
            <div className="flex justify-between mt-4 text-[10px] text-[#3F3F46] font-bold">
              <span>Start</span><span>Mid</span><span>End</span>
            </div>
          </div>
        </div>
      )}

      {/* Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          <div className="bg-[#111116] border border-[#26262C] p-4 rounded-2xl">
            <p className="text-[10px] text-[#6B7280] font-bold uppercase mb-1">Loudness</p>
            <p className="text-2xl font-black">{metrics.lufs} <span className="text-xs text-[#3F3F46]">LUFS</span></p>
          </div>
          <div className="bg-[#111116] border border-[#26262C] p-4 rounded-2xl">
            <p className="text-[10px] text-[#6B7280] font-bold uppercase mb-1">True Peak</p>
            <p className="text-2xl font-black">{metrics.true_peak} <span className="text-xs text-[#3F3F46]">dBTP</span></p>
          </div>
          <div className="bg-[#111116] border border-[#26262C] p-4 rounded-2xl">
            <p className="text-[10px] text-[#6B7280] font-bold uppercase mb-1">Correlation</p>
            <p className="text-2xl font-black">{metrics.correlation}</p>
          </div>
          <div className="bg-[#111116] border border-[#26262C] p-4 rounded-2xl">
            <p className="text-[10px] text-[#6B7280] font-bold uppercase mb-1">Mono Collapse</p>
            <p className={`text-2xl font-black ${metrics.mono_compatibility < -3 ? 'text-red-500' : 'text-white'}`}>
              {metrics.mono_compatibility} <span className="text-xs text-[#3F3F46]">dB</span>
            </p>
          </div>
          <div className="bg-[#111116] border border-[#26262C] p-4 rounded-2xl">
            <p className="text-[10px] text-[#6B7280] font-bold uppercase mb-1">PLR</p>
            <p className="text-2xl font-black">{metrics.plr} <span className="text-xs text-[#3F3F46]">dB</span></p>
          </div>
          <div className="bg-[#111116] border border-[#26262C] p-4 rounded-2xl">
            <p className="text-[10px] text-[#6B7280] font-bold uppercase mb-1">DR</p>
            <p className="text-2xl font-black">{metrics.dr ?? '--'} <span className="text-xs text-[#3F3F46]">dB</span></p>
          </div>
      </div>

      <div className="grid md:grid-cols-3 gap-6 mb-12">
        {issues.map((issue) => (
          <div 
            key={issue.id} 
            className={`p-6 rounded-[24px] border transition-all hover:scale-[1.02] ${
              issue.priority === 'FIX NOW' ? 'bg-[#110A0A] border-[#451A1A]' : 
              issue.priority === 'REVIEW' ? 'bg-[#110E0A] border-[#45361A]' : 'bg-[#0A110B] border-[#1A451F]'
            }`}
          >
            <div className="flex items-center justify-between mb-4">
              <span className={`text-[10px] font-black px-2 py-1 rounded ${
                issue.priority === 'FIX NOW' ? 'bg-[#EF4444] text-white' : 
                issue.priority === 'REVIEW' ? 'bg-[#F59E0B] text-black' : 'bg-[#10B981] text-white'
              }`}>
                {issue.priority}
              </span>
            </div>
            <h4 className="font-bold mb-3">{issue.title}</h4>
            <p className="text-sm text-[#6B7280] leading-relaxed mb-6">{issue.body}</p>
            <div className="pt-4 border-t border-[#26262C]">
              <p className="text-[10px] text-[#3F3F46] font-bold uppercase mb-2">Concrete Fix</p>
              <p className="text-xs font-medium text-white">{issue.action}</p>
            </div>
          </div>
        ))}
        {issues.length === 0 && (
          <div className="col-span-3 bg-[#0A110B] border border-[#1A451F] p-8 rounded-[24px] text-center">
             <div className="text-[#10B981] mb-4 flex justify-center"><WaveformIcon className="w-12 h-12" /></div>
             <h4 className="font-bold text-xl mb-2">Your mix is healthy!</h4>
             <p className="text-[#6B7280]">No major issues detected. Ready for the next stage of the chain.</p>
          </div>
        )}
      </div>

      {/* Streaming Readiness */}
      <div className="bg-[#111116] border border-[#26262C] rounded-[24px] p-8">
        <h3 className="text-lg font-bold mb-8">Streaming Readiness</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          {[
            { platform: 'Spotify', target: -14 },
            { platform: 'Apple Music', target: -16 },
            { platform: 'YouTube', target: -14 },
            { platform: 'Tidal', target: -14 },
          ].map((item, i) => {
            const isLoud = metrics.lufs > item.target;
            return (
              <div key={i} className="bg-[#1A1A20] p-4 rounded-xl border border-[#26262C]">
                <p className="text-xs text-[#6B7280] font-bold mb-1">{item.platform}</p>
                <p className="text-xl font-black mb-2">{metrics.lufs} <span className="text-xs text-[#3F3F46]">LUFS</span></p>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-[#3F3F46]">Target: {item.target} LUFS</span>
                  <span className={`${isLoud ? 'text-[#EF4444]' : 'text-[#10B981]'} font-bold`}>{isLoud ? 'LOUD' : 'SAFE'}</span>
                </div>                
              </div>
            );
          })}
        </div>
        
        {/* CTA Section */}
        <div className="bg-[#111116] border border-[#26262C] rounded-[24px] p-10 text-center mt-12 relative overflow-hidden shadow-2xl">
          {!showForm ? (
            <>
              <h3 className="text-3xl font-black mb-4 tracking-tight">Need a professional touch?</h3>
              <p className="text-[#9CA3AF] mb-8 max-w-xl mx-auto leading-relaxed">
                AI diagnostics are great, but nothing beats an experienced set of human ears. If you're struggling with phase issues, muddy lows, or crushed dynamics, let me handle the heavy lifting.
              </p>
              <button 
                onClick={() => setShowForm(true)}
                className="inline-flex items-center gap-2 px-8 py-4 bg-[#F59E0B] text-black rounded-xl font-bold text-lg hover:bg-[#D97706] hover:scale-[1.01] transition-all shadow-xl shadow-[#F59E0B]/20"
              >
                Book a Premium Mix & Master <ArrowRight className="w-5 h-5" />
              </button>
            </>
          ) : (
            <div className="animate-in fade-in zoom-in duration-300">
              <h3 className="text-2xl font-bold mb-6">Request your service</h3>
              {formStatus === 'success' ? (
                <div className="text-center py-8">
                  <div className="text-[#10B981] text-4xl mb-4">✓</div>
                  <h3 className="text-xl font-bold mb-2">Request Sent!</h3>
                  <p className="text-[#6B7280] mb-6">Thanks for reaching out! Divine Decibels Studio will get back to you soon.</p>
                  <button 
                    onClick={() => { setShowForm(false); setFormStatus('idle'); }}
                    className="px-6 py-2 bg-[#1A1A20] rounded-lg text-sm font-medium hover:bg-[#26262C]"
                  >
                    Close
                  </button>
                </div>
              ) : (
                <form 
                  onSubmit={async (e) => {
                    e.preventDefault();
                    setFormStatus('sending');
                    const formData = new FormData(e.currentTarget);
                    try {
                      const response = await fetch(`${API}/request-service`, { method: 'POST', body: formData });
                      if(response.ok) { 
                        setFormStatus('success');
                      } else {
                        setFormStatus('error');
                      }
                    } catch {
                      setFormStatus('error');
                    }
                  }}
                  className="flex flex-col gap-4 max-w-md mx-auto text-left"
                >
                  {formStatus === 'error' && (
                    <div className="p-3 bg-red-900/20 border border-red-500/50 rounded-xl text-red-400 text-sm text-center">
                      Error sending request. Please try again.
                    </div>
                  )}
                  <input name="name" placeholder="Your Name" required className="bg-[#1A1A20] p-4 rounded-xl border border-[#26262C] text-white" />
                  <input name="email" type="email" placeholder="Your Email" required className="bg-[#1A1A20] p-4 rounded-xl border border-[#26262C] text-white" />
                  <textarea name="message" placeholder="Tell me about your project..." required className="bg-[#1A1A20] p-4 rounded-xl border border-[#26262C] text-white h-32" />
                  <div className="flex gap-2">
                    <button type="button" onClick={() => setShowForm(false)} className="flex-1 py-4 text-[#6B7280] font-bold hover:text-white">Cancel</button>
                    <button 
                      type="submit" 
                      disabled={formStatus === 'sending'}
                      className="flex-1 bg-[#F59E0B] text-black py-4 rounded-xl font-bold hover:bg-[#D97706] disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {formStatus === 'sending' ? 'Sending...' : 'Send Request'}
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// --- Main App ---
function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [state, setState] = useState<AppState>('upload');
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState("Initializing Server...");
  const [results, setResults] = useState<AnalysisResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedGenre, setSelectedGenre] = useState('Pop / Standard');
  const [isDragging, setIsDragging] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
 
  // --- Auth State ---
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('signup');
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [otpSent, setOtpSent] = useState(false);
  const [otpLoading, setOtpLoading] = useState(false);
  const emailInputRef = useRef<HTMLInputElement>(null);

  const handleSendCode = async () => {
    const email = emailInputRef.current?.value;
    if (!email) {
      setAuthError("Please enter your email first.");
      return;
    }
    setAuthError("");
    setOtpLoading(true);
    try {
      const res = await fetch(`${API}/auth/send-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to send code");
      setOtpSent(true);
    } catch (err: any) {
      setAuthError(err.message);
    } finally {
      setOtpLoading(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) setSelectedFile(file);
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) setSelectedFile(file);
  };

  const handleAuthSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setAuthError("");
    setAuthLoading(true);
    
    const formData = new FormData(e.currentTarget);
    const email = formData.get('email');
    const password = formData.get('password');
    const code = formData.get('verification') || "";
    const name = formData.get('name') || "";

    const endpoint = authMode === 'signup' ? '/auth/register' : '/auth/login';
    
    try {
      const res = await fetch(`${API}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name, code })
      });
      const data = await res.json();
      
      if (!res.ok) throw new Error(data.detail || "Authentication failed");
      
      setIsAuthenticated(true);
      setShowAuthModal(false);
      
      if (selectedFile) uploadAndAnalyze(selectedFile);
    } catch (err: any) {
      setAuthError(err.message);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleGoogleLoginSuccess = async (credentialResponse: any) => {
    setAuthLoading(true);
    setAuthError("");
    try {
      const idToken = credentialResponse.credential;
      if (!idToken) throw new Error("No ID token received from Google");
      
      const res = await fetch(`${API}/auth/google`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: idToken })
      });
      const data = await res.json();
      
      if (!res.ok) throw new Error(data.detail || "Google authentication failed");
      
      setIsAuthenticated(true);
      setShowAuthModal(false);
      
      if (selectedFile) uploadAndAnalyze(selectedFile);
    } catch (err: any) {
      setAuthError(err.message || "An unexpected error occurred");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleGoogleLoginError = () => {
    setAuthError("Google login failed. Please try again.");
  };

  const handleStartAnalysis = async () => {
    if (!selectedFile) {
      setError("Please select a file first.");
      return;
    }
    if (!isAuthenticated) {
      setShowAuthModal(true);
      return;
    }
    await uploadAndAnalyze(selectedFile);
  };

  const uploadAndAnalyze = async (file: File) => {
    setState('analyzing');
    setProgress(5);
    setStatusMessage("Uploading file securely...");
    setError(null);

    const url = URL.createObjectURL(file);
    setAudioUrl(url);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const uploadRes = await fetch(`${API}/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!uploadRes.ok) throw new Error('File upload failed');
      const uploadData = await uploadRes.json();

      const eventSource = new EventSource(`${API}/analyze_stream/${uploadData.file_id}?genre=${encodeURIComponent(selectedGenre)}`);

      eventSource.onmessage = (event) => {
        if (event.data === "heartbeat") return;
        const data = JSON.parse(event.data);
        
        if (data.error) {
          eventSource.close();
          setError(data.error);
          setState('upload');
          return;
        }

        if (data.status === "complete") {
          eventSource.close();
          setProgress(100);
          setStatusMessage("Report Ready!");
          setTimeout(() => {
            setResults(data);
            setState('report');
          }, 500);
        } else {
          setProgress(data.progress);
          setStatusMessage(data.message);
        }
      };

      eventSource.onerror = (err) => {
        if (eventSource.readyState === EventSource.CLOSED) return;
        eventSource.close();
        console.error("SSE Error:", err);
      };

    } catch (err: any) {
      setError(err.message);
      setState('upload');
    }
  };

  const handleReset = () => {
    setState('upload');
    setResults(null);
    setProgress(0);
    setSelectedFile(null);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
  };

  return (
    <div className="min-h-screen bg-[#08080A] text-white font-sans flex flex-col items-center justify-center p-6 transition-colors duration-500 relative">
      
      {showAuthModal && (
        <div className="fixed inset-0 bg-black/90 flex items-center justify-center z-50 p-4 animate-in fade-in">
          <div className="bg-[#1C1C1E] rounded-xl p-8 max-w-sm w-full relative shadow-2xl">
            <button onClick={() => setShowAuthModal(false)} className="absolute top-6 right-6 text-[#6B7280] hover:text-white transition-colors">
              <X className="w-5 h-5" />
            </button>
            
            <h2 className="text-3xl font-bold mb-8 text-center tracking-tight">
              {authMode === 'signup' ? "Sign up" : "Log in"}
            </h2>

            <GoogleLogin
              onSuccess={handleGoogleLoginSuccess}
              onError={handleGoogleLoginError}
              theme="filled_black"
              text="continue_with"
              shape="pill"
              size="large"
              logo_alignment="left"
            />

            <div className="flex items-center text-[#636366] text-sm mb-6">
              <div className="flex-1 border-t border-[#3A3A3C]"></div>
              <span className="px-3">or with Email</span>
              <div className="flex-1 border-t border-[#3A3A3C]"></div>
            </div>

            {authError && (
              <div className="bg-red-900/20 text-red-400 text-sm p-3 rounded mb-4 text-center">
                {authError}
              </div>
            )}

            <form onSubmit={handleAuthSubmit} className="flex flex-col gap-3">
              <input 
                name="email" 
                type="email" 
                ref={emailInputRef} 
                placeholder="Email" 
                required 
                className="w-full bg-[#1C1C1E] border border-[#3A3A3C] text-white p-3 rounded outline-none focus:border-[#F59E0B] transition-colors" 
              />
              
              {authMode === 'signup' && (
                <div className="relative">
                  <input 
                    name="verification" 
                    type="text" 
                    placeholder="Verification code" 
                    required
                    className="w-full bg-[#1C1C1E] border border-[#3A3A3C] text-white p-3 rounded outline-none focus:border-[#F59E0B] transition-colors pr-28" 
                  />
                  <button 
                    type="button"
                    onClick={handleSendCode} 
                    disabled={otpLoading || otpSent}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-sm font-bold text-white hover:text-[#F59E0B] transition-colors disabled:opacity-50"
                  >
                    {otpLoading ? "Sending..." : otpSent ? "Sent!" : "Send Code"}
                  </button>
                </div>
              )}    

              <div className="relative mb-2">
                <input 
                  name="password" 
                  type={showPassword ? "text" : "password"}
                  placeholder="Password" 
                  required 
                  className="w-full bg-[#1C1C1E] border border-[#3A3A3C] text-white p-3 rounded outline-none focus:border-[#F59E0B] transition-colors pr-12" 
                />
                <button 
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-[#636366] hover:text-white transition-colors"
                >
                  <EyeIcon />
                </button>
              </div>
              
              <button 
                type="submit" 
                disabled={authLoading} 
                className="w-full bg-[#10B981] text-black py-3 rounded font-bold mt-2 hover:bg-[#059669] transition-colors disabled:opacity-50 text-lg"
              >
                {authLoading ? "Processing..." : (authMode === 'signup' ? "Sign Up" : "Log In")}
              </button>
            </form>

            <div className="mt-6 text-sm text-[#8E8E93]">
              {authMode === 'signup' ? "Already have an account? " : "Don't have an account? "}
              <button 
                onClick={() => { setAuthMode(authMode === 'signup' ? 'login' : 'signup'); setAuthError(""); }} 
                className="text-white font-bold hover:underline"
              >
                {authMode === 'signup' ? "Log in" : "Sign up"}
              </button>
            </div>

            <div className="mt-8 text-xs text-[#636366] leading-relaxed">
              by continuing, you are agreeing to Divine Decibels's <button className="text-white font-bold hover:underline">Terms of Service</button> and <button className="text-white font-bold hover:underline">Privacy Policy</button>
            </div>
          </div>
        </div>
      )}

      {state === 'upload' && (
        <div className="w-full max-w-2xl flex flex-col items-center animate-in fade-in slide-in-from-bottom-4 duration-700">
          <div className="flex items-center gap-3 mb-4">
            <div className="bg-[#F59E0B] p-1.5 rounded-lg">
              <WaveformIcon className="w-6 h-6 text-black" />
            </div>
            <div className="flex flex-col">
              <span className="text-2xl font-bold tracking-tight leading-none">Mix Oracle</span>
              <span className="text-[10px] text-[#6B7280] font-bold uppercase tracking-widest mt-1">By Divine Decibels</span>
            </div>
          </div>

          <p className="text-[#6B7280] text-center mb-12 text-[15px] font-medium">
            Pre-master diagnostic — your mix health report before it hits the chain
          </p>

          {error && (
            <div className="w-full mb-6 p-4 bg-red-900/20 border border-red-500/50 rounded-xl text-red-400 text-sm text-center">
              {error}
            </div>
          )}

          <input 
            type="file" 
            ref={fileInputRef}
            className="hidden" 
            accept=".wav,.mp3,.aiff,.flac"
            onChange={handleFileChange}
          />

          <div 
            className={`w-full border-2 border-dashed rounded-[24px] p-16 flex flex-col items-center justify-center mb-8 transition-all cursor-pointer group ${
              isDragging ? 'bg-[#1A1A20] border-[#F59E0B]' : 'bg-[#111116] border-[#26262C] hover:border-[#F59E0B]'
            }`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={handleDragOver}
            onDragEnter={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <div className="text-[#F59E0B] mb-6 group-hover:scale-110 transition-transform duration-300">
              <WaveformIcon className="w-12 h-12" />
            </div>
            <h2 className="text-xl font-semibold mb-2">
              {isDragging ? "Drop it!" : "Drop your mix here"}
            </h2>
            <p className="text-[#6B7280] text-sm mb-8">WAV · AIFF · MP3 — stereo mix or pre-master</p>
            <button className="px-6 py-2.5 bg-transparent border border-[#26262C] rounded-lg text-sm font-medium group-hover:bg-[#1A1A20] transition-colors">
              Browse file
            </button>
          </div>

          <div className="w-full mb-8 relative">
            <label className="block text-xs font-bold text-[#6B7280] uppercase mb-2">Target Genre (Calibrates AI & DSP Rules)</label>
            <select 
              value={selectedGenre} 
              onChange={(e) => setSelectedGenre(e.target.value)}
              className="w-full bg-[#111116] border border-[#26262C] rounded-xl p-4 text-white focus:border-[#F59E0B] outline-none transition-colors appearance-none cursor-pointer hover:bg-[#1A1A20] pr-10"
            >
              <option>Pop / Standard</option>
              <option>EDM / Hip-Hop</option>
              <option>Acoustic / Jazz</option>
              <option>Rock / Metal</option>
            </select>
            <div className="absolute right-4 top-[52px] pointer-events-none text-[#6B7280]">
              <svg width="12" height="8" viewBox="0 0 12 8" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M1 1.5L6 6.5L11 1.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
          </div>

          {selectedFile && (
            <p className="text-green-500 text-xs mb-4 font-bold uppercase">
               ✓ {selectedFile.name} ready to analyze
            </p>
          )}

          <button 
            onClick={handleStartAnalysis} 
            className="w-full bg-[#F59E0B] text-black py-4 rounded-xl font-bold text-lg flex items-center justify-center gap-2 hover:bg-[#D97706] hover:scale-[1.01] active:scale-[0.99] transition-all mb-8 shadow-xl shadow-orange-900/10"
          >
            {selectedFile ? `Analyze ${selectedFile.name}` : "Analyse Your Track"} <ArrowRight className="w-5 h-5" />
          </button>

          <p className="text-[#3F3F46] text-xs font-medium">
            Production Ready — Real-time AI analysis engine active
          </p>
        </div>
      )}

      {state === 'analyzing' && <AnalyzingView progress={progress} statusMessage={statusMessage} />}
      
      {state === 'report' && results && <ReportView results={results} audioUrl={audioUrl} onReset={handleReset} />}
    </div>
  );
}

export default App;
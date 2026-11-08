/**
 * SportsBall Precision Audio Trimmer & Waveform Studio
 * Provides Web Audio API waveform decoding, sub-second dual range sliders (step=0.1),
 * fine-tuning nudge buttons (-0.1s / +0.1s), live region preview with stadium fade-out,
 * and seamless form synchronization for walk-up songs and team intro anthems.
 */

class AudioTrimmer {
    constructor(options = {}) {
        this.fileInput = document.getElementById(options.fileInputId || 'audioFileInput');
        this.canvas = document.getElementById(options.canvasId || 'waveformCanvas');
        this.startSlider = document.getElementById(options.startSliderId || 'trimStartSlider');
        this.endSlider = document.getElementById(options.endSliderId || 'trimEndSlider');
        this.startInput = document.getElementById(options.startInputId || 'trimStartInput');
        this.endInput = document.getElementById(options.endInputId || 'trimEndInput');
        this.durationDisplay = document.getElementById(options.durationDisplayId || 'trimDurationDisplay');
        this.hiddenStart = document.getElementById(options.hiddenStartId || 'id_start_seconds');
        this.hiddenDuration = document.getElementById(options.hiddenDurationId || 'id_duration_seconds');
        this.playBtn = document.getElementById(options.playBtnId || 'btnPreviewClip');
        this.stopBtn = document.getElementById(options.stopBtnId || 'btnStopClip');
        this.audioPlayer = document.getElementById(options.audioPlayerId || 'trimmerAudio');

        this.maxClipDuration = options.maxClipDuration || 25.0; // Max allowed ballpark clip in seconds
        this.audioBuffer = null;
        this.audioCtx = null;
        this.currentAudioUrl = null;
        this.isPlaying = false;
        this.playbackTimer = null;
        this.animFrameId = null;
        this.playStartTime = 0;

        this.init();
    }

    init() {
        if (this.fileInput) {
            this.fileInput.addEventListener('change', (e) => this.handleFileSelected(e));
        }

        if (this.startSlider && this.endSlider) {
            this.startSlider.addEventListener('input', () => this.onSliderChange('start'));
            this.endSlider.addEventListener('input', () => this.onSliderChange('end'));
        }

        if (this.startInput && this.endInput) {
            this.startInput.addEventListener('change', () => this.onInputChange('start'));
            this.endInput.addEventListener('change', () => this.onInputChange('end'));
        }

        // Nudge buttons
        const btnStartMinus = document.getElementById('btnStartMinus');
        const btnStartPlus = document.getElementById('btnStartPlus');
        const btnEndMinus = document.getElementById('btnEndMinus');
        const btnEndPlus = document.getElementById('btnEndPlus');

        if (btnStartMinus) btnStartMinus.addEventListener('click', () => this.nudge('start', -0.1));
        if (btnStartPlus) btnStartPlus.addEventListener('click', () => this.nudge('start', 0.1));
        if (btnEndMinus) btnEndMinus.addEventListener('click', () => this.nudge('end', -0.1));
        if (btnEndPlus) btnEndPlus.addEventListener('click', () => this.nudge('end', 0.1));

        if (this.playBtn) {
            this.playBtn.addEventListener('click', () => this.togglePreview());
        }
        if (this.stopBtn) {
            this.stopBtn.addEventListener('click', () => this.stopPreview());
        }

        // Canvas click to seek or drag
        if (this.canvas) {
            this.canvas.addEventListener('click', (e) => this.onCanvasClick(e));
        }
    }

    formatTime(sec) {
        const m = Math.floor(sec / 60);
        const s = (sec % 60).toFixed(1);
        return `${m}:${s.padStart(4, '0')}`;
    }

    getAudioContext() {
        if (!this.audioCtx) {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (AudioContextClass) {
                this.audioCtx = new AudioContextClass();
            }
        }
        return this.audioCtx;
    }

    async loadFromUrl(url, initialStart = 0, initialDur = 12.0) {
        this.stopPreview();
        this.currentAudioUrl = url;
        if (this.audioPlayer) {
            this.audioPlayer.src = url;
        }

        try {
            const resp = await fetch(url);
            const arrayBuffer = await resp.arrayBuffer();
            const ctx = this.getAudioContext();
            if (ctx) {
                this.audioBuffer = await ctx.decodeAudioData(arrayBuffer);
                this.setupSliders(this.audioBuffer.duration, initialStart, initialDur);
                this.drawWaveform();
            } else {
                // Fallback without Web Audio API
                this.setupSliders(180.0, initialStart, initialDur);
            }
        } catch (err) {
            console.warn('Could not decode audio waveform, falling back to direct sliders:', err);
            this.setupSliders(180.0, initialStart, initialDur);
        }
    }

    handleFileSelected(event) {
        const file = event.target.files && event.target.files[0];
        if (!file) return;

        this.stopPreview();
        if (this.currentAudioUrl) {
            URL.revokeObjectURL(this.currentAudioUrl);
        }
        this.currentAudioUrl = URL.createObjectURL(file);
        if (this.audioPlayer) {
            this.audioPlayer.src = this.currentAudioUrl;
        }

        const reader = new FileReader();
        reader.onload = async (e) => {
            const arrayBuffer = e.target.result;
            const ctx = this.getAudioContext();
            if (ctx) {
                try {
                    this.audioBuffer = await ctx.decodeAudioData(arrayBuffer);
                    this.setupSliders(this.audioBuffer.duration, 0, Math.min(12.0, this.audioBuffer.duration));
                    this.drawWaveform();
                } catch (decodeErr) {
                    console.error('Error decoding audio buffer:', decodeErr);
                    this.setupSliders(180.0, 0, 12.0);
                }
            }
        };
        reader.readAsArrayBuffer(file);
    }

    setupSliders(totalSeconds, start = 0, duration = 12.0) {
        const maxTime = Math.max(1.0, parseFloat(totalSeconds.toFixed(1)));
        const startVal = Math.max(0.0, Math.min(parseFloat(start) || 0.0, maxTime - 1.0));
        const durVal = Math.max(1.0, Math.min(parseFloat(duration) || 12.0, this.maxClipDuration));
        const endVal = Math.min(maxTime, parseFloat((startVal + durVal).toFixed(1)));

        if (this.startSlider) {
            this.startSlider.min = '0';
            this.startSlider.max = maxTime.toString();
            this.startSlider.step = '0.1';
            this.startSlider.value = startVal.toFixed(1);
        }
        if (this.endSlider) {
            this.endSlider.min = '0';
            this.endSlider.max = maxTime.toString();
            this.endSlider.step = '0.1';
            this.endSlider.value = endVal.toFixed(1);
        }

        this.syncInputsAndDisplay();
    }

    onSliderChange(source) {
        let start = parseFloat(this.startSlider.value) || 0;
        let end = parseFloat(this.endSlider.value) || 0;

        if (source === 'start') {
            if (start >= end) {
                end = Math.min(parseFloat(this.endSlider.max), parseFloat((start + 1.0).toFixed(1)));
                this.endSlider.value = end.toFixed(1);
            }
            if (end - start > this.maxClipDuration) {
                end = parseFloat((start + this.maxClipDuration).toFixed(1));
                this.endSlider.value = end.toFixed(1);
            }
        } else {
            if (end <= start) {
                start = Math.max(0, parseFloat((end - 1.0).toFixed(1)));
                this.startSlider.value = start.toFixed(1);
            }
            if (end - start > this.maxClipDuration) {
                start = parseFloat((end - this.maxClipDuration).toFixed(1));
                this.startSlider.value = start.toFixed(1);
            }
        }

        this.syncInputsAndDisplay();
        this.drawWaveform();
    }

    onInputChange(source) {
        let start = parseFloat(this.startInput.value) || 0;
        let end = parseFloat(this.endInput.value) || 0;
        const maxTime = parseFloat(this.startSlider.max) || 300;

        start = Math.max(0, Math.min(start, maxTime - 1));
        end = Math.max(start + 0.5, Math.min(end, maxTime));

        if (end - start > this.maxClipDuration) {
            if (source === 'start') {
                end = start + this.maxClipDuration;
            } else {
                start = end - this.maxClipDuration;
            }
        }

        this.startSlider.value = start.toFixed(1);
        this.endSlider.value = end.toFixed(1);
        this.syncInputsAndDisplay();
        this.drawWaveform();
    }

    nudge(target, delta) {
        if (target === 'start') {
            let val = (parseFloat(this.startSlider.value) || 0) + delta;
            val = Math.max(0, Math.min(val, (parseFloat(this.endSlider.value) || 1) - 0.5));
            this.startSlider.value = val.toFixed(1);
            this.onSliderChange('start');
        } else {
            let val = (parseFloat(this.endSlider.value) || 0) + delta;
            val = Math.max((parseFloat(this.startSlider.value) || 0) + 0.5, Math.min(val, parseFloat(this.endSlider.max)));
            this.endSlider.value = val.toFixed(1);
            this.onSliderChange('end');
        }
    }

    syncInputsAndDisplay() {
        const start = parseFloat(this.startSlider.value) || 0;
        const end = parseFloat(this.endSlider.value) || 0;
        const duration = parseFloat((end - start).toFixed(1));

        if (this.startInput) this.startInput.value = start.toFixed(1);
        if (this.endInput) this.endInput.value = end.toFixed(1);

        if (this.durationDisplay) {
            this.durationDisplay.textContent = `${duration.toFixed(1)}s`;
        }

        if (this.hiddenStart) this.hiddenStart.value = start.toFixed(1);
        if (this.hiddenDuration) this.hiddenDuration.value = duration.toFixed(1);

        const readoutBadge = document.getElementById('trimmerReadout');
        if (readoutBadge) {
            readoutBadge.textContent = `${this.formatTime(start)} → ${this.formatTime(end)} (${duration.toFixed(1)}s)`;
        }
    }

    drawWaveform(currentPlayPos = null) {
        if (!this.canvas || !this.audioBuffer) return;
        const ctx = this.canvas.getContext('2d');
        const width = this.canvas.width = this.canvas.parentElement.clientWidth || 600;
        const height = this.canvas.height = 100;

        ctx.clearRect(0, 0, width, height);

        const data = this.audioBuffer.getChannelData(0);
        const step = Math.ceil(data.length / width);
        const amp = height / 2;

        const totalSec = this.audioBuffer.duration;
        const startSec = parseFloat(this.startSlider.value) || 0;
        const endSec = parseFloat(this.endSlider.value) || totalSec;

        const startX = (startSec / totalSec) * width;
        const endX = (endSec / totalSec) * width;

        // Background
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, 0, width, height);

        // Active region highlight
        ctx.fillStyle = 'rgba(37, 99, 235, 0.25)';
        ctx.fillRect(startX, 0, endX - startX, height);

        // Draw waveform bars
        for (let i = 0; i < width; i++) {
            let min = 1.0;
            let max = -1.0;
            for (let j = 0; j < step; j++) {
                const datum = data[(i * step) + j];
                if (datum < min) min = datum;
                if (datum > max) max = datum;
            }

            const isSelected = i >= startX && i <= endX;
            ctx.fillStyle = isSelected ? '#38bdf8' : '#475569';
            ctx.fillRect(i, (1 + min) * amp, 1, Math.max(1, (max - min) * amp));
        }

        // Region boundary markers
        ctx.strokeStyle = '#2563eb';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(startX, 0); ctx.lineTo(startX, height);
        ctx.moveTo(endX, 0); ctx.lineTo(endX, height);
        ctx.stroke();

        // Playhead scrubber needle if currently playing
        if (currentPlayPos !== null && currentPlayPos >= startSec && currentPlayPos <= endSec) {
            const playX = (currentPlayPos / totalSec) * width;
            ctx.strokeStyle = '#f59e0b';
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(playX, 0);
            ctx.lineTo(playX, height);
            ctx.stroke();
        }
    }

    onCanvasClick(e) {
        if (!this.canvas || !this.audioBuffer) return;
        const rect = this.canvas.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const ratio = Math.max(0, Math.min(1, clickX / rect.width));
        const clickedSec = parseFloat((ratio * this.audioBuffer.duration).toFixed(1));

        const start = parseFloat(this.startSlider.value) || 0;
        const end = parseFloat(this.endSlider.value) || 0;
        const dur = end - start;

        // Shift region around clicked point
        const newStart = Math.max(0, Math.min(clickedSec, this.audioBuffer.duration - dur));
        this.startSlider.value = newStart.toFixed(1);
        this.endSlider.value = (newStart + dur).toFixed(1);
        this.syncInputsAndDisplay();
        this.drawWaveform();
    }

    togglePreview() {
        if (this.isPlaying) {
            this.stopPreview();
        } else {
            this.playPreview();
        }
    }

    playPreview() {
        if (!this.audioPlayer || !this.audioPlayer.src) return;

        const startSec = parseFloat(this.startSlider.value) || 0;
        const endSec = parseFloat(this.endSlider.value) || (startSec + 12);
        const durationSec = endSec - startSec;

        this.stopPreview();
        this.isPlaying = true;
        if (this.playBtn) this.playBtn.innerHTML = '⏸️ Pause';

        this.audioPlayer.currentTime = startSec;
        this.audioPlayer.volume = 1.0;
        this.audioPlayer.play().catch(e => console.warn('Audio play prevented:', e));

        const fadeOutDuration = 1.0; // 1-second stadium fadeout
        const fadeStartTime = Math.max(startSec, endSec - fadeOutDuration);

        const stepAnim = () => {
            if (!this.isPlaying) return;
            const curTime = this.audioPlayer.currentTime;

            // Apply fade-out in final 1s
            if (curTime >= fadeStartTime && curTime <= endSec) {
                const remaining = endSec - curTime;
                this.audioPlayer.volume = Math.max(0.05, remaining / fadeOutDuration);
            }

            if (curTime >= endSec || this.audioPlayer.ended) {
                this.stopPreview();
                return;
            }

            this.drawWaveform(curTime);
            this.animFrameId = requestAnimationFrame(stepAnim);
        };

        this.animFrameId = requestAnimationFrame(stepAnim);
    }

    stopPreview() {
        this.isPlaying = false;
        if (this.animFrameId) {
            cancelAnimationFrame(this.animFrameId);
            this.animFrameId = null;
        }
        if (this.audioPlayer) {
            this.audioPlayer.pause();
            this.audioPlayer.volume = 1.0;
        }
        if (this.playBtn) {
            const dur = parseFloat(this.hiddenDuration ? this.hiddenDuration.value : 12).toFixed(1);
            this.playBtn.innerHTML = `▶️ Preview Cut (${dur}s)`;
        }
        this.drawWaveform(null);
    }
}

// Global initialization helper
window.AudioTrimmer = AudioTrimmer;

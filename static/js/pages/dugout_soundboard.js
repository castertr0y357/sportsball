/**
 * Dugout Soundboard & Stadium PA Announcer Engine
 * Provides 3-channel audio mixing with automatic ducking, emergency killswitch,
 * soundboard loop effects (Yakety Sax), and chained batter intro announcements.
 */

(function(window) {
    'use strict';

    // Audio Channels
    let announcerAudio = null;
    let walkupAudio = null;
    let soundboardAudio = null;

    let activeSoundboardSlug = null;
    let duckingTimer = null;
    const STORAGE_PREFIX = `sportsball_audio_${window.GAME_ID || 0}`;

    // Volume levels
    const MASTER_VOL = 1.0;
    const DUCKED_VOL = 0.20;

    function initChannels() {
        if (!announcerAudio) {
            announcerAudio = document.getElementById('dugout-announcer-audio') || new Audio();
            announcerAudio.id = 'dugout-announcer-audio';
        }
        if (!walkupAudio) {
            walkupAudio = document.getElementById('dugout-walkup-audio') || new Audio();
            walkupAudio.id = 'dugout-walkup-audio';
        }
        if (!soundboardAudio) {
            soundboardAudio = document.getElementById('dugout-soundboard-audio') || new Audio();
            soundboardAudio.id = 'dugout-soundboard-audio';
        }
    }

    function isCommentaryEnabled() {
        const stored = localStorage.getItem(`${STORAGE_PREFIX}_commentary`);
        // Default to false (opt-in comedy commentary)
        return stored === 'true';
    }

    function setCommentaryEnabled(enabled) {
        localStorage.setItem(`${STORAGE_PREFIX}_commentary`, enabled ? 'true' : 'false');
        const chk = document.getElementById('chk-commentary-enabled');
        if (chk) chk.checked = enabled;
    }

    function isAutoIntroEnabled() {
        const chk = document.getElementById('auto-walkup-toggle');
        return chk ? chk.checked : true;
    }

    // Duck Channel 2 & 3 while Channel 1 (Announcer) is speaking
    function duckBackgroundAudio() {
        if (soundboardAudio) soundboardAudio.volume = DUCKED_VOL;
        if (walkupAudio) walkupAudio.volume = DUCKED_VOL;
    }

    function unduckBackgroundAudio() {
        if (soundboardAudio) soundboardAudio.volume = 0.90 * MASTER_VOL;
        if (walkupAudio) walkupAudio.volume = MASTER_VOL;
    }

    // Emergency Stop / Killswitch
    function stopAllAudio() {
        initChannels();
        if (announcerAudio) {
            announcerAudio.pause();
            announcerAudio.currentTime = 0;
        }
        if (walkupAudio) {
            walkupAudio.pause();
            walkupAudio.currentTime = 0;
        }
        if (soundboardAudio) {
            soundboardAudio.pause();
            soundboardAudio.currentTime = 0;
            soundboardAudio.loop = false;
        }
        if (window.walkupTimer) {
            clearTimeout(window.walkupTimer);
            window.walkupTimer = null;
        }
        activeSoundboardSlug = null;
        unduckBackgroundAudio();

        // Remove active pulsing styling from soundboard buttons
        document.querySelectorAll('.soundboard-btn.active-looping').forEach(el => {
            el.classList.remove('active-looping');
        });

        // Hide announcer badge
        const badge = document.getElementById('announcer-active-badge');
        if (badge) badge.style.display = 'none';
    }

    // Play Voice Announcer Clip (Channel 1 with Ducking)
    function playAnnouncerClip(audioUrl, transcript, onComplete) {
        initChannels();
        const badge = document.getElementById('announcer-active-badge');
        if (badge) {
            badge.textContent = `🎙️ "${transcript || 'Announcing...'}"`;
            badge.style.display = 'inline-block';
        }

        // If audio file doesn't exist, use browser local speech synthesis fallback
        if (!audioUrl) {
            if ('speechSynthesis' in window && transcript) {
                duckBackgroundAudio();
                const utter = new SpeechSynthesisUtterance(transcript);
                utter.rate = 1.05;
                utter.onend = () => {
                    unduckBackgroundAudio();
                    if (badge) badge.style.display = 'none';
                    if (onComplete) onComplete();
                };
                utter.onerror = () => {
                    unduckBackgroundAudio();
                    if (badge) badge.style.display = 'none';
                    if (onComplete) onComplete();
                };
                window.speechSynthesis.speak(utter);
            } else {
                if (badge) badge.style.display = 'none';
                if (onComplete) onComplete();
            }
            return;
        }

        // Play recorded clip
        duckBackgroundAudio();
        announcerAudio.src = audioUrl;
        announcerAudio.volume = MASTER_VOL;

        announcerAudio.onended = () => {
            unduckBackgroundAudio();
            if (badge) badge.style.display = 'none';
            if (onComplete) onComplete();
        };

        announcerAudio.onerror = () => {
            unduckBackgroundAudio();
            if (badge) badge.style.display = 'none';
            if (onComplete) onComplete();
        };

        announcerAudio.play().catch(() => {
            unduckBackgroundAudio();
            if (badge) badge.style.display = 'none';
            if (onComplete) onComplete();
        });
    }

    // Play Soundboard FX (Channel 3)
    function playSoundboardEffect(slug) {
        initChannels();
        const effects = window.SOUNDBOARD_EFFECTS || [];
        const fx = effects.find(item => item.slug === slug);
        if (!fx || !fx.audio_url) return;

        const btn = document.getElementById(`btn-sb-${slug}`);

        // If this loop effect is already active, tapping it acts as toggle stop
        if (activeSoundboardSlug === slug) {
            stopAllAudio();
            return;
        }

        // Stop previous soundboard effect before starting new one
        if (soundboardAudio) {
            soundboardAudio.pause();
            soundboardAudio.currentTime = 0;
        }

        document.querySelectorAll('.soundboard-btn.active-looping').forEach(el => {
            el.classList.remove('active-looping');
        });

        activeSoundboardSlug = slug;
        soundboardAudio.src = fx.audio_url;
        soundboardAudio.loop = !!fx.loop_mode;
        soundboardAudio.volume = 0.90 * MASTER_VOL;

        if (fx.loop_mode && btn) {
            btn.classList.add('active-looping');
        }

        soundboardAudio.onended = () => {
            if (activeSoundboardSlug === slug) {
                activeSoundboardSlug = null;
            }
            if (btn) btn.classList.remove('active-looping');
        };

        soundboardAudio.onerror = () => {
            activeSoundboardSlug = null;
            if (btn) btn.classList.remove('active-looping');
        };

        soundboardAudio.play().catch(() => {});
    }

    // Chained Batter Intro + Walk-Up Music
    function handleBatterSequence(batterIntro, walkupCallback) {
        if (!isAutoIntroEnabled()) return;

        if (batterIntro && (batterIntro.audio_url || batterIntro.transcript)) {
            playAnnouncerClip(batterIntro.audio_url, batterIntro.transcript, () => {
                if (walkupCallback) walkupCallback();
            });
        } else {
            if (walkupCallback) walkupCallback();
        }
    }

    // Handle Scoring Action Play Announcement
    function handlePlayAnnouncement(announcement) {
        if (!announcement || !isCommentaryEnabled()) return;
        playAnnouncerClip(announcement.audio_url, announcement.transcript);
    }

    // Drawer Toggle & Rendering
    function toggleSoundboardDrawer() {
        const drawer = document.getElementById('soundboardDrawer');
        if (!drawer) return;
        const isHidden = drawer.style.display === 'none' || drawer.style.display === '';
        drawer.style.display = isHidden ? 'block' : 'none';

        if (isHidden) {
            renderSoundboardButtons();
            const chk = document.getElementById('chk-commentary-enabled');
            if (chk) chk.checked = isCommentaryEnabled();
        }
    }

    function renderSoundboardButtons() {
        const effects = window.SOUNDBOARD_EFFECTS || [];
        const chaosContainer = document.getElementById('soundboard-chaos-buttons');
        const rallyContainer = document.getElementById('soundboard-rally-buttons');

        if (!chaosContainer || !rallyContainer) return;

        const chaosEffects = effects.filter(e => e.category === 'chaos');
        const rallyEffects = effects.filter(e => e.category !== 'chaos');

        const makeButtonHtml = (fx) => `
            <button type="button" id="btn-sb-${fx.slug}" class="btn btn-secondary soundboard-btn"
                    onclick="window.DugoutSoundboard.playSoundboardEffect('${fx.slug}')"
                    title="${fx.hotkey ? 'Hotkey: ' + fx.hotkey : ''}"
                    style="text-align:left; display:flex; flex-direction:column; padding:0.6rem 0.75rem; border-radius:8px; border:1px solid var(--border);">
                <div style="font-weight:700; font-size:0.92rem; display:flex; justify-content:space-between; align-items:center;">
                    <span>${fx.icon} ${fx.name}</span>
                    ${fx.hotkey ? `<kbd style="font-size:0.7rem; background:rgba(0,0,0,0.15); padding:1px 5px; border-radius:4px;">${fx.hotkey}</kbd>` : ''}
                </div>
                <small style="color:var(--text-muted); font-size:0.76rem; margin-top:0.2rem;">
                    ${fx.loop_mode ? '🔄 Loops until stopped' : `${fx.duration || 3}s audio stinger`}
                </small>
            </button>
        `;

        chaosContainer.innerHTML = chaosEffects.map(makeButtonHtml).join('');
        rallyContainer.innerHTML = rallyEffects.map(makeButtonHtml).join('');
    }

    // Keyboard Shortcuts Listener
    document.addEventListener('keydown', (e) => {
        // Ignore if user is typing in an input or textarea
        if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
            return;
        }

        if (e.key === 'Escape') {
            stopAllAudio();
            return;
        }

        const key = e.key.toUpperCase();
        if (key === 'P') playSoundboardEffect('yakety_sax');
        else if (key === 'C') playSoundboardEffect('organ_charge');
        else if (key === 'S') playSoundboardEffect('sad_trombone');
        else if (key === 'H') playSoundboardEffect('foghorn');
        else if (key === 'B') playSoundboardEffect('boomshakalaka');
        else if (key === 'M') playSoundboardEffect('madden_boom');
    });

    // Offline Cache Storage for Audio Packs
    async function preCacheSoundboardAudio() {
        const btn = document.getElementById('btn-cache-soundboard');
        if (btn) btn.textContent = '⏳ Caching Audio...';

        try {
            if ('caches' in window) {
                const cache = await caches.open('sportsball-soundboard-v1');
                const urlsToCache = [];
                (window.SOUNDBOARD_EFFECTS || []).forEach(fx => {
                    if (fx.audio_url) urlsToCache.push(fx.audio_url);
                });
                await Promise.allSettled(urlsToCache.map(url => cache.add(url)));
                if (btn) btn.textContent = '✓ Audio Cached Offline';
            }
        } catch (e) {
            if (btn) btn.textContent = 'Pre-Cache Audio';
        }
    }

    // Initial DOM binding
    document.addEventListener('DOMContentLoaded', () => {
        renderSoundboardButtons();
        const chk = document.getElementById('chk-commentary-enabled');
        if (chk) chk.checked = isCommentaryEnabled();
    });

    // Export to global window namespace
    window.DugoutSoundboard = {
        initChannels,
        stopAllAudio,
        playAnnouncerClip,
        playSoundboardEffect,
        handleBatterSequence,
        handlePlayAnnouncement,
        toggleSoundboardDrawer,
        setCommentaryEnabled,
        isCommentaryEnabled,
        preCacheSoundboardAudio,
    };

})(window);

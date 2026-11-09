/**
 * Dugout Scoring Console - Interactive Single Page Scoring Engine
 * Manages baseball/softball diamond animation, runner drag/drop, pitch counts,
 * court game clocks, audio walk-up fanfare synthesizer, and offline sync queue.
 */
let walkupTimer = null;
let wakeLock = null;

// Screen Wake Lock API
async function requestScreenWakeLock() {
    if ('wakeLock' in navigator) {
        try {
            wakeLock = await navigator.wakeLock.request('screen');
            const badge = document.getElementById('wake-lock-badge');
            if (badge) badge.style.display = 'inline-block';
            wakeLock.addEventListener('release', () => {
                if (badge) badge.style.display = 'none';
            });
        } catch (err) {}
    }
}
document.addEventListener('visibilitychange', async () => {
    if (wakeLock !== null && document.visibilityState === 'visible') {
        await requestScreenWakeLock();
    }
});
requestScreenWakeLock();

// Console Mode (Simple vs Detailed)
function setConsoleMode(mode) {
    localStorage.setItem(MODE_STORAGE_KEY, mode);
    const simpleBtn = document.getElementById('btn-mode-simple');
    const detailedBtn = document.getElementById('btn-mode-detailed');
    const simpleSec = document.getElementById('simple-mode-section');
    const detailedSec = document.getElementById('detailed-mode-section');
    const countWrap = document.getElementById('count-tracker-wrap');

    if (mode === 'simple') {
        simpleBtn.classList.add('active');
        detailedBtn.classList.remove('active');
        simpleSec.style.display = 'block';
        detailedSec.style.display = 'none';
        countWrap.style.display = 'none';
    } else {
        detailedBtn.classList.add('active');
        simpleBtn.classList.remove('active');
        simpleSec.style.display = 'none';
        detailedSec.style.display = 'block';
        if (gameState.is_diamond_sport) countWrap.style.display = 'inline-block';
    }
}

// Bleacher Sun Mode
function toggleBleacherMode() {
    document.body.classList.toggle('bleacher-mode');
}

// Runner Base Modal
let selectedBase = null;
function handleBaseClick(base) {
    selectedBase = base;
    const isOccupied = (base === '1B' && gameState.runner_on_first) ||
                       (base === '2B' && gameState.runner_on_second) ||
                       (base === '3B' && gameState.runner_on_third);
    if (!isOccupied) {
        // Direct toggle if empty
        sendAction('toggle_base', {base: base});
    } else {
        document.getElementById('runnerBaseLabel').textContent = base;
        const advBtn = document.getElementById('btn-advance-base');
        if (base === '1B') advBtn.textContent = 'Advance to 2nd Base &rarr;';
        else if (base === '2B') advBtn.textContent = 'Advance to 3rd Base &rarr;';
        else if (base === '3B') advBtn.textContent = 'Advance Home (+1 Run) &rarr;';
        document.getElementById('runnerModal').style.display = 'flex';
    }
}
function closeRunnerModal() {
    document.getElementById('runnerModal').style.display = 'none';
    selectedBase = null;
}
function executeRunnerAction(act) {
    if (!selectedBase) return;
    const base = selectedBase;
    closeRunnerModal();
    if (act === 'advance') {
        const to = base === '1B' ? '2B' : (base === '2B' ? '3B' : 'home');
        sendAction('advance_runner', {from_base: base, to_base: to});
    } else if (act === 'score') {
        sendAction('advance_runner', {from_base: base, to_base: 'home'});
    } else if (act === 'out') {
        sendAction('advance_runner', {from_base: base, to_base: 'out'});
    } else if (act === 'toggle') {
        sendAction('toggle_base', {base: base});
    }
}

// Dispute Modal
function openDisputeModal() {
    document.getElementById('disputeModal').style.display = 'flex';
}
function closeDisputeModal() {
    document.getElementById('disputeModal').style.display = 'none';
}
function submitDispute() {
    const notes = document.getElementById('disputeNotesInput').value.trim();
    if (!notes) { alert('Please enter notes regarding the rule protest.'); return; }
    closeDisputeModal();
    sendAction('flag_dispute', {notes: notes});
}

// Forfeit Modal
function openForfeitModal() {
    document.getElementById('forfeitModal').style.display = 'flex';
}
function closeForfeitModal() {
    document.getElementById('forfeitModal').style.display = 'none';
}
function submitForfeit() {
    const winnerId = document.getElementById('forfeitWinnerSelect').value;
    const reason = document.getElementById('forfeitReasonInput').value.trim();
    if (!confirm('Confirm recording an official forfeit? This will mark the game completed.')) return;
    closeForfeitModal();
    sendAction('record_forfeit', {winner_id: winnerId, notes: reason});
}

// Offline Queue Management
function getOfflineQueue() {
    try {
        const raw = localStorage.getItem(QUEUE_STORAGE_KEY);
        return raw ? JSON.parse(raw) : [];
    } catch (e) {
        return [];
    }
}

function pushOfflineQueue(actionItem) {
    const queue = getOfflineQueue();
    queue.push(actionItem);
    try {
        localStorage.setItem(QUEUE_STORAGE_KEY, JSON.stringify(queue));
    } catch (e) {}
    updateQueueIndicator();
}

function clearOfflineQueue() {
    localStorage.removeItem(QUEUE_STORAGE_KEY);
    updateQueueIndicator();
}

function updateQueueIndicator() {
    const queue = getOfflineQueue();
    const qInd = document.getElementById('queue-indicator');
    const syncBtn = document.getElementById('btn-sync-now');
    if (queue.length > 0) {
        qInd.style.display = 'inline-block';
        qInd.textContent = `${queue.length} action${queue.length === 1 ? '' : 's'} pending sync`;
        syncBtn.style.display = 'inline-block';
    } else {
        qInd.style.display = 'none';
        syncBtn.style.display = 'none';
    }
}

function updateConnectionBadge() {
    const connInd = document.getElementById('conn-indicator');
    if (navigator.onLine) {
        connInd.className = 'badge badge-success';
        connInd.textContent = '● Online (Connected)';
        flushOfflineQueue();
    } else {
        connInd.className = 'badge badge-warning';
        connInd.textContent = '○ Offline (Dugout Local Mode)';
    }
}

window.addEventListener('online', updateConnectionBadge);
window.addEventListener('offline', updateConnectionBadge);

async function precacheGameForOffline() {
    const cacheBtn = document.getElementById('btn-precache');
    const cacheInd = document.getElementById('cache-indicator');
    cacheBtn.disabled = true;
    cacheInd.textContent = 'Caching walk-up songs...';

    const urlsToCache = [];
    if (window.caches) {
        try {
            const cache = await caches.open('csl-audio-v1');
            let cachedCount = 0;

            if (gameState.current_batter && gameState.current_batter.walkup_song_url) {
                urlsToCache.push(gameState.current_batter.walkup_song_url);
            }
            if (gameState.on_deck_batter && gameState.on_deck_batter.walkup_song_url) {
                urlsToCache.push(gameState.on_deck_batter.walkup_song_url);
            }

            for (const url of urlsToCache) {
                if (url) {
                    try {
                        const res = await fetch(url);
                        if (res.ok) {
                            await cache.put(url, res);
                            cachedCount++;
                        }
                    } catch (err) {}
                }
            }

            cacheInd.className = 'badge badge-success';
            cacheInd.textContent = `✓ Offline Ready (${cachedCount} songs cached)`;
            cacheBtn.textContent = '✓ Audio Cached';
        } catch (e) {
            cacheInd.textContent = 'Cache complete';
        }
    } else {
        cacheInd.textContent = 'Browser caching active';
    }
    cacheBtn.disabled = false;
}

function stopWalkupAudio() {
    const audio = document.getElementById('dugout-walkup-audio');
    if (walkupTimer) clearTimeout(walkupTimer);
    if (audio) {
        audio.pause();
        audio.volume = 1.0;
    }
}

function playCurrentWalkup() {
    const batter = gameState.current_batter;
    if (!batter || !batter.walkup_song_url) return;
    const audio = document.getElementById('dugout-walkup-audio');
    stopWalkupAudio();

    audio.src = batter.walkup_song_url;
    const startSec = parseFloat(batter.walkup_start_seconds) || 0;
    const durationSec = parseFloat(batter.walkup_duration_seconds) || 12;

    audio.onloadedmetadata = () => {
        audio.currentTime = Math.min(startSec, Math.max(0, audio.duration - 1));
        audio.volume = 1.0;
        audio.play().catch(() => {});
    };
    audio.load();

    walkupTimer = setTimeout(() => {
        stopWalkupAudio();
    }, durationSec * 1000);
}

function playTeamIntro(whichTeam) {
    const intro = whichTeam === 'team1' ? gameState.team1_intro : gameState.team2_intro;
    if (!intro || !intro.url) return;
    const audio = document.getElementById('dugout-walkup-audio');
    stopWalkupAudio();

    audio.src = intro.url;
    const startSec = parseFloat(intro.start) || 0;
    const durationSec = parseFloat(intro.duration) || 15;

    audio.onloadedmetadata = () => {
        audio.currentTime = Math.min(startSec, Math.max(0, audio.duration - 1));
        audio.volume = 1.0;
        audio.play().catch(() => {});
    };
    audio.load();

    walkupTimer = setTimeout(() => {
        stopWalkupAudio();
    }, durationSec * 1000);
}

// Quick Substitutions
let currentSubOutEntryId = null;
let currentSubContainerId = null;

function openSubModal(outEntryId, outPlayerName, containerId) {
    currentSubOutEntryId = outEntryId;
    currentSubContainerId = containerId;
    document.getElementById('subOutPlayerName').textContent = outPlayerName;

    const select = document.getElementById('subIncomingSelect');
    select.innerHTML = '';

    const isTeam1 = containerId.includes('team1');
    const lineup = isTeam1 ? (gameState.team1_lineup || []) : (gameState.team2_lineup || []);
    const bench = lineup.filter(p => !p.is_present);

    if (!bench.length) {
        select.innerHTML = '<option value="">-- No bench players available --</option>';
    } else {
        bench.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.entry_id;
            opt.textContent = `${p.name} ${p.jersey ? '#' + p.jersey : ''}`;
            select.appendChild(opt);
        });
    }

    document.getElementById('subModal').style.display = 'flex';
}

function closeSubModal() {
    document.getElementById('subModal').style.display = 'none';
}

function confirmSub() {
    const inEntryId = document.getElementById('subIncomingSelect').value;
    if (!inEntryId) {
        alert("Please select a bench player to substitute in.");
        return;
    }
    closeSubModal();
    sendAction('substitute_player', {
        out_entry_id: currentSubOutEntryId,
        in_entry_id: inEntryId
    });
}

function renderLineup(containerId, lineup, currentBatterId) {
    const container = document.getElementById(containerId);
    if (!lineup || !lineup.length) {
        container.innerHTML = '<p style="color:var(--text-muted);">No players on roster.</p>';
        return;
    }
    container.innerHTML = lineup.map((item, idx) => {
        const isAtBat = currentBatterId && item.player_id === currentBatterId;
        const rowClass = `lineup-row ${!item.is_present ? 'absent' : ''} ${isAtBat ? 'at-bat' : ''}`;
        const jersey = item.jersey !== null && item.jersey !== undefined ? `#${item.jersey}` : '';
        const songBadge = item.walkup_title
            ? `<span class="badge badge-primary" title="${item.walkup_title}">&#9835; ${item.walkup_title}</span>`
            : '';
        return `
            <div class="${rowClass}">
                <div style="display:flex; align-items:center; gap:0.5rem;">
                    <input type="checkbox" ${item.is_present ? 'checked' : ''}
                           onchange="sendAction('toggle_attendance', {entry_id: ${item.entry_id}})"
                           title="Toggle Game-Day Attendance" style="width:auto;">
                    <span><strong>${idx + 1}.</strong> ${item.name} ${jersey}</span>
                    ${songBadge}
                </div>
                <div style="display:flex; gap:0.25rem; align-items:center;">
                    <button type="button" class="btn btn-sm btn-secondary" style="font-size:0.75rem; padding:0.2rem 0.45rem;" onclick="openSubModal(${item.entry_id}, '${item.name.replace(/'/g, "\\'")}', '${containerId}')" title="Substitute Player">Sub</button>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="sendAction('move_lineup', {entry_id: ${item.entry_id}, direction: 'up'})">&uarr;</button>
                    <button type="button" class="btn btn-sm btn-secondary" onclick="sendAction('move_lineup', {entry_id: ${item.entry_id}, direction: 'down'})">&darr;</button>
                </div>
            </div>
        `;
    }).join('');
}

function renderState(state) {
    gameState = state;
    try {
        localStorage.setItem(STATE_STORAGE_KEY, JSON.stringify(state));
    } catch (e) {}

    document.getElementById('team1-score').textContent = state.team1_score;
    document.getElementById('team2-score').textContent = state.team2_score;
    document.getElementById('team1-hits').textContent = state.team1_hits;
    document.getElementById('team2-hits').textContent = state.team2_hits;

    const isDiamond = state.is_diamond_sport !== undefined ? state.is_diamond_sport : true;
    const scoreLabel = state.score_label || 'Pts';
    const periodLabel = state.period_label || 'Period';
    const isBasketball = (state.sport === 'basketball');
    const isVolleyball = (state.sport === 'volleyball');

    // Adapt UI for Diamond Sports vs Court/Field Sports
    document.getElementById('diamond-section').style.display = isDiamond ? 'block' : 'none';
    document.getElementById('non-diamond-quick-score').style.display = isDiamond ? 'none' : 'block';
    document.getElementById('outs-container').style.display = isDiamond ? 'inline' : 'none';
    document.getElementById('diamond-action-grid').style.display = isDiamond ? 'grid' : 'none';
    document.getElementById('court-action-grid').style.display = isDiamond ? 'none' : 'grid';
    document.getElementById('count-buttons-strip').style.display = isDiamond ? 'block' : 'none';

    // Basketball specifics
    document.getElementById('basketball-court-controls').style.display = isBasketball ? 'block' : 'none';
    document.getElementById('team1-bonus-wrap').style.display = isBasketball ? 'block' : 'none';
    document.getElementById('team2-bonus-wrap').style.display = isBasketball ? 'block' : 'none';
    if (isBasketball) {
        document.getElementById('team1-fouls-val').textContent = state.team1_fouls || 0;
        document.getElementById('team2-fouls-val').textContent = state.team2_fouls || 0;
        const b1 = document.getElementById('team1-bonus-badge');
        if (state.team1_double_bonus) { b1.textContent = 'DOUBLE BONUS'; b1.className = 'bonus-badge double-bonus-active'; }
        else if (state.team1_bonus) { b1.textContent = 'BONUS (1-and-1)'; b1.className = 'bonus-badge bonus-active'; }
        else { b1.textContent = ''; b1.className = 'bonus-badge'; }

        const b2 = document.getElementById('team2-bonus-badge');
        if (state.team2_double_bonus) { b2.textContent = 'DOUBLE BONUS'; b2.className = 'bonus-badge double-bonus-active'; }
        else if (state.team2_bonus) { b2.textContent = 'BONUS (1-and-1)'; b2.className = 'bonus-badge bonus-active'; }
        else { b2.textContent = ''; b2.className = 'bonus-badge'; }
    }

    // Volleyball specifics
    document.getElementById('volleyball-court-controls').style.display = isVolleyball ? 'block' : 'none';
    if (isVolleyball && state.volleyball_sets && state.volleyball_sets.length) {
        const setLines = state.volleyball_sets.map(s => `Set ${s.set}: ${s.winner} (${s.team1_score}-${s.team2_score})`).join(' &bull; ');
        document.getElementById('volleyball-sets-summary').innerHTML = `<strong>Sets Completed:</strong> ${setLines}`;
    }

    // Inning Run Limit Banner
    const runLimitBadge = document.getElementById('run-limit-badge');
    const runLimitBanner = document.getElementById('inning-run-limit-banner');
    if (isDiamond && state.inning_run_limit) {
        runLimitBadge.style.display = 'inline-block';
        runLimitBadge.textContent = `${state.inning_run_limit}-Run Max Inning`;
        runLimitBanner.style.display = 'block';
        document.getElementById('inning-run-count').textContent = state.current_half_runs || 0;
        document.getElementById('inning-run-max').textContent = state.inning_run_limit;
    } else {
        runLimitBadge.style.display = 'none';
        runLimitBanner.style.display = 'none';
    }

    // Mercy Rule Banner
    const mercyBanner = document.getElementById('mercy-rule-banner');
    if (state.mercy_rule_alert && state.mercy_rule_alert.triggered) {
        mercyBanner.style.display = 'flex';
        document.getElementById('mercy-rule-msg').textContent = state.mercy_rule_alert.message;
    } else {
        mercyBanner.style.display = 'none';
    }

    // Count dots update
    if (isDiamond) {
        const balls = state.balls || 0;
        const strikes = state.strikes || 0;
        document.getElementById('ball-dot-1').className = 'count-dot' + (balls >= 1 ? ' filled-ball' : '');
        document.getElementById('ball-dot-2').className = 'count-dot' + (balls >= 2 ? ' filled-ball' : '');
        document.getElementById('ball-dot-3').className = 'count-dot' + (balls >= 3 ? ' filled-ball' : '');
        document.getElementById('strike-dot-1').className = 'count-dot' + (strikes >= 1 ? ' filled-strike' : '');
        document.getElementById('strike-dot-2').className = 'count-dot' + (strikes >= 2 ? ' filled-strike' : '');
        const cfBadge = document.getElementById('courtesy-foul-badge');
        if (state.courtesy_foul_used) {
            cfBadge.style.display = 'inline-block';
        } else {
            cfBadge.style.display = 'none';
        }
    }

    if (isDiamond) {
        document.getElementById('inning-half-label').textContent = state.inning_half_display;
        document.getElementById('inning-number').textContent = state.current_inning;
        document.getElementById('outs-display').textContent = `${state.outs} Out${state.outs === 1 ? '' : 's'}`;
        document.getElementById('batting-team-badge').textContent = `At Bat: ${state.batting_team_name}`;
    } else {
        document.getElementById('inning-half-label').textContent = periodLabel;
        document.getElementById('inning-number').textContent = state.current_inning;
        document.getElementById('batting-team-badge').textContent = `Possession / Serve: ${state.batting_team_name}`;
    }

    document.getElementById('base-1B').classList.toggle('occupied', !!state.runner_on_first);
    document.getElementById('base-2B').classList.toggle('occupied', !!state.runner_on_second);
    document.getElementById('base-3B').classList.toggle('occupied', !!state.runner_on_third);

    if (state.current_batter) {
        const j = state.current_batter.jersey_number !== null ? `#${state.current_batter.jersey_number} ` : '';
        document.getElementById('current-batter-name').textContent = `${j}${state.current_batter.name}`;
        document.getElementById('current-batter-song').textContent = state.current_batter.walkup_song_title
            ? `Walk-Up: ${state.current_batter.walkup_song_title} (${state.current_batter.walkup_duration_seconds}s clip)`
            : 'No walk-up song uploaded';
    } else {
        document.getElementById('current-batter-name').textContent = 'No Active Batter';
        document.getElementById('current-batter-song').textContent = '';
    }

    document.getElementById('on-deck-batter-name').textContent = state.on_deck_batter
        ? state.on_deck_batter.name
        : '--';

    const logEl = document.getElementById('play-by-play-list');
    if (state.play_by_play && state.play_by_play.length) {
        logEl.innerHTML = state.play_by_play.map(item => `<li style="margin-bottom:0.35rem;">${item}</li>`).join('');
    } else {
        logEl.innerHTML = '<li style="color:var(--text-muted);">No plays logged yet.</li>';
    }

    const currentBatterId = state.current_batter ? state.current_batter.id : null;
    renderLineup('team2-lineup-container', state.team2_lineup, currentBatterId);
    renderLineup('team1-lineup-container', state.team1_lineup, currentBatterId);

    // Undo buttons state
    const undoTop = document.getElementById('btn-undo-top');
    const undoPad = document.getElementById('btn-undo-pad');
    if (state.can_undo) {
        if (undoTop) undoTop.style.opacity = '1';
        if (undoPad) undoPad.style.opacity = '1';
    } else {
        if (undoTop) undoTop.style.opacity = '0.5';
        if (undoPad) undoPad.style.opacity = '0.5';
    }

    // Handle situational play announcement commentary (Uecker / Madden / NBA Jam)
    if (state.announcement && window.DugoutSoundboard) {
        window.DugoutSoundboard.handlePlayAnnouncement(state.announcement);
    }

    // Handle batter introduction PA announcement chained into walk-up track
    if (state.trigger_walkup && document.getElementById('auto-walkup-toggle').checked) {
        if (window.DugoutSoundboard && state.batter_intro) {
            window.DugoutSoundboard.handleBatterSequence(state.batter_intro, () => {
                playCurrentWalkup();
            });
        } else {
            playCurrentWalkup();
        }
    }
}

// Client-Side Action Dispatcher
async function sendAction(action, extraPayload = {}) {
    const payload = { action, ...extraPayload };

    if (!navigator.onLine) {
        pushOfflineQueue(payload);
        return;
    }

    try {
        const res = await fetch(ACTION_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN
            },
            body: JSON.stringify(payload)
        });

        if (res.status === 423) {
            const data = await res.json();
            document.getElementById('scorer-lock-banner').style.display = 'flex';
            document.getElementById('active-scorer-msg').innerHTML =
                `Scores are currently being recorded by <strong>${data.active_scorer}</strong>. You are in view-only spectator mode.`;
            return;
        }

        if (res.ok) {
            const data = await res.json();
            renderState(data);
        } else {
            pushOfflineQueue(payload);
        }
    } catch (e) {
        pushOfflineQueue(payload);
    }
}

async function flushOfflineQueue() {
    const queue = getOfflineQueue();
    if (!queue.length || !navigator.onLine) return;

    try {
        const res = await fetch(SYNC_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN
            },
            body: JSON.stringify({ actions: queue })
        });
        if (res.ok) {
            const data = await res.json();
            clearOfflineQueue();
            renderState(data);
        }
    } catch (e) {}
}

// Initial Boot
document.addEventListener('DOMContentLoaded', () => {
    updateConnectionBadge();
    updateQueueIndicator();
    const savedMode = localStorage.getItem(MODE_STORAGE_KEY) || 'detailed';
    setConsoleMode(savedMode);

    // Initial state fetch
    sendAction('toggle_attendance', {noop: true});
});

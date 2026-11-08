let state = {{ initial_state_json|safe }};

// --- Web Audio Synthesizer (Zero asset dependencies for practice chimes and buzzers) ---
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
let buzzerOsc = null;

function playSynthBuzzer(freq = 240, duration = 1.0) {
    try {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
        gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + duration);
    } catch(e) {}
}

function playPracticeChime() {
    try {
        [261.63, 329.63, 392.00, 523.25].forEach((f, idx) => {
            setTimeout(() => {
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(f, audioCtx.currentTime);
                gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.4);
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start();
                osc.stop(audioCtx.currentTime + 0.4);
            }, idx * 120);
        });
    } catch(e) {}
}

function stopPracticeChime() {}

// --- Clock Logic ---
let masterSeconds = state.clock_seconds_remaining || 1200;
let masterRunning = false;
let masterInterval = null;

let playSeconds = 25;
let playInterval = null;

let qbSeconds = 7.0;
let qbInterval = null;

let timeoutSeconds = 0;
let timeoutInterval = null;

function formatClock(totalSec) {
    const m = Math.floor(totalSec / 60);
    const s = Math.floor(totalSec % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
}

function toggleMasterClock() {
    masterRunning = !masterRunning;
    const btn = document.getElementById('btn-clock-toggle');
    if (masterRunning) {
        btn.textContent = '⏸ Pause';
        btn.className = 'btn btn-sm btn-secondary';
        masterInterval = setInterval(() => {
            if (masterSeconds > 0) {
                masterSeconds--;
                updateClockUI();
            } else {
                toggleMasterClock();
                playSynthBuzzer(180, 1.5);
                logPractice("🚨 PERIOD OVER! (Game clock reached 00:00)");
            }
        }, 1000);
    } else {
        btn.textContent = '▶ Start';
        btn.className = 'btn btn-sm btn-accent';
        clearInterval(masterInterval);
    }
}

function adjustMasterClock(delta) {
    masterSeconds = Math.max(0, masterSeconds + delta);
    updateClockUI();
}

function resetMasterClock() {
    if (masterRunning) toggleMasterClock();
    masterSeconds = (state.default_period_minutes || 20) * 60;
    updateClockUI();
}

function startPlayClock(sec = 25) {
    clearInterval(playInterval);
    playSeconds = sec;
    const el = document.getElementById('play-clock-display');
    el.textContent = playSeconds;
    el.classList.remove('urgent');
    playInterval = setInterval(() => {
        if (playSeconds > 0) {
            playSeconds--;
            el.textContent = playSeconds;
            if (playSeconds <= 5) el.classList.add('urgent');
        } else {
            clearInterval(playInterval);
            playSynthBuzzer(440, 0.8);
            logPractice("⏱ PLAY CLOCK VIOLATION! (Delay of Game)");
        }
    }, 1000);
}

function stopPlayClock() {
    clearInterval(playInterval);
    const el = document.getElementById('play-clock-display');
    el.classList.remove('urgent');
}

function startQBClock(sec = 7) {
    clearInterval(qbInterval);
    qbSeconds = sec;
    const el = document.getElementById('qb-clock-display');
    el.textContent = qbSeconds.toFixed(1);
    el.classList.remove('urgent');
    qbInterval = setInterval(() => {
        if (qbSeconds > 0.1) {
            qbSeconds = +(qbSeconds - 0.1).toFixed(1);
            el.textContent = qbSeconds.toFixed(1);
            if (qbSeconds <= 2.0) el.classList.add('urgent');
        } else {
            clearInterval(qbInterval);
            el.textContent = "0.0";
            playSynthBuzzer(300, 0.8);
            logPractice("⚡ QB 7s RUSH CLOCK EXPIRED! (Ball dead / Sack)");
        }
    }, 100);
}

function stopQBClock() {
    clearInterval(qbInterval);
    document.getElementById('qb-clock-display').classList.remove('urgent');
}

function startTimeout(sec) {
    clearInterval(timeoutInterval);
    timeoutSeconds = sec;
    const el = document.getElementById('timeout-display');
    el.textContent = timeoutSeconds;
    timeoutInterval = setInterval(() => {
        if (timeoutSeconds > 0) {
            timeoutSeconds--;
            el.textContent = timeoutSeconds;
        } else {
            clearInterval(timeoutInterval);
            playSynthBuzzer(520, 0.8);
            logPractice("📣 TIMEOUT OVER! Teams break huddle.");
        }
    }, 1000);
}

function stopTimeout() {
    clearInterval(timeoutInterval);
    document.getElementById('timeout-display').textContent = '00';
}

function updateClockUI() {
    document.getElementById('master-clock-display').textContent = formatClock(masterSeconds);
}

// --- Practice Actions ---
function logPractice(msg) {
    const ul = document.getElementById('p-log-list');
    const li = document.createElement('li');
    li.textContent = msg;
    li.style.marginBottom = '0.35rem';
    ul.insertBefore(li, ul.firstChild);
}

function renderPracticeState() {
    document.getElementById('p-score-home').textContent = state.team1_score;
    document.getElementById('p-score-away').textContent = state.team2_score;

    const isDiamond = state.is_diamond_sport;
    document.getElementById('p-diamond-wrap').style.display = isDiamond ? 'block' : 'none';
    document.getElementById('p-outs-wrap').style.display = isDiamond ? 'block' : 'none';
    document.getElementById('p-diamond-actions').style.display = isDiamond ? 'grid' : 'none';
    document.getElementById('p-court-actions').style.display = isDiamond ? 'none' : 'grid';

    // Clocks visibility
    document.getElementById('master-clock-wrap').style.display = state.enable_game_clock ? 'block' : 'none';
    document.getElementById('football-clocks-wrap').style.display = state.enable_flag_football_clocks ? 'block' : 'none';

    if (isDiamond) {
        document.getElementById('p-period-label').textContent = state.inning_half_display;
        document.getElementById('p-period-num').textContent = state.current_inning;
        document.getElementById('p-outs-wrap').textContent = `${state.outs} Outs`;
    } else {
        document.getElementById('p-period-label').textContent = state.period_label;
        document.getElementById('p-period-num').textContent = state.current_inning;
        document.getElementById('p-outs-wrap').textContent = '';
    }

    if (isDiamond) {
        document.getElementById('p-base-1B').classList.toggle('occupied', !!state.runner_on_first);
        document.getElementById('p-base-2B').classList.toggle('occupied', !!state.runner_on_second);
        document.getElementById('p-base-3B').classList.toggle('occupied', !!state.runner_on_third);
    }

    if (state.current_batter) {
        document.getElementById('p-current-batter').textContent = `#${state.current_batter.jersey_number} ${state.current_batter.name}`;
        document.getElementById('p-current-song').textContent = `Walk-Up: ${state.current_batter.walkup_song_title || 'None'}`;
    }
}

function advancePracticeBatter() {
    const isTop = state.inning_half === 'top';
    const lineup = (isTop ? state.team2_lineup : state.team1_lineup) || [];
    if (!lineup.length) return;

    let currentIdx = -1;
    if (state.current_batter) {
        currentIdx = lineup.findIndex(p => p.player_id === state.current_batter.id || p.name === state.current_batter.name);
    }
    const nextIdx = (currentIdx + 1) % lineup.length;
    const nextPlayer = lineup[nextIdx];

    state.current_batter = {
        id: nextPlayer.player_id,
        name: nextPlayer.name,
        jersey_number: nextPlayer.jersey,
        walkup_song_title: nextPlayer.walkup_title || '',
        walkup_song_url: '',
        walkup_duration_seconds: 8,
    };

    const onDeckIdx = (nextIdx + 1) % lineup.length;
    const onDeckPlayer = lineup[onDeckIdx];
    state.on_deck_batter = {
        id: onDeckPlayer.player_id,
        name: onDeckPlayer.name,
        jersey_number: onDeckPlayer.jersey,
        walkup_song_title: onDeckPlayer.walkup_title || '',
        walkup_song_url: '',
        walkup_duration_seconds: 8,
    };
}

function switchInningHalfBatter() {
    const isTop = state.inning_half === 'top';
    const lineup = (isTop ? state.team2_lineup : state.team1_lineup) || [];
    if (!lineup.length) return;
    state.current_batter = {
        id: lineup[0].player_id,
        name: lineup[0].name,
        jersey_number: lineup[0].jersey,
        walkup_song_title: lineup[0].walkup_title || '',
        walkup_song_url: '',
        walkup_duration_seconds: 8,
    };
    if (lineup.length > 1) {
        state.on_deck_batter = {
            id: lineup[1].player_id,
            name: lineup[1].name,
            jersey_number: lineup[1].jersey,
            walkup_song_title: lineup[1].walkup_title || '',
            walkup_song_url: '',
            walkup_duration_seconds: 8,
        };
    }
}

function practiceNextBatter() {
    advancePracticeBatter();
    playPracticeChime();
    logPractice(`▶ Next batter: #${state.current_batter.jersey_number} ${state.current_batter.name} stepped up! Walk-up fanfare triggered.`);
    renderPracticeState();
}

function practiceHit() {
    const isTop = state.inning_half === 'top';
    const hitKey = isTop ? 'team2_hits' : 'team1_hits';
    const scoreKey = isTop ? 'team2_score' : 'team1_score';
    state[hitKey] += 1;

    const batterName = state.current_batter ? state.current_batter.name : 'Batter';
    let scored = false;
    if (state.runner_on_third) {
        state[scoreKey] += 1;
        state.runner_on_third = false;
        scored = true;
    }
    if (state.runner_on_second) { state.runner_on_third = true; state.runner_on_second = false; }
    if (state.runner_on_first) state.runner_on_second = true;
    state.runner_on_first = true;

    if (scored) {
        logPractice(`BASE HIT by ${batterName}! Runner on 3B scored (+1 Run).`);
    } else {
        logPractice(`BASE HIT by ${batterName}! Runner advances to 1B.`);
    }

    advancePracticeBatter();
    playPracticeChime();
    renderPracticeState();
}

function practiceWalk() {
    const isTop = state.inning_half === 'top';
    const scoreKey = isTop ? 'team2_score' : 'team1_score';
    const batterName = state.current_batter ? state.current_batter.name : 'Batter';

    if (state.runner_on_first && state.runner_on_second && state.runner_on_third) {
        state[scoreKey] += 1;
        logPractice(`WALK (BB) for ${batterName}! Bases-loaded walk forced in a run (+1 Run).`);
    } else if (state.runner_on_first && state.runner_on_second) {
        state.runner_on_third = true;
        logPractice(`WALK (BB) for ${batterName}! Runners forced to 2B and 3B.`);
    } else if (state.runner_on_first) {
        state.runner_on_second = true;
        logPractice(`WALK (BB) for ${batterName}! Runner on 1B forced to 2B.`);
    } else {
        logPractice(`WALK (BB) for ${batterName}! Batter takes 1B.`);
    }
    state.runner_on_first = true;

    advancePracticeBatter();
    playPracticeChime();
    renderPracticeState();
}

function practiceHomeRun() {
    const isTop = state.inning_half === 'top';
    const hitKey = isTop ? 'team2_hits' : 'team1_hits';
    const scoreKey = isTop ? 'team2_score' : 'team1_score';
    const batterName = state.current_batter ? state.current_batter.name : 'Batter';

    const runners = (state.runner_on_first ? 1 : 0) + (state.runner_on_second ? 1 : 0) + (state.runner_on_third ? 1 : 0);
    const runs = runners + 1;
    state[scoreKey] += runs;
    state[hitKey] += 1;
    state.runner_on_first = false;
    state.runner_on_second = false;
    state.runner_on_third = false;
    logPractice(`💥 HOME RUN by ${batterName}! ${runs} run(s) scored!`);

    advancePracticeBatter();
    playPracticeChime();
    renderPracticeState();
}

function practiceOut() {
    state.outs += 1;
    const outBatter = state.current_batter ? state.current_batter.name : 'Batter';
    if (state.outs >= 3) {
        state.outs = 0;
        state.runner_on_first = false;
        state.runner_on_second = false;
        state.runner_on_third = false;
        state.inning_half = state.inning_half === 'top' ? 'bottom' : 'top';
        state.inning_half_display = state.inning_half === 'top' ? 'Top' : 'Bottom';
        if (state.inning_half === 'top') state.current_inning++;
        logPractice(`3RD OUT! (${outBatter} out). Switched to ${state.inning_half_display} of Inning ${state.current_inning}. Bases cleared.`);
        switchInningHalfBatter();
    } else {
        logPractice(`OUT recorded (${outBatter} out — ${state.outs} out).`);
        advancePracticeBatter();
    }
    playPracticeChime();
    renderPracticeState();
}

function practiceScore(pts) {
    state.team1_score += pts;
    logPractice(`+${pts} Points scored by Home team!`);
    renderPracticeState();
}

function practicePeriodFlip() {
    state.current_inning += 1;
    logPractice(`Period advanced to ${state.period_label} ${state.current_inning}.`);
    renderPracticeState();
}

function togglePracticeBase(base) {
    if (base === '1B') state.runner_on_first = !state.runner_on_first;
    if (base === '2B') state.runner_on_second = !state.runner_on_second;
    if (base === '3B') state.runner_on_third = !state.runner_on_third;
    logPractice(`Toggled base runner on ${base}.`);
    renderPracticeState();
}

function resetPracticeGame() {
    state.team1_score = 0;
    state.team2_score = 0;
    state.team1_hits = 0;
    state.team2_hits = 0;
    state.outs = 0;
    state.current_inning = 1;
    state.inning_half = 'top';
    state.inning_half_display = 'Top';
    state.runner_on_first = false;
    state.runner_on_second = false;
    state.runner_on_third = false;
    switchInningHalfBatter();
    logPractice("Practice game reset to 0-0.");
    renderPracticeState();
}

// Initial mount
renderPracticeState();
updateClockUI();

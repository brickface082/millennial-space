/* Shared alert sound playback — beeps, ICQ, movie quotes, user soundboard */
(function () {
    var cfg = window.ICQ_CONFIG || {};
    var quoteBase = cfg.quoteBase || '/static/sounds/quotes/';
    var quoteFallback = cfg.quoteTexts || {};
    var userSounds = cfg.userSounds || {};

    function getCtx() {
        if (!window._msActx) {
            window._msActx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (window._msActx.state === 'suspended') {
            window._msActx.resume();
        }
        return window._msActx;
    }

    function beep(freq, start, dur, vol, type) {
        var ctx = getCtx(), t = ctx.currentTime;
        var o = ctx.createOscillator(), og = ctx.createGain();
        o.type = type || 'sine';
        o.frequency.setValueAtTime(freq, t + start);
        og.gain.setValueAtTime(vol || 0.4, t + start);
        og.gain.exponentialRampToValueAtTime(0.001, t + start + dur);
        o.connect(og);
        og.connect(ctx.destination);
        o.start(t + start);
        o.stop(t + start + dur + 0.05);
    }

    function playDataUri(src) {
        if (!src) return;
        try {
            var audio = new Audio(src);
            audio.volume = 0.9;
            audio.play().catch(function () {});
        } catch (e) {}
    }

    function playQuote(key) {
        var audio = new Audio(quoteBase + key + '.wav');
        audio.volume = 0.9;
        var played = false;
        audio.onplay = function () { played = true; };
        audio.onerror = function () {
            if (played) return;
            var mp3 = new Audio(quoteBase + key + '.mp3');
            mp3.volume = 0.9;
            mp3.play().catch(function () {});
        };
        audio.play().catch(function () {
            if (!played) {
                var mp3 = new Audio(quoteBase + key + '.mp3');
                mp3.volume = 0.9;
                mp3.play().catch(function () {});
            }
        });
    }

    window.playBuiltinSound = function (key) {
        if (!key) return;
        if (key.indexOf('us_') === 0) {
            playDataUri(userSounds[key]);
            return;
        }
        if (key.indexOf('quote_') === 0) {
            playQuote(key);
            return;
        }
        var ctx = getCtx(), t = ctx.currentTime;
        switch (key) {
            case 'icq_uhoh':
                beep(587, 0, 0.12, 0.45); beep(392, 0.14, 0.22, 0.45); break;
            case 'icq_door_open':
                { var o = ctx.createOscillator(), og = ctx.createGain(); o.type = 'sawtooth';
                  o.frequency.setValueAtTime(180, t); o.frequency.linearRampToValueAtTime(420, t + 0.18);
                  og.gain.setValueAtTime(0.15, t); og.gain.exponentialRampToValueAtTime(0.001, t + 0.2);
                  o.connect(og); og.connect(ctx.destination); o.start(t); o.stop(t + 0.22); }
                break;
            case 'icq_door_close':
                { var o2 = ctx.createOscillator(), og2 = ctx.createGain(); o2.type = 'sawtooth';
                  o2.frequency.setValueAtTime(420, t); o2.frequency.linearRampToValueAtTime(120, t + 0.2);
                  og2.gain.setValueAtTime(0.15, t); og2.gain.exponentialRampToValueAtTime(0.001, t + 0.22);
                  o2.connect(og2); og2.connect(ctx.destination); o2.start(t); o2.stop(t + 0.24); }
                break;
            case 'icq_send': beep(1200, 0, 0.06, 0.25, 'square'); break;
            case 'icq_online': beep(880, 0, 0.1, 0.3); beep(1100, 0.1, 0.12, 0.25); break;
            case 'classic_beep': beep(880, 0, 0.18); break;
            case 'double_ping': beep(1200, 0, 0.1); beep(1200, 0.18, 0.1); break;
            case 'triple_beep': beep(1000, 0, 0.08); beep(1000, 0.12, 0.08); beep(1000, 0.24, 0.08); break;
            case 'rising_tone':
                { var r = ctx.createOscillator(), rg = ctx.createGain(); r.type = 'sine';
                  r.frequency.setValueAtTime(400, t); r.frequency.linearRampToValueAtTime(1400, t + 0.35);
                  rg.gain.setValueAtTime(0.4, t); rg.gain.exponentialRampToValueAtTime(0.001, t + 0.38);
                  r.connect(rg); rg.connect(ctx.destination); r.start(t); r.stop(t + 0.4); }
                break;
            case 'falling_tone':
                { var f = ctx.createOscillator(), fg = ctx.createGain(); f.type = 'sine';
                  f.frequency.setValueAtTime(1400, t); f.frequency.linearRampToValueAtTime(300, t + 0.35);
                  fg.gain.setValueAtTime(0.4, t); fg.gain.exponentialRampToValueAtTime(0.001, t + 0.38);
                  f.connect(fg); fg.connect(ctx.destination); f.start(t); f.stop(t + 0.4); }
                break;
            case 'soft_chime': beep(1047, 0, 0.4, 0.25); beep(1319, 0.08, 0.35, 0.2); beep(1568, 0.16, 0.3, 0.15); break;
            case 'retro_game': beep(440, 0, 0.07, 0.3, 'square'); beep(660, 0.09, 0.07, 0.3, 'square'); beep(880, 0.18, 0.07, 0.3, 'square'); break;
            case 'soft_pop':
                { var p = ctx.createOscillator(), pg = ctx.createGain(); p.type = 'sine';
                  p.frequency.setValueAtTime(200, t); p.frequency.exponentialRampToValueAtTime(80, t + 0.12);
                  pg.gain.setValueAtTime(0.5, t); pg.gain.exponentialRampToValueAtTime(0.001, t + 0.15);
                  p.connect(pg); pg.connect(ctx.destination); p.start(t); p.stop(t + 0.18); }
                break;
            case 'ding': beep(1760, 0, 0.5, 0.3); break;
            case 'deep_bong': beep(110, 0, 0.7, 0.5); break;
            case 'fast_blip': beep(2000, 0, 0.04, 0.3, 'square'); break;
            case 'old_phone':
                for (var i = 0; i < 3; i++) {
                    beep(480, i * 0.25, 0.1, 0.4, 'square');
                    beep(620, i * 0.25 + 0.05, 0.08, 0.3, 'square');
                }
                break;
            case 'doorbell': beep(523, 0, 0.25, 0.35); beep(392, 0.28, 0.35, 0.35); break;
            case 'laser':
                { var l = ctx.createOscillator(), lg = ctx.createGain(); l.type = 'sawtooth';
                  l.frequency.setValueAtTime(800, t); l.frequency.exponentialRampToValueAtTime(100, t + 0.2);
                  lg.gain.setValueAtTime(0.4, t); lg.gain.exponentialRampToValueAtTime(0.001, t + 0.22);
                  l.connect(lg); lg.connect(ctx.destination); l.start(t); l.stop(t + 0.25); }
                break;
            case 'win95':
                beep(392, 0, 0.12, 0.3); beep(523, 0.14, 0.12, 0.3);
                beep(659, 0.28, 0.12, 0.3); beep(784, 0.42, 0.2, 0.3);
                break;
            default: beep(880, 0, 0.15); break;
        }
    };

    window.playAlertByKey = function (key, customSnd) {
        if (!key || key === 'none') return;
        if (key.indexOf('us_') === 0) {
            playDataUri(userSounds[key]);
            return;
        }
        if (key === 'custom') {
            playDataUri(customSnd);
            return;
        }
        playBuiltinSound(key);
    };
})();
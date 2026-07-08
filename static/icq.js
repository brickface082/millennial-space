/* ICQ-style buddy list, multi-window chat, alert sounds — Millennial Space */
(function () {
    var cfg = window.ICQ_CONFIG || {};
    var MY_USER = cfg.username || '';
    var alertKey = cfg.alertKey || 'classic_beep';
    var customSnd = cfg.customSnd || '';

    var INBOX_ID = 'icq-win';
    var BUDDY_ID = 'icq-buddy-win';
    var POS_KEY = 'icq_pos';
    var BUDDY_POS_KEY = 'icq_buddy_pos';
    var LOCK_KEY = 'icq_locked';
    var BUDDY_LOCK_KEY = 'icq_buddy_locked';

    var _locked = localStorage.getItem(LOCK_KEY) === '1';
    var _buddyLocked = localStorage.getItem(BUDDY_LOCK_KEY) === '1';
    var _dragging = null;
    var _dragOX = 0;
    var _dragOY = 0;
    var _openChats = {};
    var _chatPollTmrs = {};
    var _actx = null;
    var _audioUnlocked = false;
    var _prevUnread = 0;
    var _blinkTmr = null;
    var _buddyPollTmr = null;
    var _buddyStatuses = {};
    var _buddySoundsEnabled = true;

    function $(id) { return document.getElementById(id); }

    function escHtml(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function statusDot(status) {
        if (status === 'online') return '<span style="color:#00cc00;font-size:14px;">●</span>';
        if (status === 'away') return '<span style="color:#ffcc00;font-size:14px;">●</span>';
        if (status === 'dnd') return '<span style="color:#ff0000;font-size:14px;">●</span>';
        return '<span style="color:#888;font-size:14px;">●</span>';
    }

    function statusLabel(status) {
        if (status === 'online') return 'Online';
        if (status === 'away') return 'Away';
        if (status === 'dnd') return 'DND';
        return 'Offline';
    }

    // ── Drag helpers ────────────────────────────────────────────────────────
    function makeDraggable(win, titlebar, lockGetter, saveKey) {
        if (!titlebar || !win) return;
        titlebar.addEventListener('mousedown', function (e) {
            if (lockGetter()) return;
            if (e.target.tagName === 'BUTTON') return;
            _dragging = win;
            var rect = win.getBoundingClientRect();
            _dragOX = e.clientX - rect.left;
            _dragOY = e.clientY - rect.top;
            e.preventDefault();
        });
        win._icqSaveKey = saveKey;
    }

    document.addEventListener('mousemove', function (e) {
        if (!_dragging) return;
        _dragging.style.left = (e.clientX - _dragOX) + 'px';
        _dragging.style.top = (e.clientY - _dragOY) + 'px';
        _dragging.style.right = '';
        _dragging.style.bottom = '';
    });
    document.addEventListener('mouseup', function () {
        if (_dragging) {
            if (_dragging._icqSaveKey) {
                localStorage.setItem(_dragging._icqSaveKey, JSON.stringify({
                    left: _dragging.style.left,
                    top: _dragging.style.top,
                }));
            }
            _dragging = null;
        }
    });

    function restorePos(win, key, defaultRight, defaultBottom) {
        if (!win) return;
        var saved = localStorage.getItem(key);
        if (saved) {
            try {
                var p = JSON.parse(saved);
                win.style.left = p.left;
                win.style.top = p.top;
                win.style.right = '';
                win.style.bottom = '';
                return;
            } catch (e) { /* fall through */ }
        }
        win.style.right = defaultRight;
        win.style.bottom = defaultBottom;
        win.style.left = '';
        win.style.top = '';
    }

    // ── Inbox window ────────────────────────────────────────────────────────
    window.icqOpen = function () {
        var win = $(INBOX_ID);
        if (!win) return;
        win.style.display = 'block';
        restorePos(win, POS_KEY, '20px', '20px');
        updateLockBtn();
        icqLoadConvos();
    };

    window.icqClose = function () {
        var win = $(INBOX_ID);
        if (win) win.style.display = 'none';
    };

    window.icqToggle = function () {
        var win = $(INBOX_ID);
        if (!win) return;
        if (win.style.display === 'none') icqOpen(); else icqClose();
    };

    window.icqToggleLock = function () {
        _locked = !_locked;
        localStorage.setItem(LOCK_KEY, _locked ? '1' : '0');
        updateLockBtn();
    };

    function updateLockBtn() {
        var btn = $('icq-lock-btn');
        if (btn) btn.textContent = _locked ? '🔒' : '🔓';
    }

    window.icqBuddyToggle = function () {
        var win = $(BUDDY_ID);
        if (!win) return;
        if (win.style.display === 'none') {
            win.style.display = 'block';
            restorePos(win, BUDDY_POS_KEY, '20px', '400px');
            updateBuddyLockBtn();
            var bl = $('icq-buddy-list');
            if (bl) bl.innerHTML = '<div style="color:#555;font-style:italic;text-align:center;padding:10px 0;">Loading…</div>';
            icqLoadBuddies();
            startBuddyPoll();
        } else {
            win.style.display = 'none';
            stopBuddyPoll();
        }
    };

    window.icqBuddyToggleLock = function () {
        _buddyLocked = !_buddyLocked;
        localStorage.setItem(BUDDY_LOCK_KEY, _buddyLocked ? '1' : '0');
        updateBuddyLockBtn();
    };

    function updateBuddyLockBtn() {
        var btn = $('icq-buddy-lock-btn');
        if (btn) btn.textContent = _buddyLocked ? '🔒' : '🔓';
    }

    // ── Buddy list ──────────────────────────────────────────────────────────
    function playBuddySound(key) {
        if (!_audioUnlocked || !_buddySoundsEnabled) return;
        if (typeof window.playBuiltinSound === 'function') window.playBuiltinSound(key);
    }

    function wasOffline(status) {
        return !status || status === 'offline';
    }

    function isOnlineish(status) {
        return status === 'online' || status === 'away' || status === 'dnd';
    }

    function handleBuddyStatusChanges(buddies) {
        var hadPrior = Object.keys(_buddyStatuses).length > 0;
        buddies.forEach(function (b) {
            var prev = _buddyStatuses[b.username];
            var cur = b.status || 'offline';
            if (hadPrior && prev !== undefined && prev !== cur) {
                if (wasOffline(prev) && isOnlineish(cur)) playBuddySound('icq_door_open');
                else if (isOnlineish(prev) && wasOffline(cur)) playBuddySound('icq_door_close');
            }
            _buddyStatuses[b.username] = cur;
        });
    }

    window.icqLoadBuddies = function () {
        var list = $('icq-buddy-list');
        return fetch('/icq/buddies')
            .then(function (r) { return r.json(); })
            .then(function (buddies) {
                handleBuddyStatusChanges(buddies);
                if (!list) return buddies;
                if (!buddies.length) {
                    list.innerHTML = '<div style="color:#555;font-style:italic;text-align:center;padding:16px 8px;">Add crew to see buddies here.</div>';
                    return buddies;
                }
                list.innerHTML = '';
                buddies.forEach(function (b) {
                    var row = document.createElement('div');
                    row.className = 'icq-buddy-row';
                    row.innerHTML =
                        statusDot(b.status) +
                        ' <strong style="color:#000080;">' + escHtml(b.username) + '</strong>' +
                        ' <span style="font-size:10px;color:#555;">' + statusLabel(b.status) + '</span>';
                    row.onclick = function () { icqOpenChat(b.username); };
                    list.appendChild(row);
                });
                return buddies;
            })
            .catch(function () {
                if (list) list.innerHTML = '<div style="color:#c00;text-align:center;padding:10px;">Could not load.</div>';
            });
    };

    function startBuddyPoll() {
        stopBuddyPoll();
        _buddyPollTmr = setInterval(function () { icqLoadBuddies(); }, 30000);
    }
    function stopBuddyPoll() {
        if (_buddyPollTmr) { clearInterval(_buddyPollTmr); _buddyPollTmr = null; }
    }

    // ── Inbox conversations ─────────────────────────────────────────────────
    window.icqLoadConvos = function () {
        var list = $('icq-convo-list');
        if (!list) return;
        list.innerHTML = '<div style="color:#555;font-style:italic;text-align:center;padding:10px 0;">Loading…</div>';
        fetch('/inbox/conversations')
            .then(function (r) { return r.json(); })
            .then(function (convos) {
                if (!convos.length) {
                    list.innerHTML = '<div style="color:#555;font-style:italic;text-align:center;padding:16px 0;">No messages yet.</div>';
                    return;
                }
                list.innerHTML = '';
                convos.forEach(function (c) {
                    var row = document.createElement('div');
                    row.style.cssText = 'padding:5px 6px;border-bottom:1px solid #aaa;cursor:pointer;display:flex;justify-content:space-between;align-items:center;background:' +
                        (c.unread ? '#ffffcc' : '#f0f0f0') + ';';
                    row.onmouseenter = function () { row.style.background = '#ddeeff'; };
                    row.onmouseleave = function () { row.style.background = c.unread ? '#ffffcc' : '#f0f0f0'; };
                    row.onclick = function () { icqOpenChat(c.username); };
                    var left = document.createElement('div');
                    left.innerHTML = '<strong style="color:#000080;">' + escHtml(c.username) + '</strong>' +
                        '<div style="font-size:11px;color:#555;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px;">' +
                        escHtml(c.last_body) + '</div>';
                    var right = document.createElement('div');
                    right.style.cssText = 'font-size:10px;color:#555;text-align:right;';
                    if (c.unread) {
                        right.innerHTML = '<span style="background:#ff0000;color:#fff;padding:1px 5px;border-radius:8px;font-weight:bold;">' +
                            c.unread + '</span>';
                    }
                    row.appendChild(left);
                    row.appendChild(right);
                    list.appendChild(row);
                });
            })
            .catch(function () {
                list.innerHTML = '<div style="color:#c00;text-align:center;padding:10px;">Could not load.</div>';
            });
    };

    // ── Multi-window chat ───────────────────────────────────────────────────
    function chatWinId(username) {
        return 'icq-chat-' + username.replace(/[^a-zA-Z0-9_]/g, '_');
    }

    window.icqOpenChat = function (username) {
        if (!username) return;
        icqOpen();
        if (_openChats[username]) {
            _openChats[username].style.display = 'block';
            _openChats[username].style.zIndex = 10000 + Object.keys(_openChats).length;
            return;
        }
        spawnChatWindow(username);
    };

    function spawnChatWindow(username) {
        var id = chatWinId(username);
        var existing = $(id);
        if (existing) {
            existing.style.display = 'block';
            _openChats[username] = existing;
            return;
        }

        var offset = Object.keys(_openChats).length * 24;
        var win = document.createElement('div');
        win.id = id;
        win.className = 'icq-chat-win';
        win.style.cssText = 'display:block;position:fixed;z-index:' + (10000 + offset) +
            ';width:280px;min-height:300px;background:#c0c0c0;border:2px solid #fff;border-right-color:#808080;' +
            'border-bottom-color:#808080;box-shadow:2px 2px 0 #000;font-family:inherit;font-size:13px;';
        win.style.right = (40 + offset) + 'px';
        win.style.bottom = (60 + offset) + 'px';

        var posKey = 'icq_chat_pos_' + username;
        var saved = localStorage.getItem(posKey);
        if (saved) {
            try {
                var p = JSON.parse(saved);
                win.style.left = p.left;
                win.style.top = p.top;
                win.style.right = '';
                win.style.bottom = '';
            } catch (e) { /* keep default */ }
        }

        var titlebar = document.createElement('div');
        titlebar.className = 'icq-chat-titlebar';
        titlebar.style.cssText = 'background:linear-gradient(to right,#000080,#1084d0);color:#fff;padding:4px 6px;display:flex;align-items:center;justify-content:space-between;cursor:move;user-select:none;';
        var titleSpan = document.createElement('span');
        titleSpan.style.cssText = 'font-weight:bold;font-size:13px;';
        titleSpan.textContent = '💬 ' + username;
        var closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.textContent = '✕';
        closeBtn.style.cssText = 'background:#c0c0c0;border:1px outset #fff;width:18px;height:16px;font-size:11px;cursor:pointer;padding:0;font-weight:bold;';
        closeBtn.onclick = function () { icqCloseChat(username); };
        titlebar.appendChild(titleSpan);
        titlebar.appendChild(closeBtn);

        var body = document.createElement('div');
        body.style.padding = '6px';
        body.innerHTML =
            '<div class="icq-thread" style="height:180px;overflow-y:auto;background:#fff;border:1px inset #808080;padding:6px;display:flex;flex-direction:column;gap:4px;margin-bottom:6px;"></div>' +
            '<div style="display:flex;gap:4px;">' +
            '<input type="text" class="icq-chat-input" maxlength="1000" placeholder="Type here…" ' +
            'style="flex:1;font-family:inherit;font-size:12px;padding:3px 5px;border:1px inset #808080;background:#ffffcc;">' +
            '<button type="button" class="icq-chat-send" style="background:#000080;color:#ffff00;border:2px outset #c0c0c0;font-family:inherit;font-size:11px;padding:3px 8px;cursor:pointer;font-weight:bold;">Send</button>' +
            '</div>';
        win.appendChild(titlebar);
        win.appendChild(body);

        document.body.appendChild(win);
        _openChats[username] = win;

        makeDraggable(win, titlebar, function () { return false; }, posKey);

        var input = win.querySelector('.icq-chat-input');
        var sendBtn = win.querySelector('.icq-chat-send');
        sendBtn.onclick = function () { icqSendChat(username); };
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') icqSendChat(username);
        });

        fetch('/inbox/read/' + encodeURIComponent(username), { method: 'POST' }).catch(function () {});
        fetch('/chat/' + encodeURIComponent(username) + '/messages?after=0')
            .then(function (r) { return r.json(); })
            .then(function (msgs) {
                var state = _openChats[username]._state || { lastId: 0 };
                msgs.forEach(function (m) { appendChatMsg(win, m); });
                if (msgs.length) state.lastId = msgs[msgs.length - 1].id;
                win._state = state;
                scrollChat(win);
            }).catch(function () {});

        startChatPoll(username);
        if (typeof window.playBuiltinSound === 'function') window.playBuiltinSound('icq_online');
    }

    window.icqCloseChat = function (username) {
        var win = _openChats[username];
        if (!win) return;
        win.style.display = 'none';
        stopChatPoll(username);
    };

    function appendChatMsg(win, m) {
        var thread = win.querySelector('.icq-thread');
        if (!thread) return;
        var mine = m.from === MY_USER;
        var div = document.createElement('div');
        div.style.cssText = 'max-width:85%;padding:4px 7px;border-radius:2px;font-size:12px;word-break:break-word;' +
            (mine ? 'align-self:flex-end;background:#000080;color:#fff;margin-left:auto;'
                : 'align-self:flex-start;background:#e8f0ff;color:#000;border:1px solid #aac;');
        div.innerHTML = '<div style="font-size:10px;opacity:0.7;margin-bottom:2px;">' +
            (mine ? '' : escHtml(m.from) + ' · ') + escHtml(m.time) + '</div>' + escHtml(m.body);
        thread.appendChild(div);
    }

    function scrollChat(win) {
        var t = win.querySelector('.icq-thread');
        if (t) t.scrollTop = t.scrollHeight;
    }

    function startChatPoll(username) {
        stopChatPoll(username);
        _chatPollTmrs[username] = setInterval(function () { pollChat(username); }, 4000);
    }

    function stopChatPoll(username) {
        if (_chatPollTmrs[username]) {
            clearInterval(_chatPollTmrs[username]);
            delete _chatPollTmrs[username];
        }
    }

    function pollChat(username) {
        var win = _openChats[username];
        if (!win || win.style.display === 'none') return;
        var state = win._state || { lastId: 0 };
        fetch('/chat/' + encodeURIComponent(username) + '/messages?after=' + state.lastId)
            .then(function (r) { return r.json(); })
            .then(function (msgs) {
                if (!msgs.length) return;
                msgs.forEach(function (m) { appendChatMsg(win, m); });
                scrollChat(win);
                state.lastId = msgs[msgs.length - 1].id;
                win._state = state;
                fetch('/inbox/read/' + encodeURIComponent(username), { method: 'POST' }).catch(function () {});
            }).catch(function () {});
    }

    window.icqSendChat = function (username) {
        var win = _openChats[username];
        if (!win) return;
        var input = win.querySelector('.icq-chat-input');
        var body = (input.value || '').trim();
        if (!body) return;
        input.value = '';
        fetch('/chat/' + encodeURIComponent(username) + '/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'body=' + encodeURIComponent(body),
        }).then(function () {
            if (typeof window.playBuiltinSound === 'function') window.playBuiltinSound('icq_send');
            pollChat(username);
        }).catch(function () {});
    };

    // ── Global unread poller ──────────────────────────────────────────────────
    function startBlink() {
        var btn = $('msg-alert-btn');
        if (!btn || _blinkTmr) return;
        _blinkTmr = setInterval(function () {
            btn.style.color = btn.style.color === 'rgb(255, 0, 0)' ? '#ffccee' : 'red';
        }, 500);
    }

    function stopBlink() {
        var btn = $('msg-alert-btn');
        if (_blinkTmr) { clearInterval(_blinkTmr); _blinkTmr = null; }
        if (btn) btn.style.color = '';
    }

    function pollInbox() {
        fetch('/inbox/unread')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var badge = $('msg-badge');
                var isDND = data.dnd;
                if (data.count > 0) {
                    if (badge) {
                        badge.style.display = 'block';
                        badge.textContent = data.count;
                    }
                    if (!isDND) {
                        startBlink();
                        if (data.count > _prevUnread) playAlertSound();
                    } else {
                        stopBlink();
                    }
                } else {
                    if (badge) badge.style.display = 'none';
                    stopBlink();
                }
                _prevUnread = data.count;
                var pollsBadge = $('polls-badge');
                if (pollsBadge) {
                    if (data.polls_count > 0) {
                        pollsBadge.style.display = 'block';
                        pollsBadge.textContent = data.polls_count;
                    } else {
                        pollsBadge.style.display = 'none';
                    }
                }
            })
            .catch(function () {});
    }

    // ── Web Audio sounds ────────────────────────────────────────────────────
    function getCtx() {
        if (!_actx) _actx = new (window.AudioContext || window.webkitAudioContext)();
        if (_actx.state === 'suspended') _actx.resume();
        return _actx;
    }

    function unlockAudio() {
        getCtx();
        _audioUnlocked = true;
        document.removeEventListener('click', unlockAudio);
        document.removeEventListener('keydown', unlockAudio);
    }
    document.addEventListener('click', unlockAudio);
    document.addEventListener('keydown', unlockAudio);

    function beep(freq, start, dur, vol, type) {
        var ctx = getCtx(), t = ctx.currentTime;
        var o = ctx.createOscillator(), og = ctx.createGain();
        o.type = type || 'sine';
        o.frequency.setValueAtTime(freq, t + start);
        og.gain.setValueAtTime(vol || 0.4, t + start);
        og.gain.exponentialRampToValueAtTime(0.001, t + start + dur);
        o.connect(og); og.connect(ctx.destination);
        o.start(t + start); o.stop(t + start + dur + 0.05);
    }

    function playAlertSound() {
        if (!_audioUnlocked) return;
        if (typeof window.playAlertByKey === 'function') {
            window.playAlertByKey(alertKey, customSnd);
        }
    }

    // ── Boot ────────────────────────────────────────────────────────────────
    var inboxWin = $(INBOX_ID);
    if (inboxWin) {
        makeDraggable(inboxWin, $('icq-titlebar'), function () { return _locked; }, POS_KEY);
    }
    var buddyWin = $(BUDDY_ID);
    if (buddyWin) {
        makeDraggable(buddyWin, $('icq-buddy-titlebar'), function () { return _buddyLocked; }, BUDDY_POS_KEY);
    }

    pollInbox();
    setInterval(pollInbox, 5000);

    icqLoadBuddies();
    startBuddyPoll();
})();
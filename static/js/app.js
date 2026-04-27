const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function showToast(message, type = "success") {
    const root = $("#toast-root");
    if (!root || !message) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    root.appendChild(toast);
    window.setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(8px)";
        window.setTimeout(() => toast.remove(), 220);
    }, 3600);
}

async function fetchJson(url, options = {}) {
    const token = document.querySelector("meta[name='csrf-token']")?.content || "";
    const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": token,
            ...(options.headers || {}),
        },
    });
    const data = await response.json();
    if (!response.ok) data.ok = false;
    return data;
}

function setupExistingToasts() {
    $$(".toast").forEach((toast, index) => {
        window.setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateY(8px)";
            window.setTimeout(() => toast.remove(), 220);
        }, 3600 + index * 450);
    });
}

function setupModeSwitch() {
    const switcher = $("[data-mode-switch]");
    if (!switcher) return;
    $$("button", switcher).forEach((button) => {
        button.addEventListener("click", () => {
            $$("button", switcher).forEach((item) => item.classList.remove("active"));
            button.classList.add("active");
            const target = button.dataset.modeTarget;
            $("#challenge-one")?.classList.toggle("active", target === "one");
            $("#challenge-two")?.classList.toggle("active", target === "two");
        });
    });
}

function setupRankTabs() {
    const tabs = $("[data-rank-tabs]");
    if (!tabs) return;
    $$("button", tabs).forEach((button) => {
        button.addEventListener("click", () => {
            $$("button", tabs).forEach((item) => item.classList.remove("active"));
            button.classList.add("active");
            $$(".ranking-list").forEach((list) => list.classList.remove("active"));
            $(`#${button.dataset.rankTarget}`)?.classList.add("active");
        });
    });
}

function setupAutocomplete() {
    $$("[data-autocomplete]").forEach((root) => {
        const input = $("input[type='text']", root);
        const hidden = $("[data-player-id]", root);
        const suggestions = $("[data-suggestions]", root);
        let requestId = 0;

        input.addEventListener("input", async () => {
            hidden.value = "";
            document.dispatchEvent(new CustomEvent("player:selected"));
            const query = input.value.trim();
            if (query.length < 1) {
                suggestions.classList.remove("active");
                suggestions.innerHTML = "";
                return;
            }

            const currentRequest = ++requestId;
            const users = await fetch(`/api/users/search?q=${encodeURIComponent(query)}`, {
                credentials: "same-origin",
            }).then((response) => response.json());
            if (currentRequest !== requestId) return;

            suggestions.innerHTML = users.length
                ? users.map((user) => `
                    <button type="button" data-user-id="${user.id}" data-user-label="${escapeHtml(user.pseudo)}">
                        <img src="${escapeHtml(user.avatar)}" alt="">
                        <span><strong>${escapeHtml(user.pseudo)}</strong><small>${escapeHtml(user.name)} · ${escapeHtml(user.email)}</small></span>
                        <small>${user.rating_1v1}</small>
                    </button>
                `).join("")
                : `<div class="empty-state">Aucun joueur.</div>`;
            suggestions.classList.add("active");
        });

        suggestions.addEventListener("click", (event) => {
            const button = event.target.closest("button[data-user-id]");
            if (!button) return;
            hidden.value = button.dataset.userId;
            input.value = button.dataset.userLabel;
            suggestions.classList.remove("active");
            suggestions.innerHTML = "";
            document.dispatchEvent(new CustomEvent("player:selected"));
        });

        document.addEventListener("click", (event) => {
            if (!root.contains(event.target)) suggestions.classList.remove("active");
        });
    });
}

function selectedId(form, name) {
    return $(`[name='${name}']`, form)?.value || "";
}

async function updatePredictions() {
    const one = $("#challenge-one");
    const oneCard = $("[data-prediction='1v1']");
    if (one && oneCard) {
        const opponentId = selectedId(one, "opponent_id");
        if (opponentId) {
            const data = await fetch(`/api/predict?mode=1v1&opponent_id=${opponentId}`, {
                credentials: "same-origin",
            }).then((response) => response.json());
            renderPrediction(oneCard, data);
        } else {
            oneCard.classList.add("hidden");
        }
    }

    const two = $("#challenge-two");
    const twoCard = $("[data-prediction='2v2']");
    if (two && twoCard) {
        const partner = selectedId(two, "partner_id");
        const opponent1 = selectedId(two, "opponent1_id");
        const opponent2 = selectedId(two, "opponent2_id");
        if (partner && opponent1 && opponent2) {
            const params = new URLSearchParams({
                mode: "2v2",
                partner_id: partner,
                opponent1_id: opponent1,
                opponent2_id: opponent2,
            });
            const data = await fetch(`/api/predict?${params.toString()}`, {
                credentials: "same-origin",
            }).then((response) => response.json());
            renderPrediction(twoCard, data);
        } else {
            twoCard.classList.add("hidden");
        }
    }
}

function renderPrediction(card, data) {
    if (!data.ok) {
        card.classList.add("hidden");
        return;
    }
    const prediction = data.prediction;
    const banLine = data.ban ? `<small>Match bloqué jusqu'au ${escapeHtml(data.ban_until)}.</small>` : "";
    card.innerHTML = `${escapeHtml(prediction.text)}<small>Score attendu: ${escapeHtml(prediction.score)}</small>${banLine}`;
    card.classList.remove("hidden");
}

function setupChallengeForms() {
    $$("[data-challenge-form]").forEach((form) => {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const payload = Object.fromEntries(new FormData(form).entries());
            const data = await fetchJson(form.action, {
                method: "POST",
                body: JSON.stringify(payload),
            });
            showToast(data.message, data.ok ? "success" : "error");
            if (data.ok) {
                form.reset();
                $$("[data-player-id]", form).forEach((input) => {
                    input.value = "";
                });
                $$(".prediction-card", form).forEach((card) => card.classList.add("hidden"));
                pollDashboard();
            }
        });
    });
}

function invitationCard(invitation) {
    return `
        <article class="invite-card">
            <div>
                <strong>${escapeHtml(invitation.title)}</strong>
                <p class="muted">${escapeHtml(invitation.subtitle)}</p>
            </div>
            <div class="action-row">
                <button class="secondary-btn js-invite" data-match-id="${invitation.id}" data-action="refuse">Refuser</button>
                <button class="primary-btn js-invite" data-match-id="${invitation.id}" data-action="accept">Accepter</button>
            </div>
            <small class="muted">${Math.ceil(invitation.remaining / 60)} min restantes</small>
        </article>
    `;
}

function matchCard(match) {
    return `
        <a class="match-card" href="${escapeHtml(match.href)}">
            <span>
                <strong>${escapeHtml(match.title)}</strong>
                <small class="muted">${escapeHtml(match.subtitle)}</small>
            </span>
            <span class="soft-badge">${escapeHtml(match.status_label)}</span>
        </a>
    `;
}

function eventCard(event) {
    return `
        <article class="event-card ${escapeHtml(event.tone)}">
            <strong>${escapeHtml(event.text)}</strong>
            <small>${escapeHtml(event.date)}</small>
        </article>
    `;
}

function renderDashboard(payload) {
    const pending = $("#pending-list");
    const active = $("#active-list");
    const events = $("#event-list");
    if (!pending || !active || !events) return;

    pending.innerHTML = payload.pending_invitations.length
        ? payload.pending_invitations.map(invitationCard).join("")
        : `<div class="empty-state">Aucune invitation.</div>`;
    active.innerHTML = payload.active_matches.length
        ? payload.active_matches.map(matchCard).join("")
        : `<div class="empty-state">Aucun match ouvert.</div>`;
    events.innerHTML = payload.events.length
        ? payload.events.map(eventCard).join("")
        : `<div class="empty-state">Rien à signaler.</div>`;

    $("#pending-count").textContent = payload.pending_invitations.length;
    $("#active-count").textContent = payload.active_matches.length;
}

async function pollDashboard() {
    if (!$("[data-dashboard]")) return;
    const payload = await fetch("/api/home-state", { credentials: "same-origin" }).then((response) => response.json());
    renderDashboard(payload);
}

function setupInvitationActions() {
    document.addEventListener("click", async (event) => {
        const button = event.target.closest(".js-invite");
        if (!button) return;
        button.disabled = true;
        const data = await fetchJson(`/matches/${button.dataset.matchId}/invitation`, {
            method: "POST",
            body: JSON.stringify({ action: button.dataset.action }),
        });
        showToast(data.message, data.ok ? "success" : "error");
        if (data.ok && data.redirect && button.dataset.action === "accept") {
            window.location.href = data.redirect;
            return;
        }
        button.disabled = false;
        pollDashboard();
    });
}

function setupChrono() {
    const chrono = $("[data-started-at]");
    if (!chrono) return;
    const started = new Date(chrono.dataset.startedAt).getTime();
    const tick = () => {
        const seconds = Math.max(0, Math.floor((Date.now() - started) / 1000));
        const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
        const rest = String(seconds % 60).padStart(2, "0");
        chrono.textContent = `${minutes}:${rest}`;
    };
    tick();
    window.setInterval(tick, 1000);
}

function setupConfirmations() {
    $$("form[data-confirm]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    setupExistingToasts();
    setupModeSwitch();
    setupRankTabs();
    setupAutocomplete();
    setupChallengeForms();
    setupInvitationActions();
    setupChrono();
    setupConfirmations();

    document.addEventListener("player:selected", updatePredictions);
    if (window.INITIAL_DASHBOARD) renderDashboard(window.INITIAL_DASHBOARD);
    if ($("[data-dashboard]")) window.setInterval(pollDashboard, 5000);
});

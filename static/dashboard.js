let books = [];
let sessions = [];
let currentTrend = "weekly";
let currentTrendMetric = "minutes";
let latestAnalytics = null;
let coverSearchTimer = null;
const internetGenreSuggestions = new Set();

const $ = selector => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
  })[c]);
}

function showToast(message, type = "") {
  const stack = $("#toast-stack");
  const el = document.createElement("div");
  el.className = `toast${type ? ` ${type}` : ""}`;
  el.textContent = message;
  stack.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 200);
  }, 2600);
}

let modalAction = null;
function showConfirm(message, onConfirm) {
  $("#modal-message").textContent = message;
  modalAction = onConfirm;
  $("#modal-overlay").classList.add("show");
  $("#modal-overlay").setAttribute("aria-hidden", "false");
}
function closeModal() {
  $("#modal-overlay").classList.remove("show");
  $("#modal-overlay").setAttribute("aria-hidden", "true");
  modalAction = null;
}
$("#modal-cancel-btn").addEventListener("click", closeModal);
$("#modal-confirm-btn").addEventListener("click", async () => {
  const action = modalAction;
  closeModal();
  if (action) await action();
});

async function api(url, options = {}) {
  const config = { ...options };
  config.headers = { ...(options.headers || {}) };
  if (config.body && typeof config.body !== "string") {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(config.body);
  }
  const response = await fetch(url, config);
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) {
    window.location.href = "/login";
    throw new Error("Please log in again.");
  }
  if (!response.ok) {
    const error = new Error(data.error || "Request failed.");
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function setError(selector, message = "") {
  $(selector).textContent = message;
}

// Tabs
async function activateTab(tabName) {
  const tab = document.querySelector(`.tab[data-tab="${tabName}"]`);
  if (!tab) return;
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
  tab.classList.add("active");
  $("#panel-" + tabName).classList.add("active");

  if (tabName === "sessions") await loadSessions();
  if (tabName === "analytics") await loadAnalytics();
  if (tabName === "goals") {
    await loadGoal();
    await loadRecommendations();
  }
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

function refreshGenreOptions(extraGenres = []) {
  extraGenres.filter(Boolean).forEach(genre => internetGenreSuggestions.add(genre));
  const genres = [...new Set([
    ...books.map(b => b.genre).filter(Boolean),
    ...internetGenreSuggestions
  ])].sort((a,b) => a.localeCompare(b));
  $("#genre-options").innerHTML = genres
    .map(g => `<option value="${escapeHtml(g)}"></option>`).join("");
}

function setCoverPreview(url) {
  const img = $("#b-cover-preview");
  const placeholder = $("#b-cover-placeholder");
  const clean = String(url || "").trim();

  if (!clean) {
    img.hidden = true;
    img.removeAttribute("src");
    placeholder.hidden = false;
    return;
  }

  img.onload = () => {
    img.hidden = false;
    placeholder.hidden = true;
  };
  img.onerror = () => {
    img.hidden = true;
    placeholder.hidden = false;
  };
  img.src = clean;
}

function setCoverUrl(url) {
  $("#b-cover-url").value = url || "";
  setCoverPreview(url);
  document.querySelectorAll(".cover-choice").forEach(choice => {
    choice.classList.toggle("selected", choice.dataset.coverUrl === url);
  });
}

function clearCoverResults() {
  $("#cover-results").innerHTML = "";
  $("#cover-search-status").textContent = "";
}

function clearBookForm() {
  $("#book-form").reset();
  $("#b-id").value = "";
  $("#book-save").textContent = "Add book";
  setCoverUrl("");
  clearCoverResults();
  setError("#b-error");
}

function coverThumb(url, title) {
  if (!url) return `<div class="book-cover-thumb placeholder">No cover</div>`;
  return `<img class="book-cover-thumb" src="${escapeHtml(url)}" alt="Cover of ${escapeHtml(title)}" loading="lazy">`;
}

function renderBooks() {
  const body = $("#books-body");
  if (!books.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty">No books added yet.</td></tr>`;
  } else {
    body.innerHTML = books.map(book => {
      const percentage = book.total_pages > 0
        ? Math.min(100, Math.round((book.current_page / book.total_pages) * 100))
        : 0;
      return `
      <tr>
        <td>${coverThumb(book.cover_url, book.title)}</td>
        <td><strong>${escapeHtml(book.title)}</strong></td>
        <td>${escapeHtml(book.genre)}</td>
        <td>
          <div class="book-progress-cell">
            <div class="book-progress-track" aria-label="${percentage}% complete">
              <div class="book-progress-fill ${escapeHtml(book.status)}" style="width:${percentage}%"></div>
            </div>
            <div class="book-progress-label"><span>${book.current_page} / ${book.total_pages} pages</span><strong>${percentage}%</strong></div>
          </div>
        </td>
        <td><span class="status-pill ${escapeHtml(book.status)}">${escapeHtml(book.status.replace("_", " "))}</span></td>
        <td class="actions-cell">
          <button class="secondary" type="button" data-action="edit" data-book-id="${book.id}">Edit</button>
          <button class="danger" type="button" data-action="delete" data-book-id="${book.id}">Delete</button>
        </td>
      </tr>`;
    }).join("");
  }

  const options = books.map(book =>
    `<option value="${book.id}">${escapeHtml(book.title)} — ${book.current_page}/${book.total_pages}</option>`
  ).join("");
  $("#s-book").innerHTML = options;
  refreshGenreOptions();
}

async function loadBooks() {
  books = await api("/api/books");
  renderBooks();
}

function beginEditBook(id) {
  const book = books.find(b => b.id === id);
  if (!book) {
    showToast("Book not found. Refresh the page and try again.", "error");
    return;
  }

  $("#b-id").value = book.id;
  $("#b-title").value = book.title;
  $("#b-genre").value = book.genre;
  $("#b-pages").value = book.total_pages;
  $("#book-save").textContent = "Save changes";
  setCoverUrl(book.cover_url || "");
  clearCoverResults();
  setError("#b-error");

  $("#book-form").scrollIntoView({ behavior: "smooth", block: "start" });
  $("#b-title").focus({ preventScroll: true });
}

function requestDeleteBook(id) {
  const book = books.find(b => b.id === id);
  if (!book) {
    showToast("Book not found. Refresh the page and try again.", "error");
    return;
  }

  showConfirm(`Delete “${book.title}” and all of its reading sessions?`, async () => {
    try {
      await api(`/api/books/${id}`, { method: "DELETE" });
      showToast("Book deleted.", "success");
      if (Number($("#b-id").value) === id) clearBookForm();
      await Promise.all([loadBooks(), loadSessions()]);
    } catch (error) {
      setError("#b-error", error.message);
      showToast(error.message, "error");
    }
  });
}

// Event delegation keeps Edit/Delete working after every table re-render.
$("#books-body").addEventListener("click", event => {
  const button = event.target.closest("button[data-action][data-book-id]");
  if (!button) return;
  const id = Number(button.dataset.bookId);
  if (button.dataset.action === "edit") beginEditBook(id);
  if (button.dataset.action === "delete") requestDeleteBook(id);
});

function renderCoverResults(matches) {
  const container = $("#cover-results");
  if (!matches.length) {
    container.innerHTML = "";
    $("#cover-search-status").textContent = "No book metadata found. You can enter genre and cover manually.";
    return;
  }

  const foundGenres = matches.flatMap(match => match.genres || []).filter(Boolean);
  refreshGenreOptions(foundGenres);

  container.innerHTML = matches.map((match, index) => `
    <button type="button" class="cover-choice"
            data-cover-url="${escapeHtml(match.cover_url)}"
            data-genre="${escapeHtml(match.genre || "")}"
            data-pages="${match.total_pages || ""}"
            title="Use this book match">
      <img src="${escapeHtml(match.cover_url)}" alt="${escapeHtml(match.title)} cover option ${index + 1}" loading="lazy">
      <span class="cover-choice-text">
        <strong>${escapeHtml(match.title)}</strong>
        <small>${escapeHtml(match.author)}${match.first_publish_year ? ` · ${match.first_publish_year}` : ""}</small>
        ${match.genre ? `<small class="cover-choice-genre">${escapeHtml(match.genre)}</small>` : ""}
      </span>
    </button>`).join("");

  document.querySelectorAll(".cover-choice").forEach(choice => {
    choice.classList.toggle("selected", choice.dataset.coverUrl === $("#b-cover-url").value);
  });
}

async function searchCovers({ autoSelect = false } = {}) {
  const title = $("#b-title").value.trim();
  if (title.length < 2) {
    $("#cover-search-status").textContent = "Type at least two characters of the title.";
    return;
  }

  $("#cover-search-status").textContent = "Looking for covers…";
  try {
    const data = await api(`/api/book-search?title=${encodeURIComponent(title)}`);
    const matches = data.matches || [];
    renderCoverResults(matches);

    if (autoSelect && matches.length) {
      const first = matches[0];
      if (!$("#b-cover-url").value.trim()) setCoverUrl(first.cover_url);
      if (!$("#b-genre").value.trim() && first.genre) $("#b-genre").value = first.genre;
      if (!$("#b-pages").value && first.total_pages) $("#b-pages").value = first.total_pages;

      const pieces = [];
      if (first.cover_url) pieces.push("cover");
      if (first.genre) pieces.push(`genre (${first.genre})`);
      if (first.total_pages) pieces.push("page count");
      $("#cover-search-status").textContent = pieces.length
        ? `Suggested ${pieces.join(", ")} from the closest match. Edit anything that is not correct.`
        : "Book match found. Review the details below.";
    } else if (matches.length) {
      $("#cover-search-status").textContent = "Choose the correct edition/match, or keep the details you entered.";
    }
  } catch (error) {
    $("#cover-search-status").textContent = "Cover lookup is unavailable right now. You can paste a cover URL manually.";
  }
}

$("#b-title").addEventListener("input", () => {
  window.clearTimeout(coverSearchTimer);
  const title = $("#b-title").value.trim();
  const editingExistingWithCover = Boolean($("#b-id").value && $("#b-cover-url").value.trim());
  if (title.length < 3 || editingExistingWithCover) return;
  coverSearchTimer = window.setTimeout(() => searchCovers({ autoSelect: true }), 850);
});

$("#find-cover").addEventListener("click", () => searchCovers({ autoSelect: true }));
$("#remove-cover").addEventListener("click", () => {
  setCoverUrl("");
  $("#cover-search-status").textContent = "Cover removed. You can search again or paste another URL.";
});
$("#b-cover-url").addEventListener("input", event => setCoverPreview(event.target.value));
$("#cover-results").addEventListener("click", event => {
  const choice = event.target.closest(".cover-choice");
  if (!choice) return;
  setCoverUrl(choice.dataset.coverUrl);
  if (choice.dataset.genre && !$("#b-genre").value.trim()) {
    $("#b-genre").value = choice.dataset.genre;
  }
  if (choice.dataset.pages && !$("#b-pages").value) {
    $("#b-pages").value = choice.dataset.pages;
  }
  $("#cover-search-status").textContent =
    "Selected book match updated. Genre and page count remain editable.";
});

$("#book-clear").addEventListener("click", clearBookForm);
$("#book-form").addEventListener("submit", async event => {
  event.preventDefault();
  const id = $("#b-id").value;
  const title = $("#b-title").value.trim();
  const genre = $("#b-genre").value.trim();
  const pages = Number($("#b-pages").value);
  const coverUrl = $("#b-cover-url").value.trim();

  if (!title || !genre || !Number.isInteger(pages) || pages <= 0) {
    setError("#b-error", "Enter a title, genre, and a positive whole number of pages.");
    return;
  }

  try {
    await api(id ? `/api/books/${id}` : "/api/books", {
      method: id ? "PUT" : "POST",
      body: { title, genre, total_pages: pages, cover_url: coverUrl }
    });
    showToast(id ? "Book updated." : "Book added.", "success");
    clearBookForm();
    await loadBooks();
  } catch (error) {
    setError("#b-error", error.message);
    showToast(error.message, "error");
  }
});

function renderSessions() {
  const body = $("#sessions-body");
  if (!sessions.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty">No reading sessions logged yet.</td></tr>`;
    return;
  }
  body.innerHTML = sessions.map(s => `
    <tr>
      <td>${s.id}</td>
      <td>${escapeHtml(s.book_title)}</td>
      <td>${escapeHtml(s.session_date)}</td>
      <td>${s.duration_minutes} min</td>
      <td>${s.pages_read}</td>
      <td class="actions-cell"><button class="danger" type="button" data-action="delete-session" data-session-id="${s.id}">Delete</button></td>
    </tr>`).join("");
}

async function loadSessions() {
  sessions = await api("/api/sessions");
  renderSessions();
}

$("#sessions-body").addEventListener("click", event => {
  const button = event.target.closest("button[data-action='delete-session'][data-session-id]");
  if (!button) return;
  const id = Number(button.dataset.sessionId);
  showConfirm("Delete this reading session? Book progress will be recalculated.", async () => {
    try {
      await api(`/api/sessions/${id}`, { method: "DELETE" });
      showToast("Session deleted.", "success");
      await Promise.all([loadSessions(), loadBooks()]);
    } catch (error) {
      setError("#s-error", error.message);
      showToast(error.message, "error");
    }
  });
});

$("#session-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!books.length) {
    setError("#s-error", "Add a book before logging a reading session.");
    return;
  }
  const payload = {
    book_id: Number($("#s-book").value),
    session_date: $("#s-date").value,
    duration_minutes: Number($("#s-duration").value),
    pages_read: Number($("#s-pages").value)
  };
  if (!payload.session_date || !Number.isInteger(payload.duration_minutes) || payload.duration_minutes <= 0 ||
      !Number.isInteger(payload.pages_read) || payload.pages_read <= 0) {
    setError("#s-error", "Enter a valid date, positive duration and positive pages read.");
    return;
  }
  try {
    await api("/api/sessions", { method: "POST", body: payload });
    $("#s-duration").value = "";
    $("#s-pages").value = "";
    setError("#s-error");
    showToast("Reading session logged.", "success");
    await Promise.all([loadSessions(), loadBooks()]);
  } catch (error) {
    setError("#s-error", error.message);
    showToast(error.message, "error");
  }
});

function drawBarChart(containerId, rows, labelKey, valueKey) {
  const el = $(containerId);
  el.innerHTML = "";
  if (!rows || rows.length === 0) {
    el.innerHTML = `<div class="empty">No data available yet</div>`;
    return;
  }
  const max = Math.max(...rows.map(row => Number(row[valueKey]) || 0), 1);
  rows.forEach(row => {
    const wrap = document.createElement("div");
    wrap.className = "bar-wrap";
    const val = Number(row[valueKey]) || 0;
    wrap.innerHTML = `
      <div class="bar-val">${val}</div>
      <div class="bar" style="height:${Math.max((val / max) * 100, 2)}%"></div>
      <div class="bar-label" title="${escapeHtml(row[labelKey])}">${escapeHtml(row[labelKey])}</div>`;
    el.appendChild(wrap);
  });
}

function formatMinutes(total) {
  total = Number(total) || 0;
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  if (hours && minutes) return `${hours}h ${minutes}m`;
  if (hours) return `${hours}h`;
  return `${minutes}m`;
}

function trendRowsForCurrentPeriod(data) {
  if (currentTrend === "daily") return data.daily_trends || [];
  if (currentTrend === "monthly") return data.monthly_trends || [];
  return data.weekly_trends || [];
}

function drawLineChart(rows, valueKey) {
  const el = $("#trend-line-chart");
  if (!rows || !rows.length) {
    el.innerHTML = `<div class="empty">No trend data available.</div>`;
    return;
  }

  const width = 860;
  const height = 240;
  const pad = { left: 48, right: 18, top: 18, bottom: 38 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const values = rows.map(row => Number(row[valueKey]) || 0);
  const maxRaw = Math.max(...values, 0);
  const maxValue = Math.max(maxRaw, 1);
  const xFor = i => pad.left + (rows.length === 1 ? plotW / 2 : (i / (rows.length - 1)) * plotW);
  const yFor = value => pad.top + plotH - (value / maxValue) * plotH;
  const points = values.map((value, i) => `${xFor(i).toFixed(1)},${yFor(value).toFixed(1)}`).join(" ");
  const areaPoints = `${pad.left},${pad.top + plotH} ${points} ${pad.left + plotW},${pad.top + plotH}`;

  const gridLines = Array.from({ length: 5 }, (_, index) => {
    const fraction = index / 4;
    const y = pad.top + plotH - fraction * plotH;
    const value = Math.round(maxValue * fraction);
    return `<line x1="${pad.left}" y1="${y}" x2="${pad.left + plotW}" y2="${y}" class="trend-grid-line" />
            <text x="${pad.left - 8}" y="${y + 4}" text-anchor="end" class="trend-y-label">${value}</text>`;
  }).join("");

  const desiredLabels = currentTrend === "daily" ? 6 : Math.min(rows.length, 7);
  const labelIndexes = new Set([0, rows.length - 1]);
  if (desiredLabels > 2) {
    for (let i = 1; i < desiredLabels - 1; i++) {
      labelIndexes.add(Math.round((i / (desiredLabels - 1)) * (rows.length - 1)));
    }
  }
  const xLabels = [...labelIndexes].sort((a,b) => a-b).map(i => `
    <text x="${xFor(i)}" y="${height - 12}" text-anchor="middle" class="trend-x-label">${escapeHtml(rows[i].label || rows[i].period)}</text>
  `).join("");

  const dots = rows.length <= 14
    ? values.map((value, i) => `<circle cx="${xFor(i)}" cy="${yFor(value)}" r="3.2" class="trend-dot"><title>${escapeHtml(rows[i].label || rows[i].period)}: ${value} ${valueKey}</title></circle>`).join("")
    : "";

  el.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
      ${gridLines}
      <polygon points="${areaPoints}" class="trend-area"></polygon>
      <polyline points="${points}" class="trend-line"></polyline>
      ${dots}
      ${xLabels}
    </svg>`;

  const total = values.reduce((sum, value) => sum + value, 0);
  const bestValue = Math.max(...values);
  const bestIndex = values.indexOf(bestValue);
  const average = rows.length ? total / rows.length : 0;
  const unit = valueKey === "minutes" ? "min" : "pages";
  $("#trend-summary").innerHTML = total > 0
    ? `<span><strong>${Math.round(total)}</strong> ${unit} in range</span><span>Average <strong>${average.toFixed(1)}</strong> per period</span><span>Peak <strong>${bestValue}</strong> on ${escapeHtml(rows[bestIndex].label || rows[bestIndex].period)}</span>`
    : `<span>No reading activity logged in this range.</span>`;
}

function updateTrendChart() {
  if (!latestAnalytics) return;
  const rows = trendRowsForCurrentPeriod(latestAnalytics);
  drawLineChart(rows, currentTrendMetric);
}


function renderBookSpeeds(rows) {
  const container = $("#book-speed-list");
  if (!rows || !rows.length) {
    container.innerHTML = `<div class="empty">Add books to see reading-speed statistics.</div>`;
    return;
  }

  container.innerHTML = rows.map(row => {
    const hasSpeed = row.pages_per_hour !== null && row.pages_per_hour !== undefined;
    const speedText = hasSpeed ? `${Number(row.pages_per_hour).toFixed(1)} pages/hour` : "No sessions yet";
    const detail = hasSpeed
      ? `${row.pages_read} pages · ${formatMinutes(row.minutes)} · ${row.session_count} session${row.session_count === 1 ? "" : "s"}`
      : `${escapeHtml(row.status.replace("_", " "))} · ${row.current_page}/${row.total_pages} pages`;
    return `
      <div class="speed-row ${hasSpeed ? "" : "no-data"}">
        <div class="speed-book-info">
          <strong>${escapeHtml(row.title)}</strong>
          <span>${escapeHtml(row.genre)}</span>
        </div>
        <div class="speed-session-detail">${detail}</div>
        <div class="speed-value">${speedText}</div>
      </div>`;
  }).join("");
}

function renderGenreSpeeds(rows) {
  drawBarChart("#genre-speed-chart", rows || [], "genre", "pages_per_hour");
}

async function loadAnalytics() {
  const data = await api("/api/analytics");
  latestAnalytics = data;
  $("#total-time-stat").textContent = formatMinutes(data.total_minutes);
  $("#total-pages-stat").textContent = `${data.total_pages || 0} pages total`;

  const activity = data.activity || {};
  $("#last-seven-stat").textContent = formatMinutes(activity.last_7_minutes || 0);
  $("#last-seven-pages-stat").textContent = activity.last_7_pages || 0;
  $("#active-days-stat").textContent = `${activity.active_days_30 || 0} / 30`;
  $("#active-day-average").textContent = `${activity.average_minutes_per_active_day_30 || 0} min per active day`;

  if (activity.change_percent === null) {
    $("#weekly-change-stat").textContent = (activity.last_7_minutes || 0) > 0 ? "New activity vs previous 7 days" : "No change vs previous 7 days";
    $("#weekly-change-stat").className = "metric-change neutral";
  } else {
    const change = Number(activity.change_percent || 0);
    const prefix = change > 0 ? "+" : "";
    $("#weekly-change-stat").textContent = `${prefix}${change}% vs previous 7 days`;
    $("#weekly-change-stat").className = `metric-change ${change > 0 ? "up" : change < 0 ? "down" : "neutral"}`;
  }

  const status = data.library_status || {};
  $("#completed-stat").textContent = status.completed || 0;
  $("#reading-stat").textContent = status.reading || 0;
  $("#library-total-stat").textContent = `${status.total || 0} in library`;

  renderBookSpeeds(data.book_speeds || []);
  renderGenreSpeeds(data.genre_speeds || []);
  drawBarChart("#genre-chart", data.genre_distribution, "genre", "count");
  updateTrendChart();
}


function setTrendPeriod(period) {
  currentTrend = period;
  ["daily", "weekly", "monthly"].forEach(name => {
    $("#trend-" + name).classList.toggle("active", name === period);
  });
  updateTrendChart();
}

function setTrendMetric(metric) {
  currentTrendMetric = metric;
  $("#metric-minutes").classList.toggle("active", metric === "minutes");
  $("#metric-pages").classList.toggle("active", metric === "pages");
  updateTrendChart();
}

$("#trend-daily").addEventListener("click", () => setTrendPeriod("daily"));
$("#trend-weekly").addEventListener("click", () => setTrendPeriod("weekly"));
$("#trend-monthly").addEventListener("click", () => setTrendPeriod("monthly"));
$("#metric-minutes").addEventListener("click", () => setTrendMetric("minutes"));
$("#metric-pages").addEventListener("click", () => setTrendMetric("pages"));

$("#goal-form").addEventListener("submit", async event => {
  event.preventDefault();
  const target = Number($("#g-target").value);
  const start = $("#g-start").value;
  const end = $("#g-end").value;
  if (!Number.isInteger(target) || target <= 0 || !start || !end || end <= start) {
    setError("#g-error", "Enter a positive target and an end date after the start date.");
    return;
  }
  try {
    await api("/api/goals", {
      method: "POST",
      body: { target_books: target, start_date: start, end_date: end }
    });
    setError("#g-error");
    showToast("Goal set.", "success");
    await loadGoal();
  } catch (error) {
    setError("#g-error", error.message);
    showToast(error.message, "error");
  }
});

async function loadGoal() {
  const goal = await api("/api/goals");
  if (!goal) {
    $("#goal-progress-text").textContent = "No goal set yet.";
    $("#goal-progress-bar").style.width = "0%";
    $("#goal-status").textContent = "";
    $("#goal-status").className = "status";
    return;
  }
  $("#g-target").value = goal.target;
  $("#g-start").value = goal.start;
  $("#g-end").value = goal.end;
  $("#goal-progress-text").textContent = `Progress: ${goal.completed} / ${goal.target} books (${goal.percentage}%) — ${goal.start} to ${goal.end}`;
  $("#goal-progress-bar").style.width = `${goal.percentage}%`;
  $("#goal-status").textContent = `Status: ${goal.prediction}`;
  $("#goal-status").className = "status " + (goal.on_track === true ? "good" : goal.on_track === false ? "bad" : "neutral");
}

async function loadRecommendations() {
  const box = $("#rec-box");
  try {
    const data = await api("/api/recommendations");
    if (!data.recommendations.length) {
      box.innerHTML = `<div class="empty">${escapeHtml(data.message)}</div>`;
      return;
    }
    box.innerHTML = `<div class="recommendation-list">${data.recommendations.map((r, index) => `
      <article class="recommendation-card">
        <div class="recommendation-card-main">
          <strong>${index + 1}. ${escapeHtml(r.title)}</strong>
          <div class="recommendation-meta">${escapeHtml(r.genre)} · ${Number(r.speed_pages_per_hour || 0).toFixed(1)} pages/hour · recommendation score ${Number(r.score).toFixed(3)}</div>
          <div class="recommendation-reason">${escapeHtml(r.reason)}</div>
        </div>
        <button class="secondary recommendation-add" type="button"
                data-title="${escapeHtml(r.title)}" data-genre="${escapeHtml(r.genre)}">Add to reading list</button>
      </article>`).join("")}</div>`;
  } catch (error) {
    box.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

$("#rec-box").addEventListener("click", async event => {
  const button = event.target.closest("button.recommendation-add");
  if (!button) return;
  const title = button.dataset.title;
  const genre = button.dataset.genre;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Adding…";

  try {
    await api("/api/recommendations/add", {
      method: "POST",
      body: { title, genre }
    });
    showToast(`“${title}” added to your reading list.`, "success");
    await loadBooks();
    await loadRecommendations();
  } catch (error) {
    if (error.data?.code === "pages_required" && error.data.prefill) {
      const item = error.data.prefill;
      await activateTab("books");
      clearBookForm();
      $("#b-title").value = item.title || title;
      $("#b-genre").value = item.genre || genre;
      $("#b-pages").value = item.total_pages || "";
      setCoverUrl(item.cover_url || "");
      setError("#b-error", error.message);
      $("#book-form").scrollIntoView({ behavior: "smooth", block: "start" });
      $("#b-pages").focus({ preventScroll: true });
      showToast("Book details were prefilled. Confirm the page count to add it.", "error");
      return;
    }
    showToast(error.message, "error");
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
});

$("#refresh-recommendations").addEventListener("click", loadRecommendations);

(async function initialise() {
  const today = new Date().toISOString().slice(0,10);
  $("#s-date").value = today;
  setCoverPreview("");
  try {
    await loadBooks();
    await loadSessions();
  } catch (error) {
    showToast(error.message, "error");
  }
})();

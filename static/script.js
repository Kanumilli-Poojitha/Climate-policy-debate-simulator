const form = document.getElementById("debate-form");
const topicInput = document.getElementById("topic");
const roundsInput = document.getElementById("rounds");
const startButton = document.getElementById("start-button");
const statusText = document.getElementById("status-text");
const messageCount = document.getElementById("message-count");
const messagesContainer = document.getElementById("messages");
const errorContainer = document.getElementById("error");

function setLoading(isLoading) {
  startButton.disabled = isLoading;
  statusText.textContent = isLoading ? "Running debate..." : "Ready to start.";
  startButton.innerHTML = isLoading
    ? '<span aria-hidden="true">●</span> Debating...'
    : "Start Debate";
  startButton.setAttribute("aria-busy", String(isLoading));
}

function clearTranscript() {
  messagesContainer.innerHTML = "";
  errorContainer.textContent = "";
  messageCount.textContent = "0 messages";
}

function renderMessages(messages) {
  messagesContainer.innerHTML = messages
    .map((message) => {
      const timestamp = new Date(message.timestamp).toLocaleString();
      return `
        <article class="message">
          <header>
            <span><span class="agent">${escapeHtml(message.agent)}</span> · Round ${escapeHtml(message.round)}</span>
            <span class="stance">${escapeHtml(message.stance)}</span>
          </header>
          <div>${escapeHtml(message.message)}</div>
          <header style="margin-top: 10px;">
            <span>${escapeHtml(timestamp)}</span>
          </header>
        </article>
      `;
    })
    .join("");
  messageCount.textContent = `${messages.length} messages`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearTranscript();
  setLoading(true);

  const payload = {
    topic: topicInput.value.trim(),
    rounds: Number(roundsInput.value),
  };

  try {
    const response = await fetch("/api/v1/debate/start", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const rawText = await response.text();
    const data = rawText ? JSON.parse(rawText) : {};
    if (!response.ok) {
      throw new Error(data.detail || "Debate request failed.");
    }

    renderMessages(data.messages || []);
    statusText.textContent = `Debate complete. ${data.messages?.length || 0} messages generated.`;
  } catch (error) {
    errorContainer.textContent = error instanceof Error ? error.message : "An unexpected error occurred.";
    statusText.textContent = "Debate failed.";
  } finally {
    setLoading(false);
  }
});

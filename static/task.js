"use strict";

const tutorial = document.querySelector("#tutorial");
const instructionsButton = document.querySelector("#view-instructions");
const tutorialStorageKey = "emotion-labeler:tutorial:v3";

instructionsButton.hidden = false;
instructionsButton.addEventListener("click", () => tutorial.showModal());
document.querySelector("#tutorial-done").addEventListener("click", () => {
  try {
    localStorage.setItem(tutorialStorageKey, "complete");
  } catch {
    // Labeling also works when the browser blocks local storage.
  }
  tutorial.close();
});
let tutorialCompleted = false;
try {
  tutorialCompleted = localStorage.getItem(tutorialStorageKey) === "complete";
} catch {
  // Show instructions on each visit if completion cannot be remembered.
}
if (!tutorialCompleted) tutorial.showModal();

const taskData = document.querySelector("#task-data");
if (taskData) initializeTask(JSON.parse(taskData.textContent));

function initializeTask(task) {
  const form = document.querySelector("#labeling-form");
  const card = document.querySelector("#tweet-card");
  const heading = document.querySelector("#message-heading");
  const submitButton = document.querySelector("#submit-batch");
  const nextButton = document.querySelector("#next-tweet");
  const progressLabel = document.querySelector("#progress-label");
  const progressMeter = document.querySelector("#task-progress");
  const errorMessage = document.querySelector("#save-error");
  const resumeLink = document.querySelector("#resume-session");
  const completion = document.querySelector("#completion");
  const radios = Array.from(form.querySelectorAll('input[name="label"]'));
  const navigation = Array.from(form.querySelectorAll(".tweet-number"));
  const draftKey = `emotion-labeler:batch:${task.batchId}`;
  let labels = task.tweets.map(() => null);
  let currentIndex = 0;
  let saving = false;

  function storeDraft() {
    try {
      sessionStorage.setItem(draftKey, JSON.stringify({ labels, currentIndex }));
    } catch {
      document.querySelector("#draft-warning").hidden = false;
    }
  }

  function clearDraft() {
    try { sessionStorage.removeItem(draftKey); } catch { /* Storage may be blocked. */ }
  }

  function showCompletion(focus = false) {
    form.hidden = true;
    completion.hidden = false;
    progressMeter.value = task.tweets.length;
    progressLabel.textContent = task.submitted ? `${task.tweets.length} labels submitted` : "Labeling complete";
    document.querySelector("#total-progress").textContent = `${task.completedCount} saved overall`;
    const title = document.querySelector("#completion-title");
    const message = document.querySelector("#completion-message");
    title.textContent = task.remainingCount === 0 ? "All tweets labeled" : "Batch submitted";
    message.textContent = task.remainingCount === 0
      ? "Your answers are saved. Thank you for taking part."
      : "Your answers are saved. You can stop here or label another batch.";
    if (task.totalCount === 0) {
      title.textContent = "No tweets available";
      message.textContent = "There are no tweets in this dataset yet. Please check back later.";
      progressLabel.textContent = "No tweets available";
    }
    document.querySelector("#next-batch-form").hidden = task.remainingCount === 0;
    document.querySelector("#next-batch").textContent = `Label ${Math.min(5, task.remainingCount)} more`;
    if (focus) title.focus();
  }

  function updateProgress() {
    const answered = labels.filter(Boolean).length;
    progressLabel.textContent = `${answered} of ${task.tweets.length} labeled in this batch`;
    progressMeter.value = answered;
    const complete = answered === task.tweets.length;
    submitButton.hidden = !complete;
    nextButton.hidden = complete;
    nextButton.disabled = !labels[currentIndex];
    navigation.forEach((button, index) => {
      button.setAttribute("aria-label", `Tweet ${index + 1}, ${labels[index] ? "labeled" : "unanswered"}`);
      button.querySelector(".answer-marker").textContent = labels[index] ? "✓" : "";
      if (index === currentIndex) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
  }

  function showTweet(index, focus = true) {
    currentIndex = index;
    heading.textContent = `Tweet ${index + 1} of ${task.tweets.length}`;
    document.querySelector("#tweet-text").textContent = task.tweets[index].text;
    radios.forEach(radio => { radio.checked = radio.value === labels[index]; });
    updateProgress();
    storeDraft();
    if (focus) heading.focus({ preventScroll: true });
  }

  if (task.submitted || task.tweets.length === 0) {
    clearDraft();
    showCompletion();
    return;
  }
  try {
    const draft = JSON.parse(sessionStorage.getItem(draftKey));
    if (draft && Array.isArray(draft.labels) && draft.labels.length === labels.length) {
      labels = draft.labels.map(label => radios.some(radio => radio.value === label) ? label : null);
      if (Number.isInteger(draft.currentIndex) && draft.currentIndex >= 0 && draft.currentIndex < labels.length) {
        currentIndex = draft.currentIndex;
      }
    }
  } catch {
    // Invalid or unavailable drafts never prevent starting a batch.
  }

  navigation.forEach((button, index) => button.addEventListener("click", () => showTweet(index)));
  nextButton.addEventListener("click", () => {
    if (saving || !labels[currentIndex]) return;
    for (let offset = 1; offset < labels.length; offset++) {
      const index = (currentIndex + offset) % labels.length;
      if (!labels[index]) {
        showTweet(index);
        return;
      }
    }
  });
  radios.forEach(radio => radio.addEventListener("change", () => {
    labels[currentIndex] = radio.value;
    errorMessage.hidden = true;
    updateProgress();
    storeDraft();
  }));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (saving) return;
    errorMessage.hidden = true;
    resumeLink.hidden = true;
    const unanswered = labels.findIndex(label => !label);
    if (unanswered !== -1) {
      showTweet(unanswered);
      errorMessage.textContent = "Choose an emotion for every tweet before submitting.";
      errorMessage.hidden = false;
      return;
    }
    saving = true;
    card.disabled = true;
    navigation.forEach(button => { button.disabled = true; });
    submitButton.disabled = true;
    submitButton.textContent = "Submitting…";
    form.setAttribute("aria-busy", "true");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          batch_id: task.batchId,
          answers: task.tweets.map((tweet, index) => ({ tweet_id: tweet.id, label: labels[index] })),
        }),
        signal: controller.signal,
      });
      if (response.status === 401 || response.status === 409) {
        const result = await response.json();
        resumeLink.hidden = false;
        throw new Error(result.error);
      }
      if (!response.ok || (await response.json()).saved !== true) {
        throw new Error("Submission not confirmed");
      }
      task.submitted = true;
      task.completedCount += task.tweets.length;
      task.remainingCount -= task.tweets.length;
      clearDraft();
      showCompletion(true);
    } catch (error) {
      errorMessage.textContent = resumeLink.hidden
        ? "We couldn’t confirm the submission. Your choices are still here. Try Submit labels again."
        : error.message;
      errorMessage.hidden = false;
    } finally {
      clearTimeout(timeout);
      saving = false;
      card.disabled = false;
      navigation.forEach(button => { button.disabled = false; });
      submitButton.disabled = false;
      submitButton.textContent = "Submit labels";
      form.removeAttribute("aria-busy");
    }
  });
  form.hidden = false;
  showTweet(currentIndex, false);
}

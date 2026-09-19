"use strict";

const tutorial = document.querySelector("#tutorial");
const instructionsButton = document.querySelector("#view-instructions");
const tutorialStorageKey = "emotion-labeler:tutorial:v2";

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
  const messageHeading = document.querySelector("#message-heading");
  const previousButton = document.querySelector("#previous-message");
  const nextButton = document.querySelector("#next-message");
  const progressLabel = document.querySelector("#progress-label");
  const progressMeter = document.querySelector("#task-progress");
  const errorMessage = document.querySelector("#save-error");
  const resumeLink = document.querySelector("#resume-session");
  const completion = document.querySelector("#completion");
  const radios = Array.from(form.querySelectorAll('input[name="label"]'));
  const drafts = new Map();
  let currentIndex = task.completedCount;
  let saving = false;

  function showMessage(index, focus = true) {
    currentIndex = index;
    const finished = index === task.tweets.length;
    form.hidden = finished;
    completion.hidden = !finished;
    errorMessage.hidden = true;
    resumeLink.hidden = true;
    progressLabel.textContent = `${task.completedCount} of ${task.tweets.length} labeled`;
    progressMeter.value = task.completedCount;
    if (finished) {
      document.querySelector("#review-answers").hidden = task.tweets.length === 0;
      if (task.tweets.length === 0) {
        document.querySelector("#completion-title").textContent = "No messages available";
        document.querySelector("#completion-message").textContent = "There are no messages in this dataset yet. Please check back later.";
      }
      if (focus) document.querySelector("#completion-title").focus();
      return;
    }
    const tweet = task.tweets[index];
    const selectedLabel = drafts.get(tweet.id) ?? tweet.label;
    messageHeading.textContent = `Message ${index + 1} of ${task.tweets.length}`;
    document.querySelector("#tweet-text").textContent = tweet.text;
    radios.forEach(radio => { radio.checked = radio.value === selectedLabel; });
    previousButton.disabled = index === 0;
    if (focus) messageHeading.focus({ preventScroll: true });
  }

  radios.forEach(radio => radio.addEventListener("change", () => {
    drafts.set(task.tweets[currentIndex].id, radio.value);
  }));
  previousButton.addEventListener("click", () => showMessage(currentIndex - 1));
  document.querySelector("#review-answers").addEventListener("click", () => showMessage(0));

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (saving || !form.reportValidity()) return;
    const tweet = task.tweets[currentIndex];
    const label = radios.find(radio => radio.checked).value;
    saving = true;
    card.disabled = true;
    previousButton.disabled = true;
    nextButton.disabled = true;
    nextButton.textContent = "Saving…";
    form.setAttribute("aria-busy", "true");
    errorMessage.hidden = true;
    resumeLink.hidden = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tweet_id: tweet.id, label }),
        signal: controller.signal,
      });
      if (!response.ok) {
        resumeLink.hidden = response.status !== 401;
        throw new Error("Save failed");
      }
      const result = await response.json();
      if (result.saved !== true) throw new Error("Save not confirmed");
      if (tweet.label === null) task.completedCount += 1;
      tweet.label = label;
      drafts.delete(tweet.id);
      showMessage(currentIndex + 1);
    } catch {
      errorMessage.textContent = resumeLink.hidden
        ? "We couldn’t confirm the save. Your choice is still selected. Try Save & next again."
        : "Your session ended. Enter your email in the new tab, then retry this answer here.";
      errorMessage.hidden = false;
    } finally {
      clearTimeout(timeout);
      saving = false;
      card.disabled = false;
      previousButton.disabled = currentIndex === 0;
      nextButton.disabled = false;
      nextButton.textContent = "Save & next";
      form.removeAttribute("aria-busy");
    }
  });
  showMessage(currentIndex, false);
}

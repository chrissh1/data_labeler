"use strict";

const form = document.querySelector("#labeling-form");
const emailInput = document.querySelector("#email");
const cards = Array.from(form.querySelectorAll(".tweet-card"));
const previousButton = document.querySelector("#previous-message");
const nextButton = document.querySelector("#next-message");
const progressLabel = document.querySelector("#progress-label");
const progress = document.querySelector("#task-progress");
const tutorial = document.querySelector("#tutorial");
const instructionsButton = document.querySelector("#view-instructions");
const tutorialStorageKey = "emotion-labeler:tutorial:v1";
let currentIndex = 0;
let submitting = false;

function showMessage(index) {
  currentIndex = index;
  cards.forEach((card, cardIndex) => {
    card.hidden = cardIndex !== currentIndex;
  });
  previousButton.disabled = currentIndex === 0;
  nextButton.textContent = currentIndex === cards.length - 1 ? "Submit labels" : "Next";
  progressLabel.textContent = `Message ${currentIndex + 1} of ${cards.length}`;
  progress.value = currentIndex + 1;
  cards[currentIndex].querySelector("legend").focus();
}

function validateMessage(index) {
  if (cards[index].querySelector("input[type=radio]:checked")) {
    return true;
  }
  showMessage(index);
  cards[index].querySelector("input[type=radio]").reportValidity();
  return false;
}

form.noValidate = true; // Validate visible steps explicitly so hidden fields never steal focus.
form.addEventListener("submit", (event) => {
  if (submitting) {
    event.preventDefault();
    return;
  }
  emailInput.value = emailInput.value.trim();
  if (!emailInput.reportValidity() || !validateMessage(currentIndex)) {
    event.preventDefault();
    return;
  }
  if (currentIndex < cards.length - 1) {
    event.preventDefault();
    showMessage(currentIndex + 1);
    return;
  }
  if (!cards.every((card, index) => validateMessage(index))) {
    event.preventDefault();
    return;
  }
  submitting = true;
  nextButton.disabled = true;
  previousButton.disabled = true;
  nextButton.textContent = "Saving…";
});

previousButton.addEventListener("click", () => showMessage(currentIndex - 1));
instructionsButton.addEventListener("click", () => tutorial.showModal());
document.querySelector("#tutorial-done").addEventListener("click", () => {
  try {
    localStorage.setItem(tutorialStorageKey, "complete");
  } catch {
    // Labeling still works when the browser blocks local storage.
  }
  tutorial.close();
});

form.hidden = false;
instructionsButton.hidden = false;
let tutorialCompleted = false;
try {
  tutorialCompleted = localStorage.getItem(tutorialStorageKey) === "complete";
} catch {
  // Show the tutorial on each visit when completion cannot be remembered.
}
if (!tutorialCompleted) {
  tutorial.showModal();
}

window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    submitting = false;
    nextButton.disabled = false;
    showMessage(currentIndex);
  }
});

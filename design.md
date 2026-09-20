# Emotion Labeling — design

A small research form for participants labeling the emotion in short messages.

- Tone: plain, approachable, utilitarian. Use the existing system font intentionally.
- Genre: modern-minimal, adapted to a research form rather than a marketing page.
- Structure: one narrow working column. Small heading, Labeling/Results navigation, instructions, progress, tweet, native radio choices, numbered batch navigation, and Next. Submit labels replaces Next only when the batch is fully labeled. Results use a wider table and stacked rows on small screens.
- Palette: lightly tinted background, white working panel, dark ink, gray borders, and blue primary actions. Colors and spacing are defined in tokens.css.
- Typography: 16px system text, 26px headings, 20px message text. No external fonts.
- Controls: outlined secondary buttons, a solid primary button, and native radios in large bordered choices. Selected choices have a blue border and pale fill. Touch targets are at least 44px, with 6px control corners and immediate focus rings.
- Progress: a compact count and bar track choices in the current batch, with a separate count of submitted labels. Numbered buttons distinguish the current tweet from answered tweets.
- Motion: none. Loading and errors use inline text; submission ends with confirmation and an optional next batch.
- Tutorial: a short native dialog, shown once per browser, always reopenable.
- Results: normal links navigate between Labeling and Results in the same tab. The signed cookie retains the batch; session storage retains its unsubmitted choices and current tweet.
- Shared rules: preserve Flask routes and the email-hash privacy boundary. No decorative graphics, marketing copy, font downloads, or new UI dependencies.

The user's request for a familiar research interface and preserved flow takes precedence over Hallmark's structure rotation and multiple-font recommendations. The styling adds clear controls and grouping without decorative graphics or animation.

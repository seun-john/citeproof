# Testing the demo on a phone

About ten minutes. Open the published address on the phone (the README lists how to get it there,
including a QR code). Tick each line as you go. If something does not match, note which number
and send it with the details at the bottom.

**Before you start:** use mobile data or Wi-Fi, and close other tabs if the phone is old.

1. **Opens.** The page loads and shows "Check your references". *Expect:* nothing is cut off on
   the right; you never have to scroll sideways.
2. **Engine ready.** A pill near the top says "Loading the Python engine…", then "Ready · CiteProof
   0.1.0 runs in this tab". *Expect:* under a minute on a normal connection (it downloads about
   12 MB the first time). If it says it ran out of memory or cannot run WebAssembly, that is
   useful to know. Tell me the phone and browser.
3. **Tap, don't type.** Tap **10-reference test**, then **Check references**. *Expect:* three
   boxes in a row (Verified, Mismatch, No verdict) visible without scrolling. With the sample
   catalogue and Crossref switched off, you should see **2 of 10, 3 of 10, 5 of 10**.
4. **Online lookups.** The two Crossref boxes (just above the Check button) are ticked by
   default. Tap **Check references** again. *Expect:* a panel "Crossref lookups" listing what happened, and **Exactly what was sent**
   when you open it. Some "No verdict" references should now show "Possible DOIs from Crossref".
5. **Read a card.** Tap **Details** on any reference. *Expect:* CiteProof's own wording and the
   rest of the evidence open, and the text wraps instead of running off the screen.
6. **Filters.** Tap **No verdict**. *Expect:* only those references are listed.
7. **Reformat.** Tap **Mixed styles**, **Check references**, open **Reformat these references
   into another style**, choose **APA 7th edition**, tap **Reformat**. *Expect:* a short wait the
   first time (about 3 MB), then a neat list with italic journal names.
8. **Copy.** Tap **Copy all**, open Notes or Google Docs, and paste. *Expect:* the references
   appear, with italics.
9. **Download.** Tap **Download (.txt)**. *Expect:* a text file is saved or offered to share.
10. **Another style.** Choose **IEEE**, tap **Reformat**. *Expect:* the list is numbered `[1]`,
    `[2]`.
11. **Rotate** the phone sideways and back. *Expect:* the layout adapts, no sideways scrolling.
12. **Dark mode.** Switch the phone to dark mode. *Expect:* the page follows it, and text stays
    easy to read.
13. **Large text.** Increase the text size in the phone's settings. *Expect:* everything still
    fits and stays tappable.
14. **Offline.** After the page has loaded, switch on airplane mode and tap **Check references**.
    *Expect:* it still works (everything runs on the phone). Reformatting for the first time
    offline should explain that it could not load, not hang.
15. **Add to Home Screen** (optional). *Expect:* an icon with a white tick on blue, and the page
    opens full-screen.

## What to send me if something is wrong

- The phone model and operating system version, and the browser (Safari, Chrome, Firefox…).
- The step number, what you expected, and what happened. A screenshot helps.
- Whether it was on Wi-Fi or mobile data.

Please don't send your own references unless you are comfortable doing so. The 10-reference
test set shows the same behaviour.

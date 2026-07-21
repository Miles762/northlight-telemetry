import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const app = readFileSync(resolve("src/App.tsx"), "utf8");
const checks = [
  {
    name: "page has a header landmark",
    ok: /<header\b/.test(app),
  },
  {
    name: "page has a main landmark",
    ok: /<main\b/.test(app),
  },
  {
    name: "diagnostic disclaimer is exposed as a note",
    ok: /role="note"/.test(app),
  },
  {
    name: "status marker icon is hidden from assistive tech",
    ok: /<span aria-hidden>/.test(app),
  },
  {
    name: "buttons are not icon-only without labels",
    ok: !/<button\b(?![^>]*(aria-label|title))[^>]*>\s*<[^>]+>\s*<\/button>/s.test(app),
  },
  {
    name: "form controls have labels or aria labels if added",
    ok: unlabeledControls(app).length === 0,
  },
];

const failures = checks.filter((check) => !check.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(`FAIL: ${failure.name}`);
  }
  process.exit(1);
}

console.log(`a11y smoke OK (${checks.length} checks)`);

function unlabeledControls(source) {
  const controls = source.match(/<(input|select|textarea)\b[^>]*>/g) ?? [];
  return controls.filter((tag) => {
    return !/\b(id|aria-label|aria-labelledby)=/.test(tag);
  });
}

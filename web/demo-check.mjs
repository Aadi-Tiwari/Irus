import puppeteer from "puppeteer-core";
const SP = process.argv[3];
const b = await puppeteer.launch({ executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe", headless: false, defaultViewport: { width: 1440, height: 900 }, args: ["--autoplay-policy=no-user-gesture-required"] });
const p = await b.newPage();
const errs = [];
p.on("pageerror", e => errs.push("pageerror: " + e.message));
p.on("console", m => m.type() === "error" && errs.push("console: " + m.text()));
await p.goto(process.argv[2], { waitUntil: "load" });
await new Promise(r => setTimeout(r, 2500));
const y = await p.evaluate(() => Math.round(document.querySelector("#demo").getBoundingClientRect().top + window.scrollY));
await p.evaluate(v => window.scrollTo(0, v - 40), y);
const shots = [];
for (const wait of [1500, 3500, 4000, 5000]) {
  await new Promise(r => setTimeout(r, wait));
  const n = await p.evaluate(() => document.querySelectorAll("#demo pre > div").length);
  shots.push(n);
}
await p.screenshot({ path: `${SP}/demo.jpg`, type: "jpeg", quality: 70 });
await new Promise(r => setTimeout(r, 9000));
const final = await p.evaluate(() => ({
  lines: document.querySelectorAll("#demo pre > div").length,
  activeStep: [...document.querySelectorAll("#demo .rounded-xl")].findIndex(e => e.className.includes("border-emerald-400/30")),
  text: document.querySelector("#demo pre").innerText.slice(-260),
}));
await p.screenshot({ path: `${SP}/demo-done.jpg`, type: "jpeg", quality: 70 });
const sections = await p.evaluate(() => document.querySelectorAll("main > section, main > div[data-snap]").length);
console.log(JSON.stringify({ lineProgress: shots, final, sections, errors: errs }, null, 1));
await b.close();

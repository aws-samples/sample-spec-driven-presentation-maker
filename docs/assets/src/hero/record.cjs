// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Recorder for the README key visual. Run by replay.py, not by hand:
 *
 *   node record.cjs <plan.json>
 *
 * Opens the Local Web UI on the replay deck, starts a CDP screencast and runs the plan's
 * actions in order:
 *
 *   {"place": [[src, dst], ...], "show_ms": N?, "tail_cut_ms": N?, "pin": true?}
 *       Copy compose payloads into the deck (the Web UI picks them up on its next poll and
 *       animates the visible slides), then wait until no animation is on screen. The idle
 *       stretch between placing and the animation starting is cut; so is everything after
 *       the first show_ms of the animation (when given), or the last tail_cut_ms of it.
 *   {"speed": F}           the GIF plays the recording from here on F times faster
 *   {"resize": [[w, h], ...], "step_ms": N}   viewport sizes in turn (a zoom-out)
 *   {"scroll": slug, "ms": N}   smooth-scroll the slide list so the slug's slide is on top
 *   {"click": "<aria-label regex>", "ms": N, "cut_until_images": true?}
 *       click a button, then wait N ms (after the view's images loaded, cutting until then)
 *   {"sleep": N}
 *
 * Writes every frame to plan.frames_dir and a frames.json with the frame times, the cuts
 * (idle / trim) and the speed changes; replay.py turns that into the GIF.
 *
 * Playwright comes from web-ui/node_modules (plan.webui).
 */

const fs = require("fs")
const path = require("path")

const plan = JSON.parse(fs.readFileSync(process.argv[2], "utf8"))
const { chromium } = require(path.join(plan.webui, "node_modules", "playwright"))

const now = () => Date.now() / 1000
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** Copy through a temporary name so the poller never reads a half-written payload. */
function place(src, dst) {
  fs.mkdirSync(path.dirname(dst), { recursive: true })
  const tmp = `${dst}.part`
  fs.copyFileSync(src, tmp)
  fs.renameSync(tmp, dst)
}

async function waitFor(check, timeoutMs, label) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (await check()) return
    await sleep(40)
  }
  throw new Error(`timed out waiting for ${label}`)
}

;(async () => {
  // Without the flag, headless Chrome's screencast sends frames at 1x whatever the context's
  // deviceScaleFactor.
  const browser = await chromium.launch({
    headless: true,
    channel: "chrome",
    args: [`--force-device-scale-factor=${plan.scale}`],
  })
  const context = await browser.newContext({
    viewport: { width: plan.viewport[0], height: plan.viewport[1] },
    deviceScaleFactor: plan.scale,
    locale: plan.locale,
    colorScheme: "dark",
  })
  await context.addInitScript(({ uiLocale }) => {
    try { localStorage.setItem("sdpm-locale", uiLocale) } catch { /* ignore */ }
    // Next.js dev-mode indicator; not part of the app.
    const hide = () => {
      const style = document.createElement("style")
      style.textContent = "nextjs-portal{display:none!important}"
      document.head.appendChild(style)
    }
    if (document.head) hide()
    else document.addEventListener("DOMContentLoaded", hide)
  }, { uiLocale: plan.ui_locale })
  const page = await context.newPage()

  // Warm-up load: the dev server compiles the route on first request.
  await page.goto(plan.url, { waitUntil: "networkidle", timeout: 120000 })
  await page.reload({ waitUntil: "networkidle", timeout: 120000 })
  await page.waitForTimeout(2500)
  await page.mouse.move(plan.viewport[0] - 2, plan.viewport[1] - 2)

  const cdp = await context.newCDPSession(page)
  const frames = []
  fs.mkdirSync(plan.frames_dir, { recursive: true })
  cdp.on("Page.screencastFrame", (event) => {
    const file = path.join(plan.frames_dir, `f${String(frames.length).padStart(5, "0")}.png`)
    fs.writeFileSync(file, Buffer.from(event.data, "base64"))
    frames.push({ file, t: now() })
    cdp.send("Page.screencastFrameAck", { sessionId: event.sessionId }).catch(() => {})
  })
  await cdp.send("Page.startScreencast", {
    format: "png",
    maxWidth: plan.viewport[0] * plan.scale,
    maxHeight: plan.viewport[1] * plan.scale,
    everyNthFrame: 1,
  })

  const cuts = []
  const speeds = []
  let firstAnimation = null
  const t0 = now()
  await sleep(plan.hold_start_ms)
  // The Web UI follows compose updates to the slide that changed last, and starts following
  // again 3 s after the user last scrolled. While `pin` is set, a 1 px wheel tick (back and
  // forth) every 800 ms keeps the list where the plan scrolled it.
  let lastNudge = 0
  let nudgeDir = 1
  const nudge = async () => {
    if (Date.now() - lastNudge < 800) return
    lastNudge = Date.now()
    await page.mouse.move(12, 400)
    await page.mouse.wheel(0, nudgeDir)
    nudgeDir = -nudgeDir
  }
  const overlays = async (pin) => {
    if (pin) await nudge()
    return page.locator(".asp-overlay").count()
  }
  for (const [index, action] of plan.actions.entries()) {
    const label = `action ${index + 1}`
    if (action.place) {
      const placedAt = now()
      for (const [src, dst] of action.place) place(src, dst)
      await waitFor(async () => (await overlays(action.pin)) > 0, 20000, `${label} animation start`)
      const startedAt = now()
      firstAnimation ??= startedAt
      cuts.push([placedAt, startedAt, "idle"])
      // Done when no animation overlay has been on screen for 400 ms.
      let quietSince = null
      await waitFor(async () => {
        if ((await overlays(action.pin)) > 0) { quietSince = null; return false }
        quietSince ??= now()
        return now() - quietSince >= 0.4
      }, 90000, `${label} animation end`)
      const doneAt = now()
      if (action.show_ms) cuts.push([startedAt + action.show_ms / 1000, doneAt, "trim"])
      else cuts.push([quietSince - (action.tail_cut_ms ?? 0) / 1000, doneAt, "trim"])
      console.log(`${label}: placed ${action.place.length} file(s), animated ${(quietSince - startedAt).toFixed(1)} s`)
    } else if (action.speed) {
      speeds.push([now(), action.speed])
    } else if (action.resize) {
      for (const [width, height] of action.resize) {
        await page.setViewportSize({ width, height })
        await sleep(action.step_ms ?? 40)
      }
    } else if (action.scroll) {
      // A wheel tick over the list first: the Web UI stops following compose updates once the
      // user scrolls, so the slides placed next do not pull the list to the last of them.
      await page.mouse.move(12, 400)
      await page.mouse.wheel(0, 1)
      await page.mouse.move(plan.viewport[0] - 2, plan.viewport[1] - 2)
      await page.evaluate((slug) => {
        const scroller = document.querySelector("[data-slide-scroller]")
        const slide = scroller?.querySelector(`[data-slide-id="${slug}"]`)
        if (!scroller || !slide) throw new Error(`no slide ${slug}`)
        const top = slide.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop - 24
        scroller.scrollTo({ top, behavior: "smooth" })
      }, action.scroll)
      await sleep(action.ms ?? 700)
    } else if (action.click) {
      const clickedAt = now()
      await page.getByRole("button", { name: new RegExp(action.click) }).click()
      await page.mouse.move(2, plan.viewport[1] - 2)
      if (action.cut_until_images) {
        // The view change fades the new view in while its images load: cut to the settled view.
        await sleep(300)
        await waitFor(() => page.evaluate(() => [...document.querySelectorAll("[data-slide-scroller] img")]
          .every((img) => img.complete && img.naturalWidth > 0)), 20000, `${label} images`)
        await sleep(400)
        cuts.push([clickedAt, now(), "trim"])
      }
      await sleep(action.ms ?? 0)
    } else if (action.sleep) {
      await sleep(action.sleep)
    }
  }
  const end = now()
  await cdp.send("Page.stopScreencast")
  await sleep(300)

  fs.writeFileSync(
    path.join(plan.frames_dir, "frames.json"),
    JSON.stringify({ t0, end, first_animation: firstAnimation, frames, cuts, speeds }, null, 1),
  )
  console.log(`recorded ${frames.length} frames over ${(end - t0).toFixed(1)} s`)
  await browser.close()
})().catch((error) => {
  console.error(error)
  process.exit(1)
})

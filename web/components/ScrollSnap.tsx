"use client";

import { useEffect } from "react";

const easeInOutCubic = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

/**
 * Full-page scroll snapping. Any scroll/swipe/arrow input animates to exactly
 * the next (or previous) section, one per gesture — no free scrolling. Targets
 * are every element marked with [data-snap].
 */
export default function ScrollSnap() {
  useEffect(() => {
    const getTargets = () =>
      Array.from(document.querySelectorAll<HTMLElement>("[data-snap]")).map(
        (el) => el.getBoundingClientRect().top + window.scrollY,
      );

    let index = 0;
    let animating = false;
    let lockUntil = 0;

    const sync = () => {
      const targets = getTargets();
      const y = window.scrollY;
      let best = 0;
      let bestD = Infinity;
      targets.forEach((t, i) => {
        const d = Math.abs(t - y);
        if (d < bestD) {
          bestD = d;
          best = i;
        }
      });
      index = best;
    };
    sync();

    const goTo = (i: number) => {
      const targets = getTargets();
      i = Math.max(0, Math.min(targets.length - 1, i));
      const startY = window.scrollY;
      const endY = Math.round(targets[i]);
      if (Math.abs(endY - startY) < 2) {
        index = i;
        return;
      }
      index = i;
      animating = true;
      const dist = endY - startY;
      const dur = Math.min(1500, Math.max(750, Math.abs(dist) * 0.9));
      let start: number | null = null;
      const step = (ts: number) => {
        if (start === null) start = ts;
        const p = Math.min(1, (ts - start) / dur);
        window.scrollTo(0, startY + dist * easeInOutCubic(p));
        if (p < 1) {
          requestAnimationFrame(step);
        } else {
          animating = false;
          lockUntil = ts + 140;
        }
      };
      requestAnimationFrame(step);
    };

    const blocked = () => animating || performance.now() < lockUntil;

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (blocked() || Math.abs(e.deltaY) < 4) return;
      goTo(index + (e.deltaY > 0 ? 1 : -1));
    };

    const onKey = (e: KeyboardEvent) => {
      const down = ["ArrowDown", "PageDown", " ", "Spacebar"].includes(e.key);
      const up = ["ArrowUp", "PageUp"].includes(e.key);
      if (!down && !up) return;
      e.preventDefault();
      if (blocked()) return;
      goTo(index + (down ? 1 : -1));
    };

    let touchY = 0;
    const onTouchStart = (e: TouchEvent) => {
      touchY = e.touches[0]?.clientY ?? 0;
    };
    const onTouchMove = (e: TouchEvent) => {
      e.preventDefault();
      if (blocked()) return;
      const dy = touchY - (e.touches[0]?.clientY ?? 0);
      if (Math.abs(dy) > 24) goTo(index + (dy > 0 ? 1 : -1));
    };

    window.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("keydown", onKey);
    window.addEventListener("touchstart", onTouchStart, { passive: false });
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("resize", sync);

    return () => {
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("resize", sync);
    };
  }, []);

  return null;
}

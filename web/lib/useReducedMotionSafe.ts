"use client";

import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";

// The server cannot know the visitor's motion preference, so it always renders the
// full-motion tree. Components that branch on the preference during render must
// therefore report false on the first client render too, or React tears the tree
// down with a hydration mismatch. The real preference lands on the next commit,
// which the reduced-motion effects already handle.
export function useReducedMotionSafe(): boolean {
  const reduce = useReducedMotion();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted && !!reduce;
}

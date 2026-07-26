"use client";

import { useReducedMotion } from "motion/react";

export function useReducedMotionSafe() {
  const prefersReduced = useReducedMotion();
  return prefersReduced ?? false;
}

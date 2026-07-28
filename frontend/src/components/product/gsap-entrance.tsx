"use client";

import { useRef, useEffect } from "react";
import { useLoadGsap } from "@/lib/motion/use-load-gsap";

export function GsapEntrance() {
  const sentinelRef = useRef<HTMLDivElement>(null);
  const firedRef = useRef(false);
  const gsap = useLoadGsap(sentinelRef);

  useEffect(() => {
    if (gsap && !firedRef.current) {
      firedRef.current = true;
      requestAnimationFrame(() => {
        gsap.from(".gsap-section", { opacity: 0, y: 24, stagger: 0.12 });
      });
    }
  }, [gsap]);

  return <div ref={sentinelRef} />;
}

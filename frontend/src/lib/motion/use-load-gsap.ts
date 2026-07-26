import { useEffect, useState, useRef, type RefObject } from "react";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type GSAPModule = any;

export function useLoadGsap(
  triggerRef: RefObject<Element | null>,
  options?: { threshold?: number; rootMargin?: string }
): GSAPModule | null {
  const [gsapInstance, setGsapInstance] = useState<GSAPModule | null>(null);
  const loadedRef = useRef(false);

  useEffect(() => {
    const el = triggerRef.current;
    if (!el || loadedRef.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (!entry?.isIntersecting || loadedRef.current) return;
        loadedRef.current = true;
        import("gsap").then((mod) => {
          setGsapInstance(mod.default ?? mod);
        });
        observer.disconnect();
      },
      { threshold: options?.threshold ?? 0.1, rootMargin: options?.rootMargin ?? "200px" }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [triggerRef, options?.threshold, options?.rootMargin]);

  return gsapInstance;
}

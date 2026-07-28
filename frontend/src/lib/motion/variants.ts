import { easeBrand } from "./easings";

export const staggerEntrance = {
  initial: { opacity: 0, y: 12 },
  animate: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.65,
      ease: easeBrand,
      delay: i * 0.08,
    },
  }),
};

export const fadeIn = {
  initial: { opacity: 0 },
  animate: {
    opacity: 1,
    transition: { duration: 0.32, ease: easeBrand },
  },
};

export const scalePress = {
  whileTap: { scale: 0.98, transition: { duration: 0.18, ease: "easeOut" } },
};

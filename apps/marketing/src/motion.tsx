// Framer Motion primitives for the landing page.
//
// The page is wrapped in <MotionConfig reducedMotion="user"> (see main.tsx), so
// visitors who set "prefers-reduced-motion" get the content with no movement.
// Everything below animates transform + opacity only, so reveals stay smooth.
import { motion, MotionConfig } from 'framer-motion'
import type { Transition, Variants } from 'framer-motion'

export { motion, MotionConfig }

// Gentle ease-out so sections settle into place rather than snap.
const EASE = [0.22, 0.61, 0.36, 1] as const

/* ---------------------------------------------------- Scroll-reveal (on view) */
// Single element that fades + rises the first time it scrolls into view.
export const revealVariants: Variants = {
  hidden: { opacity: 0, y: 24 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } },
}

// Spread onto any `motion.*` element to reveal it once on scroll-in:
//   <motion.h2 {...reveal} style={…}>
export const reveal = {
  initial: 'hidden',
  whileInView: 'visible',
  viewport: { once: true, amount: 0.25, margin: '0px 0px -80px 0px' },
  variants: revealVariants,
} as const

/* ------------------------------------------------ Staggered lists (on view) */
// Spread onto a container; its motion children (each `variants={staggerItem}`)
// animate in one after another as the container enters view.
export const staggerParent = {
  initial: 'hidden',
  whileInView: 'visible',
  viewport: { once: true, amount: 0.2, margin: '0px 0px -60px 0px' },
  variants: {
    hidden: {},
    visible: { transition: { staggerChildren: 0.07, delayChildren: 0.05 } },
  } as Variants,
} as const

export const staggerItem: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.5, ease: EASE } },
}

/* ---------------------------------------------------- Hero (on initial load) */
// The hero is above the fold, so it plays immediately rather than on scroll.
export const heroParent = {
  initial: 'hidden',
  animate: 'visible',
  variants: {
    hidden: {},
    visible: { transition: { staggerChildren: 0.12, delayChildren: 0.06 } },
  } as Variants,
} as const

export const heroItem: Variants = {
  hidden: { opacity: 0, y: 26 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } },
}

// Subtle lift on hover — used sparingly on primary calls to action.
export const hoverLift = { whileHover: { y: -2 }, whileTap: { y: 0 } } as const

export const softSpring: Transition = { type: 'spring', stiffness: 300, damping: 30 }

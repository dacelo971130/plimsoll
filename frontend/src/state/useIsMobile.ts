import { useEffect, useState } from 'react';

// P5 RWD — narrow-viewport breakpoint. 768px matches Tailwind's `md`, used
// consistently across the handful of components that need real JS
// awareness of "is this a phone-width viewport" (RightPanel's expanded
// state becomes a full-screen overlay instead of pushing CenterStage aside
// — a pure-CSS media query can't do that because its resizable width is an
// inline style, which always wins over a Tailwind class). Everything else
// that only needs "narrower padding/stacking" uses plain Tailwind
// `sm:`/`md:` classes directly, no JS involved.
const QUERY = '(max-width: 767px)';

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(QUERY).matches);

  useEffect(() => {
    const mql = window.matchMedia(QUERY);
    const onChange = () => setIsMobile(mql.matches);
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, []);

  return isMobile;
}

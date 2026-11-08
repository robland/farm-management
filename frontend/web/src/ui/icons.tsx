/** Inline stroke icons (decorative: the button around them carries the label). */

import type { ReactNode } from "react";

function Svg({ children, size = 18 }: { children: ReactNode; size?: number }): ReactNode {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

export const EyeIcon = () => (
  <Svg size={20}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></Svg>
);
export const EyeOffIcon = () => (
  <Svg size={20}>
    <path d="M10.6 5.1A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-2.2 3.2" />
    <path d="M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a10 10 0 0 0 5.4-1.6" />
    <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /><path d="M2 2l20 20" />
  </Svg>
);
export const BellIcon = () => (
  <Svg><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0" /></Svg>
);
export const PowerIcon = () => <Svg><path d="M12 2v10" /><path d="M18.4 6.6a9 9 0 1 1-12.8 0" /></Svg>;
export const PlusIcon = () => <Svg size={16}><path d="M12 5v14M5 12h14" /></Svg>;
export const CheckIcon = () => <Svg><path d="M20 6 9 17l-5-5" /></Svg>;
export const AlertIcon = () => (
  <Svg><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
    <path d="M12 9v4" /><path d="M12 17h.01" /></Svg>
);
export const InfoIcon = () => <Svg><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 8h.01" /></Svg>;
export const SyncAlertIcon = () => (
  <Svg><path d="M21 12a9 9 0 0 1-15.5 6.2" /><path d="M3 12A9 9 0 0 1 18.5 5.8" /><path d="M18 2v4h-4" />
    <path d="M6 22v-4h4" /><path d="M12 9v3" /><path d="M12 15h.01" /></Svg>
);

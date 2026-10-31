import { createElement } from "react";
import { ICONS } from "@/icons";

export function Icon({ name, className, size = 16 }: { name: string; className?: string; size?: number }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`icon ${className ?? ""}`}>
      {(ICONS[name] ?? []).map(([tag, attrs], i) => createElement(tag, { key: i, ...attrs }))}
    </svg>
  );
}

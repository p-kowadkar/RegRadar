import { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
}

export function Card({ children, className = "" }: CardProps) {
  return (
    <div
      className={`rounded-md border border-line bg-surface shadow-panel ${className}`}
    >
      {children}
    </div>
  );
}

interface SectionHeaderProps {
  title: string;
  meta?: ReactNode;
  className?: string;
}

export function SectionHeader({ title, meta, className = "" }: SectionHeaderProps) {
  return (
    <div
      className={`flex items-center justify-between border-b border-line px-4 py-2.5 ${className}`}
    >
      <h3 className="text-xxs font-semibold uppercase tracking-[0.16em] text-text-secondary">
        {title}
      </h3>
      {meta && <div className="text-xs text-text-muted">{meta}</div>}
    </div>
  );
}

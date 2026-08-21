import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function IconBase({ children, ...props }: IconProps) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      focusable="false"
      viewBox="0 0 24 24"
      {...props}
    >
      {children}
    </svg>
  );
}

export function ArrowUpIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m6 12 6-6 6 6M12 6v12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </IconBase>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m5 12 4.25 4.25L19 6.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </IconBase>
  );
}

export function CarIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M5 16v2M19 16v2M4 14l1.5-5h13L20 14v3H4v-3ZM7 14h.01M17 14h.01M7 9l1.2-3h7.6L17 9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </IconBase>
  );
}

export function CompareIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M8 5H5v14h3M16 5h3v14h-3M12 8v8M9.5 10.5 12 8l2.5 2.5M9.5 13.5 12 16l2.5-2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </IconBase>
  );
}

export function ExternalLinkIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M14 5h5v5M19 5l-8 8M19 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </IconBase>
  );
}

export function EyeIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M2.5 12s3.4-6 9.5-6 9.5 6 9.5 6-3.4 6-9.5 6-9.5-6-9.5-6Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="12" r="2.5" stroke="currentColor" strokeWidth="1.8" />
    </IconBase>
  );
}

export function EyeOffIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m3 3 18 18M10.6 5.2A10.7 10.7 0 0 1 12 5c6.1 0 9.5 7 9.5 7a16 16 0 0 1-3.2 3.8M6.2 6.3C3.8 8.1 2.5 12 2.5 12s3.4 7 9.5 7a9 9 0 0 0 3-.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </IconBase>
  );
}

export function HeartIcon({ fill = "none", ...props }: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M20.8 8.6c0 5.4-8.8 10.2-8.8 10.2S3.2 14 3.2 8.6A4.4 4.4 0 0 1 12 8a4.4 4.4 0 0 1 8.8.6Z" fill={fill} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </IconBase>
  );
}

export function ListIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M9 6h10M9 12h10M9 18h10M5 6h.01M5 12h.01M5 18h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </IconBase>
  );
}

export function LocationIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M20 10c0 5-8 10-8 10S4 15 4 10a8 8 0 1 1 16 0Z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="10" r="2.5" stroke="currentColor" strokeWidth="1.8" />
    </IconBase>
  );
}

export function MapIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m4 6 5-2 6 2 5-2v14l-5 2-6-2-5 2V6ZM9 4v14M15 6v14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </IconBase>
  );
}

export function PlusIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </IconBase>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <circle cx="10.5" cy="10.5" r="5.5" stroke="currentColor" strokeWidth="1.8" />
      <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </IconBase>
  );
}

export function TransitIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <rect x="5" y="3" width="14" height="16" rx="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M8 7h8M5 13h14M8 19l-1 2M16 19l1 2M8.5 16h.01M15.5 16h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </IconBase>
  );
}

export function XIcon(props: IconProps) {
  return (
    <IconBase {...props}>
      <path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </IconBase>
  );
}

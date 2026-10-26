type IconProps = {size?: number};
const base = (size = 18) => ({
 width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
 strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true,
});

export const SendIcon = ({size}: IconProps) => <svg {...base(size)}><path d="M5 12h13M13 6l6 6-6 6"/></svg>;
export const PlusIcon = ({size}: IconProps) => <svg {...base(size)}><path d="M12 5v14M5 12h14"/></svg>;
export const ExternalIcon = ({size = 14}: IconProps) => <svg {...base(size)}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>;
export const ThumbUpIcon = ({size}: IconProps) => <svg {...base(size)}><path d="M7 10v10H4V10h3zM7 10l4-7a2 2 0 0 1 3 2l-1 4h6a2 2 0 0 1 2 2.3l-1.3 7A2 2 0 0 1 17.7 20H7"/></svg>;
export const ThumbDownIcon = ({size}: IconProps) => <svg {...base(size)}><path d="M17 14V4h3v10h-3zM17 14l-4 7a2 2 0 0 1-3-2l1-4H5a2 2 0 0 1-2-2.3l1.3-7A2 2 0 0 1 6.3 4H17"/></svg>;
export const BookIcon = ({size = 16}: IconProps) => <svg {...base(size)}><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5zM19 19v2H6"/></svg>;
export const ShieldIcon = ({size = 16}: IconProps) => <svg {...base(size)}><path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6l8-3z"/></svg>;
export const CopyIcon = ({size = 16}: IconProps) => <svg {...base(size)}><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg>;
export const MailIcon = ({size = 16}: IconProps) => <svg {...base(size)}><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>;
export const RetryIcon = ({size = 14}: IconProps) => <svg {...base(size)}><path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4"/></svg>;

// Leopard Support mark: a rounded tile with a stylised leopard rosette.
export function LeopardMark({size = 36}: IconProps) {
 return <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
  <rect width="40" height="40" rx="11" fill="var(--brand-ink)"/>
  <path d="M14 10v17h12" fill="none" stroke="var(--gold)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"/>
  <circle cx="28" cy="13" r="3.2" fill="none" stroke="var(--gold)" strokeWidth="2"/>
  <circle cx="28" cy="13" r="1" fill="var(--gold)"/>
  <circle cx="22" cy="18" r="1.6" fill="var(--gold)" opacity=".8"/>
  <circle cx="31" cy="21" r="1.3" fill="var(--gold)" opacity=".6"/>
 </svg>;
}

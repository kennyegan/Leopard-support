type IconProps = {size?: number};
const base = (size = 18) => ({
 width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
 strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true,
});

export const SendIcon = ({size}: IconProps) => <svg {...base(size)}><path d="M12 19V5M6 11l6-6 6 6"/></svg>;
export const PlusIcon = ({size}: IconProps) => <svg {...base(size)}><path d="M12 5v14M5 12h14"/></svg>;
export const ExternalIcon = ({size = 14}: IconProps) => <svg {...base(size)}><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>;
export const ThumbUpIcon = ({size}: IconProps) => <svg {...base(size)}><path d="M7 10v10H4V10h3zM7 10l4-7a2 2 0 0 1 3 2l-1 4h6a2 2 0 0 1 2 2.3l-1.3 7A2 2 0 0 1 17.7 20H7"/></svg>;
export const ThumbDownIcon = ({size}: IconProps) => <svg {...base(size)}><path d="M17 14V4h3v10h-3zM17 14l-4 7a2 2 0 0 1-3-2l1-4H5a2 2 0 0 1-2-2.3l1.3-7A2 2 0 0 1 6.3 4H17"/></svg>;
export const BookIcon = ({size = 16}: IconProps) => <svg {...base(size)}><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5zM19 19v2H6"/></svg>;
export const ShieldIcon = ({size = 16}: IconProps) => <svg {...base(size)}><path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6l8-3z"/></svg>;
export const CopyIcon = ({size = 16}: IconProps) => <svg {...base(size)}><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg>;
export const MailIcon = ({size = 16}: IconProps) => <svg {...base(size)}><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>;
export const RetryIcon = ({size = 14}: IconProps) => <svg {...base(size)}><path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4"/></svg>;

export const SidebarIcon = ({size}: IconProps) => <svg {...base(size)}><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/></svg>;
export const TrashIcon = ({size = 16}: IconProps) => <svg {...base(size)}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12M9 7V4h6v3"/></svg>;
export const CloseIcon = ({size}: IconProps) => <svg {...base(size)}><path d="M6 6l12 12M18 6L6 18"/></svg>;
export const MoreIcon = ({size}: IconProps) => <svg {...base(size)}><circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/></svg>;
export const PhoneIcon = ({size = 16}: IconProps) => <svg {...base(size)}><rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 18h2"/></svg>;
export const ChartIcon = ({size = 16}: IconProps) => <svg {...base(size)}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>;
export const SlidersIcon = ({size = 16}: IconProps) => <svg {...base(size)}><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>;
export const LogOutIcon = ({size = 16}: IconProps) => <svg {...base(size)}><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H4"/></svg>;
export const ArrowLeftIcon = ({size = 16}: IconProps) => <svg {...base(size)}><path d="M19 12H5M11 6l-6 6 6 6"/></svg>;

// Google's multicolour "G", required on Google sign-in buttons.
export const GoogleIcon = ({size = 18}: IconProps) => <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
 <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.6 2.4 30.2 0 24 0 14.6 0 6.6 5.4 2.6 13.2l7.8 6.1C12.3 13.6 17.7 9.5 24 9.5z"/>
 <path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.2-.4-4.7H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.5 5.8c4.4-4 6.8-10 6.8-17z"/>
 <path fill="#FBBC05" d="M10.4 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.9-4.7l-7.8-6.1A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.8l7.8-6.1z"/>
 <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.8 2.3-8.4 2.3-6.3 0-11.7-4.1-13.6-9.8l-7.8 6.1C6.6 42.6 14.6 48 24 48z"/>
</svg>;

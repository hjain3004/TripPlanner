import { wcagLuminance } from 'culori';

const celadon1 = 'oklch(0.848 0.027 167)';
const ink = 'oklch(0.281 0.007 145)';
const inkMuted = 'oklch(0.525 0.014 157)';
const signal = 'oklch(0.536 0.135 30)';

const c1 = wcagLuminance(celadon1);
const l_ink = wcagLuminance(ink);
const l_inkMuted = wcagLuminance(inkMuted);
const l_signal = wcagLuminance(signal);

const contrast = (l1, l2) => (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);

console.log('celadon-1 vs ink:', contrast(c1, l_ink).toFixed(2));
console.log('celadon-1 vs ink-muted:', contrast(c1, l_inkMuted).toFixed(2));
console.log('celadon-1 vs signal:', contrast(c1, l_signal).toFixed(2));

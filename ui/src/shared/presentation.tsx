import DOMPurify from 'dompurify';
import { marked } from 'marked';
import {
  Activity,
  BarChart3,
  Cpu,
  FlaskConical,
  LayoutGrid,
  Rocket,
  Shield,
  ShieldCheck,
  Target,
  Users,
  type LucideIcon,
} from 'lucide-react';
import type {
  BoardMember,
  BoardSession,
  DelegatedTask,
  SeatStatus,
  SessionMetrics,
  StageEvent,
  StageMember,
  TableStatus,
} from './types';

export const STAGE_NAMES: Record<number, string> = {
  0: 'Board intake',
  1: 'Independent analysis',
  2: 'Peer review',
  3: 'Chair synthesis',
};

export const MEMBER_ORDER = [
  'chairperson',
  'strategist',
  'product',
  'researcher',
  'critic',
  'architect',
  'builder',
  'guardian',
  'operator',
];

export const MEMBER_TONES: Record<string, string> = {
  chairperson: '#003d9b',
  strategist: '#6366f1',
  product: '#0ea5e9',
  researcher: '#10b981',
  critic: '#0f172a',
  architect: '#f59e0b',
  builder: '#14b8a6',
  guardian: '#ef4444',
  operator: '#8b5cf6',
};

export const MEMBER_IMAGES: Record<string, string> = {
  chairperson: 'https://lh3.googleusercontent.com/aida-public/AB6AXuDPjxTpQvdd0VLzAS_03j_ZB8IG2ZZvDnXPZXiGKa9odBIf04mIRpIfubUwKFCCg-19o9Tod1dBM7yYBDxfnyddjTq4tORQAwq_ULyyxYKzpe_HAItGrsTUoZaGzzHEdhbX7erp-sB5wrF8VeFZR6vuHmeHbokdstZe9uH1MRcL2ySDbk7qS_99EaLG9E1H8_SZoRf1v4OF5wuAu91cnqDUjfwx-N5zsEP5dDAM0ut0wev-i0w_NNZB4MGAdJHOC4AaWVTVB48z-scj',
  strategist: 'https://lh3.googleusercontent.com/aida-public/AB6AXuCrVaBd4VYnqvOFYvkko8fDBaOBrCiSNclCcqMeEBAUS4diZokSEk6MepS_0X8EaF6VHGASHX_Ny5OM56b_FKmggFUqAwPypH1zTA0Yy9M2ifJzuKqZ5xNCUO3XEJXJfz_5BLBdFDI95ENwvPIacWS4ururjDPg4DvaPGR2EBdPcM3EHyTS4NOG3F-SgjGQaag-wnHrNsMdD_cJU73rMJ_XI-nv6DxUgUtd78EJ1S4JBySjhwYerfj6Ztesv2LJs4AA4GjhXTucniZ2',
  product: 'https://lh3.googleusercontent.com/aida-public/AB6AXuDlSVtdhQyYtQ9jVyZ26XcGif1pd0_xC3e-RByd5XeSl4qb28uO_cAbPccGs1GOAQDg_oujDQsfqDo-uJLsPgU3riOwr9D9BzxANguEE69KcTtJkf6FtmIeikE6zdqNzFjZJkE1kvglY5FyHpcGYS8W14Jvf0m9PhuWRcYqsB3PCTNyJO2m42icA9I9_EKU3qwF7pW34ELQAkgWWT7hEuour_QtXglPSiYCrRZwkciMBJVhNlirY3txe23_JvchYAeKA5I7kleFLZwp',
  researcher: 'https://lh3.googleusercontent.com/aida-public/AB6AXuCsaCt3iNCR3dUiPoy_cDZOaIEoMMM3-DL4ioIOvugRuf0k4y-stHRtNKUaglpTaSNeOVsUI_Bbxeo5gL2QkULPd9uzSNMkWTjJqWcUpLH7EznjBv31pCpPF_jSnWQRxko-rz8xSIK0B_0o0FObUcNahhv_mTw09yAQUCNwEdupdko50swYon2kcUJv9Ano923X2C19av4j8gZQUpOcvBJy5fzMZ8yJeBTwAv8Ql_qHTll2wo_KgPdBuRV0PEhn8M4x5XZZvI9-7QY7',
  critic: 'https://lh3.googleusercontent.com/aida-public/AB6AXuChQa7i6KI-PMhD7yjQiuJiD_RA5I05yv_AGjkV_-wfUWF97zR9wQZrQGpVSGASSj7GMXLOd4nJI8uVr4_oEhOy68ncfBCT-5JiMIUU5ZNx_-F6l7ZwazwNddmAgz3cmp6yWPUbf5y4Mc9_Xs53lQ-Rjz6ktaqwkpqQjBHC3AtCjIefvYAlIIUXWQrdq4GP9AwwCDJuuoLtez3phaKuzBqypFW7WD3M-fYxg5I8hccvADy6Yd8yKFR1IGT0ItSiuKNcyUvnQ8eVjHLm',
  architect: 'https://lh3.googleusercontent.com/aida-public/AB6AXuC42thAYmO_KQkP9_zptIXA9I2GfhIAWVL93zh-2KM6KZetfB9N1fg-ncO9y1wLspl1uGExFFYb6cYt5bxXRLAOz1ilzo5tvtMpex5ZwxuTomzgWo3uvT3QOSSH86US8pOhBtZXOzg5usNEtRNO0GahLVz_g54T0tThb1F4cmzewTttFImNLV_R0enDbD8tv4ICbfq8vm4Ts4EX1LBB27g6Py8bfCZmcqYv_lmA9TIrCqysnEkD_C3hBP1Jg66In1rK_85KtCF-R3mA',
  builder: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBt_cAWwD1TsY90rAcWkl6s4J5mf2LHDD1sAkOuMT6Fqa4kJpaoZYLdSk46uKSy2TGZOrqFFzIlBTEutplSqxNWlTZ0XM3Nzv8Sdvxw50YnZ_WEGwxGLqZ8P_4sN6L-B-U56Z_Fbh4c2Fb66wdIzdnzOqlEu3d2LBds9eqRkgYZTIk7zxBm8nl_F8MDz-7_48YX4Wqfr6K8k5i7evArM51zV79GgrBt6fYAp2DY5rjR2h8wH_v7cs7veKryvDPsGEHnL75eqR6W-hdY',
};

const MEMBER_DOSSIERS: Record<string, { strength: string; focus: string; signal: string }> = {
  chairperson: {
    strength: 'Decision synthesis',
    focus: 'Conflict resolution, first principles, final calls',
    signal: 'Clear ruling',
  },
  strategist: {
    strength: 'Market evidence',
    focus: 'Segments, competition, channel tests',
    signal: 'Evidence quality',
  },
  product: {
    strength: 'MVP scope',
    focus: 'Value proposition, prioritization, PMF',
    signal: 'Smallest viable bet',
  },
  researcher: {
    strength: 'Customer truth',
    focus: 'Interviews, jobs to be done, personas',
    signal: 'Voice of customer',
  },
  critic: {
    strength: 'Risk challenge',
    focus: 'Premortems, assumptions, dissent',
    signal: 'Blind spot pressure',
  },
  architect: {
    strength: 'Technical feasibility',
    focus: 'Architecture, integrations, build versus buy',
    signal: 'Viable design',
  },
  builder: {
    strength: 'Execution plan',
    focus: 'Effort, sequencing, validation loops',
    signal: 'Build path',
  },
  guardian: {
    strength: 'Security posture',
    focus: 'Threat models, privacy, compliance',
    signal: 'Attack surface',
  },
  operator: {
    strength: 'Operational readiness',
    focus: 'Release, monitoring, incidents',
    signal: 'Runbook clarity',
  },
};

export const MEMBER_ICONS: Record<string, LucideIcon> = {
  chairperson: LayoutGrid,
  strategist: BarChart3,
  product: Target,
  researcher: FlaskConical,
  critic: Shield,
  architect: Cpu,
  builder: Rocket,
  guardian: ShieldCheck,
  operator: Activity,
};

export function orderMembers(items: BoardMember[]) {
  const byId = new Map(items.map((member) => [member.id, member]));
  return [
    ...MEMBER_ORDER.filter((id) => byId.has(id)).map((id) => byId.get(id)!),
    ...items.filter((member) => !MEMBER_ORDER.includes(member.id)),
  ];
}

export function initialSeatStates(items: BoardMember[]) {
  return Object.fromEntries(items.map((member) => [member.id, { status: 'idle' as SeatStatus, label: 'ready' }]));
}

export function resetSeatStates(items: BoardMember[], fullBoard: boolean, manualIds: string[]) {
  const selected = new Set(fullBoard ? items.map((member) => member.id) : manualIds);
  return Object.fromEntries(items.map((member) => [
    member.id,
    {
      status: selected.has(member.id) ? 'selected' as SeatStatus : 'idle' as SeatStatus,
      label: selected.has(member.id) ? 'selected' : 'ready',
      selected: selected.has(member.id),
    },
  ]));
}

export function upsertStage(events: StageEvent[], stage: number, patch: Partial<StageEvent>) {
  const existing = events.find((item) => item.stage === stage);
  if (!existing) return [...events, { stage, members: [], ...patch }];
  return events.map((item) => item.stage === stage ? { ...item, ...patch } : item);
}

export function addStageMember(events: StageEvent[], stage: number, member: StageMember) {
  const existing = events.find((item) => item.stage === stage);
  if (!existing) return [...events, { stage, active: true, done: false, members: [member] }];
  return events.map((item) => item.stage === stage ? { ...item, members: [...(item.members || []), member] } : item);
}

export function statusForStageStart(stage: number, name?: string): TableStatus {
  if (stage === 1) {
    return {
      label: 'Stage 1',
      title: 'Independent analysis',
      detail: 'Board members are forming first-pass positions without peer influence.',
    };
  }
  if (stage === 2) {
    return {
      label: 'Stage 2',
      title: 'Peer review',
      detail: 'Members are challenging compacted peer positions.',
    };
  }
  if (stage === 3) {
    return {
      label: 'Stage 3',
      title: 'Chair synthesis',
      detail: 'The chair is resolving dissent into one board decision.',
    };
  }
  return {
    label: `Stage ${stage}`,
    title: name || 'Processing',
    detail: 'The board is working.',
  };
}

export function getSynthesis(session: BoardSession | null) {
  return session?.stage3 || session?.stage3_synthesis || null;
}

export function renderMarkdown(markdown: string) {
  const html = marked.parse(markdown || '', { async: false }) as string;
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

export function stripMarkdown(markdown: string) {
  return markdown
    .replace(/[#*_`>~-]/g, ' ')
    .replace(/\[(.*?)\]\(.*?\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

export function roleShort(role: string) {
  return role.split('/')[0].trim();
}

export function compactList(items?: string[]) {
  return Array.isArray(items) ? items.filter(Boolean) : [];
}

export function memberDossier(member: BoardMember) {
  const profile = MEMBER_DOSSIERS[member.id];
  const fallbackStrength = compactList(member.capabilities)[0] || compactList(member.expertise)[0] || roleShort(member.role);
  return {
    strength: profile?.strength || humanize(fallbackStrength),
    focus: profile?.focus || humanize(roleShort(member.role)),
    signal: profile?.signal || 'Board judgment',
  };
}

export function humanize(value?: string) {
  const text = String(value || '').replace(/[_-]/g, ' ').trim();
  if (!text) return '';
  return text
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/\bGtm\b/g, 'GTM')
    .replace(/\bMvp\b/g, 'MVP')
    .replace(/\bPmf\b/g, 'PMF')
    .replace(/\bSotb\b/g, 'SOTB');
}

export function stageShortLabel(stage?: number) {
  if (stage === 1) return 'analysis';
  if (stage === 2) return 'review';
  if (stage === 3) return 'synthesis';
  return 'stage';
}

export function memberTone(id: string) {
  return MEMBER_TONES[id] || '#003d9b';
}

export function taskStatusClass(status: DelegatedTask['status']) {
  if (status === 'completed') return 'bg-[#edf8f1] text-[#2d8a52]';
  if (status === 'blocked' || status === 'rejected') return 'bg-[#fff5f2] text-[#b42318]';
  if (status === 'running') return 'bg-[#eff6ff] text-[#003d9b]';
  if (status === 'approved') return 'bg-[#f0fdf4] text-[#166534]';
  return 'bg-white text-[#64748b]';
}

export function metricsByStage(metrics: SessionMetrics) {
  return [1, 2, 3].map((stage) => {
    const row = metrics.by_stage?.[String(stage)] || metrics.by_stage?.[stage as unknown as string] || {};
    return {
      name: `Stage ${stage}`,
      calls: row.calls || 0,
      tokens: row.tokens || 0,
    };
  });
}

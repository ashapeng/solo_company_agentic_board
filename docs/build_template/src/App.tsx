/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useMemo } from 'react';
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, AreaChart, Area, Cell, PieChart, Pie
} from 'recharts';
import { 
  Bell, Settings, LayoutGrid, Cpu, Terminal, FlaskConical, 
  Shield, CreditCard, Megaphone, Rocket, Archive, HelpCircle, 
  Plus, FileText, BarChart3, StickyNote, Send, Mic, Paperclip, Bolt,
  CheckCircle, Circle, TrendingUp, Target, Activity, Users,
  Check, ArrowRight, ShieldCheck
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

// --- Types & Constants ---

type ExecutionUnit = {
  id: string;
  name: string;
  role: string;
  icon: React.ReactNode;
  img: string;
  opinion: string;
  skills: string[];
};

const EXECUTION_UNITS: ExecutionUnit[] = [
  {
    id: 'ceo',
    name: 'Sarah Chen',
    role: 'Chief Executive Officer',
    icon: <LayoutGrid className="w-4 h-4" />,
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuDPjxTpQvdd0VLzAS_03j_ZB8IG2ZZvDnXPZXiGKa9odBIf04mIRpIfubUwKFCCg-19o9Tod1dBM7yYBDxfnyddjTq4tORQAwq_ULyyxYKzpe_HAItGrsTUoZaGzzHEdhbX7erp-sB5wrF8VeFZR6vuHmeHbokdstZe9uH1MRcL2ySDbk7qS_99EaLG9E1H8_SZoRf1v4OF5wuAu91cnqDUjfwx-N5zsEP5dDAM0ut0wev-i0w_NNZB4MGAdJHOC4AaWVTVB48z-scj',
    opinion: '"We need to move aggressively on the research side before the competitors catch up."',
    skills: ['Vision', 'Risk Management']
  },
  {
    id: 'cto',
    name: 'Marcus Thorne',
    role: 'Chief Technology Officer',
    icon: <Cpu className="w-4 h-4" />,
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuC42thAYmO_KQkP9_zptIXA9I2GfhIAWVL93zh-2KM6KZetfB9N1fg-ncO9y1wLspl1uGExFFYb6cYt5bxXRLAOz1ilzo5tvtMpex5ZwxuTomzgWo3uvT3QOSSH86US8pOhBtZXOzg5usNEtRNO0GahLVz_g54T0tThb1F4cmzewTttFImNLV_R0enDbD8tv4ICbfq8vm4Ts4EX1LBB27g6Py8bfCZmcqYv_lmA9TIrCqysnEkD_C3hBP1Jg66In1rK_85KtCF-R3mA',
    opinion: '"The security layer must be autonomously verifying every handshake."',
    skills: ['Scalability', 'Security']
  },
  {
    id: 'coo',
    name: 'Elena Vance',
    role: 'Operations Lead',
    icon: <Activity className="w-4 h-4" />,
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuCsaCt3iNCR3dUiPoy_cDZOaIEoMMM3-DL4ioIOvugRuf0k4y-stHRtNKUaglpTaSNeOVsUI_Bbxeo5gL2QkULPd9uzSNMkWTjJqWcUpLH7EznjBv31pCpPF_jSnWQRxko-rz8xSIK0B_0o0FObUcNahhv_mTw09yAQUCNwEdupdko50swYon2kcUJv9Ano923X2C19av4j8gZQUpOcvBJy5fzMZ8yJeBTwAv8Ql_qHTll2wo_KgPdBuRV0PEhn8M4x5XZZvI9-7QY7',
    opinion: '"Resource allocation is peaking. We need to optimize agent training cycles."',
    skills: ['Efficiency', 'Workflow']
  },
  {
    id: 'cfo',
    name: 'Julian Blackwood',
    role: 'Financial Systems',
    icon: <CreditCard className="w-4 h-4" />,
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuChQa7i6KI-PMhD7yjQiuJiD_RA5I05yv_AGjkV_-wfUWF97zR9wQZrQGpVSGASSj7GMXLOd4nJI8uVr4_oEhOy68ncfBCT-5JiMIUU5ZNx_-F6l7ZwazwNddmAgz3cmp6yWPUbf5y4Mc9_Xs53lQ-Rjz6ktaqwkpqQjBHC3AtCjIefvYAlIIUXWQrdq4GP9AwwCDJuuoLtez3phaKuzBqypFW7WD3M-fYxg5I8hccvADy6Yd8yKFR1IGT0ItSiuKNcyUvnQ8eVjHLm',
    opinion: '"The ROI on current workflows justifies the additional GPU cluster spend."',
    skills: ['Budgeting', 'ROI Analysis']
  },
  {
    id: 'cmo',
    name: 'Aria Winters',
    role: 'Market Intelligence',
    icon: <Megaphone className="w-4 h-4" />,
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuCrVaBd4VYnqvOFYvkko8fDBaOBrCiSNclCcqMeEBAUS4diZokSEk6MepS_0X8EaF6VHGASHX_Ny5OM56b_FKmggFUqAwPypH1zTA0Yy9M2ifJzuKqZ5xNCUO3XEJXJfz_5BLBdFDI95ENwvPIacWS4ururjDPg4DvaPGR2EBdPcM3EHyTS4NOG3F-SgjGQaag-wnHrNsMdD_cJU73rMJ_XI-nv6DxUgUtd78EJ1S4JBySjhwYerfj6Ztesv2LJs4AA4GjhXTucniZ2',
    opinion: '"GTM signals suggest a high demand for empathetic agent interfaces."',
    skills: ['GTM Strat', 'Brand']
  },
  {
    id: 'vpe',
    name: 'Kaelen Voss',
    role: 'Engineering Director',
    icon: <Rocket className="w-4 h-4" />,
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBt_cAWwD1TsY90rAcWkl6s4J5mf2LHDD1sAkOuMT6Fqa4kJpaoZYLdSk46uKSy2TGZOrqFFzIlBTEutplSqxNWlTZ0XM3Nzv8Sdvxw50YnZ_WEGwxGLqZ8P_4sN6L-B-U56Z_Fbh4c2Fb66wdIzdnzOqlEu3d2LBds9eqRkgYZTIk7zxBm8nl_F8MDz-7_48YX4Wqfr6K8k5i7evArM51zV79GgrBt6fYAp2DY5rjR2h8wH_v7cs7veKryvDPsGEHnL75eqR6W-hdY',
    opinion: '"Foundation stack is stable. Ready for autonomous scale-up."',
    skills: ['Core Stack', 'Delivery']
  }
];

const KPI_DATA = [
  { name: 'Jan', velocity: 400, quality: 240, cost: 240 },
  { name: 'Feb', velocity: 300, quality: 139, cost: 221 },
  { name: 'Mar', velocity: 200, quality: 980, cost: 229 },
  { name: 'Apr', velocity: 278, quality: 390, cost: 200 },
  { name: 'May', velocity: 189, quality: 480, cost: 218 },
  { name: 'Jun', velocity: 239, quality: 380, cost: 250 },
];

const PERFORMANCE_METRICS = [
  { label: 'Agent Autonomy', value: '84%', target: '90%', trend: '+4%', color: '#3b82f6' },
  { label: 'Task Throughput', value: '1.2M/hr', target: '2.0M/hr', trend: '+12%', color: '#10b981' },
  { label: 'Latency (p99)', value: '142ms', target: '<150ms', trend: '-8ms', color: '#f59e0b' },
  { label: 'Compliance Score', value: '99.8%', target: '100%', trend: '+0.2%', color: '#6366f1' },
];

const ROADMAP = [
  { 
    id: 1, 
    phase: 'PHASE 01 - CURRENT', 
    title: 'Foundation & Alignment', 
    desc: 'Defining guardrails and operational limits for agentic units.', 
    unit: 'Security Architecture',
    status: 'In Progress'
  },
  { 
    id: 2, 
    phase: 'PHASE 02 - NEXT WEEK', 
    title: 'Mass Scale Deployment', 
    desc: 'Ramping up to 500 parallel execution agents.', 
    unit: 'Engineering Team',
    status: 'Planned'
  },
  { 
    id: 3, 
    phase: 'PHASE 03 - NEXT MONTH', 
    title: 'Autonomous Optimization', 
    desc: 'Agents begin self-refining execution based on GTM signals.', 
    unit: 'AI Researcher',
    status: 'Draft'
  }
];

// --- Components ---

const Navbar = ({ activeTab, setActiveTab }: { activeTab: string, setActiveTab: (t: string) => void }) => (
  <nav className="fixed top-0 w-full z-50 bg-white/80 backdrop-blur-xl shadow-sm flex justify-between items-center px-8 h-16 max-w-[1920px] mx-auto border-b border-slate-100">
    <div className="flex items-center gap-8">
      <span className="text-2xl font-bold tracking-tighter text-blue-700 font-manrope">The Executive Atelier</span>
      <div className="hidden md:flex gap-6 h-full items-center">
        <button 
          onClick={() => setActiveTab('portfolio')}
          className={`h-full border-b-2 transition-all font-manrope tracking-tight font-semibold px-2 ${activeTab === 'portfolio' ? 'text-blue-700 border-blue-700' : 'text-slate-500 border-transparent hover:text-slate-900'}`}
        >
          Portfolio
        </button>
        <button 
          onClick={() => setActiveTab('governance')}
          className={`h-full border-b-2 transition-all font-manrope tracking-tight font-semibold px-2 ${activeTab === 'governance' ? 'text-blue-700 border-blue-700' : 'text-slate-500 border-transparent hover:text-slate-900'}`}
        >
          Governance
        </button>
        <button 
          onClick={() => setActiveTab('performance')}
          className={`h-full border-b-2 transition-all font-manrope tracking-tight font-semibold px-2 ${activeTab === 'performance' ? 'text-blue-700 border-blue-700' : 'text-slate-500 border-transparent hover:text-slate-900'}`}
        >
          Performance
        </button>
      </div>
    </div>
    <div className="flex items-center gap-4">
      <button className="p-2 text-slate-500 hover:bg-slate-50 rounded-full transition-all active:scale-95">
        <Bell className="w-5 h-5" />
      </button>
      <button className="p-2 text-slate-500 hover:bg-slate-50 rounded-full transition-all active:scale-95">
        <Settings className="w-5 h-5" />
      </button>
      <img 
        alt="Executive Avatar" 
        className="w-10 h-10 rounded-full bg-slate-100 border-2 border-blue-100 p-0.5" 
        src="https://lh3.googleusercontent.com/aida-public/AB6AXuDlSVtdhQyYtQ9jVyZ26XcGif1pd0_xC3e-RByd5XeSl4qb28uO_cAbPccGs1GOAQDg_oujDQsfqDo-uJLsPgU3riOwr9D9BzxANguEE69KcTtJkf6FtmIeikE6zdqNzFjZJkE1kvglY5FyHpcGYS8W14Jvf0m9PhuWRcYqsB3PCTNyJO2m42icA9I9_EKU3qwF7pW34ELQAkgWWT7hEuour_QtXglPSiYCrRZwkciMBJVhNlirY3txe23_JvchYAeKA5I7kleFLZwp"
      />
    </div>
  </nav>
);

const Sidebar = ({ currentMeetingIds, onAddRemove }: { currentMeetingIds: string[], onAddRemove: (id: string) => void }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <aside 
      onMouseEnter={() => setIsExpanded(true)}
      onMouseLeave={() => setIsExpanded(false)}
      className={`fixed left-0 top-16 h-[calc(100vh-4rem)] bg-slate-50 border-r border-slate-200 flex flex-col p-4 gap-2 z-40 transition-all duration-300 ease-in-out ${isExpanded ? 'w-64' : 'w-20'}`}
    >
      <div className="flex items-center gap-3 px-1 py-4 mb-2 overflow-hidden">
        <div className="min-w-[40px] w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center text-white shrink-0 shadow-lg shadow-blue-200">
          <LayoutGrid className="w-6 h-6" />
        </div>
        {isExpanded && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="whitespace-nowrap">
            <h3 className="font-manrope font-extrabold text-blue-900 leading-none">Execution Units</h3>
            <p className="text-[10px] text-slate-500 uppercase tracking-widest mt-1">Ready for deployment</p>
          </motion.div>
        )}
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto no-scrollbar">
        {EXECUTION_UNITS.map((unit) => {
          const isActive = currentMeetingIds.includes(unit.id);
          return (
            <button
              key={unit.id}
              onClick={() => onAddRemove(unit.id)}
              className={`w-full group flex items-center gap-3 px-3 py-3 rounded-xl transition-all ${
                isActive ? 'bg-blue-600 text-white shadow-md' : 'text-slate-600 hover:bg-white hover:shadow-sm'
              }`}
            >
              <div className="shrink-0 flex items-center justify-center">
                {isActive ? <Check className="w-5 h-5" /> : unit.icon}
              </div>
              {isExpanded && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 text-left whitespace-nowrap flex items-center justify-between">
                  <span className="font-inter text-sm font-medium">{unit.role}</span>
                  {!isActive && <Plus className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" />}
                </motion.div>
              )}
            </button>
          );
        })}
      </nav>

      <div className="mt-auto pt-4 border-t border-slate-200 space-y-1 overflow-hidden">
        <button className="w-full bg-blue-700 text-white font-manrope text-sm font-bold h-12 rounded-xl shadow-lg shadow-blue-200 flex items-center justify-center gap-2 hover:opacity-90 transition-all">
          <Plus className="w-5 h-5 shrink-0" />
          {isExpanded && <span className="whitespace-nowrap">Deploy Agent</span>}
        </button>
        <div className="flex items-center gap-3 px-3 py-2 text-slate-500 hover:text-slate-900 transition-colors cursor-pointer">
          <Archive className="w-5 h-5 shrink-0" />
          {isExpanded && <span className="text-sm font-medium">Archives</span>}
        </div>
        <div className="flex items-center gap-3 px-3 py-2 text-slate-500 hover:text-slate-900 transition-colors cursor-pointer">
          <HelpCircle className="w-5 h-5 shrink-0" />
          {isExpanded && <span className="text-sm font-medium">Help</span>}
        </div>
      </div>
    </aside>
  );
};

const GovernancePage = ({ meetingMembers }: { meetingMembers: ExecutionUnit[] }) => {
  return (
    <div className="grid grid-cols-12 h-content">
      {/* Meeting Insights */}
      <section className="col-span-3 bg-slate-50/50 p-6 flex flex-col gap-6 overflow-y-auto border-r border-slate-100">
        <div>
          <h2 className="text-[11px] font-bold font-manrope uppercase tracking-[0.2em] text-slate-500 mb-6 flex items-center gap-2">
            <Activity className="w-3 h-3 text-blue-600" />
            Meeting Insights
          </h2>
          <div className="space-y-4">
            <div className="bg-white p-4 rounded-2xl shadow-sm border border-slate-100">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[9px] font-bold text-blue-700 bg-blue-50 px-2.5 py-1 rounded-lg">LIVE TRANSCRIPTION</span>
                <span className="text-[10px] text-slate-400 font-mono">14:32:04</span>
              </div>
              <p className="text-sm text-slate-700 leading-relaxed italic font-serif opacity-80">"...prioritizing the deployment of Agentic Workflows for the Q3 pipeline to ensure seamless GTM integration."</p>
            </div>
            
            <div className="bg-white p-5 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden">
              <div className="absolute top-0 left-0 w-1.5 h-full bg-blue-600" />
              <h4 className="text-xs font-bold mb-3 flex items-center gap-2 text-blue-900">
                <StickyNote className="w-4 h-4 text-blue-600" />
                Key Decision Notes
              </h4>
              <ul className="text-xs text-slate-500 space-y-3">
                <li className="flex gap-2">
                  <span className="text-blue-500">•</span>
                  <span>Approved $2.4M allocation for Agentic Security layer.</span>
                </li>
                <li className="flex gap-2">
                  <span className="text-blue-500">•</span>
                  <span>Engineering team to pivot to 2-week agent training cycles.</span>
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div>
          <h2 className="text-[11px] font-bold font-manrope uppercase tracking-[0.2em] text-slate-500 mb-6">Meeting Materials</h2>
          <div className="grid gap-3">
            <div className="flex items-center p-3 bg-white border border-slate-100 rounded-xl hover:bg-slate-50 transition-colors cursor-pointer group">
              <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 group-hover:bg-blue-100 transition-colors">
                <FileText className="w-5 h-5" />
              </div>
              <div className="flex-1 ml-3 overflow-hidden">
                <p className="text-xs font-bold text-slate-800 truncate">Q3_Execution_Manifesto.pdf</p>
                <p className="text-[10px] text-slate-400">Board Proposal • 4.2 MB</p>
              </div>
            </div>
            <div className="flex items-center p-3 bg-white border border-slate-100 rounded-xl hover:bg-slate-50 transition-colors cursor-pointer group">
              <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-600 group-hover:bg-emerald-100 transition-colors">
                <BarChart3 className="w-5 h-5" />
              </div>
              <div className="flex-1 ml-3 overflow-hidden">
                <p className="text-xs font-bold text-slate-800 truncate">Agentic_Efficiency_Report.xlsx</p>
                <p className="text-[10px] text-slate-400">Live Data • Updated 2m ago</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Round Table Main Visual */}
      <section className="col-span-6 bg-white p-8 flex flex-col items-center justify-center relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,_#eff6ff_0%,_transparent_70%)] opacity-40 pointer-events-none" />
        
        {/* Central Topic */}
        <div className="absolute top-12 text-center z-10">
          <motion.div initial={{ y: -20, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
            <span className="px-4 py-1.5 bg-blue-600 text-white rounded-full text-[10px] font-bold tracking-widest uppercase">Current Topic</span>
            <h1 className="text-3xl font-manrope font-extrabold mt-4 text-slate-900 tracking-tight">Agentic Execution Strategy</h1>
            <div className="flex items-center justify-center gap-6 mt-3 text-slate-400">
              <span className="flex items-center gap-1.5 text-xs font-medium"><Activity className="w-4 h-4" /> 45:12</span>
              <span className="flex items-center gap-1.5 text-xs font-medium"><Users className="w-4 h-4" /> {meetingMembers.length} Present</span>
            </div>
          </motion.div>
        </div>

        {/* Round Table Visualization */}
        <div className="relative w-full aspect-square max-w-[500px] flex items-center justify-center">
          <div className="w-[85%] h-[85%] rounded-full bg-white shadow-[0_32px_80px_rgba(37,99,235,0.08)] border border-slate-100 flex items-center justify-center relative z-10 transition-all duration-700">
            <div className="text-center group cursor-pointer hover:scale-110 transition-transform">
              <div className="w-24 h-24 rounded-full bg-blue-50 flex items-center justify-center mb-3 mx-auto shadow-inner">
                <Bolt className="w-10 h-10 text-blue-600 fill-blue-600 animate-pulse" />
              </div>
              <p className="font-manrope font-bold text-blue-900/30 uppercase tracking-[0.3em] text-[10px]">Round Table Collective</p>
            </div>
          </div>

          {/* Dynamic Avatars Positioned Circle */}
          <AnimatePresence>
            {meetingMembers.map((member, index) => {
              const total = meetingMembers.length;
              const angle = (index / total) * 360 - 90; // Start from top
              const radius = 240; // Pixels from center
              return (
                <motion.div
                  key={member.id}
                  initial={{ scale: 0, opacity: 0 }}
                  animate={{ 
                    scale: 1, 
                    opacity: 1,
                    top: `calc(50% + ${Math.sin((angle * Math.PI) / 180) * radius}px)`,
                    left: `calc(50% + ${Math.cos((angle * Math.PI) / 180) * radius}px)`,
                  }}
                  exit={{ scale: 0, opacity: 0 }}
                  className="absolute -translate-x-1/2 -translate-y-1/2 group z-20"
                >
                  <div className="relative cursor-pointer transition-transform hover:scale-125 z-30">
                    <img 
                      className="w-16 h-16 rounded-full border-4 border-white shadow-xl ring-4 ring-blue-50" 
                      src={member.img} 
                      alt={member.name}
                    />
                    {/* Popover */}
                    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-4 w-60 opacity-0 group-hover:opacity-100 transition-all pointer-events-none z-50">
                      <div className="bg-white p-5 rounded-2xl shadow-2xl border border-slate-100 text-left">
                        <div className="flex justify-between items-start mb-3">
                          <div>
                            <h4 className="font-manrope font-bold text-slate-900 text-sm">{member.name}</h4>
                            <p className="text-[10px] font-bold text-blue-600 uppercase tracking-wider">{member.role}</p>
                          </div>
                          <div className="p-1.5 bg-blue-50 rounded-lg text-blue-600">
                            {member.icon}
                          </div>
                        </div>
                        <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 mb-3">
                          <p className="text-[10px] uppercase font-bold text-slate-400 mb-1 flex items-center gap-1">
                            <Mic className="w-3 h-3" /> Live Perspective
                          </p>
                          <p className="text-[11px] text-slate-700 leading-relaxed font-serif italic">{member.opinion}</p>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {member.skills.map(s => (
                            <span key={s} className="text-[9px] bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-bold">{s}</span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>

        {/* Input area */}
        <div className="absolute bottom-12 w-full px-12 z-20">
          <div className="max-w-2xl mx-auto relative group">
            <input 
              className="w-full bg-white border border-slate-200 shadow-lg rounded-2xl px-6 py-5 pr-16 focus:ring-4 focus:ring-blue-100 focus:border-blue-400 transition-all outline-none text-slate-800 placeholder:text-slate-400" 
              placeholder="Instruct the Collective or ask for execution insights..." 
              type="text" 
            />
            <button className="absolute right-4 top-1/2 -translate-y-1/2 w-12 h-12 bg-blue-700 text-white rounded-xl flex items-center justify-center hover:bg-blue-800 transition-all shadow-md active:scale-95">
              <Send className="w-5 h-5" />
            </button>
          </div>
          <div className="flex justify-center gap-8 mt-6">
            <button className="flex items-center gap-2.5 text-[11px] font-bold text-slate-500 hover:text-blue-700 transition-colors uppercase tracking-widest">
              <Mic className="w-4 h-4" /> Voice Input
            </button>
            <button className="flex items-center gap-2.5 text-[11px] font-bold text-slate-500 hover:text-blue-700 transition-colors uppercase tracking-widest">
              <Paperclip className="w-4 h-4" /> Attach Reference
            </button>
          </div>
        </div>
      </section>

      {/* Right Sidebar: Roadmap & Action Items */}
      <section className="col-span-3 bg-white p-6 flex flex-col gap-10 overflow-y-auto border-l border-slate-100">
        <div>
          <h2 className="text-[11px] font-bold font-manrope uppercase tracking-[0.2em] text-slate-500 mb-6 flex items-center justify-between">
            Action Items
            <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-[10px] font-mono">3 Pending</span>
          </h2>
          <div className="space-y-3">
            {[
              { title: 'Finalize Security API Mesh', owner: 'Security Architecture', done: true },
              { title: 'Deploy 5 Agent Instances', owner: 'Engineering Team', done: false },
              { title: 'Market Resonance Test (v2)', owner: 'Marketing Control', done: false }
            ].map((task, i) => (
              <div key={i} className="p-4 bg-slate-50/50 border border-slate-100 rounded-xl hover:border-blue-200 transition-all cursor-pointer group">
                <div className="flex items-start gap-4">
                  <button className={`mt-0.5 w-5 h-5 rounded-lg border-2 flex items-center justify-center transition-colors ${task.done ? 'bg-blue-600 border-blue-600' : 'border-slate-300 group-hover:border-blue-400'}`}>
                    {task.done && <Check className="w-3.5 h-3.5 text-white stroke-[3px]" />}
                  </button>
                  <div className="flex-1">
                    <p className={`text-xs font-bold leading-tight ${task.done ? 'text-slate-400 line-through' : 'text-slate-800'}`}>{task.title}</p>
                    <p className="text-[10px] font-medium text-slate-400 mt-1.5 uppercase tracking-wide">Responsible: <span className="text-blue-600 font-bold">{task.owner}</span></p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h2 className="text-[11px] font-bold font-manrope uppercase tracking-[0.2em] text-slate-500 mb-8">Execution Roadmap</h2>
          <div className="relative pl-7 space-y-10">
            <div className="absolute left-[7.5px] top-1 bottom-1 w-[1px] bg-slate-100" />
            {ROADMAP.map((item, idx) => (
              <div key={item.id} className={`relative ${idx > 0 ? 'opacity-50 hover:opacity-100' : ''} transition-opacity`}>
                <div className={`absolute -left-[27px] top-0 w-4 h-4 rounded-full border-4 border-white shadow-sm ${idx === 0 ? 'bg-blue-600 animate-pulse' : 'bg-slate-200'}`} />
                <p className="text-[9px] font-extrabold text-blue-600 mb-1.5 uppercase tracking-widest">{item.phase}</p>
                <div className="flex items-center justify-between">
                  <p className="text-sm font-manrope font-extrabold text-slate-900">{item.title}</p>
                  <ArrowRight className="w-4 h-4 text-slate-300 group-hover:text-blue-500 transition-colors" />
                </div>
                <p className="text-[11px] text-slate-500 mt-2 font-inter leading-relaxed">{item.desc}</p>
                <div className="flex items-center gap-2 mt-4">
                  <div className="px-2.5 py-1 bg-slate-50 text-slate-500 border border-slate-100 rounded-lg text-[10px] font-bold uppercase tracking-tighter">
                    Owner: <span className="text-blue-700">{item.unit}</span>
                  </div>
                  <div className="px-2.5 py-1 bg-blue-50 text-blue-700 rounded-lg text-[9px] font-extrabold uppercase">
                    {item.status}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
};

const KPIPage = () => {
  return (
    <div className="p-10 max-w-7xl mx-auto h-content overflow-y-auto w-full no-scrollbar">
      <header className="mb-12 flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }}>
            <span className="text-[11px] font-bold text-blue-600 uppercase tracking-[0.3em] font-manrope">Performance Metrics</span>
            <h1 className="text-5xl font-manrope font-extrabold text-slate-900 mt-4 tracking-tight">Agentic Efficiency</h1>
            <p className="text-slate-500 mt-4 max-w-xl font-inter leading-relaxed">Tracking the output velocity and autonomous decision-making quality across all execution units in real-time.</p>
          </motion.div>
        </div>
        <div className="flex gap-4">
          <button className="flex items-center gap-2 px-6 py-3 bg-white border border-slate-200 text-slate-600 font-bold rounded-2xl text-xs hover:bg-slate-50 transition-all shadow-sm">
            <FileText className="w-4 h-4" /> Export Systems Report
          </button>
          <button className="flex items-center gap-2 px-6 py-3 bg-blue-700 text-white font-bold rounded-2xl text-xs hover:bg-blue-800 transition-all shadow-lg shadow-blue-100">
            <Activity className="w-4 h-4" /> Live Drill-down
          </button>
        </div>
      </header>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
        {PERFORMANCE_METRICS.map((perf, i) => (
          <motion.div 
            key={perf.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
            className="bg-white p-8 rounded-[32px] shadow-[0_16px_40px_rgba(0,0,0,0.03)] border border-slate-100 flex flex-col justify-between"
          >
            <div>
              <div className="flex items-center justify-between mb-6">
                <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest">{perf.label}</p>
                <div className="p-2.5 rounded-2xl bg-slate-50 text-slate-600">
                  {i === 0 ? <Users className="w-4 h-4" /> : i === 1 ? <TrendingUp className="w-4 h-4" /> : i === 2 ? <Activity className="w-4 h-4" /> : <ShieldCheck className="w-4 h-4" />}
                </div>
              </div>
              <p className="text-4xl font-manrope font-extrabold text-slate-900 tracking-tighter">{perf.value}</p>
            </div>
            <div className="mt-8 flex items-center justify-between pt-6 border-t border-slate-50">
              <div className="flex items-center gap-1.5">
                <TrendingUp className={`w-3.5 h-3.5 ${perf.trend.startsWith('+') ? 'text-emerald-500' : 'text-slate-400'}`} />
                <span className={`text-xs font-bold ${perf.trend.startsWith('+') ? 'text-emerald-600' : 'text-slate-500'}`}>{perf.trend}</span>
              </div>
              <span className="text-[10px] font-bold text-slate-300 uppercase">Target: {perf.target}</span>
            </div>
          </motion.div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12">
        {/* Main Chart */}
        <motion.div 
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="lg:col-span-2 bg-white p-10 rounded-[40px] shadow-[0_24px_60px_rgba(0,0,0,0.04)] border border-slate-100"
        >
          <div className="flex items-center justify-between mb-10">
            <div>
              <h3 className="text-2xl font-manrope font-extrabold text-slate-900 tracking-tight">System Velocity</h3>
              <p className="text-xs text-slate-400 font-medium mt-1">Comparing task throughput vs autonomous verification cost.</p>
            </div>
            <div className="flex gap-2">
              <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 rounded-lg">
                <div className="w-2 h-2 rounded-full bg-blue-600" />
                <span className="text-[10px] font-bold text-blue-700">Velocity</span>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-50 rounded-lg">
                <div className="w-2 h-2 rounded-full bg-slate-300" />
                <span className="text-[10px] font-bold text-slate-600">Cost</span>
              </div>
            </div>
          </div>
          <div className="h-[340px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={KPI_DATA}>
                <defs>
                  <linearGradient id="colorVel" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#2563eb" stopOpacity={0.15}/>
                    <stop offset="95%" stopColor="#2563eb" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis 
                  dataKey="name" 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }}
                  dy={10}
                />
                <YAxis hide />
                <Tooltip 
                  contentStyle={{ borderRadius: '16px', border: 'none', boxShadow: '0 20px 40px rgba(0,0,0,0.1)' }}
                  labelStyle={{ fontWeight: 'bold', marginBottom: '4px' }}
                />
                <Area type="monotone" dataKey="velocity" stroke="#2563eb" strokeWidth={4} fillOpacity={1} fill="url(#colorVel)" />
                <Area type="monotone" dataKey="cost" stroke="#94a3b8" strokeWidth={2} strokeDasharray="6 6" fill="transparent" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </motion.div>

        {/* Secondary Pie Chart */}
        <motion.div 
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.2 }}
          className="bg-white p-10 rounded-[40px] shadow-[0_24px_60px_rgba(0,0,0,0.04)] border border-slate-100"
        >
          <div className="text-center mb-8">
            <h3 className="text-xl font-manrope font-extrabold text-slate-900 tracking-tight">Unit Contribution</h3>
            <p className="text-[11px] text-slate-400 font-medium mt-1">Resource allocation by execution unit.</p>
          </div>
          <div className="h-[240px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={[
                    { name: 'Eng', value: 45 },
                    { name: 'AI Res', value: 25 },
                    { name: 'Sec', value: 20 },
                    { name: 'GTM', value: 10 },
                  ]}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={8}
                  dataKey="value"
                >
                  {[ '#2563eb', '#6366f1', '#10b981', '#f59e0b' ].map((color, index) => (
                    <Cell key={`cell-${index}`} fill={color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="space-y-4 mt-8">
            {[
              { label: 'Engineering', val: '45%', col: 'bg-blue-600' },
              { label: 'AI Research', val: '25%', col: 'bg-indigo-500' },
              { label: 'Security', val: '20%', col: 'bg-emerald-500' }
            ].map(item => (
              <div key={item.label} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-2.5 h-2.5 rounded-full ${item.col}`} />
                  <span className="text-xs font-bold text-slate-600">{item.label}</span>
                </div>
                <span className="text-xs font-mono font-bold text-slate-400">{item.val}</span>
              </div>
            ))}
          </div>
        </motion.div>
      </div>

      {/* KPI Target List */}
      <div className="bg-slate-900 p-12 rounded-[48px] text-white">
        <div className="flex flex-col md:flex-row items-center justify-between gap-8 mb-12">
          <div className="max-w-md">
            <h3 className="text-3xl font-manrope font-extrabold tracking-tight">Strategic KPI Vault</h3>
            <p className="text-slate-400 mt-4 text-sm leading-relaxed">The following hard targets represent the minimum threshold for autonomous unit scalability in Q3.</p>
          </div>
          <button className="px-8 py-4 bg-white text-slate-900 font-manrope font-extrabold rounded-2xl flex items-center gap-3 hover:scale-105 transition-transform active:scale-95">
            <Target className="w-5 h-5 text-blue-600" />
            Establish New Target
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[
            { tag: 'OPERATIONS', title: 'Token Zero-Waste Protocol', target: '< 0.02% waste', status: 'On Track', progress: 88 },
            { tag: 'SECURITY', title: 'Red-Team Resilience Index', target: 'Level 5 (Elite)', status: 'At Risk', progress: 62 },
            { tag: 'GTM', title: 'Market Sentiment Alignment', target: '> 94% positive', status: 'Exceeding', progress: 98 },
            { tag: 'AI RESEARCH', title: 'Model Iteration Frequency', target: '< 4hr cycles', status: 'On Track', progress: 74 },
          ].map((kpi, i) => (
            <motion.div 
              key={i}
              whileHover={{ x: 10 }}
              className="p-8 bg-white/5 rounded-3xl border border-white/10 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between mb-6">
                  <span className="text-[10px] font-bold text-white/30 tracking-widest uppercase">{kpi.tag}</span>
                  <span className={`text-[9px] font-extrabold px-2 py-0.5 rounded-lg ${kpi.status === 'At Risk' ? 'bg-rose-500/20 text-rose-500' : 'bg-emerald-500/20 text-emerald-500'}`}>
                    {kpi.status}
                  </span>
                </div>
                <h4 className="text-xl font-manrope font-bold text-white mb-2">{kpi.title}</h4>
                <p className="text-xs text-white/50 mb-6">Execution Target: <span className="text-blue-400 font-bold">{kpi.target}</span></p>
              </div>
              <div className="space-y-3">
                <div className="flex justify-between text-[10px] font-bold text-white/30 uppercase">
                  <span>Progress</span>
                  <span>{kpi.progress}%</span>
                </div>
                <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
                  <motion.div 
                    initial={{ width: 0 }}
                    animate={{ width: `${kpi.progress}%` }}
                    transition={{ duration: 1, delay: i * 0.2 }}
                    className={`h-full rounded-full ${kpi.status === 'At Risk' ? 'bg-rose-500' : 'bg-blue-600'}`}
                  />
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
};

// --- Main App Component ---

export default function App() {
  const [activeTab, setActiveTab] = useState('governance');
  const [meetingMemberIds, setMeetingMemberIds] = useState<string[]>(['ceo', 'cto', 'coo', 'cfo', 'cmo', 'vpe']);

  const handleAddRemoveMember = (id: string) => {
    setMeetingMemberIds(prev => 
      prev.includes(id) ? prev.filter(mid => mid !== id) : [...prev, id]
    );
  };

  const meetingMembers = useMemo(() => {
    return meetingMemberIds
      .map(id => EXECUTION_UNITS.find(u => u.id === id))
      .filter((u): u is ExecutionUnit => !!u);
  }, [meetingMemberIds]);

  return (
    <div className="h-screen bg-slate-50 font-inter text-slate-900 selection:bg-blue-100 selection:text-blue-900 overflow-hidden">
      <Navbar activeTab={activeTab} setActiveTab={setActiveTab} />
      
      <div className="flex pt-16 h-full">
        <Sidebar 
          currentMeetingIds={meetingMemberIds} 
          onAddRemove={handleAddRemoveMember} 
        />
        
        <main className="flex-1 ml-20 lg:ml-20 transition-all duration-300 h-full overflow-hidden">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
              className="h-full"
            >
              {activeTab === 'governance' && <GovernancePage meetingMembers={meetingMembers} />}
              {activeTab === 'performance' && <KPIPage />}
              {activeTab === 'portfolio' && (
                <div className="flex items-center justify-center h-full">
                  <div className="text-center group">
                    <div className="w-24 h-24 bg-blue-50 rounded-full flex items-center justify-center mx-auto mb-6 group-hover:scale-110 transition-transform">
                      <Cpu className="w-10 h-10 text-blue-600" />
                    </div>
                    <h2 className="text-3xl font-manrope font-extrabold text-slate-900">Portfolio Hub</h2>
                    <p className="text-slate-400 mt-2">Active unit portfolio visualization is in generation...</p>
                    <button 
                      onClick={() => setActiveTab('governance')}
                      className="mt-8 text-blue-600 font-bold flex items-center gap-2 mx-auto hover:gap-4 transition-all"
                    >
                      Return to Governance <ArrowRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>

      {/* FAB */}
      <div className="fixed bottom-10 right-10 z-50">
        <button className="bg-slate-900 text-white flex items-center gap-3 px-8 py-5 rounded-[24px] shadow-2xl hover:scale-105 active:scale-95 transition-all group overflow-hidden relative">
          <div className="absolute inset-0 bg-blue-600 scale-x-0 group-hover:scale-x-100 transition-transform origin-left duration-500 -z-10" />
          <Bolt className="w-5 h-5 group-hover:fill-white" />
          <span className="font-manrope font-extrabold text-sm tracking-tight">Force Sync Agents</span>
        </button>
      </div>
    </div>
  );
}

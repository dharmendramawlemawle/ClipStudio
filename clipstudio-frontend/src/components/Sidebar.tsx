import React from 'react';
import {
  LayoutDashboard,
  Video,
  Radio,
  Scissors,
  Layers,
  Settings,
  Cpu,
  Database,
} from 'lucide-react';
import { HealthResponse } from '../types';

interface SidebarProps {
  currentTab: string;
  onSelectTab: (tab: string) => void;
  health: HealthResponse | null;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentTab, onSelectTab, health }) => {
  const navItems = [
    { id: 'dashboard', label: 'Studio Dashboard', icon: LayoutDashboard },
    { id: 'videos', label: 'Imported Videos', icon: Video, badge: 'Phase 2' },
    { id: 'streams', label: 'Live Stream Monitor', icon: Radio, badge: 'Phase 6' },
    { id: 'clips', label: 'Clips & Highlights', icon: Scissors, badge: 'Phase 4' },
    { id: 'jobs', label: 'Durable Job Queue', icon: Layers },
    { id: 'settings', label: 'Settings & AI', icon: Settings },
  ];

  return (
    <aside className="w-64 border-r border-studio-800 bg-studio-900/60 flex flex-col justify-between shrink-0">
      <div className="p-4 space-y-6">
        {/* Navigation list */}
        <div className="space-y-1">
          <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-studio-400 mb-2">
            Workspace
          </p>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onSelectTab(item.id)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm font-medium transition ${
                  isActive
                    ? 'bg-studio-800 text-brand-500 border border-brand-500/20'
                    : 'text-studio-200 hover:bg-studio-850 hover:text-white'
                }`}
              >
                <div className="flex items-center space-x-3">
                  <Icon className={`w-4 h-4 ${isActive ? 'text-brand-500' : 'text-studio-400'}`} />
                  <span>{item.label}</span>
                </div>
                {item.badge && (
                  <span className="text-[10px] font-medium bg-studio-850 text-studio-400 px-1.5 py-0.5 rounded border border-studio-700">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Host Hardware & DB Specs Widget */}
      <div className="p-4 border-t border-studio-800 bg-studio-950/40 text-xs space-y-2">
        <div className="flex items-center justify-between text-studio-400">
          <span className="flex items-center space-x-1.5">
            <Cpu className="w-3.5 h-3.5" />
            <span>Target Host</span>
          </span>
          <span className="font-semibold text-studio-200">Intel i5-1135G7</span>
        </div>
        <div className="flex items-center justify-between text-studio-400">
          <span className="flex items-center space-x-1.5">
            <Database className="w-3.5 h-3.5" />
            <span>Storage Mode</span>
          </span>
          <span className="font-semibold text-brand-500">SQLite WAL</span>
        </div>
        <div className="flex items-center justify-between text-studio-400">
          <span>Active Queue Limit</span>
          <span className="text-studio-200">
            {health?.hardware.max_concurrent_heavy_jobs ?? 1} concurrent
          </span>
        </div>
      </div>
    </aside>
  );
};
